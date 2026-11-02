#!/usr/bin/env python3
"""Independent, CPU-only native SMPL-X integrity audit and raw motion triage.

Usage: python sign-smplx-post-audit.py --results bundle/results \
    --export-index bundle/export-index.json --output fresh-audit --workers 4

The export index pins chunks/chunk-index.json and each attempt's source manifest
and report. Counts come from that frozen index, never a pilot-specific scope.
Every source manifest must cover its exact file set. No input is rewritten.
Exit 2 means technical errors (report.json is still written); exit 0 includes
quarantine/review outcomes and NEVER grants approval or training readiness.

Metrics pool all joint/transition angles for each body/hand group. Midpoint
residual is distance from the observed middle rotation to the shortest SO(3)
geodesic midpoint of its neighbors, not interpolation of missing observations.
The 180-degree midpoint is inherently nonunique. Thresholds are uncalibrated
review flags, not semantic, collision, anatomical, or signing-quality evidence.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import time

import cv2
import numpy as np
from PIL import Image


SPEC = importlib.util.spec_from_file_location(
    "post_audit_motion", Path(__file__).with_name("sign-motion.py"))
motion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(motion)
FLAGS = {"human_approved": False, "training_ready": False,
         "model_training_ready": False, "text_verified": ""}
REUSED_KIND = "verified_completed_prefix_reconciliation_not_a_new_inference_run"
TIERS = ("technical_error", "missing_detections_quarantine",
         "high_priority_motion_review", "no_automatic_motion_red_flag")
THRESHOLDS = {"adjacent_max_deg": 90.0, "midpoint_max_deg": 30.0,
              "hand_midpoint_p95_deg": 10.0, "calibration": "uncalibrated review flags only"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(errors, label, function, default=None):
    """Retain every encountered failure and continue independent checks."""
    try:
        return function()
    except Exception as error:
        errors.append(f"{label}: {type(error).__name__}: {error}")
        return default


def read_json(path):
    def no_constant(value):
        raise ValueError("Nonfinite JSON number: " + value)
    value = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=no_constant)
    require(isinstance(value, dict), "Expected JSON object: " + str(path))
    return value


def rows(path, errors):
    result = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        def parse():
            value = json.loads(line, parse_constant=lambda value: require(False, "Nonfinite JSON: " + value))
            require(isinstance(value, dict), "Expected JSONL object")
            return value
        result.append(checked(errors, f"{path.name} row {number}", parse, {}))
    return result


def object_list(value, errors, label):
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        errors.append(label + ": expected list of objects")
        return []
    return value


def frame_total(cases):
    return sum(c["frames"] for c in cases if type(c.get("frames")) is int and c["frames"] > 0)


def relative_path(value, dot=False):
    require(isinstance(value, str) and bool(value) and "\\" not in value and "\0" not in value,
            "unsafe relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in value.split("/") and
            (value == "." and dot or (str(path) == value and value != ".")),
            "unsafe relative path: " + value)
    return path


def contained(root, relative, directory=False):
    relative = relative_path(relative, dot=directory)
    root = Path(root)
    path = root.joinpath(*relative.parts)
    cursor = root
    require(not cursor.is_symlink(), "unsafe symlink: " + str(cursor))
    for part in relative.parts:
        cursor = cursor / part
        require(not cursor.is_symlink(), "unsafe symlink: " + str(cursor))
    require(path.resolve().is_relative_to(root.resolve()), "unsafe escaped path: " + str(path))
    require(path.is_dir() if directory else path.is_file(), "Missing artifact: " + str(path))
    return path


def remote_path(value):
    require(isinstance(value, str) and value.startswith("/") and "\\" not in value and "\0" not in value,
            "unsafe remote origin")
    path = PurePosixPath(value)
    require(str(path) == value and not any(p in (".", "..") for p in value.split("/")),
            "unsafe remote origin: " + value)
    return path


class Origins:
    def __init__(self, root, mappings):
        self.root = root
        self.mappings = []
        for item in mappings:
            prefix = remote_path(item["remote_prefix"])
            local = relative_path(item["local_relative"], dot=True)
            require(prefix not in [r for r, _ in self.mappings], "Duplicate origin mapping")
            self.mappings.append((prefix, local))
        self.mappings.sort(key=lambda pair: len(pair[0].parts), reverse=True)

    def directory(self, value):
        path = remote_path(value)
        for prefix, local in self.mappings:
            if path.is_relative_to(prefix):
                relative = local / path.relative_to(prefix)
                return contained(self.root, str(relative), directory=True)
        raise ValueError("Unmapped remote origin: " + value)


def unapproved(value, text=False):
    require(isinstance(value, dict), "Expected unapproved object")
    for key in ("human_approved", "training_ready"):
        require(value.get(key) is False, "approval flag must be false: " + key)
    for key in ("model_training_ready", "training_started", "source_files_modified"):
        if key in value:
            require(value[key] is False, "approval/provenance flag must be false: " + key)
    if text or "text_verified" in value:
        require(value.get("text_verified") == "", "text_verified must stay empty")
    if "text_verified_count" in value:
        require(type(value["text_verified_count"]) is int and value["text_verified_count"] == 0,
                "text_verified_count must stay zero")


class Evidence:
    """Per-chunk cache: shared manifest/provenance reads, bounded by workers."""

    def __init__(self):
        self.hashes = {}
        self.images = set()
        self.images_attempted = set()
        self.native_attempted = set()
        self.videos = {}

    def sha(self, path):
        path = Path(path)
        def fingerprint_of(stat):
            # Reads may update atime; that is not content mutation.
            return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        fingerprint = fingerprint_of(path.stat())
        if path in self.hashes:
            previous, digest = self.hashes[path]
            require(previous == fingerprint, "Evidence changed during audit: " + str(path))
            return digest
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(data)
        require(fingerprint_of(path.stat()) == fingerprint, "Evidence changed during hashing: " + str(path))
        value = digest.hexdigest()
        self.hashes[path] = (fingerprint, value)
        return value

    def jpeg(self, path):
        if path not in self.images:
            self.images_attempted.add(path)
            with Image.open(path) as image:
                require(image.format == "JPEG", "Not a JPEG")
                image.load()  # Decode the entire image, not just its header.
                require(image.width > 0 and image.height > 0, "Empty JPEG")
            self.images.add(path)

    def native(self, path):
        self.native_attempted.add(path)
        return native_parameters(path)

    def video(self, path):
        if path not in self.videos:
            capture = cv2.VideoCapture(str(path))
            try:
                require(capture.isOpened(), "Clip cannot be opened")
                fps = capture.get(cv2.CAP_PROP_FPS)
                declared = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                count = 0
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    require(frame is not None and frame.size > 0, "Empty decoded clip frame")
                    count += 1
                require(count > 0 and math.isfinite(fps) and fps > 0, "Invalid clip decode/FPS")
                require(math.isfinite(declared) and int(round(declared)) == count,
                        "clip_frames: full decode differs from container count")
                self.videos[path] = {"frames": count, "fps": fps}
            finally:
                capture.release()
        return self.videos[path]

    def manifest(self, root, errors, digest=None):
        manifest_path = contained(root, "SHA256SUMS")
        if digest is not None:
            checked(errors, "manifest_sha256", lambda: require(self.sha(manifest_path) == digest,
                                                               "Pinned source manifest hash differs"))
        actual = set()
        for parent, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = Path(parent) / name
                if path.is_symlink():
                    errors.append("manifest: unsafe symlink: " + str(path))
            for name in files:
                path = Path(parent) / name
                if path != manifest_path:
                    actual.add(path.relative_to(root).as_posix())
        listed = {}
        for number, line in enumerate(manifest_path.read_text().splitlines(), 1):
            def entry():
                match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
                require(match is not None, f"Malformed manifest line {number}")
                expected, relative = match.groups()
                relative_path(relative)
                require(relative != "SHA256SUMS" and relative not in listed, "Duplicate/self manifest path: " + relative)
                listed[relative] = expected
                path = contained(root, relative)
                require(self.sha(path) == expected, "File hash mismatch: " + relative)
            checked(errors, "manifest", entry)
        if set(listed) != actual:
            errors.append(f"manifest exact file set differs: missing={sorted(set(listed) - actual)}, unlisted={sorted(actual - set(listed))}")
        # Check even unlisted regular files; there is no hash-based early skip.
        for relative in sorted(actual - set(listed)):
            checked(errors, "manifest_unlisted_hash", lambda r=relative: self.sha(contained(root, r)))
        return actual


def rotation_metrics(poses):
    """SO(3) distances using the Rodrigues math also used in sign-motion.py."""
    values = np.asarray(poses, dtype=np.float64)
    require(values.ndim == 3 and values.shape[1] > 0 and values.shape[2] == 3 and np.isfinite(values).all(),
            "Expected finite [frames,joints,3] axis angles")
    rotations = np.asarray([cv2.Rodrigues(v)[0] for v in values.reshape(-1, 3)]).reshape(*values.shape[:2], 3, 3)

    def degrees(matrix):
        return np.rad2deg(np.arccos(np.clip((np.trace(matrix, axis1=-2, axis2=-1) - 1) / 2, -1, 1)))

    adjacent = degrees(rotations[:-1].swapaxes(-1, -2) @ rotations[1:])
    residual = np.empty((0, values.shape[1]))
    if len(values) > 2:
        relative = rotations[:-2].swapaxes(-1, -2) @ rotations[2:]
        halves = np.asarray([cv2.Rodrigues(cv2.Rodrigues(r)[0] * 0.5)[0]
                             for r in relative.reshape(-1, 3, 3)]).reshape(relative.shape)
        midpoint = rotations[:-2] @ halves
        residual = degrees(midpoint.swapaxes(-1, -2) @ rotations[1:-1])

    def peaks(array, offset):
        ranked = sorted(enumerate(array.max(axis=1) if array.size else []), key=lambda x: (-x[1], x[0]))[:3]
        return [{"frame_1based": int(i + offset), "max_deg": float(value),
                 "joint_0based": int(np.argmax(array[i]))} for i, value in ranked]

    return {"max_adjacent_deg": float(adjacent.max()) if adjacent.size else None,
            "adjacent_p95_deg": float(np.percentile(adjacent, 95)) if adjacent.size else None,
            "midpoint_residual_max_deg": float(residual.max()) if residual.size else None,
            "midpoint_residual_p95_deg": float(np.percentile(residual, 95)) if residual.size else None,
            "adjacent_angle_count": int(adjacent.size), "midpoint_angle_count": int(residual.size),
            "large_jump_frames": (np.flatnonzero((adjacent > THRESHOLDS["adjacent_max_deg"]).any(axis=1)) + 2).tolist(),
            "worst_adjacent_frames": peaks(adjacent, 2), "worst_midpoint_frames": peaks(residual, 2)}


def native_parameters(path):
    # Reuse the generic reader, never its CLI/import/features path. The reader
    # already checks main-array float shapes/finiteness; strengthen its eye and
    # translation checks, which otherwise accept integer arrays.
    params = motion.native_parameters(path)
    with np.load(path, allow_pickle=False) as native:
        for key in ("transl", "leye_pose", "reye_pose"):
            require(native[key].dtype.kind == "f", "FLOAT dtype required: " + key)
    return params


def image_directory(evidence, root, relative, n, errors):
    directory = checked(errors, "JPEG_directory", lambda: contained(root, relative, directory=True))
    if directory is None:
        return None
    names = {p.name for p in directory.iterdir()}
    expected = {f"{i:06d}.jpg" for i in range(1, n + 1)}
    if names != expected:
        errors.append(f"JPEG {relative} frame set differs: missing={sorted(expected - names)}, extra={sorted(names - expected)}")
    for name in sorted(names):
        checked(errors, "JPEG " + relative + "/" + name,
                lambda name=name: evidence.jpeg(contained(directory, name)))
    return directory


def base_record(case, chunk):
    return {"uid": chunk + ":" + str(case.get("annotation_id")),
            **{key: case.get(key) for key in ("annotation_id", "source_id", "source_sha256", "label_candidate", "fps")},
            "chunk": chunk, "frames_expected": case.get("frames"), "missing_detection_frames": [],
            "status": "technical_error", "quality_tier": "technical_error", "technical_errors": [],
            "raw_rotation_metrics": {}, "review_frames": [], "clip_path": None,
            "input_directory": None, "render_directory": None, "fit_directory": None,
            "log_sha256": None, "report_sha256": None, "reused_input_jpegs_verified": 0,
            "feature_extraction_allowed": False, "missing_frames_filled": False, **FLAGS}


def finish_record(row):
    if row["technical_errors"]:
        tier = "technical_error"
        row["raw_rotation_metrics"] = {}
    elif row["missing_detection_frames"]:
        tier = "missing_detections_quarantine"
    elif row.get("motion_review_flags"):
        tier = "high_priority_motion_review"
    else:
        tier = "no_automatic_motion_red_flag"
    row["quality_tier"] = tier
    row["status"] = tier
    return row


def audit_case(case, chunk, package, attempt, report, record, origins, evidence, inherited):
    row = base_record(case, chunk)
    errors = row["technical_errors"]
    errors.extend(inherited)
    sid = case.get("annotation_id")
    checked(errors, "sequence_contract", lambda: motion.safe_id(sid))
    checked(errors, "source_identity", lambda: require(
        isinstance(case.get("source_id"), str) and bool(case["source_id"]) and
        re.fullmatch(r"[0-9a-f]{64}", case.get("source_sha256", "")) is not None and
        isinstance(case.get("label_candidate"), str) and bool(case["label_candidate"].strip()),
        "Source ID, SHA256 or label candidate is invalid"))
    checked(errors, "sequence_approval", lambda: unapproved(case, text=True))
    n = case.get("frames")
    if type(n) is not int or n < 1:
        errors.append("Invalid frames_expected")
        return row
    row["review_frames"] = sorted({1, n})
    fps = case.get("fps")
    checked(errors, "fps", lambda: require(type(fps) in (int, float) and math.isfinite(fps) and fps > 0, "Invalid FPS"))
    clip = checked(errors, "clip_path", lambda: contained(package, case["clip"]))
    if clip:
        row["clip_path"] = str(clip)
        checked(errors, "clip_sha256", lambda: require(evidence.sha(clip) == case.get("clip_sha256"), "Clip hash differs"))
        decoded = checked(errors, "clip_decode", lambda: evidence.video(clip))
        if decoded:
            row["clip_decoded"] = decoded
            checked(errors, "clip_frames", lambda: require(decoded["frames"] == n, "Full clip frame count differs"))
            checked(errors, "clip_fps", lambda: require(abs(decoded["fps"] - fps) <= 0.01, "Clip FPS differs"))
    if attempt is None:
        errors.append("Missing or unsafe attempt")
        return row
    input_dir = image_directory(evidence, attempt, "input-frames/" + str(sid), n, errors)
    render_dir = image_directory(evidence, attempt, "fits/" + str(sid) + "/img", n, errors)
    fit = checked(errors, "fit_directory", lambda: contained(attempt, "fits/" + str(sid), directory=True))
    row.update(input_directory=str(input_dir) if input_dir else None,
               render_directory=str(render_dir) if render_dir else None,
               fit_directory=str(fit) if fit else None)
    row["report_sha256"] = checked(errors, "report_sha256", lambda: evidence.sha(contained(attempt, "report.json")))
    log = checked(errors, "log_path", lambda: contained(attempt, "logs/" + str(sid) + ".log"))
    if log:
        row["log_sha256"] = evidence.sha(log)
        checked(errors, "log_sha256", lambda: require(record is not None and row["log_sha256"] == record.get("log_sha256"), "Log hash differs"))
    source_directory = None
    if report.get("report_kind") == REUSED_KIND:
        def reused():
            matches = [r for r in report.get("reused_input_mapping", []) if r.get("annotation_id") == sid]
            require(len(matches) == 1, "reused mapping must cover ID exactly once")
            mapping = matches[0]
            original = mapping["original_input_directory"]
            require(original == report["original_attempt"] + "/input-frames/" + sid, "reused original directory differs")
            require(mapping["copied_input_directory"] == report["_source_root"] + "/input-frames/" + sid,
                    "reused copied directory differs")
            require(origins.directory(mapping["copied_input_directory"]) == input_dir, "reused local copied directory differs")
            original_local = origins.directory(original)
            image_directory(evidence, original_local, ".", n, errors)
            for frame in range(1, n + 1):
                def compare(frame=frame):
                    name = f"{frame:06d}.jpg"
                    require(evidence.sha(contained(original_local, name)) == evidence.sha(contained(input_dir, name)),
                            "reused original/copied JPEG hash differs: " + name)
                    row["reused_input_jpegs_verified"] += 1
                checked(errors, "reused_JPEG", compare)
            return original
        source_directory = checked(errors, "reused_input_mapping", reused)
    else:
        source_directory = report.get("_source_root", "") + "/input-frames/" + str(sid)
    params, tracks, native_stems, metadata_stems = {}, {}, set(), set()
    native_dir = checked(errors, "native_directory", lambda: contained(fit, "smplx", directory=True)) if fit else None
    meta_dir = checked(errors, "metadata_directory", lambda: contained(fit, "meta", directory=True)) if fit else None
    if native_dir:
        for file in sorted(native_dir.iterdir()):
            match = re.fullmatch(r"(\d{5})_(\d+)\.npz", file.name)
            if not match:
                errors.append("native frame/person filename differs: " + file.name)
            else:
                frame, person = map(int, match.groups())
                native_stems.add(file.stem)
                tracks.setdefault(frame, []).append(person)
                if not 1 <= frame <= n or person != 0:
                    errors.append("native frame/person out of single-person contract: " + file.name)
            values = checked(errors, "native_parameters " + file.name,
                             lambda file=file: evidence.native(contained(native_dir, file.name)))
            if match and values is not None and int(match[2]) == 0:
                params[int(match[1])] = values
    if meta_dir:
        for file in sorted(meta_dir.iterdir()):
            def metadata(file=file):
                match = re.fullmatch(r"(\d{5})_(\d+)\.json", file.name)
                require(match is not None, "Invalid metadata filename")
                metadata_stems.add(file.stem)
                info = read_json(contained(meta_dir, file.name))
                frame, person = map(int, match.groups())
                expected = str(source_directory) + f"/{frame:06d}.jpg"
                require(info.get("img_path") == expected and type(info.get("bbox_id")) is int and info["bbox_id"] == person,
                        "metadata source img_path/frame/person differs")
            checked(errors, "metadata " + file.name, metadata)
    if metadata_stems != native_stems:
        errors.append("metadata/native exact frame/person sets differ")
    missing = sorted(set(range(1, n + 1)) - set(tracks))
    row["missing_detection_frames"] = missing
    row["native_parameter_files"] = len(native_stems)
    if any(people != [0] for people in tracks.values()):
        errors.append("Ambiguous multi-person native track")
    if record is None:
        errors.append("Missing candidate report record")
    else:
        checked(errors, "report_record_approval", lambda: unapproved(record, text=True))
        declared_missing = record.get("smplx_missing_detection_frames")
        checked(errors, "report_missing_detection_frames", lambda: require(
            isinstance(declared_missing, list) and all(type(f) is int and 1 <= f <= n for f in declared_missing) and
            declared_missing == sorted(set(declared_missing)), "Missing detections must be exact ordered integer frame IDs"))
        for key in ("annotation_id", "source_id", "source_sha256", "label_candidate"):
            if record.get(key) != case.get(key):
                errors.append("report_record_identity: " + key)
        for key, expected in (("frames_expected", n), ("render_frames", n),
                              ("smplx_parameter_files", len(native_stems)),
                              ("smplx_missing_detection_frames", missing)):
            if record.get(key) != expected or (type(expected) is int and type(record.get(key)) is not int):
                errors.append("report_" + key + " differs from physical inventory")
    if not errors and not missing:
        for name, key, joints in (("body", "smplx_body_pose", 21), ("left_hand", "smplx_lhand_pose", 15),
                                  ("right_hand", "smplx_rhand_pose", 15)):
            poses = np.stack([params[i][key].reshape(joints, 3) for i in range(1, n + 1)])
            row["raw_rotation_metrics"][name] = rotation_metrics(poses)
        flags, peaks = [], []
        for name, metrics in row["raw_rotation_metrics"].items():
            if (metrics["max_adjacent_deg"] or 0) > THRESHOLDS["adjacent_max_deg"]:
                flags.append(name + ":adjacent_over_90deg")
            if (metrics["midpoint_residual_max_deg"] or 0) > THRESHOLDS["midpoint_max_deg"]:
                flags.append(name + ":midpoint_over_30deg")
            if name != "body" and (metrics["midpoint_residual_p95_deg"] or 0) > THRESHOLDS["hand_midpoint_p95_deg"]:
                flags.append(name + ":midpoint_p95_over_10deg")
            peaks.extend(metrics["worst_adjacent_frames"] + metrics["worst_midpoint_frames"])
        row["motion_review_flags"] = flags
        peak_frames = [p["frame_1based"] for p in sorted(peaks, key=lambda p: (-p["max_deg"], p["frame_1based"]))[:3]]
        row["review_frames"] = sorted({1, n, *(f + offset for f in peak_frames for offset in (-1, 0, 1) if 1 <= f + offset <= n)})
    return finish_record(row)


def audit_chunk(root, chunk, item, origins):
    evidence, errors = Evidence(), []
    name = chunk.get("path", "")
    package = checked(errors, "input_package", lambda: contained(root, "chunks/" + name, directory=True))
    cases = checked(errors, "input_sequences", lambda: rows(contained(package, "sequences.jsonl"), errors), []) if package else []
    aliases = checked(errors, "input_aliases", lambda: rows(contained(package, "aliases.jsonl"), errors), []) if package else []
    if package:
        checked(errors, "input_manifest", lambda: evidence.manifest(package, errors))
        manifest = checked(errors, "package_manifest", lambda: read_json(contained(package, "manifest.json")), {})
        checked(errors, "package_approval", lambda: unapproved(manifest))
        checked(errors, "package_manifest_sha256", lambda: require(evidence.sha(contained(package, "SHA256SUMS")) == chunk["package_manifest_sha256"], "Package SHA256SUMS hash differs"))
        if manifest.get("schema") != "signbridge-smplerx-candidate-sequences-v1":
            errors.append("Unsupported package schema")
        for key, value in (("sequence_count", len(cases)), ("frames", frame_total(cases)),
                           ("candidate_alias_count", len(aliases))):
            if manifest.get(key) != value or chunk.get(key) != value:
                errors.append("input_count_" + key + " differs")
    ids = [c.get("annotation_id") for c in cases]
    if not ids or len(set(ids)) != len(ids):
        errors.append("Input ID coverage empty or duplicate")
    case_map = {c.get("annotation_id"): c for c in cases}
    def check_aliases():
        require(len({a["candidate_id"] for a in aliases}) == len(aliases), "Duplicate candidate alias IDs")
        require({a["fit_sequence_id"] for a in aliases} == set(ids), "Alias input ID coverage differs")
        for alias in aliases:
            unapproved(alias, text=True)
            case = case_map[alias["fit_sequence_id"]]
            require(all(alias[k] == case[k] for k in ("source_id", "source_sha256")), "Alias source identity differs")
            require(alias["candidate_clip_sha256"] == case["clip_sha256"], "Alias clip_sha256 differs")
    checked(errors, "aliases", check_aliases)
    attempt, report, attempt_files = None, {}, set()
    if item is None:
        errors.append("Missing export attempt for " + name)
    else:
        attempt = checked(errors, "attempt_path", lambda: contained(root, item["result_rel"], directory=True))
        if attempt:
            attempt_files = checked(errors, "attempt_manifest", lambda: evidence.manifest(attempt, errors, item["manifest_sha256"]), set())
            if "expected_files" in item and item["expected_files"] != len(attempt_files) + 1:
                errors.append("Export expected_files count differs from attempt")
            checked(errors, "report_sha256", lambda: require(evidence.sha(contained(attempt, "report.json")) == item["report_sha256"], "Pinned report hash differs"))
            report = checked(errors, "attempt_report", lambda: read_json(contained(attempt, "report.json")), {})
            checked(errors, "report_approval", lambda: unapproved(report))
            checked(errors, "attempt_origin", lambda: require(origins.directory(item["source_root"]) == attempt,
                                                             "Physical source_root mapping differs from materialized attempt"))
            if report.get("schema") != "signbridge-smplerx-candidate-sequences-run-v1":
                errors.append("Unsupported attempt report schema")
            if report.get("status") not in ("smplerx_sequences_completed_pending_quality_review",
                                             "smplerx_sequences_accounted_with_quarantined_candidates"):
                errors.append("Attempt report status is not completed")
            if report.get("input_manifest_sha256") != evidence.sha(contained(package, "manifest.json")):
                errors.append("Report/package input manifest linkage differs")
            for key, expected in (("sequence_count", len(cases)), ("completed_sequences", len(cases)),
                                  ("frames_expected", frame_total(cases)),
                                  ("completed_frames", frame_total(cases))):
                if report.get(key) != expected:
                    errors.append("report_count_" + key + " differs")
            report["_source_root"] = item.get("source_root", "")
            for directory, expected in (("input-frames", set(ids)), ("fits", set(ids) | {"runtime"}),
                                        ("logs", {str(sid) + ".log" for sid in ids})):
                def coverage(directory=directory, expected=expected):
                    path = contained(attempt, directory, directory=True)
                    actual = {p.name for p in path.iterdir()}
                    if directory == "fits":
                        actual.discard("runtime")
                        expected = expected - {"runtime"}
                    require(actual == expected, "Candidate directory ID coverage differs: " + directory)
                checked(errors, "ordered_input_ID_coverage", coverage)
            if report.get("report_kind") == REUSED_KIND:
                checked(errors, "reused_input_mapping", lambda: require(
                    [r["annotation_id"] for r in report.get("reused_input_mapping", [])] == ids and
                    report.get("raw_metadata_preserved") is True and report.get("native_parameters_or_images_regenerated") is False,
                    "reused mapping coverage/preservation differs"))
    source_records = object_list(report.get("candidate_records", []), errors, "candidate_records")
    if [r.get("annotation_id") for r in source_records] != ids:
        errors.append("Report ordered input ID coverage differs")
    if any(r.get("sequence_index") != index for index, r in enumerate(source_records, 1)):
        errors.append("Report sequence_index order differs")
    by_id = {r.get("annotation_id"): r for r in source_records}
    result = []
    for case in cases:
        failure = []
        row = checked(failure, "candidate_exception", lambda case=case: audit_case(
            case, name, package, attempt, report, by_id.get(case.get("annotation_id")), origins, evidence, errors))
        if row is None:
            # Preserve an identifiable row even for malformed candidate contracts.
            row = base_record(case, name)
            row["technical_errors"].extend(errors)
            row["technical_errors"].extend(failure or ["Unexpected candidate failure"])
        result.append(row)
    if attempt:
        # Exhaust the inventory even if contracts/IDs are broken. Candidate
        # checks already attempted their own assets, so never decode them twice.
        for relative in sorted(attempt_files):
            path = attempt / relative
            if path.suffix.lower() == ".npz" and path not in evidence.native_attempted:
                checked(errors, "unassigned_native_parameters " + relative,
                        lambda relative=relative: evidence.native(contained(attempt, relative)))
            if path.suffix.lower() in (".jpg", ".jpeg") and path not in evidence.images_attempted:
                checked(errors, "unassigned_JPEG " + relative,
                        lambda relative=relative: evidence.jpeg(contained(attempt, relative)))
        for key, actual in (("complete_sequences", sum(not r["missing_detection_frames"] for r in result)),
                            ("quarantined_sequences", sum(bool(r["missing_detection_frames"]) for r in result))):
            if key in item and item[key] != actual:
                errors.append("Export attempt inventory " + key + " differs")
        for row in result:
            row["technical_errors"].extend(e for e in errors if e not in row["technical_errors"])
            finish_record(row)
    return {"chunk": name, "technical_errors": errors, "records": result,
            "aliases": aliases, "sequences": len(cases), "frames": frame_total(cases)}


TRANSFER_FAILURE_STATES = {"failed", "source_failed", "interrupted", "cancelled"}
TRANSFER_IDENTITY_FIELDS = (
    "key", "kind", "archive_name", "internal_manifest_name", "source_dir", "members",
    "extract_base", "source_root", "result_rel", "chunk", "attempt", "manifest_sha256",
    "report_sha256", "expected_files", "archive_sha256", "archive_bytes",
    "internal_manifest_sha256", "internal_files",
)


def transfer_identity(item):
    return {key: item[key] for key in TRANSFER_IDENTITY_FIELDS if key in item}


def transfer_gate(path, index, attempt_items):
    """Validate transfer proof identities without reading any extracted payload."""
    errors, verified, pending = [], set(), []
    try:
        transfer = read_json(path)
    except (OSError, ValueError) as error:
        return {"status": "waiting_transfer", "terminal": False,
                "errors": ["transfer_report: " + str(error)], "verified": set(), "pending": []}
    if transfer.get("schema") != "signbridge-post-reconstruction-transfer-v1":
        errors.append("transfer_report: unsupported schema")
    status = transfer.get("status")
    source_status = transfer.get("source_status")
    if status in TRANSFER_FAILURE_STATES or source_status in TRANSFER_FAILURE_STATES:
        errors.append("transfer_report: terminal transfer failure")
    if not isinstance(transfer.get("items"), dict):
        errors.append("transfer_report: items must be an object")
        transfer_items = {}
    else:
        transfer_items = transfer["items"]
    for item in index.get("items", []):
        key = item.get("key")
        entry = transfer_items.get(key)
        if not isinstance(entry, dict) or entry.get("status") != "verified":
            pending.append(key)
            continue
        proof = entry.get("proof")
        if not isinstance(proof, dict) or not isinstance(proof.get("identity"), dict):
            errors.append(f"transfer_proof {key}: missing proof identity")
            continue
        identity = proof["identity"]
        for field, expected in transfer_identity(item).items():
            if identity.get(field) != expected:
                errors.append(f"transfer_proof {key}: identity mismatch: {field}")
        for field in ("manifest_sha256", "report_sha256"):
            if field in item and proof.get(field) != item[field]:
                errors.append(f"transfer_proof {key}: {field} mismatch")
        verified.add(key)
    required_keys = {item.get("key") for item in index.get("items", [])}
    attempt_keys = {item.get("key") for item in attempt_items}
    foundational = required_keys - attempt_keys
    if not foundational <= verified:
        errors.append("transfer_proof: foundational payload proofs are incomplete")
    terminal = status in TRANSFER_FAILURE_STATES or source_status in TRANSFER_FAILURE_STATES
    if status == "completed":
        terminal = True
        if pending:
            errors.append("transfer_proof: completed transfer is missing item proofs")
        if not attempt_keys <= verified:
            errors.append("transfer_proof: completed transfer is missing attempt proofs")
    if status not in ("running", "completed", *TRANSFER_FAILURE_STATES):
        errors.append("transfer_report: unsupported status: " + repr(status))
    ready = not pending and foundational <= verified
    return {"status": "transfer_failed" if errors and terminal else "waiting_transfer" if errors or not ready else "transfer_ready",
            "terminal": terminal or (status == "completed"),
            "errors": errors, "verified": verified, "pending": pending,
            "transfer_status": status, "source_status": source_status,
            "report": transfer}


def known_records_without_hashing(root, declared_chunks, reason):
    """Recover IDs for a terminal gate report without trusting or hashing payloads."""
    result = []
    for chunk in declared_chunks:
        name = chunk.get("path")
        try:
            path = contained(root, "chunks/" + name + "/sequences.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                case = json.loads(line)
                if isinstance(case, dict):
                    row = base_record(case, name)
                    row["technical_errors"].append(reason)
                    result.append(finish_record(row))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return result


def write_progress(output, value):
    value = {"schema": "signbridge-smplx-post-audit-progress-v1", **value}
    temporary = output / "progress.json.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output / "progress.json")
    with (output / "progress.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def run(args):
    root = Path(args.results).absolute()
    index_path = Path(args.export_index).absolute()
    output = Path(args.output).absolute()
    require(not output.exists() and not output.is_symlink(), "Output must be a fresh audit directory")
    require(not output.resolve().is_relative_to(root.resolve()) and
            not root.resolve().is_relative_to(output.resolve()) and
            not index_path.resolve().is_relative_to(output.resolve()), "Output must be outside evidence inputs")
    require(1 <= args.workers <= 32, "workers must be between 1 and 32")
    if args.wait_transfer_report:
        require(args.transfer_poll_seconds > 0, "transfer poll interval must be positive")
    output.mkdir(parents=True)
    errors, chunks, records = [], [], []
    report = {"schema": "signbridge-smplx-post-audit-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "results": str(root), "export_index": str(index_path), "thresholds": THRESHOLDS,
              "metric_contract": "Raw local-joint SO3 degrees pooled over all joints and contiguous frame pairs/triples; shortest geodesic midpoint; no smoothing or filling; first frame is 1; peak adjacent ID is destination frame.",
              "limitations": "Uncalibrated review triage only. Angles do not establish semantic correctness, collision freedom, anatomical validity, signer identity or approval. A geodesic midpoint at 180 degrees is nonunique.",
              "audit_complete": False, "technical_errors": errors, "records": records, **FLAGS}
    evidence = Evidence()
    index = checked(errors, "export_index", lambda: read_json(index_path), {})
    checked(errors, "export_approval", lambda: unapproved(index))
    if index.get("schema") != "signbridge-post-reconstruction-export-index-v1":
        errors.append("Unsupported export index schema")
    origins = checked(errors, "origin_mappings unsafe", lambda: Origins(root, index["origin_mappings"]))
    index_file = checked(errors, "chunk_index", lambda: contained(root, "chunks/chunk-index.json"))
    frozen = checked(errors, "chunk_index", lambda: read_json(index_file), {}) if index_file else {}
    if index_file and not args.wait_transfer_report:
        report["input_index_sha256"] = evidence.sha(index_file)
        checked(errors, "input_index_sha256", lambda: require(report["input_index_sha256"] == index.get("input_index_sha256"), "Frozen index hash differs"))
    if frozen.get("schema") != "signbridge-smplerx-candidate-chunk-index-v1":
        errors.append("Unsupported chunk index schema")
    declared_chunks = object_list(frozen.get("chunks", []), errors, "chunks")
    names = [c.get("path") for c in declared_chunks]
    if not names or len(set(names)) != len(names):
        errors.append("Empty or duplicate frozen chunk groups")
    if [c.get("chunk_index_1based") for c in declared_chunks] != list(range(1, len(names) + 1)):
        errors.append("Frozen chunk group ordering differs")
    all_items = object_list(index.get("items", []), errors, "items")
    items = [i for i in all_items if i.get("kind") == "attempt"]
    if len({i.get("chunk") for i in items}) != len(items) or {i.get("chunk") for i in items} != set(names):
        errors.append("Export attempt/frozen chunk ID coverage differs")
    if len({i.get("result_rel") for i in items}) != len(items):
        errors.append("Duplicate export attempt paths")
    item_map = {i.get("chunk"): i for i in items}
    if origins is None:
        origins = Origins(root, [])

    def process(chunk):
        failure = []
        value = checked(failure, "chunk_exception " + str(chunk.get("path")),
                        lambda: audit_chunk(root, chunk, item_map.get(chunk.get("path")), origins))
        return value if value is not None else {"chunk": chunk.get("path"), "technical_errors": failure,
                                                "records": [], "aliases": [], "sequences": 0, "frames": 0}

    processed = {}

    def process_selected(selected, gate=None):
        if not selected:
            return
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            values = list(pool.map(process, selected))
        for value in values:
            processed[value["chunk"]] = value
            write_progress(output, {
                "status": "auditing" if gate else "auditing_without_transfer_gate",
                "transfer_status": gate.get("transfer_status") if gate else None,
                "chunks_verified": len(gate["verified"]) if gate else None,
                "chunks_total": len(declared_chunks), "chunks_processed": len(processed),
                "chunk": value["chunk"], "chunk_technical_errors": value["technical_errors"],
            })

    gate = None
    if args.wait_transfer_report:
        transfer_path = Path(args.wait_transfer_report).absolute()
        while True:
            gate = transfer_gate(transfer_path, index, items)
            if gate["status"] == "transfer_ready" and index_file and "input_index_sha256" not in report:
                report["input_index_sha256"] = evidence.sha(index_file)
                checked(errors, "input_index_sha256", lambda: require(
                    report["input_index_sha256"] == index.get("input_index_sha256"), "Frozen index hash differs"))
            verified_chunk_names = {item.get("chunk") for item in items if item.get("key") in gate["verified"]}
            selected = [chunk for chunk in declared_chunks
                        if chunk.get("path") in verified_chunk_names and chunk.get("path") not in processed]
            if selected and gate["status"] == "transfer_ready":
                process_selected(selected, gate)
            write_progress(output, {
                "status": gate["status"], "transfer_status": gate.get("transfer_status"),
                "source_status": gate.get("source_status"), "gate_errors": gate["errors"],
                "chunks_verified": len(verified_chunk_names), "chunks_total": len(declared_chunks),
                "chunks_processed": len(processed), "chunks_pending": len(declared_chunks) - len(processed),
            })
            if gate["terminal"]:
                errors.extend(gate["errors"])
                if gate.get("transfer_status") != "completed" or gate["errors"] or len(processed) != len(declared_chunks):
                    errors.append("transfer_gate: terminal transfer did not prove/process all attempts")
                break
            time.sleep(args.transfer_poll_seconds)
    else:
        process_selected(declared_chunks)

    def unprocessed_chunk(chunk, reason):
        name = chunk.get("path")
        result = []
        aliases = []
        try:
            sequence_path = contained(root, "chunks/" + name + "/sequences.jsonl")
            for line in sequence_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    case = json.loads(line)
                    if isinstance(case, dict):
                        row = base_record(case, name)
                        row["technical_errors"].append(reason)
                        result.append(finish_record(row))
            alias_path = contained(root, "chunks/" + name + "/aliases.jsonl")
            aliases = [json.loads(line) for line in alias_path.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {"chunk": name, "technical_errors": [reason], "records": result, "aliases": aliases,
                "sequences": len(result), "frames": sum(r.get("frames_expected") or 0 for r in result)}

    chunks = []
    for frozen_chunk in declared_chunks:
        name = frozen_chunk.get("path")
        if name in processed:
            chunks.append(processed[name])
        elif args.wait_transfer_report:
            chunks.append(unprocessed_chunk(frozen_chunk, "transfer_not_verified_or_not_processed"))
    if not args.wait_transfer_report:
        chunks = [processed[name] for name in names if name in processed]
    for chunk in chunks:
        records.extend(chunk["records"])
        errors.extend(chunk["technical_errors"])
    all_aliases = [a for chunk in chunks for a in chunk["aliases"]]
    if len({a.get("candidate_id") for a in all_aliases}) != len(all_aliases):
        errors.append("Cross-chunk alias IDs repeat")
    if len({r["annotation_id"] for r in records}) != len(records):
        errors.append("Cross-chunk input sequence IDs repeat")
    total_frames = sum(c["frames"] for c in chunks)
    for key, actual in (("sequence_count", len(records)), ("candidate_alias_count", len(all_aliases)), ("frame_count", total_frames)):
        if frozen.get(key) != actual:
            errors.append("Frozen total " + key + " differs")
    for key, actual in (("sequences_total", len(records)), ("frames_total", total_frames)):
        if index.get(key) != actual:
            errors.append("Export total " + key + " differs")
    for key, actual in (("structurally_complete", sum(not r["missing_detection_frames"] for r in records)),
                        ("quarantined", sum(bool(r["missing_detection_frames"]) for r in records))):
        if key in index and index[key] != actual:
            errors.append("Export inventory total " + key + " differs")
    # Global coverage/hash faults invalidate the delivery, but local candidate
    # failures do not erase independent good candidates or their diagnostics.
    global_errors = [e for e in errors if e not in {e for c in chunks for e in c["technical_errors"]}]
    for row in records:
        row["technical_errors"].extend(global_errors)
        finish_record(row)
    counts = Counter(row["quality_tier"] for row in records)
    report["chunks"] = [{k: c[k] for k in ("chunk", "sequences", "frames", "technical_errors")} for c in chunks]
    report["summary"] = {"chunks": len(chunks), "sequences": len(records), "aliases": len(all_aliases),
                         "frames_expected": total_frames, "quality_tiers": {tier: counts[tier] for tier in TIERS},
                         "promotion_blocked": bool(errors or counts["technical_error"]),
                         "missing_detection_frames": sum(len(r["missing_detection_frames"]) for r in records),
                         "attempt_proofs_verified": len(gate["verified"] & {item.get("key") for item in items}) if gate else None}
    report["audit_complete"] = (not args.wait_transfer_report or
                                 (gate is not None and gate.get("transfer_status") == "completed" and
                                  not gate.get("errors") and len(processed) == len(declared_chunks)))
    report["status"] = "technical_error" if report["summary"]["promotion_blocked"] else "audit_completed_pending_human_review"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (output / "records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records))
    print(json.dumps({"output": str(output), "status": report["status"], **report["summary"]}, ensure_ascii=False))
    return 2 if report["summary"]["promotion_blocked"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--export-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--wait-transfer-report", type=Path,
                        help="Wait for contained transfer-report.json proofs before auditing attempts")
    parser.add_argument("--transfer-poll-seconds", type=float, default=5.0,
                        help="Polling interval for --wait-transfer-report")
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
