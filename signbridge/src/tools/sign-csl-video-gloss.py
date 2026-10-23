#!/usr/bin/env python3
"""Train-only CE-CSL video-to-Gloss CTC baseline.

This module is deliberately independent from the browser extension and the
existing text-to-Gloss or motion assets.  It reads only a train package,
supports a dataset-local source-code holdout, and writes reproducible research
artifacts.  It never reads official dev/test data and never marks the result as
ready for deployment or Demo integration.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
from typing import Iterable, Sequence

try:  # Optional for package/schema tests on machines without PyTorch.
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset
except ImportError:  # pragma: no cover - exercised only without the optional runtime.
    torch = None
    nn = None
    DataLoader = Dataset = object

try:  # Optional for package/schema tests on machines without OpenCV.
    import cv2
except ImportError:  # pragma: no cover - exercised only without the optional runtime.
    cv2 = None


SPECIALS = ["<blank>", "<unk>"]
PACKAGE_SCHEMA = "signbridge-ce-csl-video-gloss-package-v1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(path: str) -> bool:
    candidate = Path(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts and "\\" not in path


def _read_manifest(root: Path) -> dict[str, str]:
    manifest_path = root / "SHA256SUMS"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Missing or unsafe package SHA256SUMS")
    entries: dict[str, str] = {}
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"Malformed package manifest line {line_number}") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not _safe_relative(relative) or relative in entries:
            raise ValueError(f"Invalid or duplicate package manifest entry: {relative}")
        entries[relative] = digest
    if not entries:
        raise ValueError("Empty package manifest")
    return entries


def _train_samples_path(root: Path) -> tuple[Path, str]:
    # Prefer the explicit train split when a library also contains a legacy
    # aggregate samples.jsonl with dev/test rows.  The fallback supports the
    # deliberately train-only fixture/package shape used by this tool.
    candidates = [root / "splits" / "train" / "samples.jsonl", root / "samples.jsonl"]
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            return path, path.relative_to(root).as_posix()
    raise ValueError("Missing train-only samples.jsonl")


def _validate_row(row: dict, line_number: int, seen_ids: set[str], seen_videos: set[str]) -> dict:
    identity = row.get("id")
    source_code = row.get("source_translator", row.get("source_code"))
    relative_video = row.get("video_relative_path")
    gloss = row.get("gloss_sequence")
    video = row.get("video")
    if (
        row.get("schema") != "signbridge-ce-csl-sample-v1"
        or row.get("source_split") != "train"
        or not isinstance(identity, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity)
        or identity in seen_ids
        or not isinstance(source_code, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_code)
        or row.get("source_translator_scope") not in (None, "dataset_code_only_not_cross_dataset_identity")
        or not isinstance(gloss, list)
        or not gloss
        or any(not isinstance(token, str) or not token or token == "<blank>" for token in gloss)
        or not isinstance(relative_video, str)
        or not _safe_relative(relative_video)
        or relative_video != f"video/train/{source_code}/{row.get('source_id', identity)}.mp4"
        or relative_video in seen_videos
        or not isinstance(video, dict)
        or not isinstance(video.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", video["sha256"])
        or not isinstance(video.get("bytes"), int)
        or video["bytes"] <= 0
    ):
        raise ValueError(f"Malformed or ambiguous train sample at line {line_number}")
    seen_ids.add(identity)
    seen_videos.add(relative_video)
    return {
        "id": identity,
        "source_code": source_code,
        "video_relative_path": relative_video,
        "video_sha256": video["sha256"],
        "video_bytes": video["bytes"],
        "gloss_sequence": list(gloss),
    }


def read_train_package(package: Path | str) -> tuple[list[dict], dict]:
    """Read and hash-bind only the train sample file.

    The function intentionally does not enumerate, open, or validate any
    ``dev``/``test`` file.  This keeps the research package fail-closed with
    respect to the user's train-only authorization.
    """

    root_arg = Path(package).absolute()
    if root_arg.is_symlink():
        raise ValueError("Train package root cannot be a symlink")
    root = root_arg.resolve()
    if not root.is_dir():
        raise ValueError("Train package root must be a real directory")
    manifest = _read_manifest(root)
    sample_path, relative = _train_samples_path(root)
    expected = manifest.get(relative)
    if expected is None or sha(sample_path) != expected:
        raise ValueError(f"Train sample digest differs: {relative}")
    rows: list[dict] = []
    seen_ids: set[str] = set()
    seen_videos: set[str] = set()
    for line_number, line in enumerate(sample_path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            rows.append(_validate_row(json.loads(line), line_number, seen_ids, seen_videos))
    if not rows or len({row["source_code"] for row in rows}) < 2:
        raise ValueError("Train package needs samples from at least two source codes")
    return rows, {
        "package_schema": PACKAGE_SCHEMA,
        "package_root": str(root),
        "manifest_sha256": sha(root / "SHA256SUMS"),
        "train_samples_relative_path": relative,
        "train_samples_sha256": expected,
        "sample_count": len(rows),
        "source_codes": sorted({row["source_code"] for row in rows}),
        "test_read": False,
        "dev_read": False,
    }


def group_holdout(rows: Sequence[dict], source_code: str) -> tuple[list[dict], list[dict]]:
    train = [row for row in rows if row["source_code"] != source_code]
    heldout = [row for row in rows if row["source_code"] == source_code]
    if not heldout:
        raise ValueError(f"Unknown or empty held-out source code: {source_code}")
    if not train:
        raise ValueError("A holdout must leave at least one training source code")
    train_ids = {row["id"] for row in train}
    if train_ids & {row["id"] for row in heldout}:
        raise ValueError("Train and held-out identities overlap")
    return train, heldout


def grouped_partition(rows: Sequence[dict], selection_code: str, final_holdout_code: str,
                      excluded_codes: Iterable[str] = ()) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    excluded_codes = set(excluded_codes)
    if selection_code == final_holdout_code or selection_code in excluded_codes or final_holdout_code in excluded_codes:
        raise ValueError("Selection, final holdout and excluded source codes must be disjoint")
    source_codes = {row["source_code"] for row in rows}
    for code in {selection_code, final_holdout_code} | excluded_codes:
        if code not in source_codes:
            raise ValueError(f"Unknown source code in partition: {code}")
    selection = [row for row in rows if row["source_code"] == selection_code]
    final_holdout = [row for row in rows if row["source_code"] == final_holdout_code]
    excluded = [row for row in rows if row["source_code"] in excluded_codes]
    train = [row for row in rows if row["source_code"] not in ({selection_code, final_holdout_code} | excluded_codes)]
    if not train or not selection or not final_holdout:
        raise ValueError("Grouped partition produced an empty train, selection or final holdout")
    groups = [{row["id"] for row in group} for group in (train, selection, final_holdout, excluded)]
    for index, left in enumerate(groups):
        if any(left & right for right in groups[index + 1 :]):
            raise ValueError("Grouped partition identities overlap")
    return train, selection, final_holdout, excluded


def exclude_duplicate_videos(rows: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Quarantine every repeated video digest before any grouped split."""

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        digest = row.get("video_sha256")
        if digest:
            grouped.setdefault(digest, []).append(row)
    duplicate_groups = []
    excluded_ids = set()
    for digest, group in sorted(grouped.items()):
        if len(group) < 2:
            continue
        excluded_ids.update(row["id"] for row in group)
        duplicate_groups.append({
            "video_sha256": digest,
            "ids": sorted(row["id"] for row in group),
            "source_codes": sorted({row["source_code"] for row in group}),
            "label_conflict": len({tuple(row["gloss_sequence"]) for row in group}) > 1,
        })
    return [row for row in rows if row["id"] not in excluded_ids], duplicate_groups


def verify_video_assets(rows: Sequence[dict], video_root: Path | str) -> dict:
    """Verify exact train video bytes before any training decode begins."""

    root = Path(video_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Video root is not a directory: {root}")
    verified_bytes = 0
    records = []
    for row in rows:
        relative = row["video_relative_path"]
        path = root / relative
        if path.is_symlink() or not path.is_file() or os.path.commonpath((str(root), str(path.resolve()))) != str(root):
            raise ValueError(f"Missing or unsafe train video: {relative}")
        expected_sha = row.get("video_sha256")
        expected_bytes = row.get("video_bytes")
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise ValueError(f"Missing or invalid video digest: {relative}")
        if not isinstance(expected_bytes, int) or path.stat().st_size != expected_bytes:
            raise ValueError(f"Train video size differs: {relative}")
        if sha(path) != expected_sha:
            raise ValueError(f"Train video digest differs: {relative}")
        verified_bytes += expected_bytes
        records.append({"id": row["id"], "video_relative_path": relative, "sha256": expected_sha, "bytes": expected_bytes})
    return {"verified_video_count": len(rows), "verified_video_bytes": verified_bytes,
            "all_video_hashes_match": True, "records": records}


def verify_cached_frames(rows: Sequence[dict], cache_root: Path | str, manifest_path: Path | str,
                         source_report_path: Path | str, frames: int, image_size: int) -> dict:
    cache_arg = Path(cache_root).absolute()
    manifest_arg = Path(manifest_path).absolute()
    report_arg = Path(source_report_path).absolute()
    if cache_arg.is_symlink() or manifest_arg.is_symlink() or report_arg.is_symlink():
        raise ValueError("Cached frame provenance paths cannot be symlinks")
    cache = cache_arg.resolve()
    manifest = manifest_arg.resolve()
    source_report = json.loads(report_arg.read_text(encoding="utf-8"))
    source_cache = source_report.get("frame_cache", {})
    if (source_cache.get("cached_video_count") != len(rows)
            or source_cache.get("frames") != frames
            or source_cache.get("image_size") != image_size
            or Path(source_cache.get("location", "")).resolve() != cache
            or source_cache.get("sha256_manifest") != sha(manifest)):
        raise ValueError("Cached frame provenance does not match requested rows/configuration")
    entries = {}
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"Malformed cached-frame manifest line {line_number}") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not _safe_relative(relative) or relative in entries:
            raise ValueError(f"Invalid cached-frame manifest entry: {relative}")
        entries[relative] = digest
    expected_names = {row["id"] + ".npy" for row in rows}
    if set(entries) != expected_names:
        raise ValueError("Cached-frame manifest IDs differ from eligible train rows")
    actual_names = {path.name for path in cache.iterdir() if path.is_file() and path.suffix == ".npy"}
    if actual_names != expected_names:
        raise ValueError("Cached frame directory contains missing or unexpected .npy IDs")
    verified_bytes = 0
    for relative, expected_digest in entries.items():
        path = cache / relative
        if (path.is_symlink() or not path.is_file()
                or os.path.commonpath((str(cache), str(path.resolve()))) != str(cache)):
            raise ValueError(f"Missing or unsafe cached frame array: {relative}")
        if sha(path) != expected_digest:
            raise ValueError(f"Cached frame cache digest differs: {relative}")
        verified_bytes += path.stat().st_size
    return {"cached_video_count": len(rows), "cached_bytes": verified_bytes, "frames": frames,
            "image_size": image_size, "location": str(cache), "sha256_manifest": sha(manifest),
            "reused": True, "source_report": str(report_arg.resolve()), "all_cache_hashes_match": True}


def prepare_video_cache(rows: Sequence[dict], video_root: Path | str, cache_root: Path | str, frames: int, image_size: int) -> dict:
    """Decode each source video once and persist compact uint8 RGB samples."""

    import numpy as np

    root = Path(video_root).resolve()
    cache = Path(cache_root).resolve()
    cache.mkdir(parents=True, exist_ok=False)
    total_bytes = 0
    for row in rows:
        target = cache / (row["id"] + ".npy")
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite cached frames: {target}")
        sampled = sample_video(root / row["video_relative_path"], frames, image_size)
        array = sampled.mul(255).round().clamp(0, 255).to(torch.uint8).permute(0, 2, 3, 1).cpu().numpy()
        np.save(target, array, allow_pickle=False)
        total_bytes += target.stat().st_size
    return {"cached_video_count": len(rows), "cached_bytes": total_bytes, "frames": frames, "image_size": image_size}


def ctc_greedy_decode(indices: Iterable[int], blank: int = 0) -> list[int]:
    result: list[int] = []
    previous = blank
    for value in indices:
        value = int(value)
        if value != blank and value != previous:
            result.append(value)
        previous = value
    return result


def ctc_minimum_frames(tokens: Sequence[str]) -> int:
    return len(tokens) + sum(left == right for left, right in zip(tokens, tokens[1:]))


def ctc_prediction_diagnostics(frame_predictions: Sequence[Sequence[int]], blank: int = 0) -> dict:
    total_frames = sum(len(row) for row in frame_predictions)
    blank_frames = sum(int(index) == blank for row in frame_predictions for index in row)
    decoded = [ctc_greedy_decode(row, blank) for row in frame_predictions]
    empty = sum(not prediction for prediction in decoded)
    predicted_tokens = sum(len(prediction) for prediction in decoded)
    return {"prediction_frames": total_frames, "blank_frames": blank_frames,
            "blank_frame_fraction": blank_frames / max(total_frames, 1),
            "empty_prediction_samples": empty, "empty_prediction_rate": empty / max(len(decoded), 1),
            "predicted_gloss_tokens": predicted_tokens, "predicted_tokens": predicted_tokens}


def ctc_blank_penalty(log_probs):
    if torch is None:
        raise RuntimeError("PyTorch is required for CTC blank penalty")
    return log_probs.exp()[..., 0].mean()


def validate_ctc_capacity(rows: Sequence[dict], frames: int) -> dict:
    insufficient = [
        {"id": row["id"], "minimum_frames": ctc_minimum_frames(row["gloss_sequence"])}
        for row in rows if ctc_minimum_frames(row["gloss_sequence"]) > frames
    ]
    if insufficient:
        raise ValueError(f"CTC frame capacity is insufficient for {len(insufficient)} samples: {insufficient[:10]}")
    return {"checked_samples": len(rows), "max_minimum_frames": max(
        (ctc_minimum_frames(row["gloss_sequence"]) for row in rows), default=0
    ), "frames": frames, "all_samples_fit": True}


def _edit_counts(reference: Sequence[int], hypothesis: Sequence[int]) -> tuple[int, int, int]:
    n, m = len(reference), len(hypothesis)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        table[i][0] = i
    for j in range(m + 1):
        table[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            table[i][j] = min(
                table[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]),
                table[i - 1][j] + 1,
                table[i][j - 1] + 1,
            )
    i, j, substitutions, deletions, insertions = n, m, 0, 0, 0
    while i or j:
        if i and j and reference[i - 1] == hypothesis[j - 1] and table[i][j] == table[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i and j and table[i][j] == table[i - 1][j - 1] + 1:
            substitutions, i, j = substitutions + 1, i - 1, j - 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            deletions, i = deletions + 1, i - 1
        else:
            insertions, j = insertions + 1, j - 1
    return substitutions, deletions, insertions


def sequence_metrics(references: Sequence[Sequence[int]], predictions: Sequence[Sequence[int]]) -> dict:
    if len(references) != len(predictions):
        raise ValueError("Reference and prediction counts differ")
    substitutions = deletions = insertions = reference_tokens = exact = 0
    for reference, prediction in zip(references, predictions):
        s, d, ins = _edit_counts(reference, prediction)
        substitutions += s
        deletions += d
        insertions += ins
        reference_tokens += len(reference)
        exact += int(list(reference) == list(prediction))
    errors = substitutions + deletions + insertions
    return {
        "samples": len(references),
        "reference_tokens": reference_tokens,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "errors": errors,
        "gloss_error_rate": errors / max(reference_tokens, 1),
        "exact_match": exact / max(len(references), 1),
    }


def _require_runtime() -> None:
    if torch is None:
        raise RuntimeError("PyTorch is required for video training")
    if cv2 is None:
        raise RuntimeError("OpenCV is required for video training")


def _center_square(frame):
    height, width = frame.shape[:2]
    side = max(height, width)
    resized_width, resized_height = width, height
    resized = frame
    canvas = cv2.copyMakeBorder(
        resized,
        (side - resized_height) // 2,
        side - resized_height - (side - resized_height) // 2,
        (side - resized_width) // 2,
        side - resized_width - (side - resized_width) // 2,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    return canvas


def sample_video(path: Path | str, frames: int = 32, image_size: int = 64):
    """Uniformly decode a video into ``(time, channels, height, width)``."""

    _require_runtime()
    if frames < 2 or image_size < 8:
        raise ValueError("frames must be >= 2 and image_size must be >= 8")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Unable to open video: {path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count <= 0:
            raise ValueError(f"Video has no frames: {path}")
        positions = [round(index * (frame_count - 1) / (frames - 1)) for index in range(frames)]
        targets = set(positions)
        selected = {}
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index in targets:
                image = cv2.resize(_center_square(frame), (image_size, image_size), interpolation=cv2.INTER_AREA)
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                selected[index] = torch.from_numpy(image).permute(2, 0, 1).float().div_(255.0)
            index += 1
            if len(selected) == len(targets):
                break
        if len(selected) != len(targets):
            raise ValueError(f"Video decode ended early: {path} ({len(selected)}/{len(targets)} frames)")
        return torch.stack([selected[target] for target in positions])
    finally:
        capture.release()


class VideoGlossDataset(Dataset):
    def __init__(self, rows: Sequence[dict], video_root: Path, vocab: dict[str, int], frames: int, image_size: int, cache_root: Path | None = None):
        _require_runtime()
        self.rows = list(rows)
        self.video_root = Path(video_root).resolve()
        self.vocab = vocab
        self.frames = frames
        self.image_size = image_size
        self.cache_root = Path(cache_root).resolve() if cache_root else None

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        path = self.video_root / row["video_relative_path"]
        if (not path.is_file() or path.is_symlink()
                or os.path.commonpath((str(self.video_root), str(path.resolve()))) != str(self.video_root)):
            raise FileNotFoundError(f"Missing or unsafe video: {path}")
        if self.cache_root is not None:
            import numpy as np
            cache_path = self.cache_root / (row["id"] + ".npy")
            if not cache_path.is_file() or cache_path.is_symlink():
                raise FileNotFoundError(f"Missing cached frames: {cache_path}")
            video = torch.from_numpy(np.load(cache_path, allow_pickle=False)).permute(0, 3, 1, 2).float().div_(255.0)
        else:
            video = sample_video(path, self.frames, self.image_size)
        target = torch.tensor([self.vocab.get(token, self.vocab["<unk>"]) for token in row["gloss_sequence"]], dtype=torch.long)
        return video, target, row


def _collate(batch):
    videos, targets, rows = zip(*batch)
    return torch.stack(videos), torch.cat(targets), torch.tensor([len(target) for target in targets], dtype=torch.long), rows


if torch is not None:

    class VideoGlossModel(nn.Module):
        def __init__(self, vocab_size: int, width: int = 32):
            super().__init__()
            if vocab_size < 2 or width < 4:
                raise ValueError("vocab_size must include blank and width must be >= 4")
            self.spatial = nn.Sequential(
                nn.Conv2d(3, width, 5, stride=2, padding=2),
                nn.BatchNorm2d(width),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(width, width * 2, 3, stride=2, padding=1),
                nn.BatchNorm2d(width * 2),
                nn.ReLU(inplace=True),
                nn.AdaptiveAvgPool2d((4, 4)),
            )
            self.temporal = nn.GRU(width * 2 * 4 * 4, width, num_layers=2, bidirectional=True, dropout=0.1)
            self.head = nn.Linear(width * 2, vocab_size)

        def forward(self, videos):
            batch, time, channels, height, width = videos.shape
            spatial = self.spatial(videos.reshape(batch * time, channels, height, width)).flatten(1)
            temporal, _ = self.temporal(spatial.reshape(batch, time, -1).transpose(0, 1))
            return self.head(temporal).log_softmax(dim=-1)

else:  # pragma: no cover - import surface remains useful without torch.

    class VideoGlossModel:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            _require_runtime()


def build_vocab(rows: Sequence[dict], min_count: int = 1) -> dict[str, int]:
    if min_count < 1:
        raise ValueError("min_count must be at least 1")
    counts = Counter(token for row in rows for token in row["gloss_sequence"])
    tokens = sorted(token for token, count in counts.items() if count >= min_count)
    return {"<blank>": 0, "<unk>": 1, **{token: index + 2 for index, token in enumerate(tokens)}}


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def _epoch(model, loader, loss_fn, optimizer=None, device="cpu", scaler=None, blank_penalty_weight=0.0):
    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    references, predictions, records, frame_predictions = [], [], [], []
    gloss_by_id = getattr(loader.dataset, "gloss_by_id", {})
    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for videos, targets, target_lengths, rows in loader:
            videos = videos.to(device, non_blocking=True)
            targets = targets.to(device)
            if training:
                optimizer.zero_grad(set_to_none=True)
            use_amp = scaler is not None and scaler.is_enabled()
            with torch.cuda.amp.autocast(enabled=use_amp):
                log_probs = model(videos)
                input_lengths = torch.full((videos.shape[0],), log_probs.shape[0], dtype=torch.long, device="cpu")
                loss = loss_fn(log_probs, targets, input_lengths, target_lengths)
                blank_penalty = ctc_blank_penalty(log_probs)
                loss = loss + blank_penalty_weight * blank_penalty
            if training:
                if use_amp:
                    scaler.scale(loss).backward()
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                    optimizer.step()
            total_loss += float(loss.detach().cpu()) * len(rows)
            indices = log_probs.detach().argmax(dim=-1).transpose(0, 1).cpu().tolist()
            frame_predictions.extend(indices)
            offset = 0
            for row, target_length, indices_one in zip(rows, target_lengths.cpu().tolist(), indices):
                reference_ids = targets[offset : offset + target_length].detach().cpu().tolist()
                offset += target_length
                prediction_ids = ctc_greedy_decode(indices_one)
                reference = list(row["gloss_sequence"])
                prediction = [gloss_by_id.get(index, "<invalid>") for index in prediction_ids]
                references.append(reference)
                predictions.append(prediction)
                records.append({"id": row["id"], "reference_ids": reference_ids,
                                "prediction_ids": prediction_ids, "reference_gloss": reference,
                                "prediction_gloss": prediction})
    metrics = sequence_metrics(references, predictions)
    metrics.update(ctc_prediction_diagnostics(frame_predictions))
    metrics["loss"] = total_loss / max(len(loader.dataset), 1)
    return metrics, records


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _save_checkpoint(path: Path, checkpoint) -> None:
    temporary = path.with_name(path.name + ".tmp")
    torch.save(checkpoint, temporary)
    os.replace(temporary, path)


def _write_manifest(root: Path) -> None:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS" and "frame-cache" not in path.parts:
            entries.append(f"{sha(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")


def _write_tree_manifest(root: Path, destination: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append(f"{sha(path)}  {path.relative_to(root).as_posix()}")
    destination.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return sha(destination)


def train(args) -> dict:
    _require_runtime()
    if not torch.cuda.is_available():
        raise RuntimeError("GPU-only training requested, but CUDA is unavailable")
    run_started = datetime.now(timezone.utc)
    _seed_everything(args.seed)
    all_rows, package_info = read_train_package(args.package)
    rows, duplicate_video_groups = exclude_duplicate_videos(all_rows)
    ctc_capacity = validate_ctc_capacity(rows, args.frames)
    train_rows, selection_rows, heldout_rows, excluded_rows = grouped_partition(
        rows, args.selection_source_code, args.heldout_source_code, args.exclude_source_codes
    )
    package_root = Path(args.package).resolve()
    video_root = Path(args.video_root).resolve() if args.video_root else package_root
    video_integrity = verify_video_assets(all_rows, video_root)
    vocab = build_vocab(train_rows, args.min_gloss_count)
    selection_oov = sorted({token for row in selection_rows for token in row["gloss_sequence"] if token not in vocab})
    final_oov = sorted({token for row in heldout_rows for token in row["gloss_sequence"] if token not in vocab})
    train_tokens = [token for row in train_rows for token in row["gloss_sequence"]]
    selection_tokens = [token for row in selection_rows for token in row["gloss_sequence"]]
    final_tokens = [token for row in heldout_rows for token in row["gloss_sequence"]]
    output_arg = Path(args.output).absolute()
    if output_arg.is_symlink():
        raise ValueError("Output directory cannot be a symlink")
    output = output_arg.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output must be new and empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "video-integrity.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in video_integrity.pop("records")),
        encoding="utf-8",
    )
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    if args.reuse_frame_cache:
        if not args.reuse_frame_cache_manifest or not args.reuse_frame_cache_report:
            raise ValueError("Reusing frames requires both the source manifest and report")
        cache_root = Path(args.reuse_frame_cache).resolve()
        cache_info = verify_cached_frames(
            rows, cache_root, args.reuse_frame_cache_manifest, args.reuse_frame_cache_report,
            args.frames, args.image_size
        )
        (output / "frame-cache.SHA256SUMS").write_bytes(Path(args.reuse_frame_cache_manifest).read_bytes())
    else:
        cache_root = output.parent / f"{output.name}-frame-cache"
        cache_info = prepare_video_cache(rows, video_root, cache_root, args.frames, args.image_size)
        cache_info["location"] = str(cache_root)
        cache_info["sha256_manifest"] = _write_tree_manifest(cache_root, output / "frame-cache.SHA256SUMS")
    device = torch.device("cuda")
    model = VideoGlossModel(len(vocab), args.width).to(device)
    train_loader = DataLoader(
        VideoGlossDataset(train_rows, video_root, vocab, args.frames, args.image_size, cache_root),
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        collate_fn=_collate,
    )
    inverse_vocab = {index: token for token, index in vocab.items()}
    train_loader.dataset.gloss_by_id = inverse_vocab
    selection_loader = DataLoader(
        VideoGlossDataset(selection_rows, video_root, vocab, args.frames, args.image_size, cache_root),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        collate_fn=_collate,
    )
    selection_loader.dataset.gloss_by_id = inverse_vocab
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    loss_fn = nn.CTCLoss(blank=0, zero_infinity=True)
    scaler = torch.cuda.amp.GradScaler(enabled=device.type == "cuda" and args.amp)
    best_error = math.inf
    best_epoch = None
    history = []
    for epoch in range(1, args.epochs + 1):
        train_metrics, _ = _epoch(model, train_loader, loss_fn, optimizer, device, scaler, args.blank_penalty_weight)
        selection_metrics, _ = _epoch(model, selection_loader, loss_fn, None, device, None, args.blank_penalty_weight)
        entry = {"epoch": epoch, "train": train_metrics, "selection": selection_metrics}
        history.append(entry)
        checkpoint = {
            "schema": "signbridge-ce-csl-video-gloss-checkpoint-v1",
            "epoch": epoch,
            "model": model.state_dict(),
            "vocab": vocab,
            "config": config,
            "selection_source_code": args.selection_source_code,
            "final_holdout_source_code": args.heldout_source_code,
        }
        _save_checkpoint(output / "checkpoint-last.pt", checkpoint)
        if selection_metrics["gloss_error_rate"] < best_error:
            best_error = selection_metrics["gloss_error_rate"]
            best_epoch = epoch
            _save_checkpoint(output / "checkpoint-best.pt", checkpoint)
        _write_json(output / "history.json", history)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        if best_epoch is not None and epoch - best_epoch >= args.patience:
            break
    best_checkpoint = torch.load(output / "checkpoint-best.pt", map_location=device)
    model.load_state_dict(best_checkpoint["model"])
    final_loader = DataLoader(
        VideoGlossDataset(heldout_rows, video_root, vocab, args.frames, args.image_size, cache_root),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
        collate_fn=_collate,
    )
    final_loader.dataset.gloss_by_id = inverse_vocab
    final_metrics, final_predictions = _epoch(model, final_loader, loss_fn, None, device, None, args.blank_penalty_weight)
    gloss_by_id = {index: token for token, index in vocab.items()}
    (output / "predictions-final-holdout.jsonl").write_text(
        "".join(json.dumps({
            "id": record["id"],
            "reference_ids": record["reference_ids"],
            "prediction_ids": record["prediction_ids"],
            "reference_gloss": record["reference_gloss"],
            "prediction_gloss": record["prediction_gloss"],
        }, ensure_ascii=False) + "\n" for record in final_predictions), encoding="utf-8"
    )
    finished = datetime.now(timezone.utc)
    _write_json(output / "vocab.json", vocab)
    _write_json(output / "config.json", {**config, "device": str(device), "started_at_utc": run_started.isoformat()})
    report = {
        "schema": "signbridge-ce-csl-video-gloss-training-report-v1",
        "created_at_utc": finished.isoformat(),
        "started_at_utc": run_started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "package": package_info,
        "video_root": str(video_root),
        "counts": {
            "all_train_rows": len(all_rows),
            "eligible_after_duplicate_quarantine": len(rows),
            "duplicate_quarantined_rows": len(all_rows) - len(rows),
            "train_rows": len(train_rows),
            "selection_rows": len(selection_rows),
            "heldout_rows": len(heldout_rows),
            "excluded_source_rows": len(excluded_rows),
            "vocab_size": len(vocab),
            "minimum_gloss_count": args.min_gloss_count,
            "train_gloss_token_occurrences": len(train_tokens),
            "train_oov_gloss_occurrences": sum(token not in vocab for token in train_tokens),
            "selection_gloss_token_occurrences": len(selection_tokens),
            "selection_oov_gloss_occurrences": sum(token not in vocab for token in selection_tokens),
            "selection_oov_token_fraction": sum(token not in vocab for token in selection_tokens) / max(len(selection_tokens), 1),
            "selection_oov_token_types": len(selection_oov),
            "selection_oov_token_examples": selection_oov[:20],
            "final_holdout_gloss_token_occurrences": len(final_tokens),
            "final_holdout_oov_gloss_occurrences": sum(token not in vocab for token in final_tokens),
            "final_holdout_oov_token_fraction": sum(token not in vocab for token in final_tokens) / max(len(final_tokens), 1),
            "final_holdout_oov_token_types": len(final_oov),
            "final_holdout_oov_token_examples": final_oov[:20],
        },
        "video_integrity": video_integrity,
        "ctc_capacity": ctc_capacity,
        "duplicate_video_groups_quarantined": duplicate_video_groups,
        "frame_cache": cache_info,
        "source_code_partition": {
            "gradient_train_codes": sorted({row["source_code"] for row in train_rows}),
            "selection_code": args.selection_source_code,
            "final_holdout_code": args.heldout_source_code,
            "excluded_codes": sorted(set(args.exclude_source_codes)),
            "excluded_rows": len(excluded_rows),
            "signer_identity_verified": False,
        },
        "selection": {"source_code": args.selection_source_code, "used_for_checkpoint_selection": True,
                      "previously_used_for_v1_checkpoint_selection": args.selection_source_code == "G"},
        "holdout": {
            "source_code": args.heldout_source_code,
            "metrics": final_metrics,
            "is_signer_independent": False,
            "used_for_checkpoint_selection": False,
            "train_ids_disjoint": True,
            "was_used_in_v1_gradient_train": args.heldout_source_code in set("ABCDEFIJKL"),
            "cross_run_unseen": args.heldout_source_code not in set("ABCDEFIJKL"),
        },
        "device": str(device),
        "python_version": __import__("sys").version,
        "torch_version": torch.__version__,
        "opencv_version": cv2.__version__,
        "tool_sha256": sha(Path(__file__)),
        "cuda": {"available": torch.cuda.is_available(), "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
        "best_epoch": best_epoch,
        "best_selection": history[best_epoch - 1]["selection"] if best_epoch else None,
        "history": history,
        "test_read": False,
        "dev_read": False,
        "text_verified": "",
        "human_approved": False,
        "training_ready": False,
        "model_training_ready": False,
        "deployment_ready": False,
        "demo_integration": False,
        "limitations": [
            "Sequence-level Gloss labels do not provide verified word/frame boundaries.",
            "Source codes are dataset-local identifiers, not verified signer identities.",
            "The final source-code group is disjoint within this run but may have appeared in a prior run's gradient training.",
            "This is a research baseline and not evidence of complete Chinese Sign Language understanding.",
            "No official dev or test files were opened, read, uploaded or evaluated.",
        ],
    }
    _write_json(output / "report.json", report)
    _write_manifest(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--video-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--heldout-source-code", default="H")
    parser.add_argument("--selection-source-code", default="G")
    parser.add_argument("--exclude-source-codes", nargs="*", default=[])
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--image-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--patience", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--blank-penalty-weight", type=float, default=0.1)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--min-gloss-count", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--reuse-frame-cache", type=Path)
    parser.add_argument("--reuse-frame-cache-manifest", type=Path)
    parser.add_argument("--reuse-frame-cache-report", type=Path)
    amp = parser.add_mutually_exclusive_group()
    amp.add_argument("--amp", dest="amp", action="store_true")
    amp.add_argument("--no-amp", dest="amp", action="store_false")
    parser.set_defaults(amp=True)
    args = parser.parse_args()
    print(json.dumps(train(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
