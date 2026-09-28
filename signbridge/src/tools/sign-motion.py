"""Prepare reviewed clips for SMPLer-X and convert its real fits to SOKE features."""

import argparse
import csv
import importlib.util
import json
import pickle
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("sign_data", Path(__file__).with_name("sign-data.py"))
data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data)

SMPLERX_COMMIT = "064baef0e4ab5277a3297691bc1d46ea5412586f"
SOKE_COMMIT = "5cbc55d84b5a7cbf05a9cf020c468052e8d94d00"
# Order in SOKE's load_data.py, followed by dropping [:36] and shape [159:169].
PARAMETERS = [
    ("global_orient", "smplx_root_pose", (1, 3)),
    ("body_pose", "smplx_body_pose", (21, 3)),
    ("left_hand_pose", "smplx_lhand_pose", (15, 3)),
    ("right_hand_pose", "smplx_rhand_pose", (15, 3)),
    ("jaw_pose", "smplx_jaw_pose", (1, 3)),
    ("betas", "smplx_shape", (1, 10)),
    ("expression", "smplx_expr", (1, 10)),
]


def now():
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_jsonl(path, records):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("Segment IDs must be safe ASCII file names")
    return value


def artifact(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing artifact or path outside its batch: {relative}")
    return path


def new_output(path, protected=()):
    path = Path(path).resolve()
    if any(path.is_relative_to(Path(root).resolve()) for root in protected):
        raise ValueError("Keep outputs outside input directories")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("Output is not empty; choose a new versioned directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def confirm_rows(manifest, segments, prepared, reviewer):
    if not reviewer.strip() or not segments:
        raise ValueError("A reviewer and nonempty annotations are required")
    segments = data.validate_segments(manifest, segments)
    by_id = {safe_id(p["segment_id"]): p for p in prepared}
    if len(by_id) != len(prepared) or set(by_id) != {r["segment_id"] for r in segments}:
        raise ValueError("Approval must match the exact current prepared batch")
    sources = {s["source_id"]: s for s in manifest["sources"]}
    approved = []
    for row in segments:
        sample = by_id[row["segment_id"]]
        for key in ("source_id", "start_seconds", "end_seconds", "text_candidate"):
            if sample[key] != row[key]:
                raise ValueError(f"Prepared sample and annotation differ: {row['segment_id']} / {key}")
        source = sources[row["source_id"]]
        if (source.get("authorization_status") != "user_reported" or
                sample.get("source_sha256") != source["sha256"]):
            raise ValueError("Source authorization or hash differs from the prepared batch")
        if "rejected" in (row["semantics_status"], row["boundaries_status"]):
            raise ValueError("A rejected sample needs an explicit corrected annotation")
        text = (row.get("text_verified") or row.get("text_candidate") or "").strip()
        if not text:
            raise ValueError("Approval requires an existing meaning for every sample")
        approved.append({**sample, **row, "text_verified": text, "reviewer": reviewer,
                         "semantics_status": "approved", "boundaries_status": "approved",
                         "model_training_ready": False})
        approved[-1]["label_ready"] = data.label_ready(approved[-1])
    return approved


def review(args):
    if not args.statement.strip():
        raise ValueError("Save the actual review confirmation statement")
    manifest = json.loads(args.manifest.read_text())
    records = confirm_rows(manifest, data.read_segments(args.segments),
                           read_jsonl(args.batch / "prepared.jsonl"), args.reviewer)
    output = new_output(args.output, (args.batch, Path(manifest["source_root"])))
    decision = {
        "schema": "signbridge-content-review-v1", "created_at": now(),
        "basis": "user_reported_manual_review", "statement": args.statement,
        "reviewer": args.reviewer, "interpretation": "Existing meanings and ranges accepted without edits",
        "approved_fields": ["text_verified", "semantics_status", "boundaries_status"],
        "unconfirmed_fields": ["mirror orientation", "cross-video signer identity", "SMPL-X motion quality"],
        "inputs": {"annotations_sha256": data.sha256_file(args.segments),
                   "prepared_sha256": data.sha256_file(args.batch / "prepared.jsonl")},
        "samples": [{k: r[k] for k in ("segment_id", "source_id", "source_sha256",
                     "start_seconds", "end_seconds", "text_verified")} for r in records],
    }
    data.write_json(output / "review-decision.json", decision)
    decision_hash = data.sha256_file(output / "review-decision.json")
    for record in records:
        record.update(artifact_base_dir=str(args.batch.resolve()), review_decision_sha256=decision_hash)
    with (output / "segments.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=data.SEGMENT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    write_jsonl(output / "reviewed.jsonl", records)
    print(json.dumps({"reviewed_samples": len(records), "output": str(output)}, ensure_ascii=False))
    return 0


def export(args):
    import cv2

    records = read_jsonl(args.reviewed / "reviewed.jsonl")
    if not records:
        raise ValueError("No reviewed samples")
    decision_hash = data.sha256_file(args.reviewed / "review-decision.json")
    decision = json.loads((args.reviewed / "review-decision.json").read_text())
    decisions = {r["segment_id"]: r for r in decision["samples"]}
    if len(decisions) != len(records) or len({r["segment_id"] for r in records}) != len(records):
        raise ValueError("Review decision and sample set differ")
    for row in records:
        safe_id(row["segment_id"])
        if row.get("review_decision_sha256") != decision_hash:
            raise ValueError("Review decision changed; record the corrected review as a new version")
        approved = decisions.get(row["segment_id"], {})
        if (any(row.get(k) != v for k, v in approved.items()) or
                row.get("semantics_status") != "approved" or row.get("boundaries_status") != "approved"):
            raise ValueError("Sample meaning or boundaries differ from its review decision")
    protected = [args.reviewed, *(r["artifact_base_dir"] for r in records)]
    output = new_output(args.output, protected)
    tasks, checksums = [], []
    for row in records:
        sample = output / "samples" / row["segment_id"]
        images = sample / "images"
        images.mkdir(parents=True)
        base = Path(row["artifact_base_dir"])
        clip = artifact(base, row["artifacts"]["clip.mp4"])
        tracks = artifact(base, row["artifacts"]["landmarks.npz"])
        with np.load(tracks, allow_pickle=False) as arrays:
            data.validate_landmark_arrays(arrays, row["frames"])
            times = np.array(arrays["timestamps_seconds"])
            source_times = np.array(arrays["source_timestamps_seconds"])
            if not np.allclose(times, np.arange(row["frames"]) / row["fps"], atol=1e-6):
                raise ValueError("Landmark timestamps do not match the clip frame rate")
            if not np.allclose(source_times, times + row["start_seconds"], atol=1e-5):
                raise ValueError("Source timestamps do not match the reviewed segment")
        capture = cv2.VideoCapture(str(clip))
        frames, frame_records = 0, []
        try:
            if not capture.isOpened() or abs(capture.get(cv2.CAP_PROP_FPS) - row["fps"]) > 1e-6:
                raise ValueError("Clip frame rate differs from annotations")
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                if frames >= row["frames"]:
                    raise ValueError("Clip has more frames than its observation tracks")
                frames += 1
                path = images / f"{frames:06d}.jpg"
                if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                    raise ValueError("Cannot save fitting image")
                relative = str(path.relative_to(output))
                checksum = data.sha256_file(path)
                frame_records.append({"frame_id": frames, "image": relative, "sha256": checksum,
                                      "clip_seconds": float(times[frames - 1]),
                                      "source_seconds_nominal": float(source_times[frames - 1])})
                checksums.append(f"{checksum}  {relative}\n")
            if frames != row["frames"]:
                raise ValueError("Clip frame count differs from its observation tracks")
        finally:
            capture.release()
        shutil.copyfile(clip, sample / "clip.mp4")
        shutil.copyfile(tracks, sample / "observations.npz")
        write_jsonl(sample / "frames.jsonl", frame_records)
        task = {k: row[k] for k in ("segment_id", "source_id", "source_sha256", "start_seconds",
                "end_seconds", "text_verified", "language", "signer_id", "split_group", "split",
                "mirror_status", "reviewer", "authorization_status", "review_decision_sha256")}
        task.update(frames=frames, fps=row["fps"], content_reviewed=True, model_training_ready=False,
                    images=str(images.relative_to(output)), clip=f"samples/{row['segment_id']}/clip.mp4",
                    frame_manifest=f"samples/{row['segment_id']}/frames.jsonl",
                    clip_sha256=data.sha256_file(clip),
                    observation_representation="mediapipe-landmarks-v1", image_transform="none",
                    motion_review_status="not_fitted")
        tasks.append(task)
        for name in ("clip.mp4", "observations.npz", "frames.jsonl"):
            path = sample / name
            checksums.append(f"{data.sha256_file(path)}  {path.relative_to(output)}\n")
        print(json.dumps({"segment_id": row["segment_id"], "fitting_frames": frames}), flush=True)
    write_jsonl(output / "tasks.jsonl", tasks)
    shutil.copyfile(args.reviewed / "review-decision.json", output / "review-decision.json")
    data.write_json(output / "contract.json", {
        "schema": "signbridge-smplerx-input-v1", "created_at": now(),
        "samples": len(tasks), "frames": sum(t["frames"] for t in tasks),
        "smplerx_commit": SMPLERX_COMMIT, "soke_commit": SOKE_COMMIT,
        "image_naming": "1-based %06d.jpg; preserve prepared clip FPS, no interpolation or mirroring",
        "observation_coordinates": "Original MediaPipe arrays; body/hand/face z are not one metric frame",
        "expected_output": "<fit-output>/<segment_id>/smplx/%05d_0.npz",
        "fit_semantics": "SMPLer-X per-frame estimates, use_pca=False, flat_hand_mean=False",
        "soke_feature_dimensions": 133, "model_training_ready": False,
    })
    for name in ("tasks.jsonl", "contract.json", "review-decision.json"):
        path = output / name
        checksums.append(f"{data.sha256_file(path)}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums))
    print(json.dumps({"samples": len(tasks), "frames": sum(t["frames"] for t in tasks),
                      "output": str(output)}, ensure_ascii=False))
    return 0


def verify_pack(batch):
    batch = Path(batch).resolve()
    for line in (batch / "SHA256SUMS").read_text().splitlines():
        checksum, relative = line.split("  ", 1)
        if data.sha256_file(artifact(batch, relative)) != checksum:
            raise ValueError(f"Fitting input checksum changed: {relative}")
    tasks = read_jsonl(batch / "tasks.jsonl")
    if not tasks or len({safe_id(t["segment_id"]) for t in tasks}) != len(tasks):
        raise ValueError("Invalid fitting task IDs")
    contract = json.loads((batch / "contract.json").read_text())
    if (contract.get("schema") != "signbridge-smplerx-input-v1" or
            contract.get("smplerx_commit") != SMPLERX_COMMIT):
        raise ValueError("Unsupported fitting input contract")
    for task in tasks:
        frames = read_jsonl(artifact(batch, task["frame_manifest"]))
        if not (isinstance(task["frames"], int) and task["frames"] >= 4 and
                np.isfinite(task["fps"]) and task["fps"] > 0 and len(frames) == task["frames"]):
            raise ValueError("Invalid fitting frame count or frame rate")
        images = artifact(batch, frames[0]["image"]).parent
        if images != (batch / task["images"]).resolve():
            raise ValueError("Frame directory differs from fitting task")
        for index, frame in enumerate(frames, 1):
            path = artifact(batch, frame["image"])
            if (frame["frame_id"] != index or path != images / f"{index:06d}.jpg" or
                    data.sha256_file(path) != frame["sha256"]):
                raise ValueError("Fitting images changed or are not contiguous")
        if data.sha256_file(artifact(batch, task["clip"])) != task["clip_sha256"]:
            raise ValueError("Fitting reference clip changed")
    return tasks


def fitting_command(task, batch, root, python, output, model):
    # Official --end is a COUNT: range(start, start + end), not a last-frame index.
    return [str(python), "inference.py", "--num_gpus", "1", "--pretrained_model", model,
            "--img_path", str((batch / task["images"]).resolve()), "--start", "1",
            "--end", str(task["frames"]), "--output_folder", str(output / task["segment_id"]),
            "--exp_name", str(output / "runtime" / task["segment_id"]), "--show_bbox"]


def preflight(root, python, model):
    vitpose = {"smpler_x_s32": "vitpose_small.pth", "smpler_x_b32": "vitpose_base.pth",
               "smpler_x_l32": "vitpose_large.pth", "smpler_x_h32": "vitpose_huge.pth"}[model]
    required = ["main/inference.py", f"main/config/config_{model}.py",
                f"pretrained_models/{model}.pth.tar", f"pretrained_models/{vitpose}",
                "pretrained_models/mmdet/faster_rcnn_r50_fpn_1x_coco_20200130-047c8118.pth",
                "pretrained_models/mmdet/mmdet_faster_rcnn_r50_fpn_coco.py"]
    body = "common/utils/human_model_files"
    required += [f"{body}/smplx/{name}" for name in ["SMPLX_NEUTRAL.npz", "SMPLX_MALE.npz",
                 "SMPLX_FEMALE.npz", "SMPLX_to_J14.pkl", "MANO_SMPLX_vertex_ids.pkl",
                 "SMPL-X__FLAME_vertex_ids.npy"]]
    required += [f"{body}/smpl/SMPL_{gender}.pkl" for gender in ["NEUTRAL", "MALE", "FEMALE"]]
    missing = [str(root / name) for name in required if not (root / name).is_file()]
    revision = None
    if (root / ".git").exists():
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                  capture_output=True, text=True, check=True).stdout.strip()
    probe = """import importlib.util, json
names = ['torch', 'torchvision', 'cv2', 'smplx', 'mmcv', 'mmdet', 'mmpose', 'timm', 'pyrender']
missing = [name for name in names if importlib.util.find_spec(name) is None]
cuda = False
if 'torch' not in missing:
    import torch
    cuda = torch.cuda.is_available()
print(json.dumps({'missing_modules': missing, 'cuda_available': cuda}))
"""
    try:
        result = subprocess.run([str(python), "-c", probe], capture_output=True, text=True, timeout=30)
        runtime = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {
            "error": result.stderr[-2000:], "cuda_available": False}
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        runtime = {"error": str(exc), "cuda_available": False}
    return {"missing_files": missing, "expected_commit": SMPLERX_COMMIT,
            "actual_commit": revision, "runtime": runtime,
            "ready": not missing and revision == SMPLERX_COMMIT and
                     runtime.get("cuda_available", False) and not runtime.get("missing_modules") and
                     not runtime.get("error")}


def fit(args):
    batch, root = args.batch.resolve(), args.smplerx_root.resolve()
    tasks = verify_pack(batch)
    if args.segment_id:
        tasks = [t for t in tasks if t["segment_id"] in args.segment_id]
        if set(args.segment_id) != {t["segment_id"] for t in tasks}:
            raise ValueError("Unknown requested fitting segment")
    output = new_output(args.output, (batch, root))
    python = args.python.absolute()
    check = preflight(root, python, args.model)
    jobs = [{"segment_id": t["segment_id"], "cwd": str(root / "main"),
             "argv": fitting_command(t, batch, root, python, output, args.model)} for t in tasks]
    plan = {"schema": "signbridge-smplerx-run-v1", "created_at": now(), "preflight": check,
            "model": args.model, "tasks_sha256": data.sha256_file(batch / "tasks.jsonl"),
            "jobs": jobs, "status": "planned" if check["ready"] else "blocked", "completed": []}
    data.write_json(output / "run.json", plan)
    (output / "commands.txt").write_text("\n".join(
        f"(cd {shlex.quote(j['cwd'])} && {shlex.join(j['argv'])})" for j in jobs) + "\n")
    missing_files = check.get("missing_files", [])
    runtime = check.get("runtime", {})
    report_lines = [
        "# SMPLer-X 拟合运行检查", "", f"状态：`{plan['status']}`", "",
        f"输入样本：{len(tasks)} 段", f"输入清单 SHA-256：`{plan['tasks_sha256']}`",
        f"SMPLer-X 提交：`{check.get('actual_commit')}`", f"要求提交：`{check.get('expected_commit')}`", "",
        "## 缺少的文件", "", *([f"- `{path}`" for path in missing_files] or ["- 无"]),
        "", "## 运行环境", "", f"- CUDA 可用：`{runtime.get('cuda_available', False)}`",
        f"- 缺少 Python 模块：`{', '.join(runtime.get('missing_modules', [])) or '无'}`",
        "", "完整检查见 `run.json`；命令见 `commands.txt`。"
    ]
    (output / "REPORT.md").write_text("\n".join(report_lines) + "\n")
    if args.dry_run or not check["ready"]:
        print(json.dumps({"status": plan["status"], "preflight": check,
                          "run_report": str(output / "run.json")}, ensure_ascii=False))
        return 0 if args.dry_run else 2
    for job in jobs:
        log = output / (job["segment_id"] + ".log")
        with log.open("w") as stream:
            result = subprocess.run(job["argv"], cwd=job["cwd"], stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            plan.update(status="failed", failed_job=job["segment_id"], exit_code=result.returncode)
            data.write_json(output / "run.json", plan)
            return 2
        plan["completed"].append(job["segment_id"])
        data.write_json(output / "run.json", plan)
    plan["status"] = "inferred_pending_import_audit"
    data.write_json(output / "run.json", plan)
    return 0


def native_parameters(path):
    with np.load(path, allow_pickle=False) as native:
        params = {}
        for source, target, shape in PARAMETERS:
            if source not in native:
                raise ValueError(f"Missing fitted parameter: {source}")
            values = native[source]
            if values.shape != shape or values.dtype.kind != "f" or not np.isfinite(values).all():
                raise ValueError(f"Invalid fitted parameter (requires full axis-angle, not PCA): {source}")
            params[target] = values.reshape(-1).astype(np.float32)
        for name in ("transl", "leye_pose", "reye_pose"):
            if name not in native or native[name].shape != (1, 3) or not np.isfinite(native[name]).all():
                raise ValueError(f"Missing or invalid fitted reconstruction parameter: {name}")
            params[name] = native[name].reshape(3).astype(np.float32)
    return params


def soke_features(parameters):
    full = np.concatenate([parameters[name] for _, name, _ in PARAMETERS], axis=-1)
    if full.ndim != 2 or full.shape[1] != 179 or not np.isfinite(full).all():
        raise ValueError("Expected finite fitted SMPL-X sequences with 179 dimensions")
    return np.concatenate((full[:, 36:159], full[:, 169:179]), axis=1).astype(np.float32)


def rotation_quality(poses):
    import cv2

    rotations = np.array([cv2.Rodrigues(p.astype(np.float64))[0]
                          for p in poses.reshape(-1, 3)]).reshape(len(poses), -1, 3, 3)
    relative = rotations[1:] @ rotations[:-1].swapaxes(-2, -1)
    trace = np.trace(relative, axis1=-2, axis2=-1)
    angles = np.degrees(np.arccos(np.clip((trace - 1) / 2, -1, 1)))
    return {"max_adjacent_rotation_degrees": float(angles.max()) if angles.size else 0,
            "frame_transitions_over_90_degrees": int(np.any(angles > 90, axis=1).sum())}


def collect_fit(task, directory):
    smplx = directory / "smplx"
    if not smplx.is_dir():
        raise ValueError("No fitted SMPL-X directory")
    paths = sorted(smplx.glob("*.npz"))
    expected = {f"{i:05d}_0.npz" for i in range(1, task["frames"] + 1)}
    if {p.name for p in paths} != expected:
        missing = sorted(expected - {p.name for p in paths})
        extra = sorted({p.name for p in paths} - expected)
        raise ValueError(f"Incomplete or ambiguous person track; missing={missing[:8]}, extra={extra[:8]}")
    for path in paths:
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Fitting file leaves its output directory")
    frames = [native_parameters(smplx / f"{i:05d}_0.npz") for i in range(1, task["frames"] + 1)]
    keys = [target for _, target, _ in PARAMETERS] + ["transl", "leye_pose", "reye_pose"]
    return {key: np.stack([f[key] for f in frames]) for key in keys}


def import_smplerx(args):
    batch, fits = args.batch.resolve(), args.fits.resolve()
    tasks = verify_pack(batch)
    run_path = fits / "run.json"
    if not run_path.is_file():
        raise ValueError("Import requires run.json from the fitting runner for model/input provenance")
    fit_run = json.loads(run_path.read_text())
    if (fit_run.get("schema") != "signbridge-smplerx-run-v1" or
            fit_run.get("tasks_sha256") != data.sha256_file(batch / "tasks.jsonl") or
            fit_run.get("preflight", {}).get("actual_commit") != SMPLERX_COMMIT or
            fit_run.get("status") not in {"inferred_pending_import_audit", "failed"}):
        raise ValueError("Fitting run is not from the expected model and input batch")
    output = new_output(args.output, (batch, fits))
    converted, rejected, annotations, skipped = [], [], [], []
    for task in tasks:
        identity = task["segment_id"]
        if identity not in fit_run.get("completed", []):
            skipped.append({"segment_id": identity, "reason": "Not selected or fitting job not completed"})
            continue
        try:
            params = collect_fit(task, fits / identity)
            features = soke_features(params)
        except (ValueError, OSError, KeyError) as exc:
            rejected.append({"segment_id": identity, "reason": str(exc)})
            continue
        directory = output / "samples" / identity
        directory.mkdir(parents=True)
        np.save(directory / "features-133.npy", features, allow_pickle=False)
        # Only serialize arrays we just validated; never unpickle external fitting files.
        pose_dir = output / "poses" / identity
        pose_dir.mkdir(parents=True)
        fit_sources = []
        for index in range(task["frames"]):
            with (pose_dir / f"{index + 1:06d}.pkl").open("wb") as stream:
                pickle.dump({name: params[name][index] for _, name, _ in PARAMETERS}, stream,
                            protocol=4)
            fitted_path = fits / identity / "smplx" / f"{index + 1:05d}_0.npz"
            fit_sources.append({"frame_id": index + 1,
                                "file": str(fitted_path.relative_to(fits)),
                                "sha256": data.sha256_file(fitted_path)})
        write_jsonl(directory / "fit-sources.jsonl", fit_sources)
        annotations.append({"name": identity, "text": task["text_verified"],
                            "fps": task["fps"], "split": task["split"]})
        frame_records = read_jsonl(artifact(batch, task["frame_manifest"]))
        times = np.array([f["clip_seconds"] for f in frame_records])
        source_times = np.array([f["source_seconds_nominal"] for f in frame_records])
        np.savez_compressed(directory / "fitted-smplx.npz", **params, timestamps_seconds=times,
                            source_timestamps_seconds=source_times)
        quality = {"left_hand": rotation_quality(params["smplx_lhand_pose"]),
                   "right_hand": rotation_quality(params["smplx_rhand_pose"]),
                   "body": rotation_quality(params["smplx_body_pose"]),
                   "motion_review_status": "needs_review", "model_training_ready": False,
                   "limitations": ["Finite values and smoothness do not prove sign correctness",
                                   "Review mesh overlay, hand shapes and contacts before training"]}
        data.write_json(directory / "quality.json", quality)
        converted.append({**task, "representation": "soke-smplx-133-v1", "dimensions": 133,
                          "features": str((directory / "features-133.npy").relative_to(output)),
                          "motion_review_status": "needs_review", "model_training_ready": False})
    write_jsonl(output / "motions.jsonl", converted)
    write_jsonl(output / "soke-annotations.jsonl", annotations)
    report = {"created_at": now(), "converted": len(converted), "rejected": rejected,
              "skipped": skipped,
              "soke_commit": SOKE_COMMIT, "fit_run_sha256": data.sha256_file(run_path),
              "normalization": "raw, unnormalized; use pretrained tokenizer's own mean/std when adapting",
              "training_ready": False,
              "pending": ["Motion review", "Mirror orientation", "Cross-video signer identity and grouped splits"]}
    data.write_json(output / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 2 if rejected or not converted else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("review", help="Record approval of existing meanings/ranges as a new version")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--segments", type=Path, required=True)
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--statement", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(action=review)
    p = commands.add_parser("export", help="Decode reviewed clips into portable fitting inputs")
    p.add_argument("--reviewed", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(action=export)
    p = commands.add_parser("fit", help="Check assets/runtime; execute official SMPLer-X inference")
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--smplerx-root", type=Path, required=True)
    p.add_argument("--python", type=Path, required=True, help="Python in the SMPLer-X CUDA environment")
    p.add_argument("--model", choices=["smpler_x_s32", "smpler_x_b32", "smpler_x_l32", "smpler_x_h32"],
                   default="smpler_x_h32")
    p.add_argument("--segment-id", action="append", help="Repeat to fit a smaller pilot first")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(action=fit)
    p = commands.add_parser("import-smplerx", help="Strictly import real fitted sequences into 133D arrays")
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--fits", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(action=import_smplerx)
    args = parser.parse_args()
    try:
        return args.action(args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
