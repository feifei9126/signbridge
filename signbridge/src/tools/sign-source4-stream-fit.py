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
from pathlib import Path, PurePosixPath


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
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


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
    tasks_sha = sha256_file(package / "tasks.jsonl")
    if output.exists() and (output / "report.json").is_file():
        report = json.loads((output / "report.json").read_text())
        if (report.get("tasks_sha256") != tasks_sha or report.get("model") != args.model or
                report.get("preflight", {}).get("actual_commit") != check["actual_commit"]):
            raise ValueError("Resume provenance differs; use a new output attempt")
        report.update(status="running", resumed_at=now(), selected_tasks=len(selected))
        report.pop("finished_at", None)
    else:
        output.mkdir(parents=True, exist_ok=True)
        report = {
            "schema": "signbridge-source4-stream-fit-v1", "status": "running", "created_at": now(),
            "package_tasks": len(tasks), "selected_tasks": len(selected), "completed": [], "failed": [],
            "preflight": check, "model": args.model, "tasks_sha256": tasks_sha,
            "training_started": False, "training_ready": False,
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
            if fit_dir.exists() or case_work.exists():
                raise ValueError("Existing partial evidence; use a fresh output attempt")
            if shutil.disk_usage(output).free < 512 * 1024 * 1024 + task["frames"] * 200000:
                raise ValueError("Insufficient disk space for the next sequence")
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



def audit_results(package, results, output, remote_output_root):
    """Import real streamed fits as raw features; keep motion quality unapproved."""
    import cv2
    import numpy as np

    package, results, output = map(lambda p: Path(p).resolve(), (package, results, output))
    tasks = motion.verify_pack(package)
    task_map = {task["segment_id"]: task for task in tasks}
    report_path = results / "report.json"
    source = json.loads(report_path.read_text())
    if (source.get("schema") != "signbridge-source4-stream-fit-v1" or
            source.get("status") not in {"completed_pending_import_audit", "completed_with_failures_pending_review"} or
            source.get("preflight", {}).get("actual_commit") != motion.SMPLERX_COMMIT or
            source.get("training_ready") is not False or source.get("training_started") is not False):
        raise ValueError("Result report is not a completed, unpromoted SMPLer-X attempt")
    if source.get("tasks_sha256") and source["tasks_sha256"] != sha256_file(package / "tasks.jsonl"):
        raise ValueError("Result task provenance differs")
    completed = source.get("completed", [])
    records = {r["segment_id"]: r for r in source.get("records", [])}
    if (len(set(completed)) != len(completed) or not set(completed).issubset(task_map) or
            set(records) != set(completed) or len(records) != len(source.get("records", []))):
        raise ValueError("Result completion scope or records differ")
    if output.exists():
        raise ValueError("Audit output must be new; preserve previous evidence")
    if any(output == root or output in root.parents or root in output.parents for root in (package, results)):
        raise ValueError("Audit output must be separate from inputs")
    if not PurePosixPath(remote_output_root).is_absolute():
        raise ValueError("An absolute remote output root is required for metadata audit")
    output.mkdir(parents=True)
    converted, rejected = [], []
    for identity in completed:
        task = task_map[identity]
        fit = results / "fits" / identity
        names = {p.name for p in (fit / "smplx").glob("*.npz")}
        missing = [i for i in range(1, task["frames"] + 1) if f"{i:05d}_0.npz" not in names]
        try:
            record = records[identity]
            if any(record.get(k) != task["frames"] for k in ("frames_expected", "parameters", "renders")):
                raise ValueError("Reported frame counts differ from input")
            log = motion.artifact(results, f"logs/{identity}.log")
            if sha256_file(log) != record.get("log_sha256"):
                raise ValueError("Inference log checksum differs")
            parameters = motion.collect_fit(task, fit)
            expected_meta = {f"{i:05d}_0.json" for i in range(1, task["frames"] + 1)}
            expected_render = {f"{i:06d}.jpg" for i in range(1, task["frames"] + 1)}
            if {p.name for p in (fit / "meta").glob("*.json")} != expected_meta:
                raise ValueError("SMPL-X metadata frame set differs")
            if {p.name for p in (fit / "img").glob("*.jpg")} != expected_render:
                raise ValueError("SMPL-X render frame set differs")
            fit_sources = []
            for i in range(1, task["frames"] + 1):
                native = motion.artifact(results, f"fits/{identity}/smplx/{i:05d}_0.npz")
                meta = motion.artifact(results, f"fits/{identity}/meta/{i:05d}_0.json")
                render = motion.artifact(results, f"fits/{identity}/img/{i:06d}.jpg")
                expected = PurePosixPath(remote_output_root) / "work" / identity / "images" / f"{i:06d}.jpg"
                info = json.loads(meta.read_text())
                if info.get("img_path") != str(expected):
                    raise ValueError(f"SMPL-X metadata input frame differs: {i}")
                if cv2.imread(str(render)) is None:
                    raise ValueError(f"Corrupt SMPL-X render: {i}")
                fit_sources.append({"frame_id": i, "parameters_sha256": sha256_file(native),
                                    "metadata_sha256": sha256_file(meta), "render_sha256": sha256_file(render)})
            features = motion.soke_features(parameters)
            sample = output / "samples" / identity
            sample.mkdir(parents=True)
            np.save(sample / "features-133.npy", features, allow_pickle=False)
            times = np.arange(task["frames"], dtype=np.float64) / task["fps"]
            np.savez_compressed(sample / "fitted-smplx.npz", **parameters,
                                timestamps_seconds=times, source_timestamps_seconds=times + task["start_seconds"])
            motion.write_jsonl(sample / "fit-sources.jsonl", fit_sources)
            quality = {key: motion.rotation_quality(parameters[name]) for key, name in
                       (("left_hand", "smplx_lhand_pose"), ("right_hand", "smplx_rhand_pose"), ("body", "smplx_body_pose"))}
            quality.update(motion_review_status="needs_review", model_training_ready=False,
                           limitations=["Finite values and complete frames do not prove correct signing.",
                                        "Review fingers, wrists, mirror orientation, occlusions and temporal jitter."])
            write_json(sample / "quality.json", quality)
            converted.append({**task, "features": str((sample / "features-133.npy").relative_to(output)),
                              "representation": "soke-smplx-133-v1", "dimensions": 133,
                              "smplx_parameters_created": True, "model_training_ready": False,
                              "training_ready": False, "motion_review_status": "needs_review"})
        except (ValueError, OSError, KeyError) as error:
            rejected.append({"segment_id": identity, "reason": str(error),
                             "missing_detection_frames": missing, "interpolated": False})
    motion.write_jsonl(output / "motions.jsonl", converted)
    audit = {"schema": "signbridge-source4-stream-import-audit-v1", "audited_at": now(),
             "converted": len(converted), "frames": sum(t["frames"] for t in converted), "rejected": rejected,
             "unselected": [t["segment_id"] for t in tasks if t["segment_id"] not in completed],
             "source_report_sha256": sha256_file(report_path), "tasks_sha256": sha256_file(package / "tasks.jsonl"),
             "remote_output_root": remote_output_root, "soke_commit": motion.SOKE_COMMIT,
             "normalization": "raw, unnormalized; use checkpoint-specific normalization for training",
             "failed_inference": source.get("failed", []),
             "provenance_limitations": (["Legacy run omitted task digest and checkpoint digest; verify separately captured remote provenance."]
                                        if not source.get("tasks_sha256") else []) +
                                      ["Temporary inference JPEGs were released; source clip/frame count and saved metadata mapping are verified, but original inference JPEG hashes are unavailable."],
             "training_started": False, "training_ready": False,
             "pending": ["Motion quality review", "Mirror and handedness", "Signer grouping and dataset split"]}
    write_json(output / "verification.json", audit)
    files = sorted(p for p in output.rglob("*") if p.is_file())
    (output / "SHA256SUMS").write_text("".join(f"{sha256_file(p)}  {p.relative_to(output)}\n" for p in files))
    print(json.dumps({"converted": audit["converted"], "frames": audit["frames"], "rejected": rejected,
                      "training_ready": False}, ensure_ascii=False))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "audit"], nargs="?", default="run")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--smplerx-root", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--model", default="smpler_x_h32")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--results", type=Path)
    parser.add_argument("--remote-output-root")
    args = parser.parse_args()
    try:
        if args.command == "audit":
            if not args.results or not args.remote_output_root:
                raise ValueError("Audit requires --results and --remote-output-root")
            result = audit_results(args.package, args.results, args.output, args.remote_output_root)
            if result["rejected"] or not result["converted"]:
                raise SystemExit(2)
        else:
            if not args.smplerx_root or not args.python:
                raise ValueError("Run requires --smplerx-root and --python")
            run(args)
    except (OSError, ValueError, subprocess.SubprocessError):
        traceback.print_exc()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
