"""Local, offline dataset preparation. This does not train or translate signs."""

import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SEGMENT_FIELDS = [
    "segment_id", "source_id", "start_seconds", "end_seconds",
    "text_candidate", "text_verified", "sample_type", "language", "signer_id",
    "split_group", "split", "semantics_status", "boundaries_status",
    "mirror_status", "reviewer", "notes",
]


def run(args):
    return subprocess.run(args, check=True, capture_output=True)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path):
    data = json.loads(run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ]).stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid video duration: {path}")
    return {
        "duration_seconds": duration,
        "width": video["width"], "height": video["height"],
        "average_fps": float(Fraction(video["avg_frame_rate"])),
        "video_codec": video["codec_name"],
        "audio_tracks": sum(s["codec_type"] == "audio" for s in data["streams"]),
        "subtitle_tracks": sum(s["codec_type"] == "subtitle" for s in data["streams"]),
    }


def contact_sheet(path, duration, output):
    from PIL import Image, ImageDraw, ImageFont
    sheet = Image.new("RGB", (960, 640), "#111827")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=17)
    draw.text((12, 8), f"{duration:.2f} seconds", font=font, fill="white")
    for index, seconds in enumerate([min(12, duration * .1), duration * .25,
                                     duration * .5, duration * .75]):
        image = run([
            "ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(path),
            "-frames:v", "1", "-vf",
            "scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2",
            "-f", "image2pipe", "-vcodec", "png", "-threads", "1", "pipe:1",
        ]).stdout
        x, y = (index % 2) * 480, 42 + (index // 2) * 298
        sheet.paste(Image.open(io.BytesIO(image)).convert("RGB"), (x, y))
        draw.text((x + 10, y + 273), f"{seconds:.2f} s", font=font, fill="white")
    sheet.save(output, quality=88)


def scan(args):
    root, output = args.source_root.resolve(), args.output.resolve()
    if not root.is_dir():
        raise ValueError("Source directory does not exist")
    if output.is_relative_to(root):
        raise ValueError("Keep generated data outside the source directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    (output / "overview").mkdir(exist_ok=True)
    paths = sorted(p for p in root.rglob("*") if p.suffix.lower() in VIDEO_EXTENSIONS and p.is_file())

    def inspect(path):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"Source symlink leaves the selected directory: {path}")
        relative = str(path.relative_to(root))
        checksum = sha256_file(path)
        identity = hashlib.sha256((relative + "\0" + checksum).encode()).hexdigest()[:16]
        source_id = "source-" + identity
        metadata = probe(path)
        preview = "overview/" + source_id + ".jpg"
        contact_sheet(path, metadata["duration_seconds"], output / preview)
        return {
            "source_id": source_id, "relative_path": relative, "sha256": checksum,
            "size_bytes": path.stat().st_size, **metadata,
            "authorization_status": "user_reported" if args.authorization_confirmed else "scope_unverified",
            "authorization_note": args.authorization_note,
            "annotation_status": "needs_segmentation", "overview": preview,
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = list(pool.map(inspect, paths))
    manifest = {
        "schema": "signbridge.sign-sources.v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root), "sources": sources,
        "total_duration_seconds": sum(s["duration_seconds"] for s in sources),
        "total_size_bytes": sum(s["size_bytes"] for s in sources),
    }
    write_json(output / "sources.json", manifest)
    with (output / "videos.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(sources[0]) if sources else ["source_id"])
        writer.writeheader()
        writer.writerows(sources)
    with (output / "segments-template.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        csv.DictWriter(stream, fieldnames=SEGMENT_FIELDS).writeheader()
    print(json.dumps({"sources": len(sources), "seconds": manifest["total_duration_seconds"],
                      "manifest": str(output / "sources.json")}, ensure_ascii=False))


def read_segments(path):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def label_ready(row):
    return all([
        row.get("semantics_status") == "approved",
        row.get("boundaries_status") == "approved",
        bool(row.get("text_verified", "").strip()), bool(row.get("reviewer", "").strip()),
        row.get("mirror_status") in {"normal", "mirrored"},
        bool(row.get("signer_id", "").strip()), row.get("language") == "zh-CSL",
    ])


def validate_segments(manifest, segments):
    sources = {s["source_id"]: s for s in manifest["sources"]}
    seen, assignments, clean = set(), {}, []
    for row in segments:
        row = dict(row)
        segment_id = row.get("segment_id", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", segment_id):
            raise ValueError("Segment IDs must be safe ASCII file names")
        if segment_id in seen:
            raise ValueError(f"Duplicate segment ID: {segment_id}")
        seen.add(segment_id)
        source = sources.get(row.get("source_id"))
        if source is None:
            raise ValueError(f"Unknown source for {segment_id}")
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= source["duration_seconds"]):
            raise ValueError(f"Invalid segment boundaries for {segment_id}")
        row.update(start_seconds=start, end_seconds=end)
        if row.get("semantics_status") not in {"needs_review", "approved", "rejected"}:
            raise ValueError(f"Unknown semantic review status for {segment_id}")
        if row.get("boundaries_status") not in {"needs_review", "approved", "rejected"}:
            raise ValueError(f"Unknown boundary review status for {segment_id}")
        if row.get("mirror_status") not in {"unknown", "normal", "mirrored"}:
            raise ValueError(f"Unknown mirror status for {segment_id}")
        if row.get("semantics_status") == "approved" and not (
            row.get("text_verified", "").strip() and row.get("reviewer", "").strip()
        ):
            raise ValueError(f"Approved semantics require a verified text and reviewer: {segment_id}")
        split = row.get("split") or "unassigned"
        if split not in {"unassigned", "train", "validation", "test"}:
            raise ValueError(f"Unknown split for {segment_id}")
        if split != "unassigned":
            groups = [("content", source["sha256"])]
            for field in ["signer_id", "split_group"]:
                if row.get(field):
                    groups.append((field, row[field]))
            for group in groups:
                if group in assignments and assignments[group] != split:
                    raise ValueError(f"Dataset split leakage: {group[0]} crosses splits")
                assignments[group] = split
        row["split"] = split
        clean.append(row)
    return clean


def source_path(manifest, source):
    root = Path(manifest["source_root"]).resolve()
    path = (root / source["relative_path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Missing source or source path leaves the source directory")
    return path


def landmarks(clip, directory, start_seconds):
    import cv2
    import mediapipe as mp
    import numpy as np

    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        raise ValueError(f"Cannot decode {clip}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    shapes = {"pose_image": (33, 4), "pose_world": (33, 4), "left_hand_image": (21, 3),
              "right_hand_image": (21, 3), "face_image": (468, 3)}
    collected = {name: [] for name in shapes}
    fields = {"pose_image": "pose_landmarks", "pose_world": "pose_world_landmarks",
              "left_hand_image": "left_hand_landmarks", "right_hand_image": "right_hand_landmarks",
              "face_image": "face_landmarks"}
    drawing = mp.solutions.drawing_utils
    holistic_api = mp.solutions.holistic
    temporary_overlay = directory / "overlay-working.avi"
    writer = cv2.VideoWriter(str(temporary_overlay), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise ValueError("Cannot create overlay video")
    try:
        with holistic_api.Holistic(model_complexity=1, smooth_landmarks=True,
                                   refine_face_landmarks=False) as holistic:
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                result = holistic.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                for name, shape in shapes.items():
                    array = np.full(shape, np.nan, dtype=np.float32)
                    found = getattr(result, fields[name])
                    if found is not None:
                        if len(found.landmark) != shape[0]:
                            raise ValueError(f"Unexpected landmark count: {name}")
                        array[:, :3] = [[p.x, p.y, p.z] for p in found.landmark]
                        if shape[1] == 4:
                            array[:, 3] = [p.visibility for p in found.landmark]
                    collected[name].append(array)
                for field, connections, color in [
                    ("pose_landmarks", holistic_api.POSE_CONNECTIONS, (80, 220, 80)),
                    ("left_hand_landmarks", holistic_api.HAND_CONNECTIONS, (0, 220, 255)),
                    ("right_hand_landmarks", holistic_api.HAND_CONNECTIONS, (255, 200, 0)),
                    ("face_landmarks", holistic_api.FACEMESH_CONTOURS, (210, 180, 210)),
                ]:
                    drawing.draw_landmarks(image, getattr(result, field), connections,
                                           drawing.DrawingSpec(color=color, thickness=1, circle_radius=1),
                                           drawing.DrawingSpec(color=color, thickness=1, circle_radius=1))
                cv2.putText(image, "Landmark preview / NOT verified signing", (12, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 1)
                writer.write(image)
    finally:
        capture.release()
        writer.release()
    frames = len(collected["pose_image"])
    if not frames:
        raise ValueError("No frames decoded")
    arrays = {name: np.stack(values) for name, values in collected.items()}
    arrays["timestamps_seconds"] = np.arange(frames, dtype=np.float64) / fps
    arrays["source_timestamps_seconds"] = arrays["timestamps_seconds"] + start_seconds
    coverage = {}
    for name in shapes:
        # This is detection presence, not landmark accuracy or a confidence score.
        mask = np.isfinite(arrays[name][:, :, :3]).all(axis=(1, 2))
        arrays[name + "_detected"] = mask
        coverage[name] = {"detected_frames": int(mask.sum()), "fraction": float(mask.mean())}
    np.savez_compressed(directory / "landmarks.npz", **arrays)
    quality = {
        "schema": "signbridge.landmark-quality.v1", "frames": frames, "fps": fps,
        "width": width, "height": height, "detections": coverage,
        "extractor": "mediapipe-holistic", "extractor_version": mp.__version__,
        "representation": "mediapipe-landmarks-v1", "missing_values": "NaN plus detection masks",
        "coordinates": {
            "pose_image": "x/y image-normalized; z model-relative; visibility in column 4",
            "pose_world": "model-estimated meters; origin between hips; visibility in column 4",
            "hand_image": "x/y image-normalized; z wrist-relative; NOT a shared metric frame",
            "face_image": "x/y image-normalized; z model-relative",
        },
        "model_training_ready": False,
        "limitations": ["Presence is not accuracy", "No SMPL-X fitting or avatar retargeting",
                        "No semantic approval", "No mirroring correction", "No missing-frame interpolation"],
    }
    write_json(directory / "quality.json", quality)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(temporary_overlay), "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(directory / "overlay.mp4")])
    temporary_overlay.unlink()
    return quality


def review_html(records, output):
    cards = []
    for row in records:
        sid = row["segment_id"]
        e = html.escape
        cards.append(f'''<section><h2>{e(row.get('text_candidate', ''))}</h2>
<p>{e(sid)} · 原视频 {row['start_seconds']:.2f}–{row['end_seconds']:.2f} 秒 · 待核验</p>
<p>检测返回帧：左手 {row.get('hand_detection_frames', {}).get('left_hand_image', '—')} / {row['frames']}；
右手 {row.get('hand_detection_frames', {}).get('right_hand_image', '—')} / {row['frames']}。请关注手部参与动作时的缺失。</p>
<div class="pair"><div><h3>原片段</h3><video controls preload="metadata" src="samples/{sid}/clip.mp4"></video></div>
<div><h3>关键点提取预览</h3><video controls preload="metadata" src="samples/{sid}/overlay.mp4"></video></div></div>
<button type="button">同步播放／暂停</button><p>候选释义来自画面文字，尚未确认手语含义、边界和镜像方向。</p></section>''')
    output.write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SignBridge 数据样本核验</title>
<style>body{font-family:system-ui,sans-serif;margin:32px auto;padding:0 24px;max-width:1200px;background:#f5f7fb;color:#182230}
section{background:white;padding:24px;margin:24px 0;border-radius:12px}h1{font-size:28px}h2{font-size:22px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}video{width:100%;background:#111;border-radius:8px}
button{margin-top:16px;padding:10px 18px;background:#164e63;color:white;border:0;border-radius:6px;cursor:pointer}
@media(max-width:720px){.pair{grid-template-columns:1fr}}p{line-height:1.7}</style>
<h1>中国手语数据准备：第一批候选样本</h1>
<p>这是本地数据核验页。预览展示自动提取的身体、双手、面部点；检测到关键点不代表动作或释义正确，也不是可直接用于 SOKE 的 SMPL-X 参数。请在 segments.csv 中记录核验结果。</p>
''' + "\n".join(cards) + '''<script>
for(const section of document.querySelectorAll('section')){
 const [a,b]=section.querySelectorAll('video');
 section.querySelector('button').addEventListener('click',async()=>{
  if(!a.paused||!b.paused){a.pause();b.pause();return;}
  b.currentTime=a.currentTime;
  await Promise.allSettled([a.play(),b.play()]);
 });
 a.addEventListener('seeked',()=>{if(Math.abs(a.currentTime-b.currentTime)>.08)b.currentTime=a.currentTime;});
 for(const v of [a,b])v.addEventListener('ended',()=>{a.pause();b.pause();});
}
</script></html>''')


def prepare(args):
    manifest = json.loads(args.manifest.read_text())
    segments = validate_segments(manifest, read_segments(args.segments))
    sources = {s["source_id"]: s for s in manifest["sources"]}
    output = args.output.resolve()
    if output.is_relative_to(Path(manifest["source_root"]).resolve()):
        raise ValueError("Keep generated data outside the source directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new output directory")
    if args.fps <= 0 or args.max_side < 320:
        raise ValueError("Invalid FPS or image size")
    records, checked = [], set()
    output.mkdir(parents=True, exist_ok=True)
    for row in segments:
        source = sources[row["source_id"]]
        if source.get("authorization_status") not in {"user_reported", "scope_unverified"}:
            raise ValueError("Unknown authorization status in source manifest")
        if row.get("sample_type") not in {"word", "sentence"}:
            raise ValueError("This single-person pilot supports word/sentence segments only")
        path = source_path(manifest, source)
        if row["source_id"] not in checked:
            if sha256_file(path) != source["sha256"]:
                raise ValueError("Source has changed since inventory")
            checked.add(row["source_id"])
        directory = output / "samples" / row["segment_id"]
        directory.mkdir(parents=True, exist_ok=False)
        scale = min(1, args.max_side / max(source["width"], source["height"]))
        width, height = [max(2, int(source[k] * scale) // 2 * 2) for k in ["width", "height"]]
        clip = directory / "clip.mp4"
        run(["ffmpeg", "-v", "error", "-ss", str(row["start_seconds"]), "-i", str(path),
             "-t", str(row["end_seconds"] - row["start_seconds"]), "-an", "-vf",
             f"fps={args.fps},scale={width}:{height}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)])
        quality = landmarks(clip, directory, row["start_seconds"])
        record = {**row, "authorization_status": source["authorization_status"],
                  "hand_detection_frames": {side: quality["detections"][side]["detected_frames"]
                                            for side in ["left_hand_image", "right_hand_image"]},
                  "label_ready": label_ready(row), "model_training_ready": False,
                  "representation": "mediapipe-landmarks-v1", "source_sha256": source["sha256"],
                  "frames": quality["frames"], "fps": quality["fps"],
                  "artifacts": {name: str((directory / name).relative_to(output))
                                for name in ["clip.mp4", "overlay.mp4", "landmarks.npz", "quality.json"]}}
        write_json(directory / "segment.json", record)
        records.append(record)
        print(json.dumps({"segment_id": row["segment_id"], "frames": quality["frames"],
                          "detections": quality["detections"]}, ensure_ascii=False), flush=True)
    (output / "prepared.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    review_html(records, output / "review.html")


def validate_ocr_range(manifest, source_id, start, end):
    source = next((s for s in manifest["sources"] if s["source_id"] == source_id), None)
    if source is None:
        raise ValueError(f"Unknown source: {source_id}")
    if not (math.isfinite(start) and math.isfinite(end) and
            0 <= start < end <= source["duration_seconds"]):
        raise ValueError("Invalid OCR time range")
    if source.get("authorization_status") != "user_reported":
        raise ValueError("OCR source has no recorded user authorization")
    return source


def ocr(args):
    """Sample burned-in lower captions for human review; frame times are approximate."""
    manifest = json.loads(args.manifest.read_text())
    source = validate_ocr_range(manifest, args.source_id, args.start, args.end)
    path = source_path(manifest, source)
    output = args.output.resolve()
    if output.is_relative_to(Path(manifest["source_root"]).resolve()):
        raise ValueError("Keep generated data outside the source directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty; choose a new output directory")
    if args.fps <= 0 or args.fps > 4:
        raise ValueError("OCR sampling rate must be between 1 and 4 FPS")
    if sha256_file(path) != source["sha256"]:
        raise ValueError("Source has changed since inventory")
    frames = output / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-ss", str(args.start), "-i", str(path),
         "-t", str(args.end - args.start), "-vf",
         f"fps={args.fps},crop=iw:ih*0.32:0:ih*0.68", "-q:v", "2",
         str(frames / "frame-%05d.jpg")])
    images = sorted(frames.glob("frame-*.jpg"))
    if not images:
        raise ValueError("No OCR frames extracted")
    swift_tool = Path(__file__).with_name("sign-text-ocr.swift")
    result = run(["swift", str(swift_tool), *map(str, images)])
    lines = [json.loads(line) for line in result.stdout.decode().splitlines()]
    if len(lines) != len(images):
        raise ValueError("OCR results do not match decoded frames")
    with (output / "captions.jsonl").open("w") as stream:
        for index, record in enumerate(lines):
            # ffmpeg fps resampling may shift first/last sample by up to half a frame.
            value = {"source_id": args.source_id,
                     "source_time_approx_seconds": args.start + index / args.fps,
                     "sampling_fps": args.fps, "image": str(images[index].relative_to(output)),
                     "lines": record["lines"], "review_status": "ocr_candidate_only"}
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
    write_json(output / "provenance.json", {
        "source_id": args.source_id, "source_sha256": source["sha256"],
        "authorization_status": source["authorization_status"],
        "time_range_seconds": [args.start, args.end], "sampling_fps": args.fps,
        "images": len(images), "extractor": "macOS Vision VNRecognizeTextRequest",
        "region": "bottom 32% of image", "timestamps": "nominal, check original footage for boundaries",
        "limitations": ["OCR text is not verified sign meaning", "Frame sampling can miss brief captions",
                        "Captions can lag or precede signing", "Only bottom captions inspected"],
    })
    print(json.dumps({"frames": len(images), "output": str(output / "captions.jsonl")}, ensure_ascii=False))


def validate_landmark_arrays(arrays, frames):
    import numpy as np
    shapes = {"pose_image": (33, 4), "pose_world": (33, 4),
              "left_hand_image": (21, 3), "right_hand_image": (21, 3),
              "face_image": (468, 3)}
    for name, shape in shapes.items():
        values, mask = arrays[name], arrays[name + "_detected"]
        if values.shape != (frames, *shape) or mask.shape != (frames,) or mask.dtype != np.bool_:
            raise ValueError(f"Wrong landmark shape or mask for {name}")
        actual = np.isfinite(values[:, :, :3]).all(axis=(1, 2))
        if not np.array_equal(actual, mask):
            raise ValueError(f"Landmark detection mask disagrees with values for {name}")
        if np.any(~mask & np.isfinite(values[:, :, :3]).any(axis=(1, 2))):
            raise ValueError(f"Missing detection contains partial points for {name}")
    for key in ("timestamps_seconds", "source_timestamps_seconds"):
        values = arrays[key]
        if values.shape != (frames,) or not np.isfinite(values).all() or np.any(np.diff(values) <= 0):
            raise ValueError(f"Invalid time series: {key}")


def audit(args):
    """Fully decode sample videos and compare them to saved NPZ arrays."""
    import cv2
    import numpy as np

    batch = args.batch.resolve()
    records = [json.loads(line) for line in (batch / "prepared.jsonl").read_text().splitlines()
               if line.strip()]
    if not records:
        raise ValueError("No prepared samples")
    checked, total = [], 0
    for record in records:
        artifacts = {}
        for name, relative in record["artifacts"].items():
            path = (batch / relative).resolve()
            if not path.is_relative_to(batch) or not path.is_file():
                raise ValueError("Invalid sample artifact path")
            artifacts[name] = path
        frames = int(record["frames"])
        with np.load(artifacts["landmarks.npz"], allow_pickle=False) as arrays:
            validate_landmark_arrays(arrays, frames)
            detected = {key: int(arrays[key + "_detected"].sum()) for key in
                        ["left_hand_image", "right_hand_image", "pose_image", "face_image"]}
        quality = json.loads(artifacts["quality.json"].read_text())
        if quality["frames"] != frames or any(
            detected[key] != quality["detections"][key]["detected_frames"] for key in detected
        ):
            raise ValueError("Quality counts disagree with NPZ")
        for key in ("clip.mp4", "overlay.mp4"):
            capture = cv2.VideoCapture(str(artifacts[key]))
            if not capture.isOpened():
                raise ValueError(f"Cannot open {key}")
            count = 0
            while True:
                decoded, _ = capture.read()
                if not decoded:
                    break
                count += 1
            capture.release()
            if count != frames:
                raise ValueError(f"Fully decoded {key}: {count} frames vs {frames}")
        total += frames
        checked.append({"segment_id": record["segment_id"], "frames": frames,
                        "hand_detected_frames": {key: detected[key] for key in
                                                 ("left_hand_image", "right_hand_image")},
                        "decode_shape_and_mask": "passed", "model_training_ready": False})
    report = {"checked_samples": len(checked), "total_frames": total,
              "results": checked, "note": "Structural check only; no semantic or signing accuracy approval"}
    write_json(batch / "verification.json", report)
    print(json.dumps({"checked_samples": len(checked), "total_frames": total}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scanner = commands.add_parser("scan")
    scanner.add_argument("--source-root", type=Path, required=True)
    scanner.add_argument("--output", type=Path, required=True)
    scanner.add_argument("--authorization-confirmed", action="store_true",
                         help="Use only when every scanned file is user-confirmed for processing")
    scanner.add_argument("--authorization-note", default="")
    scanner.set_defaults(action=scan)
    preparer = commands.add_parser("prepare")
    preparer.add_argument("--manifest", type=Path, required=True)
    preparer.add_argument("--segments", type=Path, required=True)
    preparer.add_argument("--output", type=Path, required=True)
    preparer.add_argument("--fps", type=int, default=25, choices=range(1, 61))
    preparer.add_argument("--max-side", type=int, default=1280, choices=range(320, 3841))
    preparer.set_defaults(action=prepare)
    scanner_ocr = commands.add_parser("ocr", help="Sample burned-in captions offline (macOS only)")
    scanner_ocr.add_argument("--manifest", type=Path, required=True)
    scanner_ocr.add_argument("--source-id", required=True)
    scanner_ocr.add_argument("--start", type=float, required=True)
    scanner_ocr.add_argument("--end", type=float, required=True)
    scanner_ocr.add_argument("--fps", type=int, default=1)
    scanner_ocr.add_argument("--output", type=Path, required=True)
    scanner_ocr.set_defaults(action=ocr)
    auditor = commands.add_parser("audit", help="Fully decode videos and validate saved landmarks")
    auditor.add_argument("--batch", type=Path, required=True)
    auditor.set_defaults(action=audit)
    validator = commands.add_parser("validate")
    validator.add_argument("--manifest", type=Path, required=True)
    validator.add_argument("--segments", type=Path, required=True)
    def validate(args):
        rows = validate_segments(json.loads(args.manifest.read_text()), read_segments(args.segments))
        print(json.dumps({"segments": len(rows), "labels_approved": sum(label_ready(r) for r in rows),
                          "model_training_ready": False}))
    validator.set_defaults(action=validate)
    args = parser.parse_args()
    args.action(args)


if __name__ == "__main__":
    main()
