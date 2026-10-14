"""Build and run the reviewed source-4 SMPLer-X fitting batch.

This tool creates fitting inputs only.  It never promotes a candidate to a
training sample: SMPL-X fitting, motion review, signer/mirror review and the
final training gate remain separate stages.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
MOTION_SPEC = importlib.util.spec_from_file_location("sign_motion_source4", HERE / "sign-motion.py")
motion = importlib.util.module_from_spec(MOTION_SPEC)
MOTION_SPEC.loader.exec_module(motion)

SMPLERX_COMMIT = motion.SMPLERX_COMMIT
SOURCE4_SCHEMA = "signbridge-source4-smplx-fit-input-v1"


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,120}", value) is None:
        raise ValueError(f"Unsafe annotation ID: {value!r}")
    return value


def build_fitting_tasks(approved, references, sources, approved_ids):
    """Join reviewed labels to 2D references without promoting either artifact."""
    approved_by_id = {safe_id(row.get("annotation_id")): row for row in approved}
    reference_by_id = {safe_id(row.get("annotation_id")): row for row in references}
    if len(approved_by_id) != len(approved) or len(reference_by_id) != len(references):
        raise ValueError("Annotation IDs must be unique")
    expected = set(approved_ids)
    if set(approved_by_id) != expected:
        raise ValueError("approved ID set differs from the attested shortlist")
    if set(reference_by_id) != expected:
        raise ValueError("reference ID set differs from the approved ID set")

    tasks = []
    for annotation_id in sorted(expected):
        row = approved_by_id[annotation_id]
        reference = reference_by_id[annotation_id]
        source_id = row.get("source_id")
        source = sources.get(source_id)
        if not source or source.get("authorization_status") != "user_reported":
            raise ValueError(f"source provenance is not authorized: {annotation_id}")
        if row.get("source_sha256") != source.get("sha256") or row.get("relative_path") != source.get("relative_path"):
            raise ValueError(f"source provenance differs: {annotation_id}")
        if not (row.get("human_approved") is True and row.get("semantics_approved") is True and
                row.get("boundaries_approved") is True):
            raise ValueError(f"review approval is incomplete: {annotation_id}")
        if any(row.get(key) is not False for key in ("training_ready", "model_training_ready", "smplx_parameters_created")):
            raise ValueError(f"training flags must remain false: {annotation_id}")

        text = row.get("text_verified")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"reviewed text is empty: {annotation_id}")
        if reference.get("label") != text:
            raise ValueError(f"reference label differs from reviewed text: {annotation_id}")
        if reference.get("source_id") != source_id or reference.get("source_sha256") != row.get("source_sha256"):
            raise ValueError(f"reference source provenance differs: {annotation_id}")
        if reference.get("start_seconds") != float(row.get("start_seconds_nominal")) or \
                reference.get("end_seconds") != float(row.get("end_seconds_nominal")):
            raise ValueError(f"reference timing differs from reviewed candidate: {annotation_id}")
        if reference.get("human_approved") is not False or reference.get("training_ready") is not False:
            raise ValueError(f"2D reference must remain unapproved: {annotation_id}")
        if reference.get("smplx_parameters_created") is not False:
            raise ValueError(f"SMPL-X parameters already promoted in reference: {annotation_id}")
        if type(reference.get("frames")) is not int or reference["frames"] < 4 or reference.get("fps") != 25.0:
            raise ValueError(f"reference frame contract is invalid: {annotation_id}")
        artifact = reference.get("artifacts", {}).get("clip.mp4")
        landmarks = reference.get("artifacts", {}).get("landmarks.npz")
        if not isinstance(artifact, str) or not isinstance(landmarks, str):
            raise ValueError(f"reference artifacts are incomplete: {annotation_id}")

        tasks.append({
            "segment_id": annotation_id,
            "source_id": source_id,
            "source_sha256": row["source_sha256"],
            "start_seconds": float(row["start_seconds_nominal"]),
            "end_seconds": float(row["end_seconds_nominal"]),
            "text_verified": text,
            "language": row.get("language", "unconfirmed"),
            "signer_id": row.get("signer_identity", "unconfirmed"),
            "split_group": "unverified-csl-source4",
            "split": row.get("split", "unassigned"),
            "mirror_status": row.get("mirror_status", "unknown"),
            "reviewer": row.get("reviewer", "user-confirmed-batch-review"),
            "authorization_status": source["authorization_status"],
            "review_attestation_sha256": row.get("review_attestation_sha256"),
            "frames": reference["frames"],
            "fps": reference["fps"],
            "content_reviewed": True,
            "label_review_status": "approved_for_fitting",
            "human_approved": False,
            "model_training_ready": False,
            "training_ready": False,
            "smplx_parameters_created": False,
            "observation_representation": "mediapipe-2d-reference-only",
            "image_transform": "none",
            "motion_review_status": "not_fitted",
            "reference_clip": artifact,
            "reference_landmarks": landmarks,
        })
    return tasks


def ffprobe_clip(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValueError("ffprobe is unavailable")
    result = subprocess.run([
        ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,nb_read_frames,width,height", "-of", "json", str(path)
    ], check=True, capture_output=True, text=True)
    stream = json.loads(result.stdout)["streams"][0]
    numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
    return {
        "frames": int(stream["nb_read_frames"]),
        "fps": numerator / denominator,
        "width": int(stream["width"]),
        "height": int(stream["height"]),
    }


def extract_images(clip, images, expected_frames):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is unavailable")
    images.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(clip),
        "-q:v", "2", "-threads", "2", str(images / "%06d.jpg")
    ], check=True, timeout=900)
    files = sorted(images.glob("*.jpg"))
    if len(files) != expected_frames or any(path.name != f"{i:06d}.jpg" for i, path in enumerate(files, 1)):
        raise ValueError(f"non-contiguous extraction for {clip}: {len(files)}/{expected_frames}")
    return files


def prepare(args):
    approved_path = args.approved.resolve()
    reference_path = args.references.resolve()
    source_manifest_path = args.source_manifest.resolve()
    reference_root = args.reference_root.resolve()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be a new empty directory")
    approved = read_jsonl(approved_path)
    references = read_jsonl(reference_path)
    source_manifest = read_json(source_manifest_path)
    sources = {row["source_id"]: row for row in source_manifest["sources"]}
    attestation = read_json(args.attestation.resolve())
    approved_ids = {row["annotation_id"] for row in approved}
    if attestation.get("candidates") != len(approved) or attestation.get("training_ready") is not False:
        raise ValueError("attestation does not match an unpromoted approved batch")
    tasks = build_fitting_tasks(approved, references, sources, approved_ids)
    output.mkdir(parents=True)
    checksums = []
    prepared = []
    for index, task in enumerate(tasks, 1):
        sample = output / "samples" / task["segment_id"]
        sample.mkdir(parents=True)
        reference_clip = (reference_root / task.pop("reference_clip")).resolve()
        reference_landmarks = (reference_root / task.pop("reference_landmarks")).resolve()
        if reference_root not in reference_clip.parents or not reference_clip.is_file():
            raise ValueError(f"missing reference clip: {task['segment_id']}")
        if reference_root not in reference_landmarks.parents or not reference_landmarks.is_file():
            raise ValueError(f"missing reference landmarks: {task['segment_id']}")
        clip = sample / "clip.mp4"
        try:
            os.link(reference_clip, clip)
        except OSError:
            shutil.copy2(reference_clip, clip)
        observation = sample / "observations.npz"
        shutil.copy2(reference_landmarks, observation)
        probe = ffprobe_clip(clip)
        if probe["frames"] != task["frames"] or abs(probe["fps"] - task["fps"]) > 0.01:
            raise ValueError(f"reference clip metadata differs: {task['segment_id']}")
        images = sample / "images"
        files = extract_images(clip, images, task["frames"])
        frame_records = []
        for frame_id, image in enumerate(files, 1):
            relative = str(image.relative_to(output))
            frame_records.append({
                "frame_id": frame_id, "image": relative, "sha256": sha256_file(image),
                "clip_seconds": (frame_id - 1) / task["fps"],
                "source_seconds_nominal": task["start_seconds"] + (frame_id - 1) / task["fps"],
            })
        frame_manifest = sample / "frames.jsonl"
        write_jsonl(frame_manifest, frame_records)
        task.update({
            "images": str(images.relative_to(output)),
            "clip": str(clip.relative_to(output)),
            "frame_manifest": str(frame_manifest.relative_to(output)),
            "clip_sha256": sha256_file(clip),
            "observation_artifact": str(observation.relative_to(output)),
            "observation_sha256": sha256_file(observation),
        })
        prepared.append(task)
        print(json.dumps({"sequence": index, "total": len(tasks), "segment_id": task["segment_id"], "frames": task["frames"]}, ensure_ascii=False), flush=True)

    write_jsonl(output / "tasks.jsonl", prepared)
    contract = {
        "schema": "signbridge-smplerx-input-v1",
        "created_at": now(),
        "samples": len(prepared),
        "frames": sum(task["frames"] for task in prepared),
        "smplerx_commit": SMPLERX_COMMIT,
        "soke_commit": motion.SOKE_COMMIT,
        "image_naming": "1-based %06d.jpg; preserve reference FPS, no interpolation or mirroring",
        "observation_coordinates": "MediaPipe estimates are retained as audit references only",
        "expected_output": "<fit-output>/<segment_id>/smplx/%05d_0.npz",
        "fit_semantics": "SMPLer-X per-frame estimates, use_pca=False, flat_hand_mean=False",
        "soke_feature_dimensions": 133,
        "model_training_ready": False,
        "training_ready": False,
    }
    write_json(output / "contract.json", contract)
    manifest = {
        "schema": SOURCE4_SCHEMA,
        "created_at": now(),
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "approved_candidates_sha256": sha256_file(approved_path),
        "reference_index_sha256": sha256_file(reference_path),
        "attestation_sha256": sha256_file(args.attestation.resolve()),
        "samples": len(prepared),
        "frames": sum(task["frames"] for task in prepared),
        "source_count": len({task["source_id"] for task in prepared}),
        "observation_reference_only": True,
        "human_approved": True,
        "smplx_parameters_created": False,
        "training_started": False,
        "training_ready": False,
    }
    write_json(output / "manifest.json", manifest)
    (output / "review-attestation.json").write_text(Path(args.attestation).read_text())
    write_json(output / "preflight-input.json", {
        "status": "prepared_pending_cuda_fit",
        "contract": contract,
        "manifest": manifest,
        "training_ready": False,
    })
    for file in sorted(output.rglob("*")):
        if file.is_file() and file.name != "SHA256SUMS":
            checksums.append(f"{sha256_file(file)}  {file.relative_to(output)}\n")
    (output / "SHA256SUMS").write_text("".join(checksums))
    motion.verify_pack(output)
    print(json.dumps({"status": "prepared_pending_cuda_fit", "output": str(output), **manifest}, ensure_ascii=False))


def run_fit(args):
    package = args.package.resolve()
    output = args.output.resolve()
    motion.verify_pack(package)
    namespace = argparse.Namespace(
        batch=package,
        smplerx_root=args.smplerx_root,
        python=args.python,
        model=args.model,
        segment_id=None,
        dry_run=args.dry_run,
        output=output,
    )
    return motion.fit(namespace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--approved", type=Path, required=True)
    prepare_parser.add_argument("--references", type=Path, required=True)
    prepare_parser.add_argument("--source-manifest", type=Path, required=True)
    prepare_parser.add_argument("--reference-root", type=Path, required=True)
    prepare_parser.add_argument("--attestation", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.set_defaults(func=prepare)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--package", type=Path, required=True)
    run_parser.add_argument("--smplerx-root", type=Path, required=True)
    run_parser.add_argument("--python", type=Path, required=True)
    run_parser.add_argument("--model", choices=["smpler_x_s32", "smpler_x_b32", "smpler_x_l32", "smpler_x_h32"], default="smpler_x_h32")
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.set_defaults(func=run_fit)
    args = parser.parse_args()
    try:
        return args.func(args) or 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
