"""Stream source-4 SMPLer-X fitting on a space-constrained CUDA host."""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sign_motion_stream", HERE / "sign-motion.py")
motion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(motion)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def ffprobe(path):
    ffprobe_bin = shutil.which("ffprobe") or str(Path(sys.executable).with_name("ffprobe"))
    result = subprocess.run([
        ffprobe_bin, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,nb_read_frames", "-of", "json", str(path)
    ], check=True, capture_output=True, text=True)
    stream = json.loads(result.stdout)["streams"][0]
    numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
    return int(stream["nb_read_frames"]), numerator / denominator


def validate_package(package):
    package = Path(package).resolve()
    tasks = read_jsonl(package / "tasks.jsonl")
    if not tasks:
        raise ValueError("source-4 package contains no tasks")
    for task in tasks:
        clip = package / task["clip"]
        observation = package / task["observation_artifact"]
        if not clip.is_file() or sha256_file(clip) != task["clip_sha256"]:
            raise ValueError(f"clip checksum mismatch: {task['segment_id']}")
        if not observation.is_file() or sha256_file(observation) != task["observation_sha256"]:
            raise ValueError(f"observation checksum mismatch: {task['segment_id']}")
        if task.get("training_ready") is not False or task.get("model_training_ready") is not False:
            raise ValueError(f"training flag was promoted: {task['segment_id']}")
        frames, fps = ffprobe(clip)
        if frames != task["frames"] or abs(fps - task["fps"]) > 0.01:
            raise ValueError(f"clip frame contract mismatch: {task['segment_id']}")
    return tasks


def extract_images(clip, images, expected):
    images.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = shutil.which("ffmpeg") or str(Path(sys.executable).with_name("ffmpeg"))
    subprocess.run([
        ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(clip), "-q:v", "2", "-threads", "2", str(images / "%06d.jpg")
    ], check=True, timeout=900)
    files = sorted(images.glob("*.jpg"))
    if len(files) != expected:
        raise ValueError(f"frame extraction mismatch: {len(files)}/{expected}")
    return files


def audit_fit(task, fit_dir, images):
    params = fit_dir / "smplx"
    meta = fit_dir / "meta"
    renders = fit_dir / "img"
    expected = {f"{index:05d}_0.npz" for index in range(1, task["frames"] + 1)}
    files = {path.name for path in params.glob("*.npz")}
    if files != expected:
        raise ValueError(f"SMPL-X parameter set mismatch: {task['segment_id']}")
    render_count = 0
    for index in range(1, task["frames"] + 1):
        image = images / f"{index:06d}.jpg"
        render = renders / f"{index:06d}.jpg"
        if not image.is_file() or not render.is_file():
            raise ValueError(f"missing input/render frame {index}: {task['segment_id']}")
        with __import__("numpy").load(params / f"{index:05d}_0.npz", allow_pickle=False) as values:
            motion.native_parameters(params / f"{index:05d}_0.npz")
        metadata = meta / f"{index:05d}_0.json"
        if not metadata.is_file():
            raise ValueError(f"missing SMPL-X metadata frame {index}: {task['segment_id']}")
        info = json.loads(metadata.read_text())
        if Path(info.get("img_path", "")).resolve() != image.resolve():
            raise ValueError(f"metadata input mismatch: {task['segment_id']} frame {index}")
        render_count += 1
    return {"frames_expected": task["frames"], "parameters": len(files), "renders": render_count}


def run(args):
    package = Path(args.package).resolve()
    root = Path(args.smplerx_root).resolve()
    python = Path(args.python).resolve()
    output = Path(args.output).resolve()
    tasks = validate_package(package)
    check = motion.preflight(root, python, args.model)
    if not check["ready"]:
        raise ValueError("SMPLer-X preflight blocked: " + json.dumps(check, ensure_ascii=False))
    selected = tasks[args.start_index:args.start_index + args.limit if args.limit else None]
    if output.exists() and (output / "report.json").is_file():
        report = json.loads((output / "report.json").read_text())
    else:
        output.mkdir(parents=True, exist_ok=True)
        report = {
            "schema": "signbridge-source4-stream-fit-v1", "status": "running", "created_at": now(),
            "package_tasks": len(tasks), "selected_tasks": len(selected), "completed": [], "failed": [],
            "preflight": check, "model": args.model, "training_started": False, "training_ready": False,
        }
    write_json(output / "report.json", report)
    work = output / "work"; work.mkdir(exist_ok=True)
    fits = output / "fits"; fits.mkdir(exist_ok=True)
    logs = output / "logs"; logs.mkdir(exist_ok=True)
    for index, task in enumerate(selected, args.start_index + 1):
        if task["segment_id"] in report["completed"]:
            continue
        case_work = work / task["segment_id"]
        images = case_work / "images"
        fit_dir = fits / task["segment_id"]
        log_path = logs / f"{task['segment_id']}.log"
        try:
            clip = package / task["clip"]
            extract_images(clip, images, task["frames"])
            argv = [str(python), "inference.py", "--num_gpus", "1", "--pretrained_model", args.model,
                    "--img_path", str(images), "--start", "1", "--end", str(task["frames"]),
                    "--output_folder", str(fit_dir), "--exp_name", str(output / "runtime" / task["segment_id"]),
                    "--show_bbox"]
            log_path.parent.mkdir(exist_ok=True)
            with log_path.open("w") as log:
                env = os.environ.copy(); env.setdefault("PYOPENGL_PLATFORM", "egl"); env.setdefault("MPLBACKEND", "Agg")
                subprocess.run(argv, cwd=root / "main", env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            audit = audit_fit(task, fit_dir, images)
            report["completed"].append(task["segment_id"])
            report.setdefault("records", []).append({"segment_id": task["segment_id"], "index": index, **audit,
                                                       "log_sha256": sha256_file(log_path), "training_ready": False})
            write_json(output / "report.json", report)
            shutil.rmtree(case_work)
            print(json.dumps({"index": index, "total": len(tasks), "segment_id": task["segment_id"], **audit}, ensure_ascii=False), flush=True)
        except Exception as error:
            record = {"segment_id": task["segment_id"], "index": index, "error": str(error),
                      "log": str(log_path), "traceback": traceback.format_exc()}
            report["failed"].append(record)
            write_json(output / "report.json", report)
            if args.stop_on_error:
                raise
    report["status"] = "completed_pending_import_audit" if not report["failed"] else "completed_with_failures_pending_review"
    report["finished_at"] = now()
    write_json(output / "report.json", report)
    print(json.dumps({"status": report["status"], "completed": len(report["completed"]),
                      "failed": len(report["failed"]), "training_ready": False}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--smplerx-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--model", default="smpler_x_h32")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, subprocess.SubprocessError):
        traceback.print_exc()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
