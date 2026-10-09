"""Four-frame bounded two-elbow contact/depth hypothesis; never training data promotion."""

import argparse
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

spec = importlib.util.spec_from_file_location(
    "contact_alignment", Path(__file__).with_name("sign-mano-align.py")
)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
hand = align.hand
SIDES = ("left", "right")
FRAMES = tuple(range(88, 92))
SEGMENT = "pilot-greeting-hello-001"


def initial_elbow_vector(original, fusion):
    return np.concatenate(
        [
            (
                Rotation.from_rotvec(fusion["body_pose"][hand.ELBOWS[s] - 1])
                * Rotation.from_rotvec(original["body_pose"][hand.ELBOWS[s] - 1]).inv()
            ).as_rotvec()
            for s in SIDES
        ]
    )


def contact_parameters(model, original, fusion, vector):
    hand.require(
        np.asarray(vector).shape == (6,) and np.isfinite(vector).all(),
        "Invalid two-elbow vector",
    )
    candidate = {k: v.astype(np.float64).copy() for k, v in fusion.items()}
    world = align.global_rotations(model, fusion)
    for i, side in enumerate(SIDES):
        elbow = hand.ELBOWS[side] - 1
        candidate["body_pose"][elbow] = hand.bounded_elbow_rotation(
            vector[i * 3 : i * 3 + 3], original["body_pose"][elbow], 15
        )
    parents = align.global_rotations(model, candidate)
    for side in SIDES:
        wrist = hand.WRISTS[side]
        candidate["body_pose"][wrist - 1] = Rotation.from_matrix(
            parents[model.parents[wrist]].T @ world[wrist]
        ).as_rotvec()
    hand.preserved(fusion, candidate, SIDES, allow_elbow=True)
    for side in SIDES:
        hand.require(
            np.array_equal(candidate[side + "_hand_pose"], fusion[side + "_hand_pose"]),
            "Contact changed finger pose",
        )
    return candidate


def metrics(model, params, targets, camera, pair):
    hands = {}
    xyz = {}
    for side in SIDES:
        xyz[side] = model.hand(params, side)
        projected = hand.project(xyz[side], camera)
        hands[side] = {
            **hand.reprojection_metrics(
                xyz[side], np.c_[targets[side], np.zeros(21)], camera
            ),
            "wrist_error_pixels": float(
                np.linalg.norm(projected[0] - targets[side][0])
            ),
        }
    delta = xyz["left"][pair[0]] - xyz["right"][pair[1]]
    return {
        "gap_metres": float(np.linalg.norm(delta)),
        "depth_gap_metres": float(abs(delta[2])),
        "lateral_gap_metres": float(np.linalg.norm(delta[:2])),
        "tip_delta_xyz_metres": delta.tolist(),
        "hands": hands,
    }


def proposal_gate(before, after, optimizer_status):
    # Small explicit pixel tolerance is experimental, never a sign/contact acceptance rule.
    projection = all(
        np.isfinite(after["hands"][s]["absolute_rmse_pixels"])
        and after["hands"][s]["absolute_rmse_pixels"]
        <= before["hands"][s]["absolute_rmse_pixels"] + 2.0
        and after["hands"][s]["wrist_error_pixels"]
        <= before["hands"][s]["wrist_error_pixels"] + 3.0
        for s in SIDES
    )
    gap = (
        np.isfinite(after["gap_metres"])
        and after["gap_metres"] <= 0.015
        and after["gap_metres"] <= before["gap_metres"] * 0.6
    )
    return {
        "candidate_gate_passed": bool(optimizer_status > 0 and projection and gap),
        "projection_guard_passed": bool(projection),
        "point_proximity_guard_passed": bool(gap),
        "contact_approved": False,
        "surface_collision_evaluated": False,
        "training_ready": False,
    }


def fit_contact(model, original, fusion, targets, camera):
    hand.require(
        set(targets) == set(SIDES)
        and all(
            np.asarray(targets[s]).shape == (21, 2) and np.isfinite(targets[s]).all()
            for s in SIDES
        ),
        "Invalid contact projection targets",
    )
    xyz = {s: model.hand(fusion, s) for s in SIDES}
    choices = (8, 12)
    distances = np.linalg.norm(
        xyz["left"][list(choices)][:, None] - xyz["right"][list(choices)][None, :],
        axis=-1,
    )
    indices = np.unravel_index(distances.argmin(), distances.shape)
    pair = (choices[indices[0]], choices[indices[1]])
    initial = initial_elbow_vector(original, fusion)
    reference_wrist = {s: xyz[s][0] for s in SIDES}

    def residual(vector):
        values = contact_parameters(model, original, fusion, vector)
        pts = {s: model.hand(values, s) for s in SIDES}
        parts = []
        for side in SIDES:
            xy = hand.project(pts[side], camera)
            scale = max(hand.target_scale(targets[side]), 15.0)
            parts.extend(
                [
                    (xy - targets[side]).ravel() / scale,
                    2 * (xy[0] - targets[side][0]) / scale,
                    0.2 * (pts[side][0] - reference_wrist[side]) / 0.03,
                ]
            )
        parts.append(3 * (pts["left"][pair[0]] - pts["right"][pair[1]]) / 0.03)
        parts.append(0.15 * (vector - initial))
        return np.concatenate(parts)

    solution = least_squares(
        residual,
        initial,
        max_nfev=150,
        loss="soft_l1",
        f_scale=0.1,
        xtol=1e-7,
        ftol=1e-7,
        gtol=1e-7,
    )
    proposal = {
        k: v.astype(fusion[k].dtype)
        for k, v in contact_parameters(model, original, fusion, solution.x).items()
    }
    before = metrics(model, fusion, targets, camera, pair)
    after = metrics(model, proposal, targets, camera, pair)
    gate = proposal_gate(before, after, solution.status)
    elbow_changes = {
        s: float(
            np.rad2deg(
                (
                    Rotation.from_rotvec(proposal["body_pose"][hand.ELBOWS[s] - 1])
                    * Rotation.from_rotvec(
                        original["body_pose"][hand.ELBOWS[s] - 1]
                    ).inv()
                ).magnitude()
            )
        )
        for s in SIDES
    }
    old_world = align.global_rotations(model, fusion)
    proposed_world = align.global_rotations(model, proposal)
    wrist_world_errors = {
        s: float(
            Rotation.from_matrix(
                proposed_world[hand.WRISTS[s]] @ old_world[hand.WRISTS[s]].T
            ).magnitude()
        )
        for s in SIDES
    }
    hand.require(
        all(value < 1e-6 for value in wrist_world_errors.values()),
        "Contact changed absolute wrist orientation",
    )
    local_wrist_changes = {
        s: float(
            np.rad2deg(
                (
                    Rotation.from_rotvec(proposal["body_pose"][hand.WRISTS[s] - 1])
                    * Rotation.from_rotvec(
                        original["body_pose"][hand.WRISTS[s] - 1]
                    ).inv()
                ).magnitude()
            )
        )
        for s in SIDES
    }
    gate["candidate_gate_passed"] = (
        gate["candidate_gate_passed"]
        and all(v <= 15.00001 for v in elbow_changes.values())
        and all(v <= 80 for v in local_wrist_changes.values())
    )
    selected = (
        proposal
        if gate["candidate_gate_passed"]
        else {k: v.copy() for k, v in fusion.items()}
    )
    return (
        selected,
        proposal,
        {
            **gate,
            "before": before,
            "after_proposal": after,
            "saved": metrics(model, selected, targets, camera, pair),
            "tip_pair_openpose_indices": list(pair),
            "pair_selection": "nearest index/middle tip pair in unchanged fusion, frozen during optimization",
            "optimizer_status": int(solution.status),
            "nfev": int(solution.nfev),
            "elbow_changes_from_original_degrees": elbow_changes,
            "local_wrist_changes_from_original_degrees": local_wrist_changes,
            "absolute_wrist_orientation_preservation_error_radians": wrist_world_errors,
            "finger_rotations_changed": False,
            "wrist_world_rotations_changed": False,
            "contact_hypothesis": "possible index/middle fingertip contact; not labelled truth",
        },
    )


def verified_evidence(folder, expected_sha):
    folder = folder.resolve()
    report = folder / "report.json"
    hand.require(hand.sha256(report) == expected_sha, "Previous report SHA-256 differs")
    checks = {}
    for line in (folder.parent / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        hand.require(name not in checks, "Duplicate evidence manifest path")
        path = hand.inside(folder.parent, name)
        hand.require(hand.sha256(path) == digest, "Evidence file changed: " + name)
        checks[name] = digest
    return json.loads(report.read_text()), checks


def run(args):
    from PIL import Image

    fusion, fits, root, batch, wilor, out = [
        getattr(args, k).resolve()
        for k in (
            "fusion_results",
            "fits",
            "smplerx_root",
            "batch",
            "wilor_results",
            "output",
        )
    ]
    prior, checks = verified_evidence(fusion, args.fusion_report_sha256)
    wprior, wchecks = verified_evidence(wilor, args.wilor_report_sha256)
    hand.require(
        prior["status"] == "alignment_candidates_pending_visual_review"
        and prior["short_window"]
        and prior["source_files_unchanged"]
        and prior["training_ready"] is False,
        "Incomplete fusion inputs",
    )
    hand.require(
        wprior["status"] == "inferred_pending_visual_review"
        and wprior["source_files_unchanged"]
        and wprior["training_ready"] is False,
        "Incomplete WiLoR inputs",
    )
    hand.require(
        prior["wilor_report_sha256"] == args.wilor_report_sha256,
        "Wrong upstream WiLoR evidence",
    )
    findex = {(c["segment_id"], c["frame_1based"]): c for c in prior["cases"]}
    windex = align.prior_case_index(wprior, short_window=True)
    hand.require(
        len(findex) == len(prior["cases"]) == 14, "Incomplete/duplicate fusion scope"
    )
    hand.require(set(findex) == set(windex), "Fusion and WiLoR frame sets differ")
    hand.require(
        prior["fit_run_sha256"] == hand.sha256(fits / "run.json"),
        "Wrong original fitting report",
    )
    cases = [(SEGMENT, n, SIDES) for n in FRAMES]
    selected = hand.task_cases(batch, cases=cases)
    out = hand.new_output(out, [fusion, fits, root, batch, wilor])
    report = {
        "schema": "signbridge-contact-hypothesis-pilot-v1",
        "status": "running",
        "training_ready": False,
        "deployment_ready": False,
        "contact_approved": False,
        "surface_collision_evaluated": False,
        "original_fits_overwritten": False,
        "full_sequence_refined": False,
        "temporal_smoothing": False,
        "scope": "greeting 88-91 only; no network inference, no finger or camera fitting",
        "fusion_report_sha256": args.fusion_report_sha256,
        "wilor_report_sha256": args.wilor_report_sha256,
        "source_sha256": {},
        "cases": [],
        "numerical_thresholds": {
            "tip_gap_metres": 0.015,
            "gap_fraction_max": 0.6,
            "absolute_projection_extra_pixels": 2.0,
            "wrist_projection_extra_pixels": 3.0,
            "elbow_cap_degrees": 15,
        },
    }
    path = out / "report.json"

    def save():
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )

    save()
    stage = "runtime"
    try:
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
        os.environ.setdefault("MPLBACKEND", "Agg")
        import torch, smplx

        hand.require(torch.cuda.is_available(), "CUDA verification required")
        modelpath = hand.verify_model_assets(root)
        model = hand.SparseSMPLX(modelpath)
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
                native.pose_mean.detach().cpu().numpy().reshape(55, 3), model.mean
            ),
            "Native hand mean differs",
        )

        def mesh(values):
            params = {
                k: torch.tensor(v.reshape(1, -1), dtype=torch.float32, device="cuda")
                for k, v in values.items()
            }
            with torch.inference_mode():
                obj = native(**params)
            j, v = obj.joints[0, :55].cpu().numpy(), obj.vertices[0].cpu().numpy()
            sj, st = model.forward(values)
            error = max(
                float(np.max(np.abs(j - sj))),
                float(np.max(np.abs(v[model.tip_ids] - st))),
            )
            hand.require(error < 5e-5, "Native contact candidate parity failed")
            return v, error

        paths = [
            fusion / "report.json",
            fusion.parent / "SHA256SUMS",
            wilor / "report.json",
            wilor.parent / "SHA256SUMS",
            modelpath,
            Path(__file__).resolve(),
            Path(align.__file__).resolve(),
            Path(hand.__file__).resolve(),
            Path(align.wilor.__file__).resolve(),
            batch / "contract.json",
            batch / "tasks.jsonl",
            batch / "SHA256SUMS",
        ]
        # Recheck all original provenance paths recorded by the previous fusion.
        for name, digest in prior["source_sha256"].items():
            hand.require(
                hand.sha256(Path(name)) == digest,
                "Previous fusion source modified: " + name,
            )
            report["source_sha256"][name] = digest
        report["source_sha256"].update({str(p): hand.sha256(p) for p in paths})
        report["runtime"] = {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
        }
        report["renderer_preflight"] = hand.renderer_preflight()
        for task, n, sides, image_path, obs in selected:
            stage = "contact_fit:%d" % n
            row = findex[(SEGMENT, n)]
            wrow = windex[(SEGMENT, n)]
            framefolder = hand.inside(
                fusion, row["output_relative"] + "/candidate.npz"
            ).parent
            source = hand.inside(fits, SEGMENT + "/smplx/%05d_0.npz" % n)
            meta = hand.inside(fits, SEGMENT + "/meta/%05d_0.json" % n)
            original = hand.read_native(source)
            saved_baseline = hand.read_native(framefolder / "baseline.npz")
            hand.require(
                all(
                    np.array_equal(original[key], saved_baseline[key])
                    for key in hand.SHAPES
                ),
                "Fusion baseline differs from original fitting frame",
            )
            previous = hand.read_native(framefolder / "candidate.npz")
            hand.preserved(original, previous, SIDES, allow_elbow=True)
            hand.require(
                all(h["candidate_gate_passed"] for h in row["hands"]),
                "Contact source contains rejected hand",
            )
            camera = hand.native_camera(json.loads(meta.read_text()), image_path)
            targets = {}
            inputpaths = [source, meta, image_path, framefolder / "candidate.npz"]
            for side in SIDES:
                item = next(h for h in wrow["hands"] if h["side"] == side)
                p = hand.inside(
                    wilor, wrow["output_relative"] + "/" + item["parameters_file"]
                )
                with np.load(p, allow_pickle=False) as a:
                    targets[side] = a["projected_joints"].copy()
                inputpaths.append(p)
            report["source_sha256"].update({str(p): hand.sha256(p) for p in inputpaths})
            saved, proposal, data = fit_contact(
                model, original, previous, targets, camera
            )
            folder = out / ("%06d" % n)
            folder.mkdir()
            for name, values in (
                ("previous-fusion", previous),
                ("raw-contact-proposal", proposal),
                ("saved-candidate", saved),
            ):
                np.savez_compressed(folder / (name + ".npz"), **values)
            image = Image.open(image_path).convert("RGB")
            panels = [image]
            parity = {}
            for name, values in (
                ("previous-fusion", previous),
                ("raw-contact-proposal", proposal),
                ("saved-candidate", saved),
            ):
                vertices, error = mesh(values)
                parity[name] = error
                im = Image.fromarray(
                    hand.render_overlay(
                        np.asarray(image),
                        vertices,
                        native.faces,
                        camera,
                        diagnostic=True,
                    )
                )
                check = align.wilor.check_render_bounds(
                    np.asarray(image), np.asarray(im), hand.project(vertices, camera)
                )
                hand.require(
                    check["render_projection_bbox_passed"],
                    "Contact render projection failed",
                )
                im.save(folder / (name + "-overlay.jpg"))
                panels.append(im)
            image.save(folder / "original.jpg")
            crop = (420, 230, 900, 460)
            hand.save_comparison(
                folder / "contact-compare.jpg",
                [im.crop(crop).resize((640, 310)) for im in panels],
                [
                    "Original",
                    "Previous fusion - unapproved",
                    "Raw contact proposal - NOT accepted",
                    "Saved - NOT approved",
                ],
            )
            data.update(
                frame_1based=n,
                output_relative=str(folder.relative_to(out)),
                native_parity_max_metres=parity,
            )
            report["cases"].append(data)
            save()
            print(json.dumps({"frame": n, **data}, ensure_ascii=False), flush=True)
        stage = "source_recheck"
        for name, digest in report["source_sha256"].items():
            hand.require(
                hand.sha256(Path(name)) == digest, "Source changed during contact pilot"
            )
        report.update(
            status=(
                "contact_proposals_pending_visual_review"
                if all(c["candidate_gate_passed"] for c in report["cases"])
                else "contact_proposals_rejected"
            ),
            source_files_unchanged=True,
            limitations=[
                "Contact is a visual hypothesis, not labelled three-dimensional truth",
                "Nearest fingertip distance is not mesh collision or interpenetration validation",
                "No camera, torso, shape, finger pose or wrist-world orientation changes",
                "No temporal smoothing or full-sequence/data promotion",
                "Single initialized local solve; rejection is not proof of global infeasibility",
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
    for key in (
        "fusion-results",
        "wilor-results",
        "fits",
        "smplerx-root",
        "batch",
        "output",
    ):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--fusion-report-sha256", required=True)
    p.add_argument("--wilor-report-sha256", required=True)
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
