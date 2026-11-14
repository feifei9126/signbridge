"""Frozen motion-tokenizer diagnostics, never independent sign-language accuracy."""

import argparse
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.spatial.transform import Rotation


def tool(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inference = tool("sign-tokenizer-infer")
evaluation = tool("sign-heldout-eval")
smoke = inference.smoke
evidence = evaluation.evidence
PARTS = ("all", "body_face", "left_hand", "right_hand")
GROUP_FIELDS = ("source_id", "source_sha256", "signer_id", "split_group")


def evaluation_scope(training, reference):
    scopes = []
    for rows in (training, reference):
        ids = [row.get("segment_id") for row in rows]
        if not ids or any(not isinstance(value, str) or
                          re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value) is None
                          for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("Missing, duplicate or unsafe clip IDs")
        scopes.append(ids)
    if set(scopes[0]) & set(scopes[1]):
        raise ValueError("Training and evaluation clips overlap")
    shared = {field: sorted({r.get(field) for r in training if r.get(field)} &
                            {r.get(field) for r in reference if r.get(field)})
              for field in GROUP_FIELDS}
    return {"train_segments": scopes[0], "evaluation_segments": scopes[1],
            "segment_disjoint": True, "shared_recorded_groups": shared,
            "person_independence_verified": False, "independent_final_test": False,
            "evaluation_used_for_weight_updates": False,
            "evaluation_used_for_checkpoint_selection": False,
            "prior_use_by_other_models_checked": False}


def verify_training_scope(report, saved, rows):
    expected = [{"segment_id": r["segment_id"], "frames": r["frames"]} for r in rows]
    if report.get("schema") != "signbridge-tokenizer-smoke-v1" or \
            report.get("status") != "research_smoke_trained_not_deployable" or \
            report.get("checkpoint_reload_passed") is not True or \
            report.get("research_only") is not True or report.get("training_ready") is not False or \
            report.get("sequences") != expected or \
            saved.get("train_segments") != [r["segment_id"] for r in rows]:
        raise ValueError("Checkpoint training scope differs or training report is incomplete")


def summarize_metrics(samples):
    result = {}
    for part in PARTS:
        values = [s["metrics"][part] for s in samples]
        count = sum(v["valid_values"] for v in values)
        if not count:
            result[part] = {"valid_values": 0, "normalized_mse": None, "raw_rmse": None,
                            "mean_baseline_normalized_mse": None,
                            "mean_baseline_improvement_percent": None}
            continue
        valid = [v for v in values if v["valid_values"]]
        mse = sum(v["normalized_mse"] * v["valid_values"] for v in valid) / count
        baseline = sum(v["mean_baseline_normalized_mse"] * v["valid_values"] for v in valid) / count
        rmse = np.sqrt(sum(v["raw_rmse"] ** 2 * v["valid_values"] for v in valid) / count)
        result[part] = {"valid_values": count, "normalized_mse": float(mse), "raw_rmse": float(rmse),
                        "mean_baseline_normalized_mse": float(baseline),
                        "mean_baseline_improvement_percent": float(100 * (baseline - mse) / baseline)
                        if baseline > 0 else None}
    return result


def rotation_errors(prediction, truth, valid):
    if prediction.shape != truth.shape or truth.ndim != 2 or truth.shape[1] != 133 or \
            valid.shape != truth.shape or valid.dtype.kind != "b" or \
            not np.isfinite(prediction).all() or not np.isfinite(truth).all():
        raise ValueError("Invalid motion rotation/mask arrays")
    result = {}
    for part, start, end in (("body", 0, 30), ("left_hand", 30, 75),
                             ("right_hand", 75, 120), ("jaw", 120, 123)):
        mask = valid[:, start:end].reshape(-1, 3).all(axis=1)
        a = prediction[:, start:end].reshape(-1, 3)[mask].astype(np.float64)
        b = truth[:, start:end].reshape(-1, 3)[mask].astype(np.float64)
        angles = np.degrees((Rotation.from_rotvec(a) * Rotation.from_rotvec(b).inv()).magnitude()) \
            if len(a) else np.empty(0)
        result[part] = {"valid_rotations": len(a),
                        "mean_degrees": float(angles.mean()) if len(a) else None,
                        "p95_degrees": float(np.percentile(angles, 95)) if len(a) else None,
                        "max_degrees": float(angles.max()) if len(a) else None}
    return result


def load_motion_inputs(root):
    rows = [json.loads(line) for line in (root / "motions.jsonl").read_text().splitlines() if line.strip()]
    ids = [r.get("segment_id") for r in rows]
    rows, arrays, hashes = smoke.load_inputs(root, True, segment_ids=ids)
    contract = json.loads((root / "verification.json").read_text())
    masks, mask_hashes = smoke.load_quality_masks(
        root, rows, required=smoke.quality_masks_required(contract))
    return rows, arrays, masks, hashes + mask_hashes


def evaluate(args):
    training = args.training_results.resolve()
    train_motions = args.training_motions.resolve()
    reference = args.evaluation_motions.resolve()
    out = args.output.resolve()
    for root in (training, train_motions, reference, args.soke_root.resolve()):
        if out == root or root in out.parents or out in root.parents:
            raise ValueError("Keep output separate from source inputs")
    if out.exists():
        raise ValueError("Choose a new output directory")
    report_path = training / "report.json"
    inference.verify_checkpoint(report_path, args.training_report_sha256)
    evidence.verify_manifest(reference, reference / "SHA256SUMS")
    report = json.loads(report_path.read_text())
    checkpoint = training / "tokenizer-smoke.pt"
    inference.verify_checkpoint(checkpoint, report["checkpoint_sha256"])
    train_rows, train_arrays, train_masks, train_hashes = load_motion_inputs(train_motions)
    rows, arrays, masks, _ = load_motion_inputs(reference)
    scope = evaluation_scope(train_rows, rows)
    if train_hashes != report.get("input_sha256"):
        raise ValueError("Training data digests differ from the saved experiment")
    import torch
    version = tuple(map(int, torch.__version__.split("+")[0].split(".")[:2]))
    saved = torch.load(checkpoint, map_location="cpu", weights_only=False) if version >= (2, 0) \
        else torch.load(checkpoint, map_location="cpu")
    inference.checkpoint_contract(saved)
    verify_training_scope(report, saved, train_rows)
    mean, std = smoke.normalization(train_arrays, train_masks)
    if not np.array_equal(mean, saved["mean"]) or not np.array_equal(std, saved["std"]):
        raise ValueError("Checkpoint normalization differs from training-only statistics")
    watched = {str(path): evidence.digest(path) for root in (training, train_motions, reference)
               for path in root.rglob("*") if path.is_file()}
    out.mkdir(parents=True)
    samples = []
    for row, truth, valid in zip(rows, arrays, masks):
        mask_path = reference / row["features"]
        mask_path = mask_path.with_name("feature-valid-mask.npy")
        folder = out / "inference" / row["segment_id"]
        inference.infer(SimpleNamespace(checkpoint=checkpoint,
                        checkpoint_sha256=report["checkpoint_sha256"],
                        features=reference / row["features"],
                        mask=mask_path if mask_path.is_file() else None,
                        soke_root=args.soke_root, device="cpu", output=folder))
        prediction = np.load(folder / "reconstructed-133.npy", allow_pickle=False)
        samples.append({"segment_id": row["segment_id"], "frames": row["frames"],
                        "text_verified": row["text_verified"],
                        "metrics": evaluation.comparison_metrics(prediction, truth, valid, mean, std),
                        "rotation_geodesic_vs_fitted_reference": rotation_errors(prediction, truth, valid)})
    for path, digest in watched.items():
        if evidence.digest(path) != digest:
            raise ValueError("Input or checkpoint changed during frozen evaluation: " + path)
    result = {"schema": "signbridge-frozen-clip-diagnostic-v1",
              "status": "frozen_clip_diagnostic_complete_pending_review", "scope": scope,
              "checkpoint_sha256": report["checkpoint_sha256"], "checkpoint_step": saved["step"],
              "training_report_sha256": args.training_report_sha256,
              "normalization_training_only_verified": True, "training_weight_updates": 0,
              "source_files_unchanged": True, "samples": samples,
              "summary": summarize_metrics(samples), "research_only": True,
              "training_ready": False, "deployment_ready": False,
              "text_to_sign_generated": False, "independent_generalization_evaluated": False,
              "source_sha256": watched, "evaluation_tool_sha256": evidence.digest(__file__),
              "limitations": ["Unseen clips for this checkpoint are not independent-source tests.",
                              "References are model-estimated motion, not independent motion capture.",
                              "Axis-angle/expression reconstruction error is not sign-language accuracy.",
                              "Evaluation clips may have been used by earlier models or diagnostics.",
                              "Mirror, actual identity and final test qualification remain unconfirmed."]}
    (out / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (out / "SHA256SUMS").write_text("".join(evidence.digest(p) + "  " + str(p.relative_to(out)) + "\n"
                                            for p in sorted(out.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"))
    return out / "report.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("training-results", "training-motions", "evaluation-motions", "soke-root", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--training-report-sha256", required=True)
    print(evaluate(parser.parse_args()))


if __name__ == "__main__":
    main()
