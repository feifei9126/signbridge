"""Two-keyframe MANO-to-SMPL-X pose/camera alignment candidates, never accepted training data."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

spec = importlib.util.spec_from_file_location(
    "hand_align_helper", Path(__file__).with_name("sign-hand-refine.py")
)
hand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hand)


def image_side_rotations(rotations, side):
    rotations = np.asarray(rotations, dtype=np.float64)
    hand.require(
        side in ("left", "right")
        and rotations.ndim == 3
        and rotations.shape[1:] == (3, 3),
        "Expected MANO rotation matrices and valid side",
    )
    hand.require(
        np.isfinite(rotations).all()
        and np.allclose(rotations @ rotations.transpose(0, 2, 1), np.eye(3), atol=1e-4)
        and np.allclose(np.linalg.det(rotations), 1, atol=1e-4),
        "Invalid MANO rotations",
    )
    mirror = np.diag([-1.0, 1.0, 1.0])
    return mirror @ rotations @ mirror if side == "left" else rotations.copy()


def global_rotations(model, params):
    pose = (
        np.concatenate(
            [
                params[k].reshape(-1, 3)
                for k in (
                    "global_orient",
                    "body_pose",
                    "jaw_pose",
                    "leye_pose",
                    "reye_pose",
                    "left_hand_pose",
                    "right_hand_pose",
                )
            ]
        )
        + model.mean
    )
    local = Rotation.from_rotvec(pose).as_matrix()
    world = local.copy()
    for i in range(1, 55):
        world[i] = world[model.parents[i]] @ local[i]
    return world


def map_pose(model, source, side, mano_fingers, mano_global):
    """MANOLayer matrix output is effective local rotation; SMPL-X AA expects mean offsets."""
    hand.require(
        np.asarray(mano_fingers).shape == (15, 3, 3)
        and np.asarray(mano_global).shape == (1, 3, 3),
        "Unexpected native MANO matrix dimensions",
    )
    candidate = {k: v.astype(np.float64).copy() for k, v in source.items()}
    start = 25 if side == "left" else 40
    candidate[side + "_hand_pose"] = (
        Rotation.from_matrix(image_side_rotations(mano_fingers, side)).as_rotvec()
        - model.mean[start : start + 15]
    )
    joint = hand.WRISTS[side]
    parent = global_rotations(model, candidate)[model.parents[joint]]
    desired = image_side_rotations(mano_global, side)[0]
    candidate["body_pose"][joint - 1] = Rotation.from_matrix(
        parent.T @ desired
    ).as_rotvec()
    return candidate


def fit_alignment(model, source, side, fingers, global_wrist, target, camera):
    """Keep MANO fingers/world wrist fixed; fit only same-side elbow within 15 degrees."""
    elbow = hand.ELBOWS[side] - 1
    baseline_elbow = source["body_pose"][elbow]

    def unpack(vector):
        values = {k: v.astype(np.float64).copy() for k, v in source.items()}
        values["body_pose"][elbow] = hand.bounded_elbow_rotation(
            vector, baseline_elbow, 15
        )
        return map_pose(model, values, side, fingers, global_wrist)

    initial = unpack(np.zeros(3))
    scale = max(hand.target_scale(target), 15.0)

    def residual(vector):
        candidate = unpack(vector)
        projected = hand.project(model.hand(candidate, side), camera)
        delta = (
            Rotation.from_rotvec(candidate["body_pose"][elbow])
            * Rotation.from_rotvec(baseline_elbow).inv()
        )
        return np.r_[
            (projected - target).ravel() / scale,
            3 * (projected[0] - target[0]) / scale,
            0.10 * delta.as_rotvec(),
        ]

    solution = least_squares(
        residual,
        np.zeros(3),
        max_nfev=100,
        loss="soft_l1",
        f_scale=0.1,
        xtol=1e-7,
        ftol=1e-7,
        gtol=1e-7,
    )
    fitted = unpack(solution.x)
    fitted = {k: v.astype(source[k].dtype) for k, v in fitted.items()}
    hand.preserved(source, fitted, (side,), allow_elbow=True)
    target3 = np.c_[target, np.zeros(len(target))]
    before = hand.reprojection_metrics(model.hand(source, side), target3, camera)
    mapped = hand.reprojection_metrics(model.hand(initial, side), target3, camera)
    after = hand.reprojection_metrics(model.hand(fitted, side), target3, camera)
    elbow_change = (
        Rotation.from_rotvec(fitted["body_pose"][elbow])
        * Rotation.from_rotvec(baseline_elbow).inv()
    ).magnitude()
    finger_change = Rotation.from_matrix(
        hand.hand_rotations(fitted, model, side)
        @ hand.hand_rotations(source, model, side).transpose(0, 2, 1)
    ).magnitude()
    wrist_index = hand.WRISTS[side] - 1
    wrist_change = (
        Rotation.from_rotvec(fitted["body_pose"][wrist_index])
        * Rotation.from_rotvec(source["body_pose"][wrist_index]).inv()
    ).magnitude()
    wb = float(
        np.linalg.norm(hand.project(model.hand(source, side), camera)[0] - target[0])
    )
    wa = float(
        np.linalg.norm(hand.project(model.hand(fitted, side), camera)[0] - target[0])
    )
    passed = (
        solution.status > 0
        and hand.projection_gate(before, after)
        and wa <= (wb * 0.8 if wb > 8 else wb + 1e-5)
        and elbow_change <= np.deg2rad(15) + 1e-7
        and finger_change.max() <= np.deg2rad(155)
        and wrist_change <= np.deg2rad(80)
    )
    return fitted, {
        "side": side,
        "fit_mode": "hand_plus_elbow",
        "candidate_gate_passed": bool(passed),
        "training_ready": False,
        "optimizer_status": int(solution.status),
        "nfev": int(solution.nfev),
        "before": before,
        "after_direct_mapping": mapped,
        "after": after,
        "elbow_change_degrees": float(np.rad2deg(elbow_change)),
        "max_finger_change_degrees": float(np.rad2deg(finger_change.max())),
        "local_wrist_change_degrees": float(np.rad2deg(wrist_change)),
        "wrist_error_before_pixels": wb,
        "wrist_error_after_pixels": wa,
        "finger_rotations_optimized": False,
        "global_wrist_rotation_optimized": False,
        "goal": "fit projected WiLoR joints, not human ground truth",
    }


def run(args):
    from PIL import Image

    source, fits, root, batch, out = [
        getattr(args, k).resolve()
        for k in ("wilor_results", "fits", "smplerx_root", "batch", "output")
    ]
    priorpath = source / "report.json"
    hand.require(
        hand.sha256(priorpath) == args.wilor_report_sha256,
        "Wrong WiLoR evidence report",
    )
    prior = json.loads(priorpath.read_text())
    hand.require(
        prior["status"] == "inferred_pending_visual_review"
        and prior["training_ready"] is False
        and prior["checkpoint_strict_load_passed"]
        and prior["source_files_unchanged"],
        "Incomplete WiLoR evidence",
    )
    hand.require(
        hand.sha256(fits / "run.json") == args.fit_run_sha256,
        "Wrong original SMPL-X run",
    )
    actual_commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    hand.require(actual_commit == hand.COMMIT, "Wrong fixed SMPLer-X source")
    old_run = json.loads((fits / "run.json").read_text())
    hand.require(
        old_run.get("status") == "inferred_pending_import_audit"
        and old_run.get("tasks_sha256") == hand.sha256(batch / "tasks.jsonl"),
        "Original fitting run does not match batch",
    )
    # Saved WiLoR output hashes from the downloaded inference evidence must still match.
    checks = {}
    for line in (source.parent / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        hand.require(name not in checks, "Duplicate prior evidence file")
        checks[name] = digest
    for case in prior["cases"]:
        for item in case["hands"]:
            relative = "results/" + case["segment_id"] + "/" + item["parameters_file"]
            value = hand.inside(source.parent, relative)
            hand.require(
                checks.get(relative) == hand.sha256(value),
                "Previous MANO parameter digest differs",
            )
    selected = hand.task_cases(batch)
    out = hand.new_output(out, [source, fits, root, batch])
    report = {
        "schema": "signbridge-mano-smplx-alignment-v1",
        "status": "running",
        "training_ready": False,
        "deployment_ready": False,
        "full_sequence_refined": False,
        "original_fits_overwritten": False,
        "wilor_report_sha256": args.wilor_report_sha256,
        "fit_run_sha256": args.fit_run_sha256,
        "source_sha256": {
            str(priorpath): hand.sha256(priorpath),
            str(fits / "run.json"): hand.sha256(fits / "run.json"),
        },
        "pose_convention": "MANO effective matrices; left SRS; subtract SMPL-X mean once; wrist parent-relative",
        "finger_fitting": False,
        "elbow_limit_degrees": 15,
        "cases": [],
    }
    reportpath = out / "report.json"

    def save():
        reportpath.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )

    save()
    report["source_sha256"].update(
        {
            str(p): hand.sha256(p)
            for p in (
                Path(__file__).resolve(),
                Path(hand.__file__).resolve(),
                batch / "contract.json",
                batch / "tasks.jsonl",
                batch / "SHA256SUMS",
                source.parent / "SHA256SUMS",
            )
        }
    )
    stage = "runtime"
    try:
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
        os.environ.setdefault("MPLBACKEND", "Agg")
        import torch, smplx

        hand.require(torch.cuda.is_available(), "Alignment verification requires CUDA")
        modelpath = hand.verify_model_assets(root)
        sparse = hand.SparseSMPLX(modelpath)
        native = (
            smplx.create(
                str(modelpath),
                model_type="smplx",
                gender="neutral",
                use_pca=False,
                flat_hand_mean=False,
                use_face_contour=False,
            )
            .cuda()
            .eval()
        )
        hand.require(
            np.allclose(
                native.pose_mean.detach().cpu().numpy().reshape(55, 3), sparse.mean
            ),
            "Wrong hand mean convention",
        )
        report["source_sha256"][str(modelpath)] = hand.sha256(modelpath)
        report["runtime"] = {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "native_smplx": str(Path(smplx.__file__).resolve()),
        }

        def mesh(params):
            values = {
                k: torch.tensor(v.reshape(1, -1), dtype=torch.float32, device="cuda")
                for k, v in params.items()
            }
            with torch.inference_mode():
                output = native(**values)
            j, v = output.joints[0, :55].cpu().numpy(), output.vertices[0].cpu().numpy()
            sj, st = sparse.forward(params)
            error = max(
                float(np.max(np.abs(j - sj))),
                float(np.max(np.abs(v[sparse.tip_ids] - st))),
            )
            hand.require(error < 5e-5, "Native alignment SMPL-X parity failed")
            return v, error

        report["renderer_preflight"] = hand.renderer_preflight()
        for task, number, sides, image_path, obs in selected:
            segment = task["segment_id"]
            stage = "mapping:" + segment
            case0 = next(
                c
                for c in prior["cases"]
                if c["segment_id"] == segment and c["frame_1based"] == number
            )
            original = hand.inside(fits, segment + "/smplx/%05d_0.npz" % number)
            meta = hand.inside(fits, segment + "/meta/%05d_0.json" % number)
            params = hand.read_native(original)
            camera = hand.native_camera(json.loads(meta.read_text()), image_path)
            folder = out / segment
            folder.mkdir()
            image = Image.open(image_path).convert("RGB")
            proposals = {}
            metrics = []
            targets = {}
            case = {"segment_id": segment, "frame_1based": number, "hands": []}
            report["cases"].append(case)
            report["source_sha256"].update(
                {str(p): hand.sha256(p) for p in (original, meta, image_path)}
            )
            for side in sides:
                hands = [h for h in case0["hands"] if h["side"] == side]
                hand.require(len(hands) == 1, "Ambiguous WiLoR source side")
                path = hand.inside(source, segment + "/" + hands[0]["parameters_file"])
                report["source_sha256"][str(path)] = hand.sha256(path)
                with np.load(path, allow_pickle=False) as a:
                    fingers = a["hand_pose"].copy()
                    wrist = a["global_orient"].copy()
                    target = a["projected_joints"].copy()
                fitted, metric = fit_alignment(
                    sparse, params, side, fingers, wrist, target, camera
                )
                proposals[side] = fitted
                metrics.append(metric)
                targets[side] = np.c_[target, np.zeros(21)]
                np.savez_compressed(
                    folder / (side + "-alignment-proposal.npz"), **fitted
                )
            candidate, passed = hand.merge_hand_candidates(
                sparse, params, proposals, metrics, targets, camera
            )
            case.update(
                hands=metrics,
                combined_projection_gate_passed=passed,
                all_candidate_gates_passed=all(
                    h["candidate_gate_passed"] for h in metrics
                ),
            )
            np.savez_compressed(folder / "baseline.npz", **params)
            np.savez_compressed(folder / "candidate.npz", **candidate)
            vb, eb = mesh(params)
            vc, ec = mesh(candidate)
            case.update(
                baseline_native_parity_max_metres=eb,
                candidate_native_parity_max_metres=ec,
            )
            baseline = Image.fromarray(
                hand.render_overlay(
                    np.asarray(image), vb, native.faces, camera, diagnostic=True
                )
            )
            saved = Image.fromarray(
                hand.render_overlay(
                    np.asarray(image), vc, native.faces, camera, diagnostic=True
                )
            )
            baseline.save(folder / "baseline-overlay.jpg")
            saved.save(folder / "candidate-overlay.jpg")
            for side in sides:
                vp, ep = mesh(proposals[side])
                proposal = Image.fromarray(
                    hand.render_overlay(
                        np.asarray(image), vp, native.faces, camera, diagnostic=True
                    )
                )
                case[side + "_proposal_parity_max_metres"] = ep
                target = targets[side][:, :2]
                lo, hi = target.min(axis=0), target.max(axis=0)
                center = np.rint((lo + hi) / 2).astype(int)
                radius = int(np.ceil(np.max(hi - lo) / 2 + 70))
                crop = (
                    center[0] - radius,
                    center[1] - radius,
                    center[0] + radius,
                    center[1] + radius,
                )
                hand.save_comparison(
                    folder / (side + "-alignment-compare.jpg"),
                    [
                        im.crop(crop).resize((480, 480))
                        for im in (image, baseline, saved, proposal)
                    ],
                    [
                        "Original",
                        "SMPL-X baseline",
                        "Saved candidate - unapproved",
                        "Alignment proposal - unapproved",
                    ],
                )
            save()
        stage = "source_recheck"
        for p, d in report["source_sha256"].items():
            hand.require(hand.sha256(p) == d, "Source changed: " + p)
        report.update(
            status=(
                "alignment_candidates_pending_visual_review"
                if all(c["all_candidate_gates_passed"] for c in report["cases"])
                else "alignment_candidate_gate_failed"
            ),
            source_files_unchanged=True,
            limitations=[
                "Pose correspondence candidate, not exact hand-shape correspondence",
                "MANO shape/camera not copied; original SMPL-X shape and camera fixed",
                "No contact, collision, temporal or semantic acceptance",
            ],
        )
        save()
        return 0
    except Exception as error:
        report.update(
            status="failed",
            error=str(error),
            failure_stage=stage,
            traceback=traceback.format_exc(),
        )
        save()
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("wilor-results", "fits", "smplerx-root", "batch", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--wilor-report-sha256", required=True)
    p.add_argument("--fit-run-sha256", required=True)
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
