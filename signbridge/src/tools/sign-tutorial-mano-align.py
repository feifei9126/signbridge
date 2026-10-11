"""Align verified MANO keyframe candidates to SMPL-X frames without promotion."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hand = load_tool("sign-hand-refine.py", "tutorial_alignment_hand")
alignment = load_tool("sign-mano-align.py", "tutorial_alignment_mano")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def require(value, message):
    if not value:
        raise ValueError(message)


def read_native(path):
    return hand.read_native(Path(path))


def load_mano_candidate(path, expected_side):
    with np.load(path, allow_pickle=False) as archive:
        side_key = "detector_right" if "detector_right" in archive.files else "right"
        required = {"hand_pose", "global_orient", "projected_joints", side_key, "detector_confidence"}
        require(required <= set(archive.files), "Incomplete MANO candidate: " + str(path))
        side = "right" if bool(archive[side_key]) else "left"
        require(side == expected_side, "MANO detector side differs from manifest")
        fingers = archive["hand_pose"].copy()
        wrist = archive["global_orient"].copy()
        target = np.asarray(archive["projected_joints"], dtype=np.float64)
        confidence = float(archive["detector_confidence"])
    require(fingers.shape == (15, 3, 3) and wrist.shape == (1, 3, 3), "Invalid MANO rotation shapes")
    require(target.shape == (21, 2) and np.isfinite(target).all(), "Invalid MANO projected joints")
    require(np.isfinite(confidence) and 0 <= confidence <= 1, "Invalid detector confidence")
    return fingers, wrist, np.c_[target, np.zeros(21)], confidence


def main(args):
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("MPLBACKEND", "Agg")
    import cv2
    import smplx
    import torch
    from PIL import Image

    root = args.smplerx_root.resolve()
    mano_inputs = args.mano_inputs.resolve()
    mano_results = args.mano_results.resolve()
    smplx_job = args.smplerx_job.resolve()
    output = args.output.resolve()
    require(not output.exists(), "Alignment output must be a new directory")
    require(torch.cuda.is_available(), "CUDA is required for SMPL-X alignment")
    manifest = json.loads((mano_inputs / "manifest.json").read_text())
    require(manifest["schema"] == "signbridge-tutorial-smplerx-independent-frames-v2", "Unexpected MANO input manifest")
    frame_count = manifest.get("frames")
    require(type(frame_count) is int and 1 <= frame_count <= 500 and len(manifest["cases"]) == frame_count,
            "Expected a bounded batch of 1-500 independent tutorial frames")
    mano_report_path = mano_results / "report.json"
    mano_report = json.loads(mano_report_path.read_text())
    require(mano_report.get("status") == "mano_batch_completed_pending_smplerx_alignment" and
            mano_report.get("cases_expected") == frame_count and mano_report.get("cases_completed") == frame_count and
            mano_report.get("training_ready") is False and mano_report.get("training_started") is False,
            "WiLoR/MANO batch is incomplete or promoted")
    mano_cases = {row["case_id"]: row for row in mano_report.get("cases", [])}
    require(len(mano_cases) == frame_count, "MANO result index is incomplete")
    model_path = hand.verify_model_assets(root)
    sparse = hand.SparseSMPLX(model_path)
    native = smplx.create(str(model_path), model_type="smplx", gender="neutral", use_pca=False,
                          flat_hand_mean=False, use_face_contour=False).cuda().eval()
    require(np.allclose(native.pose_mean.detach().cpu().numpy().reshape(55, 3), sparse.mean),
            "SMPL-X hand mean differs from sparse alignment model")

    output.mkdir(parents=True)
    report = {
        "schema": "signbridge-tutorial-mano-smplx-alignment-v1",
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "smplerx_commit": hand.COMMIT,
        "frames": frame_count,
        "pose_convention": "MANO effective matrices; image-side left reflection; SMPL-X hand mean subtracted once; parent-relative wrist",
        "scope": f"{frame_count} independent tutorial keyframes; no temporal smoothing or continuous sequence",
        "training_ready": False,
        "human_approved": False,
        "full_sequence_refined": False,
        "original_smplx_overwritten": False,
        "cases": [],
    }
    write_json(output / "report.json", report)
    source_paths = [Path(__file__).resolve(), Path(hand.__file__).resolve(), Path(alignment.__file__).resolve(), model_path,
                    mano_inputs / "manifest.json", mano_results / "report.json", mano_results / "SHA256SUMS",
                    smplx_job / "server-audit.json"]
    stage = "runtime"

    def mesh(params):
        values = {key: torch.tensor(value.reshape(1, -1), dtype=torch.float32, device="cuda")
                  for key, value in params.items()}
        with torch.inference_mode():
            result = native(**values)
        joints = result.joints[0, :55].detach().cpu().numpy()
        vertices = result.vertices[0].detach().cpu().numpy()
        sparse_joints, sparse_tips = sparse.forward(params)
        parity = max(float(np.max(np.abs(joints - sparse_joints))),
                     float(np.max(np.abs(vertices[sparse.tip_ids] - sparse_tips))))
        require(parity < 5e-5, "Native SMPL-X parity failed")
        return vertices, parity

    try:
        report["runtime"] = {"torch": torch.__version__, "cuda": torch.version.cuda,
                              "gpu": torch.cuda.get_device_name(0), "smplx": str(Path(smplx.__file__).resolve())}
        report["renderer_preflight"] = hand.renderer_preflight()
        for index, manifest_case in enumerate(manifest["cases"], 1):
            stage = "frame_" + str(index)
            smplx_params_path = smplx_job / "output/smplx" / ("%05d_0.npz" % index)
            meta_path = smplx_job / "output/meta" / ("%05d_0.json" % index)
            image_path = mano_inputs / manifest_case["image"]
            require(smplx_params_path.is_file() and meta_path.is_file() and image_path.is_file(), "Missing aligned input")
            params = read_native(smplx_params_path)
            meta = json.loads(meta_path.read_text())
            camera = hand.native_camera(meta, image_path)
            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
            folder = output / manifest_case["case_id"]
            folder.mkdir()
            np.savez_compressed(folder / "baseline.npz", **params)
            baseline_vertices, baseline_parity = mesh(params)
            candidates_by_side = {"left": [], "right": []}
            alternatives = []
            batch_case = mano_cases.get(manifest_case["case_id"])
            require(batch_case is not None and batch_case["gpu_input_frame_1based"] == index,
                    "MANO result case differs from input frame order")
            for candidate in batch_case["hands"]:
                side = candidate["side"]
                candidate_path = mano_results / candidate["parameters"]
                require(candidate_path.is_file() and hand.sha256(candidate_path) == candidate["parameters_sha256"],
                        "MANO result candidate hash differs")
                fingers, wrist, target_3d, confidence = load_mano_candidate(candidate_path, side)
                target = target_3d[:, :2]
                proposal, metric = alignment.fit_alignment(sparse, params, side, fingers, wrist, target, camera)
                metric.update({"detector_confidence": confidence, "candidate_parameters": candidate["parameters"],
                               "candidate_parameters_sha256": sha256(candidate_path),
                               "source_side_verified": False, "anatomical_side_verified": False,
                               "mirror_status": "unknown", "training_ready": False})
                candidates_by_side[side].append((proposal, metric, np.c_[target, np.zeros(21)]))
                alternatives.append(metric)
            proposals, metrics, targets = {}, [], {}
            selected = {}
            for side, options in candidates_by_side.items():
                if not options:
                    continue
                options.sort(key=lambda item: (not item[1]["candidate_gate_passed"], item[1]["after"]["local_rmse_pixels"],
                                               -item[1]["detector_confidence"]))
                proposal, metric, target = options[0]
                proposals[side] = proposal
                metrics.append(metric)
                targets[side] = target
                selected[side] = {"candidate_parameters": metric["candidate_parameters"],
                                  "candidate_gate_passed": metric["candidate_gate_passed"],
                                  "alternatives": len(options)}
            if proposals:
                candidate_params, combined_passed = alignment.hand.merge_hand_candidates(
                    sparse, params, proposals, metrics, targets, camera)
            else:
                candidate_params, combined_passed = dict(params), False
            np.savez_compressed(folder / "candidate.npz", **candidate_params)
            candidate_vertices, candidate_parity = mesh(candidate_params)
            baseline_image = Image.fromarray(hand.render_overlay(np.asarray(image), baseline_vertices,
                                                                 native.faces, camera, diagnostic=True))
            candidate_image = Image.fromarray(hand.render_overlay(np.asarray(image), candidate_vertices,
                                                                  native.faces, camera, diagnostic=True))
            baseline_image.save(folder / "baseline-overlay.jpg")
            candidate_image.save(folder / "candidate-overlay.jpg")
            hand.save_comparison(folder / "frame-compare.jpg", [image, baseline_image, candidate_image],
                                 ["Original", "SMPL-X baseline", "Aligned candidate - NOT approved"])
            case = {
                "output_index": index, "case_id": manifest_case["case_id"], "annotation_id": manifest_case["annotation_id"],
                "label": manifest_case["label"], "source_reference_frame_1based": manifest_case.get("source_reference_frame_1based", manifest_case.get("frame_1based")),
                "source_seconds_nominal": manifest_case["source_seconds_nominal"], "selected": selected,
                "candidate_alternatives": alternatives, "combined_projection_gate_passed": bool(combined_passed),
                "all_candidate_gates_passed": bool(metrics) and all(m["candidate_gate_passed"] for m in metrics),
                "baseline_native_parity_max_metres": baseline_parity, "candidate_native_parity_max_metres": candidate_parity,
                "baseline": "baseline.npz", "candidate": "candidate.npz", "baseline_overlay": "baseline-overlay.jpg",
                "candidate_overlay": "candidate-overlay.jpg", "frame_compare": "frame-compare.jpg",
                "training_ready": False, "human_approved": False, "mirror_status": "unknown",
                "anatomical_handedness_verified": False,
            }
            report["cases"].append(case)
            write_json(output / "report.json", report)
            print(json.dumps({"frame": index, "label": manifest_case["label"], "hands": len(metrics),
                              "combined_gate": bool(combined_passed)}, ensure_ascii=False), flush=True)
        report.update(status="alignment_candidates_pending_visual_review", elapsed_frames=len(report["cases"]),
                      training_started=False, smplx_parameters_created=True,
                      limitations=["MANO and SMPL-X are both model estimates; no 3D hand ground truth.",
                                   "Detector side, source mirroring and anatomical handedness remain unverified.",
                                   "Only isolated keyframes; no temporal smoothing or continuous action acceptance.",
                                   "Candidate files never overwrite original SMPL-X parameters."])
        report["source_sha256"] = {str(path): sha256(path) for path in source_paths}
        write_json(output / "report.json", report)
        files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
        (output / "SHA256SUMS").write_text("".join(sha256(path) + "  " + str(path.relative_to(output)) + "\n" for path in files))
    except Exception as error:
        report.update(status="failed", failure_stage=stage, error=str(error), traceback=traceback.format_exc())
        write_json(output / "report.json", report)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smplerx-root", type=Path, required=True)
    parser.add_argument("--smplerx-job", type=Path, required=True)
    parser.add_argument("--mano-inputs", type=Path, required=True)
    parser.add_argument("--mano-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
