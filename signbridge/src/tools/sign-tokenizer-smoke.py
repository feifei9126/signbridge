"""Research-only SOKE tokenizer smoke training; never authorizes training-ready data."""

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

SOKE_COMMIT = "5cbc55d84b5a7cbf05a9cf020c468052e8d94d00"
SEGMENTS = ("pilot-greeting-hello-001", "pilot-hospital-cough-003")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_inputs(root, acknowledged=False, segment_ids=None):
    root = Path(root).resolve()
    expected_segments = list(SEGMENTS) if segment_ids is None else list(segment_ids)
    if not expected_segments or any(not isinstance(segment, str) or
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", segment) is None
            for segment in expected_segments) or len(set(expected_segments)) != len(expected_segments):
        raise ValueError("Explicit segment scope must be nonempty, unique, and path-safe")
    verification = json.loads((root / "verification.json").read_text())
    if (verification.get("soke_commit") != SOKE_COMMIT or verification.get("training_ready") is not False or
            verification.get("converted") != len(expected_segments) or verification.get("rejected") != []):
        raise ValueError("Unexpected motion verification contract")
    skipped = {item.get("segment_id") for item in verification.get("skipped", [])
               if isinstance(item, dict)}
    if skipped & set(expected_segments):
        raise ValueError("Explicit scope contains skipped samples")
    if not acknowledged:
        raise ValueError("research-only smoke requires explicit acknowledgement of unreviewed data")
    rows = [json.loads(line) for line in (root / "motions.jsonl").read_text().splitlines() if line.strip()]
    if [row.get("segment_id") for row in rows] != expected_segments:
        raise ValueError("Unexpected smoke segment order or explicit scope")
    arrays, hashes = [], [digest(root / "verification.json"), digest(root / "motions.jsonl")]
    for row in rows:
        if row.get("model_training_ready") is not False or row.get("motion_review_status") != "needs_review":
            raise ValueError("Smoke input unexpectedly marked trainable")
        if segment_ids is not None and (row.get("content_reviewed") is not True or
                                       not row.get("text_verified", "").strip()):
            raise ValueError("Explicit scope requires content-reviewed samples with verified text")
        if row.get("representation") != "soke-smplx-133-v1" or row.get("dimensions") != 133:
            raise ValueError("Unexpected motion representation")
        relative = Path(row["features"])
        path = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or root not in path.parents or not path.is_file():
            raise ValueError("Unsafe or missing feature path")
        values = np.load(path, allow_pickle=False)
        if values.ndim != 2 or values.shape != (row["frames"], 133) or values.dtype != np.float32:
            raise ValueError("Unexpected feature dimensions or dtype")
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite feature values")
        if len(values) < 64:
            raise ValueError("Input shorter than smoke training window")
        arrays.append(values.copy())
        hashes.append(digest(path))
    return rows, arrays, hashes


def split_parts(values):
    if values.ndim != 2 or values.shape[1] != 133:
        raise ValueError("Expected SOKE 133 dimensions")
    return [np.concatenate((values[:, :30], values[:, 120:]), axis=1),
            values[:, 30:75], values[:, 75:120]]


def combine_parts(parts):
    if len(parts) != 3 or [part.shape[1] for part in parts] != [43, 45, 45]:
        raise ValueError("Invalid SOKE part dimensions")
    return np.concatenate((parts[0][:, :30], parts[1], parts[2], parts[0][:, 30:]), axis=1)


def make_windows(arrays, window=64):
    result = []
    for values in arrays:
        if values.shape[0] < window:
            raise ValueError("Sequence shorter than smoke window")
        starts = list(range(0, values.shape[0] - window + 1, 16))
        if starts[-1] != values.shape[0] - window:
            starts.append(values.shape[0] - window)
        result.extend(values[start:start + window] for start in starts)
    return np.stack(result).astype(np.float32, copy=False)


def load_quality_masks(root, rows, required=False):
    masks, hashes = [], []
    root = Path(root).resolve()
    for row in rows:
        feature = (root / row["features"]).resolve()
        path = feature.with_name("feature-valid-mask.npy")
        if not path.is_file():
            if required:
                raise ValueError("Missing full-fusion quality mask")
            masks.append(np.ones((row["frames"],133),dtype=bool))
            continue
        if root not in path.parents:
            raise ValueError("Unsafe quality mask path")
        value=np.load(path,allow_pickle=False)
        if value.shape!=(row["frames"],133) or value.dtype.kind!="b":
            raise ValueError("Invalid quality mask shape/dtype")
        masks.append(value.copy());hashes.append(digest(path))
    return masks,hashes


def quality_masks_required(verification):
    if verification.get('schema') == 'signbridge-hand-observation-screen-v1':
        if verification.get('quality_masks_required') is not True:
            raise ValueError('Hand observation screening requires explicit quality masks')
        return True
    return verification.get('schema') == 'signbridge-full-fusion-export-v1'


def normalization(arrays, masks=None):
    joined=np.concatenate(arrays,axis=0).astype(np.float64)
    valid=np.ones_like(joined,dtype=bool) if masks is None else np.concatenate(masks,axis=0)
    if valid.shape!=joined.shape or valid.dtype.kind!="b":
        raise ValueError("Invalid normalization mask")
    count=valid.sum(axis=0)
    mean=np.sum(np.where(valid,joined,0.),axis=0)/np.maximum(count,1)
    variance=np.sum(np.where(valid,(joined-mean)**2,0.),axis=0)/np.maximum(count,1)
    std=np.maximum(np.sqrt(variance),.05)
    std[count==0]=1.
    return mean.astype(np.float32),std.astype(np.float32)


def normalized_model_input(values,mean,std,valid):
    values=np.asarray(values);mean=np.asarray(mean);std=np.asarray(std);valid=np.asarray(valid)
    if values.ndim!=2 or values.shape[1]!=133 or valid.shape!=values.shape or valid.dtype.kind!='b' or \
       mean.shape!=(133,) or std.shape!=(133,) or not np.isfinite(values).all() or \
       not np.isfinite(mean).all() or not np.isfinite(std).all() or not (std>0).all():
        raise ValueError('Invalid masked model input')
    # Neutral placeholders exist only inside model input; saved motion and detection masks are untouched.
    return np.where(valid,(values-mean)/std,0.).astype(np.float32)


def train(args):
    """Small from-scratch tokenizer overfit test; no text generator or held-out claims."""
    root, soke, output = args.motions.resolve(), args.soke_root.resolve(), args.output.resolve()
    if any(output == p or p in output.parents or output in p.parents for p in (root, soke)):
        raise ValueError("Output must be separate from source inputs")
    segment_ids = getattr(args, "segment_id", None)
    rows, arrays, hashes = load_inputs(root, args.research_only, segment_ids)
    verification=json.loads((root/"verification.json").read_text())
    quality_masked=quality_masks_required(verification)
    masks,mask_hashes=load_quality_masks(root,rows,required=quality_masked)
    hashes+=mask_hashes
    commit = subprocess.check_output(["git", "-C", str(soke), "rev-parse", "HEAD"], text=True).strip()
    if commit != SOKE_COMMIT:
        raise ValueError("SOKE source commit differs")
    source_files = [soke / "mGPT/archs/mgpt_vq.py", soke / "mGPT/archs/tools/resnet.py",
                    soke / "mGPT/archs/tools/quantize_cnn.py"]
    source_hashes = {str(p): digest(p) for p in source_files}
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "signbridge-tokenizer-smoke-v1", "status": "running",
              "research_only": True, "training_ready": False, "deployment_ready": False,
              "text_to_sign_trained": False, "generalization_evaluated": False,
              "input_quality": verification.get("input_quality", "UNREVIEWED original SMPLer-X estimates, not corrected sequences"),
              "quality_masked_hand_targets": quality_masked,
              "unaccepted_model_inputs": "neutral normalized placeholders with loss mask; never written to motion tracks",
              "valid_target_counts": np.concatenate(masks).sum(axis=0).tolist(),
              "normalization": "own training samples only; from scratch, NOT pretrained mean/std",
              "soke_commit": commit, "source_sha256": source_hashes, "input_sha256": hashes,
              "sequences": [{"segment_id": r["segment_id"], "frames": r["frames"]} for r in rows],
              "scope": "smaller official SOKE VQVae architecture for training-pipeline debugging",
              "seed": 20261009, "steps": args.steps, "learning_rate": .001,
              "explicit_segment_scope": segment_ids is not None,
              "evaluation_completed": False,
              "training_source_ids": sorted({r.get("source_id", "") for r in rows}),
              "source_or_person_independence_verified": False}
    report_path = output / "report.json"

    def save_report():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")

    save_report()
    try:
        import torch
        if not torch.cuda.is_available():
            raise ValueError("Actual CUDA required for this research smoke")
        torch.manual_seed(report["seed"])
        torch.cuda.manual_seed_all(report["seed"])
        torch.set_num_threads(1)
        sys.path.insert(0, str(soke))
        module = importlib.import_module("mGPT.archs.mgpt_vq")
        if Path(module.__file__).resolve() != source_files[0]:
            raise ValueError("Wrong VQVae source module")
        config = {"quantizer": "ema_reset", "code_dim": 64, "output_emb_width": 64,
                  "width": 128, "down_t": 2, "stride_t": 2, "depth": 2,
                  "dilation_growth_rate": 2, "activation": "relu", "norm": None}
        configs = [{**config, "nfeats": width, "code_num": count}
                   for width, count in ((43, 16), (45, 32), (45, 32))]
        models = torch.nn.ModuleList([module.VQVae(**values).cuda() for values in configs])
        report.update(torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
                      parameters=sum(p.numel() for p in models.parameters()), model_configs=configs)
        mean, std = normalization(arrays,masks)
        normalized = [normalized_model_input(value,mean,std,mask) for value,mask in zip(arrays,masks)]
        windows = make_windows(normalized)
        report["train_windows"] = len(windows)
        tensor = torch.from_numpy(windows).cuda()
        mask_tensor=torch.from_numpy(make_windows(masks)).cuda()
        mask_parts=[torch.cat((mask_tensor[...,:30],mask_tensor[...,120:]),dim=-1),
                    mask_tensor[...,30:75],mask_tensor[...,75:120]]
        parts = [torch.cat((tensor[..., :30], tensor[..., 120:]), dim=-1),
                 tensor[..., 30:75], tensor[..., 75:120]]
        optimizer = torch.optim.AdamW(models.parameters(), lr=.001, weight_decay=0.0)

        def forward(part_batch):
            predictions, commits = [], []
            for model, part in zip(models, part_batch):
                prediction, commitment, _ = model(part)
                predictions.append(prediction)
                commits.append(commitment)
            return predictions, commits

        def eval_mse():
            models.eval()
            with torch.no_grad():
                predictions, _ = forward(parts)
                numerator=sum(((p-t)**2*m).sum() for p,t,m in zip(predictions,parts,mask_parts))
                denominator=sum(m.sum() for m in mask_parts).clamp(min=1)
                return float((numerator/denominator).item())

        # Initialize the EMA codebooks using observed activations, without optimizing weights.
        models.train()
        with torch.no_grad():
            forward([part[:4] for part in parts])
        initial = eval_mse()
        report["initial_training_mse_normalized"] = initial
        report["best_training_mse_normalized"] = initial
        history = []
        start = time.monotonic()
        for step in range(1, args.steps + 1):
            models.train()
            indices = torch.randint(0, tensor.shape[0], (min(8, tensor.shape[0]),), device="cuda")
            inputs = [part[indices] for part in parts]
            predicted, commits = forward(inputs)
            loss = sum((torch.nn.functional.smooth_l1_loss(p,t,reduction="none")*m[indices]).sum() /
                       m[indices].sum().clamp(min=1) for p,t,m in zip(predicted,inputs,mask_parts)) + .02*sum(commits)
            if not torch.isfinite(loss):
                raise ValueError("Training loss became nonfinite")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(models.parameters(), 1.0)
            optimizer.step()
            if step == 1 or step % 50 == 0 or step == args.steps:
                mse = eval_mse()
                record = {"step": step, "loss": float(loss.item()), "training_mse_normalized": mse}
                history.append(record)
                print(json.dumps(record), flush=True)
                if mse < report["best_training_mse_normalized"]:
                    report["best_training_mse_normalized"] = mse
                    torch.save({"schema": "signbridge-tokenizer-smoke-checkpoint-v1", "model_configs": configs,
                                "state_dict": models.state_dict(), "mean": mean, "std": std,
                                "research_only": True, "training_ready": False, "step": step,
                                "train_segments": [r["segment_id"] for r in rows],
                                "train_source_ids": sorted({r.get("source_id", "") for r in rows}),
                                "soke_commit": commit}, output / "tokenizer-smoke.pt")
                save_report()
        checkpoint = output / "tokenizer-smoke.pt"
        if not checkpoint.is_file():
            raise ValueError("No training improvement; no checkpoint saved")
        loaded = torch.load(checkpoint, map_location="cuda")  # Our own just-written checkpoint only.
        models.load_state_dict(loaded["state_dict"], strict=True)
        models.eval()
        sample_metrics = []
        with torch.no_grad():
            for row, normalized_values, raw, valid in zip(rows, normalized, arrays, masks):
                count = len(normalized_values)
                pad = (-count) % 4
                padded = np.pad(normalized_values, ((0, pad), (0, 0)), mode="edge")
                inputs = [torch.from_numpy(p).unsqueeze(0).cuda() for p in split_parts(padded)]
                predicted, _ = forward(inputs)
                prediction = combine_parts([p[0].cpu().numpy() for p in predicted])[:count] * std + mean
                folder = output / row["segment_id"]
                folder.mkdir()
                np.save(folder / "reconstructed-133.npy", prediction.astype(np.float32))
                for name, model, part in zip(("body", "left", "right"), models, inputs):
                    tokens, _ = model.encode(part)
                    np.save(folder / (name + "-tokens.npy"), tokens.cpu().numpy())
                sample_metrics.append({"segment_id": row["segment_id"], "frames": count,
                    "in_sample_rmse_raw": float(np.sqrt(np.sum((prediction-raw)**2*valid)/max(int(valid.sum()),1))),
                    "all_frames_rmse_including_unaccepted": float(np.sqrt(np.mean((prediction-raw)**2))),
                    "left_hand_rmse_radians": float(np.sqrt(np.sum((prediction[:,30:75]-raw[:,30:75])**2*valid[:,30:75])/
                        max(int(valid[:,30:75].sum()),1))) if valid[:,30:75].any() else None,
                    "right_hand_rmse_radians": float(np.sqrt(np.sum((prediction[:,75:120]-raw[:,75:120])**2*valid[:,75:120])/
                        max(int(valid[:,75:120].sum()),1))) if valid[:,75:120].any() else None})
        _, _, after_hashes = load_inputs(root, True, segment_ids)
        _,after_masks=load_quality_masks(root,rows,required=quality_masked)
        after_hashes+=after_masks
        if hashes != after_hashes or any(digest(Path(name)) != value for name, value in source_hashes.items()):
            raise ValueError("Source changed during training")
        reloaded_mse = eval_mse()
        if not np.isclose(reloaded_mse, report["best_training_mse_normalized"], atol=1e-6, rtol=1e-5):
            raise ValueError("Reloaded checkpoint reconstruction differs")
        report.update(status="research_smoke_trained_not_deployable", elapsed_seconds=time.monotonic() - start,
                      checkpoint=str(checkpoint), checkpoint_sha256=digest(checkpoint),
                      checkpoint_reload_passed=True, reloaded_training_mse_normalized=reloaded_mse,
                      checkpoint_step=loaded["step"], history=history,
                      in_sample_metrics=sample_metrics, source_files_unchanged=True,
                      limitations=[f"{len(rows)} sequences, no held-out evaluation; improvement can be memorization",
                                   "Learns model-estimated motion; quality masks exclude missing/rejected hand reconstruction targets" if quality_masked else
                                   "Learns unreviewed original motion including hand errors",
                                   "No text conditioning; NOT a trained text-to-sign model",
                                   "Not the full-width official SOKE pretrained tokenizer",
                                   "Do not import outputs into production or mark data as training-ready"])
        save_report()
        print(json.dumps({"status": report["status"], "report": str(report_path)}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        report.update(status="failed", error=str(exc), traceback=traceback.format_exc())
        save_report()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motions", type=Path, required=True)
    parser.add_argument("--soke-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-only", action="store_true")
    parser.add_argument("--steps", type=int, choices=range(50, 1001), default=500)
    parser.add_argument("--segment-id", action="append", dest="segment_id",
                        help="Explicit complete motion scope; repeat once per segment")
    return train(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
