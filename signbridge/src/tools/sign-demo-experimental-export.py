"""Export audited fitted motions for a demo, not training or approval."""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import numpy as np

MODEL_SHA = "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_key(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).lower()
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


def effective_pose(features, mean):
    if (features.ndim != 2 or features.shape[1] != 133 or features.dtype != np.float32
            or not 4 <= len(features) <= 2000 or not np.isfinite(features).all()
            or mean.shape != (55, 3) or not np.isfinite(mean).all()):
        raise ValueError("Expected complete finite native SMPL-X features")
    pose = np.zeros((len(features), 55, 3), dtype=np.float32)
    pose[:, 12:22] = features[:, :30].reshape(-1, 10, 3)
    pose[:, 25:40] = features[:, 30:75].reshape(-1, 15, 3)
    pose[:, 40:55] = features[:, 75:120].reshape(-1, 15, 3)
    pose[:, 22] = features[:, 120:123]
    return pose + mean[None]


def deduplicate(rows, existing_keys):
    keys = {key: "existing-reference" for key in existing_keys}
    features, selected, excluded = {}, [], []
    for row in sorted(rows, key=lambda r: (r["max_jump"], r["id"])):
        key = text_key(row["text"])
        retained = keys.get(key) or features.get(row["feature_sha256"])
        if retained:
            excluded.append({"id": row["id"], "text": row["text"],
                             "retained_id": retained, "reason": "duplicate_text_or_features"})
        else:
            selected.append(row)
            keys[key] = row["id"]
            features[row["feature_sha256"]] = row["id"]
    return sorted(selected, key=lambda r: r["id"]), excluded


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def export(args):
    source, output, model = (p.resolve() for p in (args.source, args.output, args.smplx_model))
    if output.exists():
        raise ValueError("Output must be new; preserve previous evidence")
    if sha(model) != MODEL_SHA:
        raise ValueError("SMPL-X rest asset digest differs")
    audit_path = source / "verification.json"
    audit = json.loads(audit_path.read_text())
    rows = [json.loads(line) for line in (source / "motions.jsonl").read_text().splitlines() if line.strip()]
    if (audit.get("schema") != "signbridge-source4-stream-import-audit-v1"
            or audit.get("training_ready") is not False or audit.get("training_started") is not False
            or audit.get("converted") != len(rows) or audit.get("frames") != sum(r["frames"] for r in rows)
            or len({r["segment_id"] for r in rows}) != len(rows)):
        raise ValueError("Completed import audit scope differs")
    existing = set()
    for bundle in args.exclude_bundle:
        for clip in json.loads(bundle.read_text())["clips"]:
            existing.update(text_key(t) for t in [clip["text"], *clip.get("aliases", [])])
    with np.load(model, allow_pickle=False) as assets:
        mean = np.zeros((55, 3), dtype=np.float32)
        mean[25:40] = assets["hands_meanl"].reshape(15, 3)
        mean[40:55] = assets["hands_meanr"].reshape(15, 3)
        rest = np.asarray(assets["J_regressor"] @ assets["v_template"], dtype=np.float32)
        parents = assets["kintree_table"][0].astype(np.int32)
        parents[0] = -1
    prepared = []
    for row in rows:
        identity = row["segment_id"]
        if (not re.fullmatch(r"[a-zA-Z0-9_-]+", identity) or not text_key(row["text_verified"])
                or row.get("content_reviewed") is not True or row.get("training_ready") is not False
                or row.get("human_approved") is not False or row.get("model_training_ready") is not False
                or row.get("motion_review_status") != "needs_review"
                or row.get("label_review_status") != "approved_for_fitting"
                or not np.isfinite(row["fps"]) or not 0 < row["fps"] <= 120):
            raise ValueError("Experimental text/quality gate differs: " + identity)
        feature = (source / row["features"]).resolve()
        if not feature.is_relative_to(source):
            raise ValueError("Unsafe feature path")
        values = np.load(feature, allow_pickle=False)
        if values.shape != (row["frames"], 133):
            raise ValueError("Feature frame count differs: " + identity)
        effective_pose(values, mean)
        fitted = feature.with_name("fitted-smplx.npz")
        with np.load(fitted, allow_pickle=False) as native:
            raw = np.concatenate([native["smplx_body_pose"][:, 33:63], native["smplx_lhand_pose"],
                                  native["smplx_rhand_pose"], native["smplx_jaw_pose"], native["smplx_expr"]], axis=1)
            if not np.array_equal(raw, values):
                raise ValueError("Native fit and feature mapping differ: " + identity)
            if not np.allclose(native["timestamps_seconds"], np.arange(row["frames"]) / row["fps"], atol=1e-8):
                raise ValueError("Native timestamp sequence differs: " + identity)
        quality = json.loads(feature.with_name("quality.json").read_text())
        maximum = max(quality[k]["max_adjacent_rotation_degrees"] for k in ("body", "left_hand", "right_hand"))
        prepared.append({"id": identity, "text": row["text_verified"], "feature_sha256": sha(feature),
                         "max_jump": maximum, "feature": feature, "row": row, "fitted_sha256": sha(fitted)})
    selected, duplicates = deduplicate(prepared, existing)
    output.mkdir(parents=True)
    (output / "experimental").mkdir()
    clips = []
    for item in selected:
        row = item["row"]
        clip = {"id": item["id"], "text": item["text"], "aliases": [item["text"]],
                "fps": row["fps"], "frames": row["frames"], "experimental": True,
                "model_output": "smplx_fit_demo", "source_sha256": row["source_sha256"],
                "feature_sha256": item["feature_sha256"], "fitted_sha256": item["fitted_sha256"],
                "source_id": row["source_id"], "training_data_member": False, "training_ready": False,
                "model_training_ready": False, "human_approved": False, "motion_review_status": "needs_review",
                "mirror_status": "unknown", "signer_id": "unconfirmed", "quality_warning": item["max_jump"] > 90,
                "max_adjacent_rotation_degrees": item["max_jump"],
                "review_attestation_sha256": row["review_attestation_sha256"]}
        relative = "experimental/" + item["id"] + ".json"
        values = np.load(item["feature"], allow_pickle=False)
        write_json(output / relative, {"schema": "signbridge-experimental-clip-v1", **clip,
                                      "poses": np.round(effective_pose(values, mean), 6).tolist()})
        clips.append({**clip, "asset": relative, "sha256": sha(output / relative)})
    manifest = {"schema": "signbridge-experimental-motion-index-v1",
                "representation": "effective-smplx-55-axis-angle", "smplx_rest_model_sha256": MODEL_SHA,
                "training_weights_updated": False, "text_to_sign_trained": False, "training_ready": False,
                "model_training_ready": False, "research_only": True, "parents": parents.tolist(),
                "restJoints": np.round(rest, 7).tolist(), "clips": clips,
                "source_manifest_sha256": sha(source / "motions.jsonl"), "source_audit_sha256": sha(audit_path),
                "export_tool_sha256": sha(Path(__file__)), "input_sequences": len(rows),
                "duplicates": duplicates, "incomplete_excluded": audit["unselected"],
                "provenance_limitations": audit.get("provenance_limitations", []),
                "presentation": "Native upper-body/hand fits; root, lower body and spine at rest; hand mean added once. No interpolation of missing detections."}
    write_json(output / "experimental-index.json", manifest)
    print(json.dumps({"clips": len(clips), "frames": sum(c["frames"] for c in clips),
                      "duplicates": len(duplicates), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--smplx-model", type=Path, required=True)
    parser.add_argument("--exclude-bundle", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    export(parser.parse_args())
