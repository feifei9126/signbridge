"""Create a new, provenance-bound local Demo bundle for motion-only approval."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile


EXPECTED_CLIPS = 83
APPROVAL_ID = "motion-approval-20261020-v1"
APPROVAL_STATEMENT = "验证过了，现候选的83条实验拟合动作已获人工批准"
MODEL_SHA = "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992"
DIGEST = re.compile(r"^[a-f0-9]{64}$")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")


def pose_digest(poses):
    values = []
    if not isinstance(poses, list):
        raise ValueError("Expected complete pose frames")
    for frame in poses:
        if not isinstance(frame, list) or len(frame) != 55:
            raise ValueError("Expected 55-joint pose frames")
        for joint in frame:
            if not isinstance(joint, list) or len(joint) != 3:
                raise ValueError("Expected 3-axis joint rotations")
            for value in joint:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Pose values must be finite numbers")
                scaled = float(value) * 1_000_000
                quantized = math.floor(scaled + 0.5)
                values.append(str(quantized))
    return sha256(",".join(values).encode("ascii"))


def read_clip(source, entry):
    asset = entry.get("asset")
    if not isinstance(asset, str) or not re.fullmatch(
            r"experimental/[a-zA-Z0-9_-]+\.json", asset):
        raise ValueError("Unsafe fitted clip path")
    path = source / asset
    if path.is_symlink() or not path.resolve().is_relative_to(source):
        raise ValueError("Fitted clip must be a regular file under the source root")
    raw = path.read_bytes()
    if sha256(raw) != entry.get("sha256"):
        raise ValueError("Source fitted clip digest differs: " + entry.get("id", "?"))
    clip = json.loads(raw)
    if (clip.get("schema") != "signbridge-experimental-clip-v1"
            or clip.get("id") != entry.get("id")
            or clip.get("human_approved") is not False
            or clip.get("motion_review_status") != "needs_review"
            or clip.get("training_data_member") is not False
            or clip.get("training_ready") is not False
            or clip.get("model_training_ready") is not False
            or clip.get("mirror_status") != "unknown"
            or clip.get("signer_id") != "unconfirmed"
            or clip.get("frames") != entry.get("frames")
            or len(clip.get("poses", [])) != entry.get("frames")):
        raise ValueError("Source motion state or frame count differs: " + entry.get("id", "?"))
    for field in ("source_sha256", "fitted_sha256"):
        if not DIGEST.fullmatch(entry.get(field, "")) or clip.get(field) != entry[field]:
            raise ValueError("Source provenance digest differs: " + entry.get("id", "?"))
    return raw, clip


def validate_source(source, index_bytes):
    index = json.loads(index_bytes)
    if (index.get("schema") != "signbridge-experimental-motion-index-v1"
            or index.get("representation") != "effective-smplx-55-axis-angle"
            or index.get("smplx_rest_model_sha256") != MODEL_SHA
            or index.get("training_weights_updated") is not False
            or index.get("text_to_sign_trained") is not False
            or index.get("training_ready") is not False
            or index.get("model_training_ready") is not False
            or index.get("research_only") is not True
            or "motion_approval" in index
            or len(index.get("clips", [])) != EXPECTED_CLIPS):
        raise ValueError("Expected the unchanged unapproved 83-clip research index")
    ids = [entry.get("id") for entry in index["clips"]]
    if len(set(ids)) != EXPECTED_CLIPS:
        raise ValueError("Clip IDs must be unique")
    prepared = []
    for entry in index["clips"]:
        if (entry.get("human_approved") is not False
                or entry.get("motion_review_status") != "needs_review"
                or entry.get("training_data_member") is not False
                or entry.get("training_ready") is not False
                or entry.get("model_training_ready") is not False):
            raise ValueError("Input clip approval/training state differs: " + entry["id"])
        raw, clip = read_clip(source, entry)
        prepared.append({"entry": entry, "clip": clip, "raw_sha256": sha256(raw),
                         "poses_sha256": pose_digest(clip["poses"])})
    return index, prepared


def promote(source_dir, output_dir):
    source_path = Path(source_dir)
    output_path = Path(output_dir).absolute()
    if source_path.is_symlink():
        raise ValueError("Source root must not be a symlink")
    source = source_path.resolve()
    index_path = source / "experimental-index.json"
    if index_path.is_symlink():
        raise ValueError("Source index must not be a symlink")
    index_bytes = index_path.read_bytes()
    index, prepared = validate_source(source, index_bytes)
    if output_path.exists():
        raise FileExistsError("Output must be new; preserve previous evidence")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=output_path.name + ".tmp-",
                                  dir=output_path.parent))
    try:
        (stage / "experimental").mkdir()
        captured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        record = {
            "schema": "signbridge-human-motion-approval-v1",
            "id": APPROVAL_ID,
            "scope": "motion_quality_only",
            "declaration": APPROVAL_STATEMENT,
            "basis": "explicit_user_statement_in_current_conversation",
            "captured_at_utc": captured_at,
            "source_index_sha256": sha256(index_bytes),
            "clips": [],
        }
        promoted_entries = []
        total_frames = 0
        for prepared_clip in prepared:
            entry = prepared_clip["entry"]
            clip = prepared_clip["clip"]
            item = {
                "id": entry["id"],
                "reviewed_asset_sha256": prepared_clip["raw_sha256"],
                "source_sha256": entry["source_sha256"],
                "fitted_sha256": entry["fitted_sha256"],
                "poses_sha256": prepared_clip["poses_sha256"],
            }
            record["clips"].append(item)
            clip.update({"human_approved": True,
                         "motion_review_status": "approved_for_demo_motion",
                         "motion_approval_id": APPROVAL_ID})
            updated = json_bytes(clip)
            relative_asset = entry["asset"]
            (stage / relative_asset).write_bytes(updated)
            promoted = {**entry, "human_approved": True,
                        "motion_review_status": "approved_for_demo_motion",
                        "motion_approval_id": APPROVAL_ID,
                        "sha256": sha256(updated)}
            promoted_entries.append(promoted)
            total_frames += entry["frames"]
        approval_bytes = json_bytes(record)
        (stage / "experimental/motion-approval.json").write_bytes(approval_bytes)
        index["motion_approval"] = {
            "schema": "signbridge-human-motion-approval-ref-v1",
            "id": APPROVAL_ID,
            "scope": "motion_quality_only",
            "asset": "experimental/motion-approval.json",
            "sha256": sha256(approval_bytes),
        }
        index["clips"] = promoted_entries
        (stage / "experimental-index.json").write_bytes(json_bytes(index))
        os.replace(stage, output_path)
        return {"clips": len(promoted_entries), "frames": total_frames,
                "source_index_sha256": record["source_index_sha256"],
                "approval_sha256": sha256(approval_bytes),
                "output": str(output_path)}
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Existing experimental bundle root; never modified")
    parser.add_argument("--output", type=Path, required=True,
                        help="New output directory; existing directories are rejected")
    args = parser.parse_args()
    print(json.dumps(promote(args.source, args.output), ensure_ascii=False))
