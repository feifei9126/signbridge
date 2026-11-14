"""CPU encode/decode the three user-reviewed motion candidates for demo-only use."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

T08_SHA = "438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b"
SOKE_COMMIT = "5cbc55d84b5a7cbf05a9cf020c468052e8d94d00"
MODEL_SHA = "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992"
MOTION_REVIEW_SHA = "8297549518aaed82f88b94ff20550f4d708ddfe2229a1c614300a7f962752507"
SEGMENTS = (
    "new-fe2208d9680580cd-0087",
    "new-8ffc3bdb3f8d0763-0124",
    "new-58a5b3d6622ea72a-0068",
)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_reviewed_candidates(source):
    source = Path(source).resolve()
    approval = json.loads((source / "motion-review-decision.json").read_text())
    verification = json.loads((source / "verification.json").read_text())
    if (
        approval.get("status") != "approved_by_user"
        or approval.get("reviewer") != "user_reported"
        or approval.get("training_ready") is not False
        or verification.get("motion_visual_review_approved") is not True
        or verification.get("training_ready") is not False
        or verification.get("soke_commit") != SOKE_COMMIT
        or sha(source / "motion-review-decision.json") != MOTION_REVIEW_SHA
    ):
        raise ValueError("Reviewed candidate approval contract differs")
    decisions = {row["segment_id"]: row for row in approval["samples"]}
    rows = read_jsonl(source / "motions.jsonl")
    if [row["segment_id"] for row in rows] != list(SEGMENTS):
        raise ValueError("Candidate segment order or scope differs")
    content = {
        row["segment_id"]: row
        for row in read_jsonl(source.parent / "reviewed" / "reviewed.jsonl")
    }
    for row in rows:
        segment = row["segment_id"]
        reviewed = content.get(segment, {})
        quality = json.loads((source / "samples" / segment / "quality.json").read_text())
        if (
            row.get("motion_review_status") != "approved"
            or row.get("model_training_ready") is not False
            or row.get("motion_reviewer") != "user_reported"
            or row.get("mirror_status") != "unknown"
            or row.get("content_reviewed") is not True
            or reviewed.get("text_verified") != row.get("text_verified")
            or reviewed.get("source_sha256") != row.get("source_sha256")
            or reviewed.get("source_id") != row.get("source_id")
            or decisions[segment].get("source_id") != row.get("source_id")
            or reviewed.get("reviewer") != "user_reported"
            or reviewed.get("authorization_status") != "user_reported"
            or quality.get("motion_review_status") != "approved"
            or quality.get("model_training_ready") is not False
            or quality.get("motion_review_decision_sha256") != MOTION_REVIEW_SHA
        ):
            raise ValueError("Candidate review, text or training gate differs: " + segment)
        feature = (source / row["features"]).resolve()
        if source not in feature.parents or not feature.is_file():
            raise ValueError("Unsafe or missing candidate feature path: " + segment)
        if sha(feature) != decisions[segment]["evidence_sha256"]["features_133"]:
            raise ValueError("User-reviewed candidate feature digest differs: " + segment)
    return rows, approval


def main(args):
    import torch

    source, checkpoint, soke, model = (
        value.resolve()
        for value in (args.source, args.checkpoint, args.soke_root, args.smplx_model)
    )
    if sha(checkpoint) != T08_SHA or sha(model) != MODEL_SHA:
        raise ValueError("Frozen T08 or SMPL-X asset digest differs")
    if subprocess.check_output(
        ["git", "-C", str(soke), "rev-parse", "HEAD"], text=True
    ).strip() != SOKE_COMMIT:
        raise ValueError("SOKE revision differs")

    verification_path = source / "verification.json"
    rows, approval = load_reviewed_candidates(source)
    verification = json.loads(verification_path.read_text())
    if (
        approval.get("status") != "approved_by_user"
        or approval.get("reviewer") != "user_reported"
        or approval.get("training_ready") is not False
        or verification.get("motion_visual_review_approved") is not True
        or verification.get("training_ready") is not False
        or verification.get("soke_commit") != SOKE_COMMIT
        or sha(source / "motion-review-decision.json") != MOTION_REVIEW_SHA
    ):
        raise ValueError("Reviewed candidate approval contract differs")
    decisions = {row["segment_id"]: row for row in approval["samples"]}
    if set(decisions) != set(SEGMENTS):
        raise ValueError("Expected exactly the three approved demo candidates")
    saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
    if saved.get("research_only") is not True or saved.get("training_ready") is not False:
        raise ValueError("Unexpected baseline model contract")

    tool = Path(__file__).with_name("sign-tokenizer-smoke.py")
    spec = importlib.util.spec_from_file_location("candidate_smoke", tool)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    sys.path.insert(0, str(soke))
    module = importlib.import_module("mGPT.archs.mgpt_vq")
    models = torch.nn.ModuleList(
        [module.VQVae(**config) for config in saved["model_configs"]]
    )
    models.load_state_dict(saved["state_dict"], strict=True)
    models.eval()
    torch.set_num_threads(2)

    with np.load(model, allow_pickle=False) as assets:
        mean_pose = np.zeros((55, 3), dtype=np.float32)
        mean_pose[25:40] = assets["hands_meanl"].reshape(15, 3)
        mean_pose[40:55] = assets["hands_meanr"].reshape(15, 3)
        rest = np.asarray(assets["J_regressor"] @ assets["v_template"], dtype=np.float32)
        parents = assets["kintree_table"][0].astype(np.int32)
        parents[0] = -1

    clips = []
    for row in rows:
        segment = row["segment_id"]
        decision = decisions[segment]
        feature_path = (source / row["features"]).resolve()
        if source not in feature_path.parents:
            raise ValueError("Feature path escaped candidate data root")
        if sha(feature_path) != decision["evidence_sha256"]["features_133"]:
            raise ValueError("User-reviewed feature digest differs: " + segment)
        values = np.load(feature_path, allow_pickle=False)
        if (
            values.shape != (row["frames"], 133)
            or values.dtype != np.float32
            or not np.isfinite(values).all()
        ):
            raise ValueError("Invalid candidate feature array: " + segment)

        padded = np.pad(values, ((0, (-len(values)) % 4), (0, 0)), mode="edge")
        normalized = smoke.normalized_model_input(
            padded, saved["mean"], saved["std"], np.ones_like(padded, dtype=bool)
        )
        decoded, tokens, parity = [], [], []
        with torch.inference_mode():
            for vq, part in zip(models, smoke.split_parts(normalized)):
                tensor = torch.from_numpy(part).unsqueeze(0)
                ids, _ = vq.encode(tensor)
                prediction = vq.decode(ids)
                forward, _, _ = vq(tensor)
                maximum_error = float((prediction - forward).abs().max())
                if maximum_error > 1e-4:
                    raise ValueError("Token decode parity failed: " + segment)
                decoded.append(prediction[0].numpy())
                tokens.append(ids[0].tolist())
                parity.append(maximum_error)

        reconstructed = (
            smoke.combine_parts(decoded) * saved["std"] + saved["mean"]
        )[: len(values)].astype(np.float32)
        normalized_mse = float(
            np.mean(((reconstructed - values) / saved["std"]) ** 2)
        )
        if not np.isfinite(normalized_mse):
            raise ValueError("Nonfinite candidate reconstruction metric: " + segment)
        pose = np.zeros((len(values), 55, 3), dtype=np.float32)
        pose[:, 12:22] = reconstructed[:, :30].reshape(-1, 10, 3)
        pose[:, 25:40] = reconstructed[:, 30:75].reshape(-1, 15, 3)
        pose[:, 40:55] = reconstructed[:, 75:120].reshape(-1, 15, 3)
        pose[:, 22] = reconstructed[:, 120:123]
        pose += mean_pose[None]
        clips.append(
            {
                "id": segment,
                "text": row["text_verified"],
                "aliases": [row["text_verified"]],
                "fps": row["fps"],
                "frames": row["frames"],
                "duration": round(row["frames"] / row["fps"], 3),
                "tokens": dict(zip(("body", "left", "right"), tokens)),
                "poses": np.round(pose, 6).tolist(),
                "feature_sha256": sha(feature_path),
                "token_decode_parity_max": max(parity),
                "source_id": row["source_id"],
                "source_sha256": row["source_sha256"],
                "model_output": "token_decode_candidate",
                "normalized_reconstruction_mse": normalized_mse,
                "runtime_candidate": True,
                "training_data_member": False,
                "training_ready": False,
                "mirror_orientation_confirmed": False,
                "speaker_identity_confirmed": False,
                "source_sha256_reviewed": True,
                "authorization_status": row["authorization_status"],
                "motion_review_decision_sha256": MOTION_REVIEW_SHA,
            }
        )
        print(
            segment,
            "frames",
            row["frames"],
            "candidate normalized MSE",
            normalized_mse,
            "decode parity",
            max(parity),
            flush=True,
        )

    result = {
        "schema": "signbridge-t08-motion-candidates-v1",
        "training_checkpoint_sha256": T08_SHA,
        "training_checkpoint_step": saved["step"],
        "soke_commit": SOKE_COMMIT,
        "smplx_rest_model_sha256": MODEL_SHA,
        "representation": "effective-smplx-55-axis-angle",
        "restJoints": rest.tolist(),
        "parents": parents.tolist(),
        "clips": clips,
        "training_weights_updated": False,
        "text_to_sign_trained": False,
        "training_ready": False,
        "research_only": True,
        "human_review": "content and motion candidates user-reviewed; mirror orientation and speaker grouping remain unconfirmed",
        "export_tool_sha256": sha(__file__),
        "motion_review_decision_sha256": MOTION_REVIEW_SHA,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    print("EXPORT", args.output, sha(args.output), args.output.stat().st_size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--soke-root", type=Path, required=True)
    parser.add_argument("--smplx-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
