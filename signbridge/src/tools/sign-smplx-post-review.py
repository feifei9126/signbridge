#!/usr/bin/env python3
"""Build an offline, unapproved all-candidate review from a post-fit audit.

Usage: python3 -B src/tools/sign-smplx-post-review.py --audit /local/audit/report.json
       --output /local/fresh-review --workers 3

Only Python's standard library, node (for the scoped LOCALES export), ffmpeg and
ffprobe are used. No inference, pose filling, interpolation or training occurs.
JPEG sequence names and review_frames are one-based. Each row is retained, even
if malformed; absent metrics stay null. source_sha256 identifies provenance, not
necessarily the candidate clip. The actual clip gets a separate SHA-256.

Exit 0: every requested media asset built; exit 2: failures (report still written
for all rows). Fatal invalid audit/output/setup errors also exit 2. Existing
output directories are never reused. report.json describes counts explicitly;
SHA256SUMS covers every final asset except itself, including report.json.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess


HERE = Path(__file__).resolve().parent
FLAGS = {"human_approved": False, "semantic_approved": False,
         "training_ready": False, "model_training_ready": False,
         "training_started": False, "text_verified": ""}
UNASSESSED = {"collision": "unassessed", "semantic": "unassessed", "human_visual": "unassessed"}
FIELDS = ("uid", "annotation_id", "chunk", "source_id", "source_sha256",
          "label_candidate", "fps", "frames_expected", "missing_detection_frames",
          "status", "quality_tier", "technical_errors", "raw_rotation_metrics",
          "review_frames", "clip_path", "input_directory", "render_directory", "fit_directory")


class MediaError(ValueError):
    def __init__(self, code, detail, **evidence):
        super().__init__(detail)
        self.evidence = {"code": code, "detail": str(detail), **evidence}


def load_pillow():
    try:
        from PIL import Image, ImageOps

        return Image, ImageOps
    except ModuleNotFoundError:
        roots = [HERE.parents[2] / ".venv-wilor", HERE.parents[2] / ".venv-sign-data"]
        runtime = f"python{sys.version_info.major}.{sys.version_info.minor}"
        for root in roots:
            for site in sorted(root.glob("lib/python*/site-packages")):
                if site.parent.name != runtime:
                    continue
                if str(site) not in sys.path:
                    sys.path.insert(0, str(site))
                try:
                    from PIL import Image, ImageOps

                    return Image, ImageOps
                except (ImportError, ModuleNotFoundError):
                    continue
        raise MediaError("pillow_unavailable", "Pillow is required for bounded JPEG contact-sheet composition")


Image, ImageOps = load_pillow()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, data=None, timeout=900):
    try:
        result = subprocess.run(command, input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaError("command_unavailable_or_timeout", str(error), command=command) from error
    # ffmpeg can recover from broken frames and still exit 0. Error-level stderr
    # is a failure as well; never certify a concealed partial decode.
    if result.returncode or result.stderr.strip():
        raise MediaError("media_command_failed", result.stderr.decode("utf-8", errors="replace")[-6000:],
                         command=command, returncode=result.returncode)
    return result.stdout


def ffmpeg(*args, data=None):
    arguments = []
    for value in args:
        if value == "-i":
            arguments.extend(("-protocol_whitelist", "file,pipe"))
        arguments.append(str(value))
    return run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-xerror",
                "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
                *arguments], data=data)


def local_path(value, directory=False):
    if (not isinstance(value, str) or not value or "\x00" in value or "\\" in value
            or any(part in (".", "..") for part in value.split("/"))
            or not value.startswith("/") or value.startswith("//")):
        raise MediaError("unsafe_local_path", "Expected an absolute local path without traversal")
    path = Path(value).resolve(strict=True)
    if not (path.is_dir() if directory else path.is_file()):
        raise MediaError("missing_local_media", value)
    return path


def jpeg(directory, frame):
    root = local_path(directory, directory=True)
    path = root / f"{frame:06d}.jpg"
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise MediaError("unsafe_frame_path", str(path))
    try:
        with Image.open(resolved) as image:
            image.load()
            if image.format != "JPEG":
                raise MediaError("invalid_jpeg", str(path))
    except MediaError:
        raise
    except Exception as error:
        raise MediaError("invalid_jpeg", f"{path}: {error}") from error
    return resolved


def expected_frames(row):
    count = row.get("frames_expected")
    if type(count) is not int or count < 1:
        raise MediaError("invalid_frame_count", "frames_expected must be a positive integer")
    return count


def frame_rate(row):
    value = row.get("fps")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MediaError("invalid_fps", "fps must be a positive finite number or rational")
    try:
        fps = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as error:
        raise MediaError("invalid_fps", str(value)) from error
    if not math.isfinite(float(fps)) or fps <= 0 or fps > 240:
        raise MediaError("invalid_fps", "fps must be in (0, 240]")
    return str(fps)


def validate_video(path, count):
    # Count decoded frames, never container nb_frames alone. Decode all streams
    # separately too, so errors near the end (including audio) are not ignored.
    probe = json.loads(run(["ffprobe", "-v", "error", "-threads", "1", "-count_frames",
                            "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov",
                            "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames,width,height,codec_name,avg_frame_rate",
                            "-of", "json", str(path)]))
    streams = probe.get("streams", [])
    if len(streams) != 1:
        raise MediaError("missing_video_stream", str(path))
    stream = streams[0]
    frames = int(stream.get("nb_read_frames", -1))
    if frames != count:
        raise MediaError("decoded_frame_count_mismatch", f"Expected {count}, decoded {frames}")
    ffmpeg("-f", "mov", "-err_detect", "explode", "-i", path, "-map", "0:v", "-map", "0:a?",
           "-threads", "1", "-f", "null", "-")
    return {"frames": frames, "width": stream["width"], "height": stream["height"],
            "codec": stream["codec_name"], "fps": stream.get("avg_frame_rate")}


def asset(path, output, **metadata):
    return {"path": path.relative_to(output).as_posix(), "sha256": sha256(path), **metadata}


def original_clip(row, folder, output):
    source = local_path(row.get("clip_path"))
    count = expected_frames(row)
    metadata = validate_video(source, count)
    before = sha256(source)
    supplied = row.get("clip_sha256")
    if supplied is not None and supplied != before:
        raise MediaError("clip_hash_mismatch", "Actual original clip differs from clip_sha256")
    path = folder / "original.mp4"
    shutil.copyfile(source, path)
    if sha256(path) != before or sha256(source) != before:
        raise MediaError("source_changed", "Original clip changed during the byte-for-byte copy")
    return asset(path, output, **metadata)


def contact_sheet(row, folder, output):
    count = expected_frames(row)
    frames = row.get("review_frames")
    if (not isinstance(frames, list) or not frames or
            any(type(frame) is not int or not 1 <= frame <= count for frame in frames)):
        raise MediaError("invalid_review_frames", "review_frames must be nonempty one-based integer indices")
    # JPEG dimensions have a 65535 limit. Bound temporary memory, failing
    # explicitly rather than dropping selected frames or changing their order.
    if len(frames) > 180:
        raise MediaError("contact_sheet_size_limit", "At most 180 review frames fit the bounded contact sheet")
    pairs, failures, sources = [], [], []

    def fit_pad(path):
        try:
            with Image.open(path) as image:
                image.load()
                if image.format != "JPEG":
                    raise MediaError("invalid_jpeg", str(path))
                image = ImageOps.contain(image.convert("RGB"), (320, 180))
                canvas = Image.new("RGB", (320, 180), "black")
                canvas.paste(image, ((320 - image.width) // 2, (180 - image.height) // 2))
                return canvas
        except MediaError:
            raise
        except Exception as error:
            raise MediaError("invalid_jpeg", f"{path}: {error}") from error

    for frame in frames:
        try:
            original = jpeg(row.get("input_directory"), frame)
            rendered = jpeg(row.get("render_directory"), frame)
            left, right = fit_pad(original), fit_pad(rendered)
            pair = Image.new("RGB", (640, 180), "black")
            pair.paste(left, (0, 0))
            pair.paste(right, (320, 0))
            pairs.append(pair)
            sources.append({"frame": frame, "input_sha256": sha256(original), "render_sha256": sha256(rendered)})
        except (OSError, ValueError) as error:
            failures.append({"frame": frame, **error_evidence(error)})
    if failures:
        raise MediaError("contact_frames_failed", "Selected original/render JPEG pairs failed", failures=failures)
    height = len(frames) * 180
    path = folder / "contact.jpg"
    sheet = Image.new("RGB", (640, height), "black")
    for index, pair in enumerate(pairs):
        sheet.paste(pair, (0, index * 180))
    sheet.save(path, format="JPEG", quality=90, optimize=False, progressive=False)
    with Image.open(path) as image:
        image.load()
        if image.size != (640, height) or image.format != "JPEG":
            raise MediaError("invalid_contact_pixels", "Contact sheet failed full Pillow decode")
    return asset(path, output, width=640, height=height, review_frames=frames, source_pairs=sources)


def comparison_video(row, folder, output, original):
    count, fps = expected_frames(row), frame_rate(row)
    root = local_path(row.get("render_directory"), directory=True)
    failures = []
    for frame in range(1, count + 1):
        try:
            jpeg(str(root), frame)
        except (OSError, ValueError) as error:
            failures.append({"frame": frame, **error_evidence(error)})
    if failures:
        raise MediaError("render_frames_failed", "Expected render JPEG sequence is incomplete or malformed", failures=failures)
    if not original:
        raise MediaError("original_clip_unavailable", "Comparison requires a validated byte-for-byte original clip")
    # Normalize timestamps by frame index, not an fps filter that fills/duplicates
    # frames. Missing-detection images remain the actual renderer output.
    scale = (f"settb=AVTB,setpts=N/(({fps})*TB),"
             "scale=640:360:force_original_aspect_ratio=decrease:force_divisible_by=2,"
             "pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1")
    path = folder / "comparison.mp4"
    ffmpeg("-f", "mov", "-err_detect", "explode", "-i", folder / "original.mp4", "-threads", "1",
           "-framerate", fps, "-start_number", "1", "-err_detect", "explode",
           "-i", root / "%06d.jpg", "-filter_complex",
           f"[0:v]{scale}[a];[1:v]{scale}[b];[a][b]hstack=inputs=2:shortest=1[v]",
           "-map", "[v]", "-an", "-frames:v", str(count), "-fps_mode", "passthrough",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
           "-threads", "1", "-movflags", "+faststart", path)
    metadata = validate_video(path, count)
    return asset(path, output, **metadata)


def error_evidence(error):
    return error.evidence if isinstance(error, MediaError) else {"code": type(error).__name__, "detail": str(error)}


def finite_metadata(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): finite_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite_metadata(item) for item in value]
    return value


def process_record(index, value, output):
    source = finite_metadata(value) if isinstance(value, dict) else {}
    row = {field: source.get(field) for field in FIELDS}
    row.update(row_index=index, label_status="candidate_only", **FLAGS,
               media={"contact": None, "original": None, "comparison": None},
               failures=[], processed_frames=0, review_status="candidate_only",
               quality_assessments=dict(UNASSESSED))
    if not isinstance(value, dict):
        row["failures"].append({"stage": "record", "code": "invalid_record", "detail": "Audit row must be an object"})
    for key, expected in FLAGS.items():
        if key in source and source[key] != expected:
            row["failures"].append({"stage": "record", "code": "approval_flag_rejected", "detail": key})
    if isinstance(source.get("flags"), dict):
        for key, expected in FLAGS.items():
            if key in source["flags"] and source["flags"][key] != expected:
                row["failures"].append({"stage": "record", "code": "approval_flag_rejected", "detail": "flags." + key})
    uid = source.get("uid")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", uid if isinstance(uid, str) else "candidate").strip("-")[:60] or "candidate"
    folder = output / "media" / f"row-{index:06d}-{slug}"
    folder.mkdir(parents=True)
    tasks = (("original", original_clip), ("contact", contact_sheet), ("comparison", comparison_video))
    for stage, function in tasks:
        try:
            args = (source, folder, output)
            row["media"][stage] = function(*args, row["media"]["original"]) if stage == "comparison" else function(*args)
        except Exception as error:  # One candidate/stage never suppresses subsequent candidates.
            (folder / {"contact": "contact.jpg", "original": "original.mp4", "comparison": "comparison.mp4"}[stage]).unlink(missing_ok=True)
            evidence = error_evidence(error)
            nested = evidence.pop("failures", [])
            row["failures"].append({"stage": stage, **evidence})
            row["failures"].extend({"stage": stage, **item} for item in nested)
    if row["media"]["comparison"]:
        row["processed_frames"] = row["media"]["comparison"]["frames"]
    if row["failures"] or source.get("missing_detection_frames") or source.get("technical_errors") or any(
            token in str(source.get("quality_tier", "")).lower() for token in ("quarantin", "technical_error")):
        row["review_status"] = "quarantined_candidate"
    row["flags"] = dict(FLAGS)
    return row


def scoped_locales():
    script = """import {LOCALES} from './src/i18n/locales.js';
const result = Object.fromEntries(['zh-CN','en','ja'].map(code => [code,
  Object.fromEntries(Object.entries(LOCALES[code]).filter(([key]) => key.startsWith('postFit')))]));
process.stdout.write(JSON.stringify(result));"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=HERE.parents[1],
                            capture_output=True, timeout=20)
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise ValueError("Scoped locale export failed or exceeded 256 KiB")
    locales = json.loads(result.stdout)
    if any(not locales[code].get("postFitTitle") for code in ("zh-CN", "en", "ja")):
        raise ValueError("Post-fit locale strings are missing")
    return locales


def safe_json(value):
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def prepare_output(audit, rows, value):
    raw = Path(value)
    if raw.exists() or raw.is_symlink():
        raise ValueError("Review output must be a fresh directory")
    output = raw.resolve()
    protected = [audit.parent]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in ("clip_path", "input_directory", "render_directory", "fit_directory"):
            path = row.get(field)
            if isinstance(path, str) and path.startswith("/"):
                path = Path(path).resolve()
                protected.append(path.parent if field == "clip_path" else path)
    # Audit and source data can be siblings of the output; source directories
    # themselves cannot contain the output, or be contained by it.
    for path in protected[1:]:
        if output.is_relative_to(path) or path.is_relative_to(output):
            raise ValueError("Review output overlaps immutable source data")
    if audit.is_relative_to(output):
        raise ValueError("Review output contains the audit input")
    output.mkdir(parents=True)
    return output


def build(audit_path, output_path, workers):
    audit = local_path(str(Path(audit_path).absolute()))
    with audit.open(encoding="utf-8") as stream:
        data = json.load(stream, parse_constant=lambda value: None)
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError("Audit must contain records[]")
    rows = data["records"]
    for tool in ("ffmpeg", "ffprobe", "node"):
        if not shutil.which(tool):
            raise ValueError(f"Required installed executable unavailable: {tool}")
    locales = scoped_locales()
    output = prepare_output(audit, rows, output_path)
    records = [None] * len(rows)
    journal_path = output / "progress.jsonl"
    completed = 0
    with journal_path.open("w", encoding="utf-8") as journal, ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_record, index, value, output): index
            for index, value in enumerate(rows)
        }
        for future in as_completed(futures):
            index = futures[future]
            record = future.result()
            records[index] = record
            completed += 1
            entry = {"completed_candidates": completed, "total_candidates": len(rows),
                     "record": {"row_index": index, "uid": record["uid"],
                                "review_status": record["review_status"],
                                "successful_media": sum(asset is not None for asset in record["media"].values()),
                                "failure_count": len(record["failures"]),
                                "processed_frames": record["processed_frames"]}}
            journal.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            if completed % 20 == 0 or completed == len(rows):
                print(json.dumps({"completed_candidates": completed, "total_candidates": len(rows),
                                  "failure_count": sum(len(item["failures"]) for item in records if item)},
                                 separators=(",", ":")), file=sys.stderr, flush=True)
    records = [record for record in records if record is not None]
    summary = {"total_records": len(rows),
               "successful_candidates": sum(not row["failures"] and all(row["media"].values()) for row in records),
               "failed_candidates": sum(bool(row["failures"]) or not all(row["media"].values()) for row in records),
               "successful_media": sum(sum(asset is not None for asset in row["media"].values()) for row in records),
               "failure_count": sum(len(row["failures"]) for row in records),
               "processed_frames": sum(row["processed_frames"] for row in records),
               "frames_expected": sum(row["frames_expected"] for row in records
                                      if type(row["frames_expected"]) is int and row["frames_expected"] > 0),
               "quarantined_candidates": sum(row["review_status"] == "quarantined_candidate" for row in records),
               "label_status": "candidate_only", "quality_assessments": dict(UNASSESSED), **FLAGS}
    report = {"schema": "signbridge-smplx-post-review-v1", "label_status": "candidate_only",
              "audit_path": str(audit), "audit_sha256": sha256(audit), "workers": workers,
              "threads_per_ffmpeg": 1, "quality_assessments": dict(UNASSESSED),
              "summary": summary, "records": records, **FLAGS}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for source, target in (("smplx-post-review.html", "index.html"),
                           ("smplx-post-review.js", "review.js"), ("smplx-post-review.css", "review.css")):
        shutil.copyfile(HERE / source, output / target)
    (output / "review-data.js").write_text(
        "globalThis.SIGNBRIDGE_POST_FIT_LOCALES=" + safe_json(locales) + ";\n"
        "globalThis.SIGNBRIDGE_POST_FIT_REVIEW=" + safe_json(report) + ";\n", encoding="utf-8")
    files = sorted(path for path in output.rglob("*") if path.is_file())
    (output / "SHA256SUMS").write_text("".join(
        f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in files), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 9))
    args = parser.parse_args()
    try:
        report = build(args.audit, args.output, args.workers)
    except Exception as error:
        print(json.dumps({"error": str(error), "label_status": "candidate_only", **FLAGS}), file=sys.stderr)
        return 2
    print(json.dumps({"report": str(Path(args.output).resolve() / "report.json"), **report["summary"]}))
    return 2 if report["summary"]["failure_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
