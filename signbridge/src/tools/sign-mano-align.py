"""Audited keyframe/short-window MANO-to-SMPL-X candidates, never accepted training data."""

import argparse
import importlib.util
import json
import os
import re
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
spec = importlib.util.spec_from_file_location(
    "wilor_alignment_audit", Path(__file__).with_name("sign-wilor-pilot.py")
)
wilor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wilor)


def prior_case_index(prior, short_window=False):
    expected = wilor.short_window_cases() if short_window else hand.CASES
    index = {}
    for case in prior["cases"]:
        segment, frame = case["segment_id"], case["frame_1based"]
        key = (segment, frame)
        hand.require(key not in index, "Duplicate prior frame")
        match = [sides for s, n, sides in expected if (s, n) == key]
        hand.require(len(match) == 1, "Unexpected prior frame scope")
        path = segment + ("/%06d" % frame if short_window else "")
        hand.require(
            case.get("output_relative", segment) == path, "Wrong prior output path"
        )
        hand.require(
            case["required_sides"] == list(match[0]), "Wrong prior required sides"
        )
        for side in match[0]:
            hands = [h for h in case["hands"] if h["side"] == side]
            hand.require(len(hands) == 1, "Missing or ambiguous prior hand")
        for item in case["hands"]:
            name = item["parameters_file"]
            hand.require(
                item["side"] in ("left", "right")
                and Path(name).name == name
                and name.startswith(item["side"] + "-")
                and name.endswith(".npz"),
                "Unsafe prior hand parameter path",
            )
        index[key] = case
    hand.require(
        set(index) == {(s, n) for s, n, _ in expected}, "Missing prior frame scope"
    )
    return index


def pack_series(records):
    """Package observed frame pairs; rejected hands must retain exact baseline parameters."""
    hand.require(bool(records), "Empty sequence")
    ids = np.asarray([row["frame_1based"] for row in records], dtype=np.int64)
    hand.require(
        (np.diff(ids) == 1).all(), "Sequence frame IDs must be contiguous and ordered"
    )
    fps, sides = records[0]["fps"], records[0]["sides"]
    hand.require(np.isfinite(fps) and fps > 0, "Invalid sequence FPS")
    for row in records:
        hand.require(
            row["fps"] == fps and row["sides"] == sides, "Sequence contract differs"
        )
        hand.require(
            set(row["decisions"]) == set(sides)
            and all(
                isinstance(value, (bool, np.bool_))
                for value in row["decisions"].values()
            ),
            "Invalid candidate selection mask for observed sides",
        )
        for kind in ("baseline", "candidate"):
            values = row[kind]
            hand.require(
                set(values) == set(hand.SHAPES), "Unexpected sequence parameter fields"
            )
            for key, shape in hand.SHAPES.items():
                value = values[key]
                hand.require(
                    value.shape == shape
                    and value.dtype.kind == "f"
                    and np.isfinite(value).all(),
                    "Invalid sequence values: " + key,
                )
        hand.preserved(row["baseline"], row["candidate"], sides, allow_elbow=True)
        for side in sides:
            if not row["decisions"].get(side, False):
                for key in (side + "_hand_pose", "body_pose"):
                    indices = [hand.WRISTS[side] - 1, hand.ELBOWS[side] - 1]
                    before = (
                        row["baseline"][key]
                        if key != "body_pose"
                        else row["baseline"][key][indices]
                    )
                    after = (
                        row["candidate"][key]
                        if key != "body_pose"
                        else row["candidate"][key][indices]
                    )
                    hand.require(
                        np.array_equal(before, after),
                        "Rejected hand parameters changed",
                    )
    packed = {
        kind + "_" + key: np.stack([row[kind][key] for row in records])
        for kind in ("baseline", "candidate")
        for key in hand.SHAPES
    }
    packed.update(
        frame_ids=ids,
        timestamps_seconds=(ids - 1) / fps,
        fps=np.asarray(fps),
        observed_hand_mask=np.asarray(
            [[s in sides for s in ("left", "right")] for _ in records]
        ),
        candidate_applied_mask=np.asarray(
            [
                [row["decisions"].get(s, False) for s in ("left", "right")]
                for row in records
            ],
            dtype=bool,
        ),
        training_ready=np.asarray(False),
    )
    return packed


def fingertip_contact_diagnostic(model, params, camera):
    """Proximity of index/middle tips in model coordinates, NOT surface/semantic contact."""
    left = model.hand(params, "left")[[8, 12]]
    right = model.hand(params, "right")[[8, 12]]
    pixels_left = hand.project(left, camera)
    pixels_right = hand.project(right, camera)
    return {
        "minimum_index_middle_tip_distance_metres": float(
            np.linalg.norm(left[:, None] - right[None, :], axis=-1).min()
        ),
        "minimum_index_middle_tip_distance_pixels": float(
            np.linalg.norm(pixels_left[:, None] - pixels_right[None, :], axis=-1).min()
        ),
        "measurement_scope": "model-estimated index/middle tip proximity, not observed contact",
        "contact_approved": False,
        "surface_collision_evaluated": False,
        "training_ready": False,
    }


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


def validate_fit_source(fits, batch, fit_run_sha256, short_window=False,
                        stable_report_sha256=None, stable_source_manifest=None):
    """Choose a provenance contract explicitly; stable crops keep the original run link."""
    fits, batch = Path(fits).resolve(), Path(batch).resolve()
    if stable_report_sha256 is None:
        hand.require(stable_source_manifest is None, "Stable manifest requires a stable report")
        path = hand.inside(fits, "run.json")
        hand.require(hand.sha256(path) == fit_run_sha256, "Wrong original SMPL-X run")
        run = json.loads(path.read_text())
        hand.require(run.get("schema") == "signbridge-smplerx-run-v1" and
                     run.get("status") == "inferred_pending_import_audit" and
                     run.get("tasks_sha256") == hand.sha256(batch / "tasks.jsonl"),
                     "Original fitting run does not match batch")
        return {"kind": "original_fit", "source_sha256": {str(path): hand.sha256(path)}}
    hand.require(short_window, "Stable-crop fusion requires --short-window")
    hand.require(stable_source_manifest is not None, "Stable-crop fusion requires an evidence manifest")
    report_path = hand.inside(fits, "report.json")
    hand.require(hand.sha256(report_path) == stable_report_sha256, "Stable-crop report digest differs")
    manifest_path = Path(stable_source_manifest).resolve()
    checks = {}
    for line in manifest_path.read_text().splitlines():
        digest, relative = line.split("  ", 1)
        hand.require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None and relative not in checks,
                     "Invalid stable-crop evidence manifest")
        path = hand.inside(fits.parent, relative)
        hand.require(hand.sha256(path) == digest, "Stable-crop evidence digest differs: " + relative)
        checks[relative] = digest

    def listed(relative):
        path = hand.inside(fits.parent, relative)
        hand.require(checks.get(relative) == hand.sha256(path), "Unlisted stable-crop input: " + relative)
        return path

    listed("results/report.json")
    plan_path = listed("plan.json")
    prior = json.loads(report_path.read_text())
    plan = json.loads(plan_path.read_text())
    hand.require(prior.get("schema") == "signbridge-stable-crop-pilot-v1" and
                 prior.get("status") == "inferred_pending_stable_crop_review" and
                 prior.get("training_ready") is False and prior.get("source_files_unchanged") is True,
                 "Incomplete stable-crop source")

    def recorded(suffix, expected):
        matches = [value for name, value in prior.get("source_sha256", {}).items()
                   if name.endswith("/" + suffix)]
        hand.require(len(matches) == 1 and matches[0] == expected,
                     "Stable-crop recorded batch/source digest differs: " + suffix)

    for name in ("contract.json", "tasks.jsonl", "SHA256SUMS"):
        recorded("batch/" + name, hand.sha256(batch / name))
    recorded("fits/run.json", fit_run_sha256)
    recorded("plan.json", hand.sha256(plan_path))
    hand.require(plan.get("schema") == "signbridge-stable-crop-plan-v1" and
                 plan.get("training_ready") is False and plan.get("fit_run_sha256") == fit_run_sha256,
                 "Stable-crop plan/run linkage differs")
    expected = {(s, n): sides for s, n, sides in wilor.short_window_cases()}
    cases = {(r["segment_id"], r["frame_1based"]): r for r in prior.get("cases", [])}
    scope = {s: [n for segment, n in expected if segment == s] for s, _ in expected}
    hand.require(set(cases) == set(expected) and len(cases) == len(prior.get("cases", [])) and
                 prior.get("scope") == scope and set(plan.get("windows", {})) == set(scope),
                 "Stable-crop frame scope differs")
    sources = {str(report_path): stable_report_sha256, str(manifest_path): hand.sha256(manifest_path),
               str(plan_path): hand.sha256(plan_path)}
    for (segment, number), row in cases.items():
        window = plan["windows"][segment]
        hand.require(window.get("frames") == scope[segment], "Stable-crop plan frame scope differs")
        parity = row.get("native_parity_max_metres")
        hand.require(isinstance(parity, (int, float)) and np.isfinite(parity) and 0 <= parity <= 5e-5,
                     "Stable-crop saved native parity failed")
        params_rel = segment + "/smplx/%05d_0.npz" % number
        meta_rel = segment + "/meta/%05d_0.json" % number
        hand.require(row.get("parameters_file") == params_rel and row.get("camera_file") == meta_rel and
                     row.get("training_ready") is False, "Stable-crop frame/file identity differs")
        params_path = listed("results/" + params_rel)
        meta_path = listed("results/" + meta_rel)
        hand.read_native(params_path)
        meta = json.loads(meta_path.read_text())
        image = batch / "samples" / segment / "images" / ("%06d.jpg" % number)
        camera = hand.native_camera(meta, image)
        box = np.asarray(window["fixed_bbox"], dtype=np.float64)
        hand.require(box.shape == (4,) and np.isfinite(box).all() and (box[2:] > 0).all() and
                     np.allclose(box[2] / box[3], .75, atol=1e-6) and
                     np.array_equal(np.asarray(meta["bbox"], dtype=np.float32), box.astype(np.float32)) and
                     np.allclose(camera["focal"], box[2:] * [5000. / 192., 5000. / 256.], rtol=1e-6) and
                     np.allclose(camera["princpt"], box[:2] + box[2:] / 2., rtol=0, atol=1e-5),
                     "Stable crop/camera differs from fixed plan")
        sources.update({str(params_path): hand.sha256(params_path), str(meta_path): hand.sha256(meta_path)})
    return {"kind": "stable_crop", "stable_report_sha256": stable_report_sha256,
            "cases": cases, "source_sha256": sources}


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
    short_window = getattr(args, "short_window", False)
    prior_index = prior_case_index(prior, short_window)
    fit_source = validate_fit_source(
        fits, batch, args.fit_run_sha256, short_window=short_window,
        stable_report_sha256=getattr(args, "stable_report_sha256", None),
        stable_source_manifest=getattr(args, "stable_source_manifest", None),
    )
    actual_commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    hand.require(actual_commit == hand.COMMIT, "Wrong fixed SMPLer-X source")
    # Saved WiLoR output hashes from the downloaded inference evidence must still match.
    checks = {}
    for line in (source.parent / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        hand.require(name not in checks, "Duplicate prior evidence file")
        checks[name] = digest
    for case in prior["cases"]:
        for item in case["hands"]:
            relative = (
                "results/"
                + case.get("output_relative", case["segment_id"])
                + "/"
                + item["parameters_file"]
            )
            value = hand.inside(source.parent, relative)
            hand.require(
                checks.get(relative) == hand.sha256(value),
                "Previous MANO parameter digest differs",
            )
    selected = hand.task_cases(
        batch, cases=wilor.short_window_cases() if short_window else None
    )
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
        "fit_source_kind": fit_source["kind"],
        "stable_report_sha256": fit_source.get("stable_report_sha256"),
        "source_sha256": {
            str(priorpath): hand.sha256(priorpath),
            **fit_source["source_sha256"],
        },
        "pose_convention": "MANO effective matrices; left SRS; subtract SMPL-X mean once; wrist parent-relative",
        "finger_fitting": False,
        "elbow_limit_degrees": 15,
        "scope": (
            "14 frames: 88-94 and 156-162"
            if short_window
            else "two keyframes: 91 and 159"
        ),
        "short_window": short_window,
        "temporal_smoothing": False,
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
                Path(wilor.__file__).resolve(),
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
        sequence_records = {}
        audit_rows = {}
        for task, number, sides, image_path, obs in selected:
            segment = task["segment_id"]
            stage = "mapping:" + segment
            case0 = prior_index[(segment, number)]
            original = hand.inside(fits, segment + "/smplx/%05d_0.npz" % number)
            meta = hand.inside(fits, segment + "/meta/%05d_0.json" % number)
            params = hand.read_native(original)
            camera = hand.native_camera(json.loads(meta.read_text()), image_path)
            folder = (
                out / segment / ("%06d" % number) if short_window else out / segment
            )
            folder.mkdir(parents=True)
            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
            proposals = {}
            metrics = []
            targets = {}
            case = {
                "segment_id": segment,
                "frame_1based": number,
                "timestamp_seconds": (number - 1) / task["fps"],
                "output_relative": str(folder.relative_to(out)),
                "required_sides": list(sides),
                "training_ready": False,
                "hands": [],
            }
            report["cases"].append(case)
            report["source_sha256"].update(
                {
                    str(p): hand.sha256(p)
                    for p in (
                        original,
                        meta,
                        image_path,
                        batch / task["frame_manifest"],
                    )
                }
            )
            for side in sides:
                hands = [h for h in case0["hands"] if h["side"] == side]
                hand.require(len(hands) == 1, "Ambiguous WiLoR source side")
                path = hand.inside(
                    source,
                    case0.get("output_relative", segment)
                    + "/"
                    + hands[0]["parameters_file"],
                )
                report["source_sha256"][str(path)] = hand.sha256(path)
                with np.load(path, allow_pickle=False) as a:
                    arrays = {k: a[k].copy() for k in a.files}
                    wilor.check_outputs(arrays)
                    hand.require(
                        bool(a["right"]) == (side == "right")
                        and a["projected_joints"].shape == (21, 2)
                        and np.isfinite(a["projected_joints"]).all(),
                        "Wrong hand identity or target projection",
                    )
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
            if set(sides) == {"left", "right"}:
                case["contact_diagnostic"] = {
                    kind: fingertip_contact_diagnostic(sparse, values, camera)
                    for kind, values in (("baseline", params), ("candidate", candidate))
                }
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
            image.save(folder / "original.jpg")
            hand.save_comparison(
                folder / "frame-compare.jpg",
                [image, baseline, saved],
                ["Original", "SMPL-X baseline", "Saved candidate - NOT approved"],
            )
            case["candidate_render_projection"] = wilor.check_render_bounds(
                np.asarray(image), np.asarray(saved), hand.project(vc, camera)
            )
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
            if short_window:
                sequence_records.setdefault(segment, []).append(
                    {
                        "frame_1based": number,
                        "fps": task["fps"],
                        "sides": sides,
                        "baseline": params,
                        "candidate": candidate,
                        "decisions": {
                            m["side"]: m["candidate_gate_passed"] for m in metrics
                        },
                    }
                )
                views = audit_rows.setdefault(
                    segment, {"baseline": [], "candidate": [], "wilor": []}
                )
                for kind, values in (("baseline", params), ("candidate", candidate)):
                    world = global_rotations(sparse, values)
                    views[kind].append(
                        {
                            "frame_1based": number,
                            "hands": [
                                {
                                    "side": side,
                                    "hand_pose": hand.hand_rotations(
                                        values, sparse, side
                                    ),
                                    "global_orient": world[hand.WRISTS[side]][None],
                                    "projected_joints": hand.project(
                                        sparse.hand(values, side), camera
                                    ),
                                }
                                for side in sides
                            ],
                        }
                    )
                target_hands = []
                for side in sides:
                    item = next(h for h in case0["hands"] if h["side"] == side)
                    path = (
                        source
                        / case0.get("output_relative", segment)
                        / item["parameters_file"]
                    )
                    with np.load(path, allow_pickle=False) as a:
                        target_hands.append(
                            {
                                "side": side,
                                "hand_pose": image_side_rotations(a["hand_pose"], side),
                                "global_orient": image_side_rotations(
                                    a["global_orient"], side
                                ),
                                "projected_joints": a["projected_joints"].copy(),
                            }
                        )
                views["wilor"].append({"frame_1based": number, "hands": target_hands})
        if short_window:
            report["temporal_audit"] = {}
            report["sequence_outputs"] = {}
            for segment, records in sequence_records.items():
                series = pack_series(records)
                filename = out / segment / "baseline-candidate-series.npz"
                np.savez_compressed(filename, **series)
                report["sequence_outputs"][segment] = {
                    "path": str(filename.relative_to(out)),
                    "frames": len(records),
                    "source_fps": records[0]["fps"],
                    "training_ready": False,
                    "side_order": ["left", "right"],
                    "candidate_applied_mask": series["candidate_applied_mask"].tolist(),
                }
                comparisons = {
                    kind: wilor.temporal_summary(rows, records[0]["sides"])
                    for kind, rows in audit_rows[segment].items()
                }
                for side in records[0]["sides"]:
                    decisions = [
                        (r["frame_1based"], r["decisions"][side]) for r in records
                    ]
                    comparisons["candidate"][side]["selection_switch_frames"] = [
                        decisions[i][0]
                        for i in range(1, len(decisions))
                        if decisions[i][1] != decisions[i - 1][1]
                    ]
                    source_alerts = comparisons["wilor"][side]["suspicious_transitions"]
                    candidate_alerts = comparisons["candidate"][side][
                        "suspicious_transitions"
                    ]
                    comparisons["candidate"][side]["new_alert_frames_not_in_wilor"] = [
                        n for n in candidate_alerts if n not in source_alerts
                    ]
                report["temporal_audit"][segment] = comparisons
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
                (
                    "Short-window per-frame gates may cause fallback discontinuities; no automatic smoothing"
                    if short_window
                    else "Two-keyframe mapping only, not continuous fusion"
                ),
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
    p.add_argument("--stable-report-sha256", help="Explicit stable-crop report; requires --short-window")
    p.add_argument("--stable-source-manifest", type=Path,
                   help="Trusted SHA256SUMS for stable-crop results.parent")
    p.add_argument(
        "--short-window",
        action="store_true",
        help="Align fixed 14-frame WiLoR window evidence; no smoothing",
    )
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
