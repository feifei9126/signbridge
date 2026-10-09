"""Audited key-frame hand refitting; never produces training-ready sequences.

Python 3.8+; NumPy/SciPy/Pillow. The GPU pilot also requires the existing
SMPLer-X environment (torch, pyrender, trimesh, and its vendored smplx).
No new weights, network inference, dependency changes, or zero-filled tracks.
"""

import argparse
import hashlib
import importlib
import json
import os
import pickletools
import re
import subprocess
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

COMMIT = "064baef0e4ab5277a3297691bc1d46ea5412586f"
BODY_REVISION = "2de1f98db5c59da6326dc8fac4c00c78010fa6e5"
MODEL_FILE = "common/utils/human_model_files/smplx/SMPLX_NEUTRAL.npz"
MODEL_SHA256 = "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992"
CASES = [("pilot-greeting-hello-001", 91, ("left", "right")),
         ("pilot-hospital-cough-003", 159, ("right",))]
SHAPES = {"global_orient": (1, 3), "body_pose": (21, 3),
          "left_hand_pose": (15, 3), "right_hand_pose": (15, 3),
          "jaw_pose": (1, 3), "leye_pose": (1, 3), "reye_pose": (1, 3),
          "betas": (1, 10), "expression": (1, 10), "transl": (1, 3)}
# Native SMPL-X joints: wrist, thumb, index, middle, ring, pinky.
JOINTS = {"left": [[37, 38, 39], [25, 26, 27], [28, 29, 30], [34, 35, 36], [31, 32, 33]],
          "right": [[52, 53, 54], [40, 41, 42], [43, 44, 45], [49, 50, 51], [46, 47, 48]]}
TIPS = {"left": [5361, 4933, 5058, 5169, 5286],
        "right": [8079, 7669, 7794, 7905, 8022]}
WRISTS = {"left": 20, "right": 21}
ELBOWS = {"left": 18, "right": 19}
ELBOW_LIMIT_DEGREES = 15
EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
         (0, 9), (9, 10), (10, 11), (11, 12), (0, 13), (13, 14), (14, 15), (15, 16),
         (0, 17), (17, 18), (18, 19), (19, 20)]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8")


def inside(root, relative):
    root = root.resolve()
    relative = Path(relative)
    path = (root / relative).resolve()
    require(not relative.is_absolute() and root in path.parents and path.is_file(),
            "Missing input or unsafe path: " + str(relative))
    return path


def new_output(path, protected):
    output = path.resolve()
    for root in protected:
        root = root.resolve()
        require(output != root and root not in output.parents and output not in root.parents,
                "Output must be separate from source inputs")
    output.mkdir(parents=True, exist_ok=False)
    return output


def read_native(path):
    with np.load(path, allow_pickle=False) as archive:
        require(set(archive.files) == set(SHAPES), "Unexpected native parameter fields")
        values = {key: archive[key].copy() for key in SHAPES}
    for key, shape in SHAPES.items():
        value = values[key]
        require(value.shape == shape and value.dtype.kind == "f" and np.isfinite(value).all(),
                "Invalid axis-angle/native parameter: " + key)
    return values


def task_cases(batch, cases=None):
    batch = batch.resolve()
    contract = json.loads((batch / "contract.json").read_text())
    require(contract.get("schema") == "signbridge-smplerx-input-v1" and
            contract.get("smplerx_commit") == COMMIT, "Unsupported batch contract")
    require(contract.get("model_training_ready") is False, "Unexpected training-ready batch")
    require(contract.get("fit_semantics") == "SMPLer-X per-frame estimates, use_pca=False, flat_hand_mean=False",
            "Unsupported pose/hand-mean convention")
    rows = [json.loads(line) for line in (batch / "tasks.jsonl").read_text().splitlines() if line.strip()]
    require(len({row["segment_id"] for row in rows}) == len(rows), "Duplicate task IDs")
    tasks = {row["segment_id"]: row for row in rows}
    checksums = {}
    for line in (batch / "SHA256SUMS").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None and relative not in checksums,
                "Invalid input checksum manifest")
        inside(batch, relative)
        checksums[relative] = digest
    for name in ("tasks.jsonl", "contract.json"):
        require(checksums.get(name) == sha256(batch / name), "Input manifest changed: " + name)
    selected = []
    for segment, number, sides in CASES if cases is None else cases:
        require(segment in tasks, "Pilot segment missing")
        task = tasks[segment]
        require(task.get("image_transform") == "none" and task.get("content_reviewed") is True and
                task.get("model_training_ready") is False, "Unsupported/unreviewed input")
        require(task.get("frames", 0) >= number and np.isfinite(task.get("fps", 0)) and
                task["fps"] > 0, "Invalid frame count/rate")
        frame_path = inside(batch, task["frame_manifest"])
        require(checksums.get(task["frame_manifest"]) == sha256(frame_path), "Frame manifest changed")
        frames = [json.loads(line) for line in frame_path.read_text().splitlines() if line.strip()]
        require(len(frames) == task["frames"], "Frame manifest count differs")
        frame = frames[number - 1]
        image = inside(batch, frame["image"])
        require(frame["frame_id"] == number and image.name == "%06d.jpg" % number and
                image.parent == (batch / task["images"]).resolve(), "Frame/image identity differs")
        require(frame["sha256"] == sha256(image) == checksums.get(frame["image"]), "Image changed")
        require(np.isclose(frame["clip_seconds"], (number - 1) / task["fps"], atol=1e-6, rtol=0),
                "Frame timestamp differs")
        observation = inside(batch, "samples/" + segment + "/observations.npz")
        require(checksums.get(str(observation.relative_to(batch))) == sha256(observation),
                "Observation tracks changed")
        selected.append((task, number, sides, image, observation))
    return selected


def load_target(path, count, number, side, width, height, fps):
    require(side in WRISTS and 1 <= number <= count and width > 0 and height > 0 and fps > 0,
            "Invalid hand/frame/image dimensions")
    with np.load(path, allow_pickle=False) as arrays:
        name = side + "_hand_image"
        points = arrays[name]
        mask = arrays[name + "_detected"]
        times = arrays["timestamps_seconds"]
        require(points.shape == (count, 21, 3) and mask.shape == (count,) and mask.dtype.kind == "b",
                "Invalid hand observation shape/mask")
        require(times.shape == (count,) and np.allclose(times, np.arange(count) / fps, atol=1e-6, rtol=0),
                "Observation timestamps differ")
        require(mask[number - 1], "No detected hand; refusing to fill/interpolate: " + side)
        target = np.asarray(points[number - 1], dtype=np.float64).copy()
    require(np.isfinite(target).all() and np.max(np.abs(target[:, :2])) <= 2,
            "Missing/nonfinite/out-of-range hand observations")
    target *= [width, height, width]
    require(target_scale(target[:, :2]) >= 15, "Hand too small for this pilot")
    return target


def native_camera(meta, image_path):
    require(meta.get("bbox_id") == 0 and Path(meta["img_path"]).resolve() == image_path.resolve(),
            "Camera meta belongs to another frame/person/segment")
    camera = {key: np.asarray(meta[key], dtype=np.float64) for key in ("focal", "princpt")}
    require(all(v.shape == (2,) and np.isfinite(v).all() for v in camera.values()) and
            (camera["focal"] > 0).all(), "Invalid native camera intrinsics")
    return camera


def target_scale(points):
    # A stable palm scale, not image units treated as metres.
    return float(np.median(np.linalg.norm(points[[5, 9, 13, 17]] - points[0], axis=-1)))


def project(points, camera):
    require(np.isfinite(points).all() and (points[:, 2] > 1e-5).all(), "Hand behind camera")
    return points[:, :2] / points[:, 2:3] * camera["focal"] + camera["princpt"]


class SparseSMPLX:
    """Exact SMPL-X joints and ten LBS fingertip vertices, not a new hand model."""

    def __init__(self, path):
        with np.load(path, allow_pickle=False) as a:
            template = np.asarray(a["v_template"], dtype=np.float64)
            shape = np.asarray(a["shapedirs"], dtype=np.float64)
            regressor = np.asarray(a["J_regressor"], dtype=np.float64)
            require(template.shape == (10475, 3) and shape.shape == (10475, 3, 400) and
                    regressor.shape == (55, 10475), "Unsupported neutral SMPL-X model")
            self.tip_ids = TIPS["left"] + TIPS["right"]
            shape = np.concatenate((shape[:, :, :10], shape[:, :, 300:310]), axis=2)
            self.rest_joints = regressor @ template
            self.joint_shapes = np.einsum("jv,vcd->jcd", regressor, shape)
            self.tip_template = template[self.tip_ids]
            self.tip_shapes = shape[self.tip_ids]
            self.tip_poses = np.asarray(a["posedirs"][self.tip_ids], dtype=np.float64)
            self.tip_weights = np.asarray(a["weights"][self.tip_ids], dtype=np.float64)
            self.parents = np.asarray(a["kintree_table"][0], dtype=np.int64).copy()
            self.parents[0] = -1
            self.mean = np.zeros((55, 3))
            self.mean[25:40] = a["hands_meanl"].reshape(15, 3)
            self.mean[40:55] = a["hands_meanr"].reshape(15, 3)
        require(self.tip_poses.shape == (10, 3, 486) and self.tip_weights.shape == (10, 55) and
                all(0 <= self.parents[i] < i for i in range(1, 55)), "Invalid skinning arrays/tree")
        require(all(np.isfinite(x).all() for x in (self.rest_joints, self.joint_shapes,
                self.tip_template, self.tip_shapes, self.tip_poses, self.tip_weights, self.mean)),
                "Nonfinite SMPL-X model")

    def prepared(self, params):
        beta = np.concatenate((params["betas"].ravel(), params["expression"].ravel()))
        joints = self.rest_joints + np.einsum("jcd,d->jc", self.joint_shapes, beta)
        tips = self.tip_template + np.einsum("vcd,d->vc", self.tip_shapes, beta)
        return joints, tips

    def forward(self, params, prepared=None):
        pose = np.concatenate([params[key].reshape(-1, 3) for key in
                               ("global_orient", "body_pose", "jaw_pose", "leye_pose", "reye_pose",
                                "left_hand_pose", "right_hand_pose")]) + self.mean
        rotations = Rotation.from_rotvec(pose).as_matrix()
        joints, tip_shape = prepared if prepared is not None else self.prepared(params)
        translations = joints.copy()
        translations[1:] -= joints[self.parents[1:]]
        local = np.repeat(np.eye(4)[None], 55, axis=0)
        local[:, :3, :3] = rotations
        local[:, :3, 3] = translations
        transforms = local.copy()
        for index in range(1, 55):
            transforms[index] = transforms[self.parents[index]] @ local[index]
        posed_joints = transforms[:, :3, 3].copy()
        transforms[:, :3, 3] -= np.einsum("jcd,jd->jc", transforms[:, :3, :3], joints)
        features = (rotations[1:] - np.eye(3)).ravel()
        tips_posed = tip_shape + np.einsum("vcp,p->vc", self.tip_poses, features)
        skinning = np.einsum("vj,jcd->vcd", self.tip_weights, transforms)
        tips = np.einsum("vcd,vd->vc", skinning,
                         np.concatenate((tips_posed, np.ones((10, 1))), axis=1))[:, :3]
        translation = params["transl"].reshape(3)
        return posed_joints + translation, tips + translation

    def hand(self, params, side, prepared=None):
        joints, tips = self.forward(params, prepared)
        points = [joints[WRISTS[side]]]
        for index, group in enumerate(JOINTS[side]):
            points.extend(joints[group])
            points.append(tips[index + (0 if side == "left" else 5)])
        return np.asarray(points)


def hand_rotations(params, model, side):
    start = 25 if side == "left" else 40
    vectors = params[side + "_hand_pose"] + model.mean[start:start + 15]
    return Rotation.from_rotvec(vectors).as_matrix()


def bounded_elbow_rotation(vector, baseline, limit_degrees):
    """Map an unconstrained 3-vector to a geodesic ball around baseline."""
    delta = Rotation.from_rotvec(np.asarray(vector, dtype=np.float64))
    magnitude = delta.magnitude()
    limit = np.deg2rad(limit_degrees)
    if magnitude > limit:
        delta = Rotation.from_rotvec(delta.as_rotvec() * (limit / magnitude))
    return (delta * Rotation.from_rotvec(np.asarray(baseline, dtype=np.float64))).as_rotvec()


def fit_hand(model, source, side, target, camera, max_nfev=80, allow_elbow=False,
             elbow_limit_degrees=ELBOW_LIMIT_DEGREES):
    """Fit one hand, optionally allowing a small same-side elbow rotation."""
    require(0 < elbow_limit_degrees <= ELBOW_LIMIT_DEGREES, "Elbow limit may not exceed 15 degrees")
    key = side + "_hand_pose"
    wrist_index = WRISTS[side] - 1
    elbow_index = ELBOWS[side] - 1
    hand0 = source[key].ravel().astype(np.float64)
    elbow0 = source["body_pose"][elbow_index].astype(np.float64)
    wrist0 = source["body_pose"][wrist_index].astype(np.float64)
    x0 = np.concatenate((hand0, np.zeros(3), wrist0)) if allow_elbow else np.concatenate((hand0, wrist0))
    bounds = np.concatenate((np.full(45, np.deg2rad(150)),
                             np.full(3, np.deg2rad(180)),
                             np.full(3, np.deg2rad(55)))) if allow_elbow else \
        np.concatenate((np.full(45, np.deg2rad(150)), np.full(3, np.deg2rad(55))))
    prepared = model.prepared(source)
    scale = target_scale(target[:, :2])
    target_local = (target[:, :2] - target[0, :2]) / scale
    baseline_rotations = hand_rotations(source, model, side)
    wrist_rotation = Rotation.from_rotvec(wrist0).as_matrix()
    weights = np.ones((21, 1))
    weights[[4, 8, 12, 16, 20]] = 1.5

    def unpack(vector):
        candidate = {name: value.astype(np.float64).copy() for name, value in source.items()}
        candidate[key] = vector[:45].reshape(15, 3)
        offset = 45
        if allow_elbow:
            candidate["body_pose"][elbow_index] = bounded_elbow_rotation(
                vector[offset:offset + 3], elbow0, elbow_limit_degrees)
            offset += 3
        candidate["body_pose"][wrist_index] = vector[offset:offset + 3]
        return candidate

    def residual(vector):
        params = unpack(vector)
        points = model.hand(params, side, prepared)
        xy = project(points, camera)
        local = (xy - xy[0]) / scale
        prior = hand_rotations(params, model, side) - baseline_rotations
        offset = 45
        elbow_prior = np.zeros((3, 3))
        if allow_elbow:
            elbow_prior = Rotation.from_rotvec(bounded_elbow_rotation(
                vector[offset:offset + 3], elbow0, elbow_limit_degrees)).as_matrix() - \
                Rotation.from_rotvec(elbow0).as_matrix()
            offset += 3
        wrist_prior = Rotation.from_rotvec(vector[offset:offset + 3]).as_matrix() - wrist_rotation
        absolute_weight = 1.25 if allow_elbow else 0.5
        wrist_weight = 2.0 if allow_elbow else 0.0
        return np.concatenate(((weights * (local - target_local)).ravel(),
                               (absolute_weight * weights * (xy - target[:, :2]) / scale).ravel(),
                               (wrist_weight * (xy[0] - target[0, :2]) / scale).ravel(),
                               (0.03 * prior).ravel(), (0.03 * elbow_prior).ravel(),
                               (0.10 * wrist_prior).ravel()))

    result = least_squares(residual, x0, bounds=(x0 - bounds, x0 + bounds),
                           loss="soft_l1", f_scale=0.1, max_nfev=max_nfev,
                           xtol=1e-5, ftol=1e-5, gtol=1e-5)
    candidate = {key: values.astype(source[key].dtype) for key, values in unpack(result.x).items()}
    preserved(source, candidate, (side,), allow_elbow=allow_elbow)
    before = reprojection_metrics(model.hand(source, side, prepared), target, camera)
    after = reprojection_metrics(model.hand(candidate, side, prepared), target, camera)
    change = Rotation.from_matrix(hand_rotations(candidate, model, side) @
                                  baseline_rotations.transpose(0, 2, 1)).magnitude()
    wrist_change = (Rotation.from_rotvec(candidate["body_pose"][wrist_index]) *
                    Rotation.from_rotvec(wrist0).inv()).magnitude()
    elbow_change = (Rotation.from_rotvec(candidate["body_pose"][elbow_index]) *
                    Rotation.from_rotvec(elbow0).inv()).magnitude()
    # A pixel improvement only qualifies a *candidate*, not a correct sign.
    accepted = (result.status > 0 and projection_gate(before, after) and
                float(change.max()) <= np.deg2rad(155) and wrist_change <= np.deg2rad(80) and
                (not allow_elbow or elbow_change <= np.deg2rad(elbow_limit_degrees) + 1e-7))
    projected_before = project(model.hand(source, side, prepared), camera)
    projected_after = project(model.hand(candidate, side, prepared), camera)
    wrist_before = float(np.linalg.norm(projected_before[0] - target[0, :2]))
    wrist_after = float(np.linalg.norm(projected_after[0] - target[0, :2]))
    wrist_gate_passed = wrist_after <= (0.8 * wrist_before if wrist_before > 8 else wrist_before + 1e-5)
    if allow_elbow:
        accepted = accepted and wrist_gate_passed
    return candidate, {"side": side, "optimizer_status": int(result.status), "nfev": int(result.nfev),
                       "optimizer_message": str(result.message), "before": before, "after": after,
                       "max_finger_change_degrees": float(np.rad2deg(change.max())),
                       "wrist_change_degrees": float(np.rad2deg(wrist_change)),
                       "elbow_change_degrees": float(np.rad2deg(elbow_change)),
                       "wrist_error_before_pixels": wrist_before,
                       "wrist_error_after_pixels": wrist_after,
                       "wrist_gate_passed": bool(wrist_gate_passed),
                       "elbow_limit_degrees": elbow_limit_degrees if allow_elbow else 0,
                       "fit_mode": "hand_plus_elbow" if allow_elbow else "hand_only",
                       "candidate_gate_passed": bool(accepted), "training_ready": False,
                       "depth_constraint": "none: MediaPipe relative z is not metric ground truth"}


def reprojection_metrics(points, target, camera):
    projected = project(points, camera)
    error = projected - target[:, :2]
    local = error - error[0]
    return {"absolute_rmse_pixels": float(np.sqrt(np.mean(error ** 2))),
            "local_rmse_pixels": float(np.sqrt(np.mean(local ** 2))),
            "fingertip_local_rmse_pixels": float(np.sqrt(np.mean(local[[4, 8, 12, 16, 20]] ** 2)))}



def projection_gate(before, after):
    return (all(np.isfinite(value) for metrics in (before, after) for value in metrics.values()) and
            after["local_rmse_pixels"] < before["local_rmse_pixels"] * 0.8 and
            after["absolute_rmse_pixels"] <= before["absolute_rmse_pixels"] and
            after["fingertip_local_rmse_pixels"] <= before["fingertip_local_rmse_pixels"])


def merge_hand_candidates(model, source, proposals, metrics, targets, camera):
    """Recheck the actual combined pose; cross-hand pose blend shapes can move tips."""
    candidate = {key: value.copy() for key, value in source.items()}
    for item in metrics:
        side = item["side"]
        item["optimizer_gate_passed"] = item["candidate_gate_passed"]
        if item["optimizer_gate_passed"]:
            proposal = proposals[side]
            allow_elbow = item.get("fit_mode") == "hand_plus_elbow"
            preserved(source, proposal, (side,), allow_elbow=allow_elbow)
            candidate[side + "_hand_pose"] = proposal[side + "_hand_pose"].copy()
            index = WRISTS[side] - 1
            candidate["body_pose"][index] = proposal["body_pose"][index]
            if allow_elbow:
                elbow_index = ELBOWS[side] - 1
                candidate["body_pose"][elbow_index] = proposal["body_pose"][elbow_index]
    preserved(source, candidate, tuple(targets),
              allow_elbow=any(item.get("fit_mode") == "hand_plus_elbow" for item in metrics))
    combined_passed = True
    for item in metrics:
        side = item["side"]
        before = reprojection_metrics(model.hand(source, side), targets[side], camera)
        after = reprojection_metrics(model.hand(candidate, side), targets[side], camera)
        item["merged_proposal_after"] = after
        # Failed hands must not regress when updates to the other hand are merged.
        passed = (projection_gate(before, after) if item["optimizer_gate_passed"] else
                  all(np.isfinite(after[key]) and after[key] <= before[key] + 1e-6 for key in before))
        item["merged_projection_gate_passed"] = bool(passed)
        if item.get("fit_mode") == "hand_plus_elbow" and item["optimizer_gate_passed"]:
            wrist_before = np.linalg.norm(project(model.hand(source, side), camera)[0] - targets[side][0, :2])
            wrist_after = np.linalg.norm(project(model.hand(candidate, side), camera)[0] - targets[side][0, :2])
            passed = passed and wrist_after <= (wrist_before * .8 if wrist_before > 8 else wrist_before + 1e-5)
            item["merged_wrist_gate_passed"] = bool(passed)
        combined_passed = combined_passed and passed
    if not combined_passed:
        candidate = {key: value.copy() for key, value in source.items()}
    for item in metrics:
        item["candidate_gate_passed"] = bool(item["optimizer_gate_passed"] and combined_passed)
        item["applied_to_candidate"] = item["candidate_gate_passed"]
        item["saved_candidate_after"] = reprojection_metrics(
            model.hand(candidate, item["side"]), targets[item["side"]], camera)
    return candidate, bool(combined_passed)


def preserved(source, candidate, sides, allow_elbow=False):
    wrists = [WRISTS[side] - 1 for side in sides]
    elbows = [ELBOWS[side] - 1 for side in sides] if allow_elbow else []
    for key in source:
        if key in {side + "_hand_pose" for side in sides}:
            continue
        if key == "body_pose":
            indices = [i for i in range(21) if i not in wrists and i not in elbows]
            require(np.array_equal(source[key][indices], candidate[key][indices]), "Non-wrist body modified")
        else:
            require(np.array_equal(source[key], candidate[key]), "Protected parameter modified: " + key)


def checkpoint_head_inventory(path):
    # Parse strings only. Never unpickle the 8 GB checkpoint or execute globals.
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.infolist() if item.filename.endswith("/data.pkl")]
        require(len(entries) == 1 and entries[0].file_size <= 8 * 1024 * 1024, "Unexpected checkpoint metadata")
        strings = [arg for op, arg, _ in pickletools.genops(archive.read(entries[0]))
                   if op.name in ("BINUNICODE", "SHORT_BINUNICODE", "UNICODE")]
    heads = {}
    for name in ("hand_regressor", "hand_position_net", "hand_roi_net", "box_net"):
        heads[name] = sorted({key for key in strings if "module." + name + "." in key and
                              key.endswith(".weight")})
        require(heads[name], "Checkpoint is missing learned head: " + name)
    return {"method": "nonexecuting pickle opcode string inventory", "heads": heads,
            "runtime_load_verified": False, "note": "Key presence alone does not verify runtime weight loading."}


def configure_native_import_path(root):
    """Expose the legacy SMPLer-X config module before importing vendored SMPL-X."""
    main_root = root / "main"
    smplx_root = root / "common/utils/smplx"
    require((main_root / "config.py").is_file() and (smplx_root / "smplx").is_dir(),
            "Incomplete SMPLer-X import roots")
    # body_models.py imports `config` as a top-level legacy module. The pilot runs
    # from an isolated job directory, so the repository's main/ path is not cwd.
    for entry in (str(smplx_root), str(main_root)):
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    loaded = sys.modules.get("config")
    loaded_file = getattr(loaded, "__file__", None) if loaded is not None else None
    if loaded is not None and (not loaded_file or Path(loaded_file).resolve() != (main_root / "config.py").resolve()):
        del sys.modules["config"]
    return main_root, smplx_root


def native_runtime(root):
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("MPLBACKEND", "Agg")
    require(os.environ["PYOPENGL_PLATFORM"] == "egl", "Use the already-verified EGL backend")
    import torch
    require(torch.cuda.is_available(), "Native CUDA parity/render requires the existing GPU environment")
    _, smplx_root = configure_native_import_path(root)
    smplx = importlib.import_module("smplx")
    require(smplx_root.resolve() in Path(smplx.__file__).resolve().parents,
            "Wrong smplx package; refusing a change of model convention")
    layer = smplx.create(str(root / "common/utils/human_model_files"), "smplx", gender="NEUTRAL",
                         use_pca=False, flat_hand_mean=False, use_face_contour=False).cuda().eval()
    return torch, layer


def native_forward(runtime, params):
    torch, layer = runtime
    kwargs = {key: torch.as_tensor(values.reshape(1, -1), dtype=torch.float32, device="cuda")
              for key, values in params.items()}
    with torch.no_grad():
        output = layer(**kwargs)
    return output.joints[0, :55].cpu().numpy(), output.vertices[0].cpu().numpy()


def parity(model, runtime, params):
    joints, tips = model.forward(params)
    native_joints, vertices = native_forward(runtime, params)
    error = max(float(np.max(np.abs(joints - native_joints))),
                float(np.max(np.abs(tips - vertices[model.tip_ids]))))
    require(error <= 5e-5, "Native SMPL-X parity failed; do not optimize: %.9f metres" % error)
    return error


def diagnostic_face_colors(vertices, faces):
    """Explicit camera-space Lambert colors; visualization only, no pose correction."""
    triangles = np.asarray(vertices, dtype=np.float64)[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    require(np.isfinite(normals).all() and (lengths > 1e-12).all(), "Invalid diagnostic triangles")
    normals /= lengths[:, None]
    light = np.asarray([-0.35, -0.45, -1.0])
    light /= np.linalg.norm(light)
    brightness = 0.25 + 0.75 * np.maximum(0, normals @ light)
    rgb = np.rint(brightness[:, None] * [180, 220, 250]).astype(np.uint8)
    return np.c_[rgb, np.full(len(rgb), 255, dtype=np.uint8)]


def camera_to_opengl(vertices):
    """Exact Rx(pi) without BLAS; preserves the original native-camera vertices."""
    values = np.asarray(vertices, dtype=np.float64)
    require(values.ndim == 2 and values.shape[1] == 3 and np.isfinite(values).all(),
            "Invalid camera-space mesh vertices")
    return values * np.asarray([1., -1., -1.])


def render_overlay(image, vertices, faces, camera, diagnostic=False):
    import pyrender
    import trimesh
    colors = diagnostic_face_colors(vertices, faces) if diagnostic else None
    mesh = trimesh.Trimesh(vertices=camera_to_opengl(vertices), faces=faces, process=False, face_colors=colors)
    material = None if diagnostic else pyrender.MetallicRoughnessMaterial(
        metallicFactor=0.0, alphaMode="OPAQUE", baseColorFactor=(1.0, 1.0, 0.9, 1.0))
    scene = pyrender.Scene(ambient_light=(0.3, 0.3, 0.3))
    scene.add(pyrender.Mesh.from_trimesh(mesh, material=material, smooth=False))
    scene.add(pyrender.IntrinsicsCamera(fx=camera["focal"][0], fy=camera["focal"][1],
                                      cx=camera["princpt"][0], cy=camera["princpt"][1]))
    for position in ((0, -1, 1), (0, 1, 1), (1, 1, 2)):
        pose = np.eye(4)
        pose[:3, 3] = position
        scene.add(pyrender.DirectionalLight(color=[1, 1, 1], intensity=0.8), pose=pose)
    renderer = pyrender.OffscreenRenderer(viewport_width=image.shape[1], viewport_height=image.shape[0])
    try:
        flags = pyrender.RenderFlags.RGBA | (pyrender.RenderFlags.FLAT if diagnostic else 0)
        rgb, depth = renderer.render(scene, flags=flags)
        return np.where((depth > 0)[:, :, None], rgb[:, :, :3], image).astype(np.uint8)
    finally:
        renderer.delete()


def renderer_preflight():
    """Render a tiny real mesh before any GPU fitting, so missing GL libraries fail early."""
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("MPLBACKEND", "Agg")
    require(os.environ["PYOPENGL_PLATFORM"] == "egl", "Use the already-verified EGL backend")
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    # Native camera uses +z; render_overlay rotates to OpenGL -z. Wind toward camera.
    vertices = np.asarray([[-0.35, -0.35, 2.0], [0.35, -0.35, 2.0],
                           [0.35, 0.35, 2.0], [-0.35, 0.35, 2.0]], dtype=np.float64)
    faces = np.asarray([[0, 2, 1], [0, 3, 2]], dtype=np.int64)
    camera = {"focal": np.asarray([55.0, 55.0]), "princpt": np.asarray([32.0, 32.0])}
    rendered = render_overlay(image, vertices, faces, camera)
    require(rendered.shape == image.shape and rendered.dtype == np.uint8,
            "Renderer returned invalid preflight image")
    changed = np.any(rendered != image, axis=2)
    pixels = int(np.count_nonzero(changed))
    require(pixels > 0, "EGL renderer produced no visible pixels")
    return {"ready": True, "backend": os.environ.get("PYOPENGL_PLATFORM"),
            "rendered_pixels": pixels, "image_shape": list(rendered.shape)}


def draw_targets(image, targets):
    from PIL import ImageDraw
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    for side, points in targets.items():
        color = (0, 170, 255) if side == "left" else (255, 120, 0)
        for start, end in EDGES:
            draw.line([tuple(points[start, :2]), tuple(points[end, :2])], fill=color, width=3)
        for index, point in enumerate(points):
            x, y = point[:2]
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
            draw.text((x + 4, y), str(index), fill=color)
    return marked


def save_comparison(path, panels, labels):
    from PIL import Image, ImageDraw
    width, height = panels[0].size
    result = Image.new("RGB", (width * len(panels), height + 30), (245, 245, 248))
    draw = ImageDraw.Draw(result)
    for index, (image, label) in enumerate(zip(panels, labels)):
        result.paste(image, (index * width, 30))
        draw.text((index * width + 12, 8), label, fill=(10, 20, 30))
    result.save(path)


def verify_model_assets(root):
    model = inside(root, MODEL_FILE)
    provenance = root / "common/utils/human_model_files/signbridge-body-assets.json"
    info = json.loads(provenance.read_text())
    require(info.get("schema") == "signbridge-body-assets-v1" and
            info.get("space") == "caizhongang/SMPLer-X" and info.get("revision") == BODY_REVISION,
            "Unsupported neutral model provenance")
    records = [record for record in info["assets"] if record.get("path") == MODEL_FILE]
    require(len(records) == 1, "Missing/duplicate neutral model provenance")
    record = records[0]
    require(record.get("sha256") == MODEL_SHA256 == sha256(model) and
            record.get("bytes") == model.stat().st_size, "Neutral model provenance mismatch")
    return model


def run(args):
    from PIL import Image
    batch = args.batch.resolve()
    selected = task_cases(batch)
    protected = [batch]
    if args.command == "pilot":
        protected += [args.fits, args.smplerx_root]
    output = new_output(args.output, protected)
    report = {"schema": "signbridge-hand-keyframe-pilot-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "running", "training_ready": False, "scope": "two key frames, three observed hands only",
              "full_sequence_refined": False, "new_network_inference": False, "source_sha256": {}, "cases": []}
    allow_elbow = getattr(args, "allow_elbow", False)
    report["fit_mode"] = "hand_plus_elbow" if allow_elbow else "hand_only"
    report["elbow_limit_degrees"] = ELBOW_LIMIT_DEGREES if allow_elbow else 0
    report_path = output / "report.json"
    write_json(report_path, report)
    stage = "input_validation"
    try:
        inputs = [batch / "contract.json", batch / "tasks.jsonl", batch / "SHA256SUMS",
                  Path(__file__).resolve()]
        inputs += [inside(batch, task["frame_manifest"]) for task, _, _, _, _ in selected]
        report["source_sha256"].update({str(path): sha256(path) for path in inputs})
        model = runtime = None
        if args.command == "pilot":
            root = args.smplerx_root.resolve()
            fits = args.fits.resolve()
            run_path = fits / "run.json"
            require(sha256(run_path) == args.fit_run_sha256, "Wrong fitting run or source digest changed")
            source_run = json.loads(run_path.read_text())
            require(source_run.get("schema") == "signbridge-smplerx-run-v1" and
                    source_run.get("status") == "inferred_pending_import_audit" and
                    set(source_run.get("completed", [])) == {c[0] for c in CASES}, "Wrong/incomplete fitting run")
            actual_commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                                     text=True).strip()
            require(actual_commit == source_run.get("preflight", {}).get("actual_commit") == COMMIT and
                    source_run.get("tasks_sha256") == sha256(batch / "tasks.jsonl"),
                    "Source run/commit/batch provenance differs")
            report["smplerx_commit"] = actual_commit
            report["source_sha256"][str(run_path)] = sha256(run_path)
            model_path = verify_model_assets(root)
            report["source_sha256"][str(model_path)] = sha256(model_path)
            provenance = root / "common/utils/human_model_files/signbridge-body-assets.json"
            report["source_sha256"][str(provenance)] = sha256(provenance)
            report["checkpoint_inventory"] = checkpoint_head_inventory(root / "pretrained_models/smpler_x_h32.pth.tar")
            stage = "render_preflight"
            report["renderer_preflight"] = renderer_preflight()
            print("Actual EGL render preflight passed; starting native checks and keyframe fitting.", flush=True)
            stage = "native_runtime"
            model = SparseSMPLX(model_path)
            runtime = native_runtime(root)
            report["runtime"] = {"torch": runtime[0].__version__, "cuda": runtime[0].version.cuda,
                                 "gpu": runtime[0].cuda.get_device_name(0), "opengl_platform": "egl"}
            require(np.allclose(runtime[1].pose_mean.detach().cpu().numpy().reshape(55, 3), model.mean),
                    "Native hand mean differs")
        for task, number, sides, image_path, observation in selected:
            segment = task["segment_id"]
            stage = "frame_targets:" + segment
            folder = output / segment
            folder.mkdir()
            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
            targets = {side: load_target(observation, task["frames"], number, side, *image.size, task["fps"])
                       for side in sides}
            draw_targets(image, targets).save(folder / "targets.jpg")
            report["source_sha256"].update({str(p): sha256(p) for p in (image_path, observation)})
            case = {"segment_id": segment, "frame_1based": number, "timestamp_seconds": (number - 1) / task["fps"],
                    "observed_hands": list(sides), "mirror_status": task["mirror_status"], "training_ready": False}
            report["cases"].append(case)
            if args.command == "pilot":
                source_path = inside(fits, segment + "/smplx/%05d_0.npz" % number)
                meta_path = inside(fits, segment + "/meta/%05d_0.json" % number)
                params = read_native(source_path)
                meta = json.loads(meta_path.read_text())
                camera = native_camera(meta, image_path)
                report["source_sha256"].update({str(p): sha256(p) for p in (source_path, meta_path)})
                stage = "baseline_parity:" + segment
                case["baseline_native_parity_max_metres"] = parity(model, runtime, params)
                stage = "hand_fitting:" + segment
                case["hands"] = []
                proposals = {}
                for side in sides:
                    # Independent baseline starts avoid propagating an unverified update.
                    if allow_elbow:
                        fitted, metrics = fit_hand(model, params, side, targets[side], camera,
                                                   args.max_nfev, allow_elbow=True)
                    else:
                        fitted, metrics = fit_hand(model, params, side, targets[side], camera, args.max_nfev)
                    np.savez_compressed(folder / (side + "-optimizer-proposal.npz"), **fitted)
                    proposals[side] = fitted
                    case["hands"].append(metrics)
                candidate, combined_passed = merge_hand_candidates(
                    model, params, proposals, case["hands"], targets, camera)
                case["combined_projection_gate_passed"] = combined_passed
                stage = "candidate_parity:" + segment
                case["candidate_native_parity_max_metres"] = parity(model, runtime, candidate)
                case["all_candidate_gates_passed"] = all(h["candidate_gate_passed"] for h in case["hands"])
                case["candidate_policy"] = ("Failed hands retain baseline; a combined projection failure "
                                            "reverts the entire frame; raw proposals are not accepted outputs")
                np.savez_compressed(folder / "baseline.npz", **params)
                np.savez_compressed(folder / "candidate.npz", **candidate)
                stage = "rendering:" + segment
                _, vertices0 = native_forward(runtime, params)
                _, vertices1 = native_forward(runtime, candidate)
                render_args = {"diagnostic": True} if allow_elbow else {}
                base = Image.fromarray(render_overlay(np.asarray(image), vertices0, runtime[1].faces, camera,
                                                      **render_args))
                result = Image.fromarray(render_overlay(np.asarray(image), vertices1, runtime[1].faces, camera,
                                                        **render_args))
                base.save(folder / "baseline-overlay.jpg")
                result.save(folder / "candidate-overlay.jpg")
                save_comparison(folder / "compare.jpg", [image, base, result],
                                ["Original", "Native baseline", "Candidate (NOT training-ready)"])
                for side, target in targets.items():
                    low, high = target[:, :2].min(axis=0), target[:, :2].max(axis=0)
                    center = (low + high) / 2
                    radius = int(np.ceil(np.max(high - low) / 2 + 65))
                    x, y = np.rint(center).astype(int)
                    # Square crop keeps hand geometry/aspect ratio unchanged in the close-up.
                    crop = (x - radius, y - radius, x + radius, y + radius)
                    panels = [panel.crop(crop).resize((480, 480)) for panel in (image, base, result)]
                    save_comparison(folder / (side + "-hand-compare.jpg"), panels,
                                    ["Original", "Baseline", "Candidate - NEEDS REVIEW"])
            print(json.dumps(case, ensure_ascii=False), flush=True)
            write_json(report_path, report)
        stage = "source_digest_recheck"
        for name, digest in report["source_sha256"].items():
            require(sha256(name) == digest, "Source modified during pilot: " + name)
        report["source_files_unchanged"] = True
        report["status"] = ("targets_pending_visual_check" if args.command == "targets" else
                            "keyframe_candidates_pending_visual_review" if
                            all(c["all_candidate_gates_passed"] for c in report["cases"]) else
                            "candidate_gate_failed")
        report["limitations"] = ["Single-frame pilot, not a corrected motion sequence",
                                 "No temporal continuity/contact/semantic sign-language acceptance",
                                 "MediaPipe targets are estimates; pixel fit is not 3D ground truth",
                                 "Depth is underconstrained; no MediaPipe z used as metric 3D supervision",
                                 "Only same-side elbow/wrist/fingers may change; elbow capped at 15 degrees" if allow_elbow
                                 else "Only wrist and finger rotations are allowed to change; no hand/side swapping",
                                 "Mirror/source signer/split review still pending"]
        write_json(report_path, report)
        print("Report: " + str(report_path), flush=True)
        return 2 if report["status"] == "candidate_gate_failed" else 0
    except Exception as exc:
        report.update(status="failed", error=str(exc), error_type=type(exc).__name__,
                      failure_stage=stage,
                      traceback=traceback.format_exc(), training_ready=False)
        write_json(report_path, report)
        raise


def review_saved(args):
    """Audit and rerender saved baseline/candidate/proposals; never call the optimizer."""
    from PIL import Image
    previous = args.previous_results.resolve()
    prior_path = inside(previous, "report.json")
    require(sha256(prior_path) == args.previous_report_sha256, "Previous report digest differs")
    prior = json.loads(prior_path.read_text())
    require(prior.get("schema") == "signbridge-hand-keyframe-pilot-v1" and
            prior.get("status") in ("candidate_gate_failed", "keyframe_candidates_pending_visual_review") and
            prior.get("training_ready") is False and prior.get("source_files_unchanged") is True and
            prior.get("full_sequence_refined") is False, "Previous run is not auditable/completed")
    batch, fits, root = args.batch.resolve(), args.fits.resolve(), args.smplerx_root.resolve()
    selected = task_cases(batch)
    prior_cases = {c["segment_id"]: c for c in prior["cases"]}
    require(len(prior_cases) == len(prior["cases"]) == len(CASES) and
            set(prior_cases) == {c[0] for c in CASES}, "Previous case scope differs")
    output = new_output(args.output, [batch, fits, root, previous])
    report = {"schema": "signbridge-hand-keyframe-pilot-v1", "status": "running",
              "created_at": datetime.now(timezone.utc).isoformat(), "training_ready": False,
              "full_sequence_refined": False, "new_network_inference": False, "new_optimizer_run": False,
              "source_pilot_status": prior["status"], "render_style": "explicit face-normal colors, unlit depth-tested EGL",
              "source_sha256": {str(prior_path): sha256(prior_path)}, "cases": []}
    report_path = output / "report.json"
    stage = "review_inputs"
    write_json(report_path, report)
    try:
        # Anchor all original inputs to the pinned prior report, not just filenames.
        allowed_roots = (batch, fits, root, previous.parent)
        for name, digest in prior["source_sha256"].items():
            path = Path(name).resolve()
            require(path == Path(__file__).resolve() or
                    any(path == source or source in path.parents for source in allowed_roots),
                    "Unexpected previous source root")
            require(sha256(path) == digest, "Previous source modified: " + name)
            report["source_sha256"][str(path)] = digest
        run_path = fits / "run.json"
        require(sha256(run_path) == args.fit_run_sha256 == prior["source_sha256"].get(str(run_path)),
                "Wrong original fitting run")
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        require(commit == prior.get("smplerx_commit") == COMMIT, "Source commit differs")
        model_path = verify_model_assets(root)
        stage = "review_native_runtime"
        model, runtime = SparseSMPLX(model_path), native_runtime(root)
        require(np.allclose(runtime[1].pose_mean.detach().cpu().numpy().reshape(55, 3), model.mean),
                "Native hand mean differs")
        report["source_sha256"][str(Path(__file__).resolve())] = sha256(Path(__file__).resolve())
        for task, number, sides, image_path, observation in selected:
            segment = task["segment_id"]
            stage = "review_frame:" + segment
            old = prior_cases[segment]
            require(old["frame_1based"] == number and old["observed_hands"] == list(sides) and
                    np.isclose(old["timestamp_seconds"], (number - 1) / task["fps"], atol=1e-6),
                    "Previous frame/hand scope differs")
            folder = output / segment
            folder.mkdir()
            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
            targets = {side: load_target(observation, task["frames"], number, side, *image.size, task["fps"])
                       for side in sides}
            source = inside(fits, segment + "/smplx/%05d_0.npz" % number)
            meta = inside(fits, segment + "/meta/%05d_0.json" % number)
            require(all(prior["source_sha256"].get(str(p)) == sha256(p)
                        for p in (source, meta, image_path, observation)), "Previous frame source not anchored")
            baseline = read_native(source)
            files = {"baseline": inside(previous, segment + "/baseline.npz"),
                     "candidate": inside(previous, segment + "/candidate.npz")}
            files.update({side: inside(previous, segment + "/" + side + "-optimizer-proposal.npz") for side in sides})
            params = {name: read_native(path) for name, path in files.items()}
            require(all(np.array_equal(baseline[k], params["baseline"][k]) for k in baseline),
                    "Saved baseline differs from original")
            allow_elbow = prior.get("fit_mode", "hand_only") == "hand_plus_elbow"
            for side in sides:
                preserved(baseline, params[side], (side,), allow_elbow=allow_elbow)
            preserved(baseline, params["candidate"], sides, allow_elbow=allow_elbow)
            camera = native_camera(json.loads(meta.read_text()), image_path)
            metrics = json.loads(json.dumps(old["hands"]))
            require([item["side"] for item in metrics] == list(sides), "Previous per-hand order differs")
            for item in metrics:
                item["candidate_gate_passed"] = item["optimizer_gate_passed"]
            merged, _ = merge_hand_candidates(model, baseline, {s: params[s] for s in sides}, metrics, targets, camera)
            require(all(np.array_equal(merged[k], params["candidate"][k]) for k in merged),
                    "Saved candidate disagrees with original selection policy")
            for item, original in zip(metrics, old["hands"]):
                require(item["candidate_gate_passed"] == original["candidate_gate_passed"] and
                        all(np.isclose(item["saved_candidate_after"][key], original["saved_candidate_after"][key],
                                       atol=1e-3, rtol=1e-6) for key in item["saved_candidate_after"]),
                        "Saved candidate metrics differ from prior report")
            report["source_sha256"].update({str(path): sha256(path) for path in files.values()})
            panels = {"original": image}
            case = {"segment_id": segment, "frame_1based": number, "observed_hands": list(sides),
                    "training_ready": False, "hands": [], "native_parity_max_metres": {}}
            report["cases"].append(case)
            for name, values in params.items():
                case["native_parity_max_metres"][name] = parity(model, runtime, values)
                _, vertices = native_forward(runtime, values)
                stage = "review_rendering:" + segment
                panels[name] = Image.fromarray(render_overlay(np.asarray(image), vertices, runtime[1].faces,
                                                             camera, diagnostic=True))
                panels[name].save(folder / (name + "-diagnostic.jpg"))
            save_comparison(folder / "saved-review.jpg", [panels[n] for n in ("original", "baseline", "candidate")],
                            ["Original", "Saved baseline", "Saved candidate - NOT approved"])
            for side, target in targets.items():
                before = reprojection_metrics(model.hand(baseline, side), target, camera)
                proposed = reprojection_metrics(model.hand(params[side], side), target, camera)
                saved = reprojection_metrics(model.hand(params["candidate"], side), target, camera)
                old_hand = next(item for item in old["hands"] if item["side"] == side)
                if "after" in old_hand:
                    require(all(np.isclose(proposed[key], old_hand["after"][key], atol=1e-3, rtol=1e-6)
                                for key in proposed), "Proposal metrics differ")
                case["hands"].append({"side": side, "source_candidate_gate_passed": old_hand["candidate_gate_passed"],
                                      "before": before, "saved_candidate": saved, "raw_proposal": proposed,
                                      "wrist_error_pixels": {name: float(np.linalg.norm(
                                          project(model.hand(values, side), camera)[0] - target[0, :2]))
                                                             for name, values in params.items()},
                                      "proposal_accepted_by_review": False})
                low, high = target[:, :2].min(axis=0), target[:, :2].max(axis=0)
                center = np.rint((low + high) / 2).astype(int)
                radius = int(np.ceil(np.max(high - low) / 2 + 65))
                crop = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)
                require(side in panels, "Missing raw proposal diagnostic panel")
                selected_panels = [panels[name].crop(crop).resize((480, 480))
                                   for name in ("original", "baseline", "candidate", side)]
                save_comparison(folder / (side + "-hand-review.jpg"), selected_panels,
                                ["Original", "Baseline", "Saved - NOT approved" if old_hand["candidate_gate_passed"]
                                 else "Saved = baseline (REJECTED)", "Raw proposal - NOT accepted"])
            write_json(report_path, report)
        stage = "review_digest_recheck"
        for name, digest in report["source_sha256"].items():
            require(sha256(name) == digest, "Source changed during review: " + name)
        report.update(status="saved_parameters_rerendered_pending_review", source_files_unchanged=True,
                      limitations=["Visualization only; no optimizer and no new candidate acceptance",
                                   "Normal-based color is diagnostic shading, not observed appearance or physical lighting",
                                   "Original candidate gates and training-ready state are not changed"])
        write_json(report_path, report)
        return 0
    except Exception as exc:
        report.update(status="failed", error=str(exc), error_type=type(exc).__name__, failure_stage=stage,
                      traceback=traceback.format_exc(), training_ready=False)
        write_json(report_path, report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("targets", "pilot", "review"):
        command = commands.add_parser(name)
        command.add_argument("--batch", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name in ("pilot", "review"):
            command.add_argument("--fits", type=Path, required=True)
            command.add_argument("--smplerx-root", type=Path, required=True)
            command.add_argument("--fit-run-sha256", required=True)
        if name == "pilot":
            command.add_argument("--max-nfev", type=int, default=80, choices=range(10, 201), metavar="10..200")
            command.add_argument("--allow-elbow", action="store_true",
                                 help="Also fit same-side elbow rotation, at most 15 degrees")
        if name == "review":
            command.add_argument("--previous-results", type=Path, required=True)
            command.add_argument("--previous-report-sha256", required=True)
    args = parser.parse_args()
    try:
        return review_saved(args) if args.command == "review" else run(args)
    except (ValueError, OSError, KeyError, ImportError) as exc:
        traceback.print_exc()
        parser.exit(2, "error: " + str(exc) + "\n")


if __name__ == "__main__":
    sys.exit(main())
