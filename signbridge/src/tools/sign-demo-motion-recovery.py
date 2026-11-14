"""Create a provenance-bound display-only smoothing variant; never edits fitted poses."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

RECOVERY_PROFILES = {
    "new-cb8ac953180a2b6e-cap-0025": "quaternion-temporal-recovery-v1",
    "new-db3d18d67ffd0f9a-cap-0004": "quaternion-temporal-recovery-v1",
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def recover_bundle(source_index, output, profiles):
    source_index = Path(source_index).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Recovery output must be new; preserve all prior builds")
    source_root = source_index.parent
    original_index = json.loads(source_index.read_text())
    entries = {clip["id"]: clip for clip in original_index.get("clips", [])}
    if not profiles or not set(profiles).issubset(entries):
        raise ValueError("Recovery IDs must exist in the frozen source index")
    original_assets = {}
    for identity, profile in profiles.items():
        if profile != "quaternion-temporal-recovery-v1":
            raise ValueError("Unapproved display profile")
        entry = entries[identity]
        asset_path = (source_root / entry["asset"]).resolve()
        if not asset_path.is_relative_to(source_root) or not asset_path.is_file():
            raise ValueError("Unsafe or missing source asset: " + identity)
        if sha(asset_path) != entry["sha256"]:
            raise ValueError("Source clip digest differs: " + identity)
        clip = json.loads(asset_path.read_text())
        poses = np.asarray(clip.get("poses"))
        if (poses.shape != (entry["frames"], 55, 3) or not np.isfinite(poses).all()
                or clip.get("human_approved") is not False
                or clip.get("training_ready") is not False
                or clip.get("model_training_ready") is not False):
            raise ValueError("Source clip integrity/status differs: " + identity)
        original_assets[identity] = (asset_path, clip)

    output.mkdir(parents=True)
    shutil.copytree(source_root / "experimental", output / "experimental")
    clips = []
    for original in original_index["clips"]:
        entry = dict(original)
        if entry["id"] in profiles:
            path, clip = original_assets[entry["id"]]
            clip["display_stabilization_profile"] = profiles[entry["id"]]
            entry["display_stabilization_profile"] = profiles[entry["id"]]
            target = output / entry["asset"]
            write(target, clip)
            entry["sha256"] = sha(target)
        clips.append(entry)
    recovered_index = dict(original_index)
    recovered_index["clips"] = clips
    recovered_index["display_smoothing_recovery"] = True
    recovered_index["recovery_profiles"] = profiles
    recovered_index["source_experimental_index_sha256"] = sha(source_index)
    write(output / "experimental-index.json", recovered_index)
    return {
        "source_index": str(source_index),
        "source_index_sha256": sha(source_index),
        "output_index_sha256": sha(output / "experimental-index.json"),
        "profiles": profiles,
        "clips_total": len(clips),
        "source_asset_sha256": {identity: sha(path) for identity, (path, _) in original_assets.items()},
        "output_clip_sha256": {
            identity: sha(output / entries[identity]["asset"]) for identity in profiles
        },
        "source_pose_arrays_unchanged": all(
            np.array_equal(
                original_assets[identity][1]["poses"],
                json.loads((output / entries[identity]["asset"]).read_text())["poses"],
            )
            for identity in profiles
        ),
        "training_weights_updated": False,
        "training_ready": False,
        "model_training_ready": False,
        "human_approved": False,
    }


def incomplete_fit_status(records, recovered_index):
    runtime_ids = {clip["id"] for clip in recovered_index["clips"]}
    report = []
    for row in records:
        if row.get("group") != "source4" or row.get("kind") != "native" or not row.get("errors"):
            continue
        clip = Path(row["clip"]).resolve()
        package = clip.parents[2]
        tasks_path = package / "tasks.jsonl"
        tasks = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]
        task = next(item for item in tasks if item["segment_id"] == row["id"])
        fit = Path(row["fit"])
        package_images = package / task["images"]
        image_files = sorted(package_images.glob("*.jpg"))
        expected_images = {f"{number:06d}.jpg" for number in range(1, task["frames"] + 1)}
        actual_images = {path.name for path in image_files}
        input_hashes = [{"path": path.name, "sha256": sha(path)} for path in image_files]
        input_manifest = "".join(f"{item['sha256']}  {item['path']}\n" for item in input_hashes)
        remote_report = fit.parents[1] / "report.json"
        report_data = json.loads(remote_report.read_text())
        failure = next((item for item in report_data.get("failed", [])
                        if item.get("segment_id") == row["id"]), {})
        report.append({
            "id": row["id"], "text": row["text"], "frames_expected": row["frames"],
            "native_frames_present": row["fitted_frames"], "missing_frames": row["missing_frames"],
            "package_input_frames": len(image_files),
            "package_missing_input_frames": sorted(expected_images - actual_images),
            "package_input_frame_set_complete": actual_images == expected_images,
            "package_input_jpeg_sha256_manifest": hashlib.sha256(input_manifest.encode()).hexdigest(),
            "source_clip_sha256": task["clip_sha256"], "source_tasks_sha256": sha(tasks_path),
            "prior_failure": failure.get("error", "recorded output parameter-set mismatch"),
            "prior_remote_log_path": failure.get("log"),
            "prior_report_sha256": sha(remote_report), "present_in_current_demo": row["id"] in runtime_ids,
            "status": "incomplete_and_excluded",
            "automatic_repair_safe": False,
            "reason": "Native parameter frames are absent. No zero-fill, interpolation, or guessed pose was created.",
            "next_valid_action": "Requires a separately authorized new inference attempt with the frozen input/model, or a reviewed window correction; preserve this failed output.",
        })
    return report


def run(args):
    source_index = args.source_index.resolve()
    evidence = json.loads(args.evidence_report.read_text())
    avatar = json.loads(args.avatar_report.read_text())
    for identity in RECOVERY_PROFILES:
        row = next((r for r in evidence["records"] if r.get("id") == identity and r.get("kind") == "runtime"), None)
        metric = next((r for r in avatar["records"] if r.get("uid") == "runtime-source4--" + identity), None)
        if (row is None or metric is None or row["asset_sha256"] != next(
                c["sha256"] for c in json.loads(source_index.read_text())["clips"] if c["id"] == identity)
                or "avatar_wrist_residual_p95_over_2cm" not in metric["risk_flags"]):
            raise ValueError("Frozen audit does not justify recovery profile: " + identity)
    result = recover_bundle(source_index, args.output, RECOVERY_PROFILES)
    result.update({
        "schema": "signbridge-display-motion-recovery-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_report_sha256": sha(args.evidence_report),
        "avatar_report_sha256": sha(args.avatar_report),
        "limitations": [
            "Display-only quaternion smoothing; native fitted poses and training weights are unchanged.",
            "No semantic, handshape, contact, mirror, signer, or boundary approval is implied.",
        ],
    })
    index_data = json.loads((args.output / "experimental-index.json").read_text())
    result["unresolved_incomplete_fits"] = incomplete_fit_status(evidence["records"], index_data)
    write(args.output / "recovery-report.json", result)
    audit_input = dict(evidence)
    jobs = []
    for job in evidence["pose_jobs"]:
        new_job = dict(job)
        if job["uid"] in {"runtime-source4--" + key for key in RECOVERY_PROFILES}:
            identity = job["uid"].split("--", 1)[1]
            entry = next(c for c in json.loads((args.output / "experimental-index.json").read_text())["clips"] if c["id"] == identity)
            new_job["asset"] = str(args.output / entry["asset"])
            new_job["display_stabilization_profile"] = RECOVERY_PROFILES[identity]
        jobs.append(new_job)
    audit_input["pose_jobs"] = jobs
    write(args.output / "avatar-audit-input.json", audit_input)
    manifest = []
    for path in sorted(args.output.rglob("*")):
        if path.is_file():
            manifest.append(sha(path) + "  " + str(path.relative_to(args.output)))
    (args.output / "SHA256SUMS").write_text("\n".join(manifest) + "\n")
    print(json.dumps({"output": str(args.output), "profiles": RECOVERY_PROFILES,
                      "source_pose_arrays_unchanged": result["source_pose_arrays_unchanged"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--evidence-report", type=Path, required=True)
    parser.add_argument("--avatar-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
