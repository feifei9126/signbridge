"""Synthetic-only tests: hand fitting never authorizes motion-training readiness."""

import contextlib
import copy
import importlib.util
import io
import json
import pickle
import tempfile
import sys
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-hand-refine.py"
spec = importlib.util.spec_from_file_location("sign_hand_refine", SCRIPT)
hand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hand)


def parameters():
    values = {key: np.zeros(shape, dtype=np.float32) for key, shape in hand.SHAPES.items()}
    values["transl"][0, 2] = 3
    return values


def synthetic_model():
    """Small independent skinning fixture; no licensed body files used in tests."""
    rng = np.random.default_rng(47)
    vertices = rng.normal(0, .04, (65, 3))
    parents = np.zeros(55, dtype=int)
    parents[0] = -1
    vertices[0] = 0
    for side, sign in (("left", 1), ("right", -1)):
        wrist = hand.WRISTS[side]
        vertices[wrist] = [sign * .3, 0, 0]
        for finger, chain in enumerate(hand.JOINTS[side]):
            parents[chain] = [wrist, chain[0], chain[1]]
            for depth, index in enumerate(chain):
                vertices[index] = vertices[wrist] + [sign * (.025 * (finger - 2)), .025 * (depth + 1), .002 * finger]
            tip = 55 + finger + (0 if side == "left" else 5)
            vertices[tip] = vertices[chain[-1]] + [0, .025, 0]
    regressor = np.zeros((55, 65))
    regressor[np.arange(55), np.arange(55)] = 1
    shape = rng.normal(0, .0005, (65, 3, 20))
    poses = rng.normal(0, .00002, (65, 3, 486))
    weights = np.zeros((65, 55))
    weights[np.arange(55), np.arange(55)] = 1
    for side in ("left", "right"):
        for finger, chain in enumerate(hand.JOINTS[side]):
            weights[55 + finger + (0 if side == "left" else 5), chain[-1]] = 1
    model = hand.SparseSMPLX.__new__(hand.SparseSMPLX)
    model.tip_ids = list(range(55, 65))
    model.rest_joints = regressor @ vertices
    model.joint_shapes = np.einsum("jv,vcd->jcd", regressor, shape)
    model.tip_template = vertices[model.tip_ids]
    model.tip_shapes = shape[model.tip_ids]
    model.tip_poses = poses[model.tip_ids]
    model.tip_weights = weights[model.tip_ids]
    model.parents = parents
    model.mean = np.zeros((55, 3))
    full = dict(template=vertices, regressor=regressor, shape=shape, poses=poses,
                weights=weights, parents=parents)
    return model, full


def full_lbs(params, mean, fixture):
    """Independent full-mesh LBS reference, including our own Rodrigues formula."""
    pose = np.vstack([params[key].reshape(-1, 3) for key in (
        "global_orient", "body_pose", "jaw_pose", "leye_pose", "reye_pose",
        "left_hand_pose", "right_hand_pose")]) + mean
    rotations = []
    for vector in pose:
        theta = np.linalg.norm(vector)
        x, y, z = vector
        skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
        a = np.sin(theta) / theta if theta > 1e-8 else 1 - theta ** 2 / 6
        b = (1 - np.cos(theta)) / theta ** 2 if theta > 1e-8 else .5 - theta ** 2 / 24
        rotations.append(np.eye(3) + a * skew + b * skew @ skew)
    beta = np.r_[params["betas"].ravel(), params["expression"].ravel()]
    shaped = fixture["template"] + (fixture["shape"].reshape(-1, 20) @ beta).reshape(-1, 3)
    rest = fixture["regressor"] @ shaped
    feature = (np.asarray(rotations[1:]) - np.eye(3)).reshape(-1)
    posed = shaped + (fixture["poses"].reshape(-1, 486) @ feature).reshape(-1, 3)
    globals_ = []
    transforms = []
    for index, parent in enumerate(fixture["parents"]):
        local = np.eye(4)
        local[:3, :3] = rotations[index]
        local[:3, 3] = rest[index] if parent == -1 else rest[index] - rest[parent]
        global_ = local if parent == -1 else globals_[parent] @ local
        globals_.append(global_)
        bind = np.eye(4)
        bind[:3, 3] = -rest[index]
        transforms.append(global_ @ bind)
    vertices = []
    for index, vertex in enumerate(posed):
        weighted = sum(weight * transform for weight, transform in zip(fixture["weights"][index], transforms))
        vertices.append((weighted @ np.r_[vertex, 1])[:3])
    translation = params["transl"].ravel()
    return np.array([g[:3, 3] for g in globals_]) + translation, np.asarray(vertices) + translation


class HandRefineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.camera = {"focal": np.array([1000, 1000]), "princpt": np.array([320, 240])}

    def batch_fixture(self):
        batch = self.root / "batch"
        batch.mkdir()
        tasks = []
        for segment, count, sides in hand.CASES:
            folder = batch / "samples" / segment
            images = folder / "images"
            images.mkdir(parents=True)
            frames = []
            for number in range(1, count + 1):
                path = images / ("%06d.jpg" % number)
                Image.new("RGB", (200, 160), (240, 240, 240)).save(path)
                frames.append({"frame_id": number, "image": str(path.relative_to(batch)),
                               "sha256": hand.sha256(path), "clip_seconds": (number - 1) / 25})
            manifest = folder / "frames.jsonl"
            manifest.write_text("".join(json.dumps(frame) + "\n" for frame in frames))
            points = np.zeros((count, 21, 3), dtype=np.float32)
            points[:, :, :2] = [.5, .5]
            points[:, [5, 9, 13, 17], 0] = .65
            arrays = {"timestamps_seconds": np.arange(count) / 25}
            for side in ("left", "right"):
                arrays[side + "_hand_image"] = points
                arrays[side + "_hand_image_detected"] = np.full(count, side in sides, dtype=bool)
            np.savez(folder / "observations.npz", **arrays)
            tasks.append({"segment_id": segment, "frames": count, "fps": 25, "images": str(images.relative_to(batch)),
                          "frame_manifest": str(manifest.relative_to(batch)), "image_transform": "none",
                          "content_reviewed": True, "model_training_ready": False, "mirror_status": "unknown"})
        hand.write_json(batch / "contract.json", {"schema": "signbridge-smplerx-input-v1",
                        "smplerx_commit": hand.COMMIT, "model_training_ready": False,
                        "fit_semantics": "SMPLer-X per-frame estimates, use_pca=False, flat_hand_mean=False"})
        (batch / "tasks.jsonl").write_text("".join(json.dumps(task) + "\n" for task in tasks))
        self.refresh_checksums(batch)
        return batch

    def refresh_checksums(self, batch):
        files = sorted(path for path in batch.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
        (batch / "SHA256SUMS").write_text("".join(hand.sha256(path) + "  " + str(path.relative_to(batch)) + "\n"
                                                   for path in files))

    def test_sparse_matches_independent_full_lbs_and_adds_mean_once(self):
        model, full = synthetic_model()
        rng = np.random.default_rng(7)
        for size in (0, .15, .8):
            with self.subTest(rotation=size):
                params = parameters()
                for name in hand.SHAPES:
                    if name != "transl":
                        params[name] = rng.normal(0, size, params[name].shape)
                model.mean[25:] = rng.normal(0, .12, (30, 3))
                joints, tips = model.forward(params)
                full_joints, full_vertices = full_lbs(params, model.mean, full)
                np.testing.assert_allclose(joints, full_joints, atol=1e-12)
                np.testing.assert_allclose(tips, full_vertices[model.tip_ids], atol=1e-12)
                for side in ("left", "right"):
                    points = model.hand(params, side)
                    np.testing.assert_equal(points[0], joints[hand.WRISTS[side]])
                    expected = [joints[hand.WRISTS[side]]]
                    for index, group in enumerate(hand.JOINTS[side]):
                        expected.extend(joints[group])
                        expected.append(tips[index + (0 if side == "left" else 5)])
                    np.testing.assert_allclose(points, expected)
        self.assertEqual(hand.WRISTS["left"] - 1, 19)
        self.assertEqual(hand.WRISTS["right"] - 1, 20)
        self.assertEqual(hand.JOINTS["left"][-2:], [[34, 35, 36], [31, 32, 33]])

    def test_native_import_path_exposes_legacy_smplerx_config(self):
        root = self.root / "smplerx"
        (root / "main").mkdir(parents=True)
        (root / "main/config.py").write_text("cfg = object()\n")
        (root / "common/utils/smplx/smplx").mkdir(parents=True)
        main_root, smplx_root = hand.configure_native_import_path(root)
        self.assertEqual(main_root, root / "main")
        self.assertEqual(smplx_root, root / "common/utils/smplx")
        self.assertEqual(Path(sys.path[0]), root / "main")
        self.assertEqual(Path(sys.path[1]), root / "common/utils/smplx")
        with patch.dict(hand.sys.modules, {"config": types.SimpleNamespace(__file__="/tmp/wrong-config.py")}, clear=False):
            hand.configure_native_import_path(root)
            self.assertNotIn("config", hand.sys.modules)

    def test_projection_is_native_positive_z_not_opengl_sign(self):
        np.testing.assert_allclose(hand.project(np.array([[.3, -.6, 3.]]), self.camera), [[420, 40]])
        for points in ([[0, 0, -1]], [[0, 0, 0]], [[np.nan, 0, 1]]):
            with self.assertRaises(ValueError):
                hand.project(np.array(points), self.camera)

    def test_synthetic_fitting_improves_target_but_never_marks_training_ready(self):
        model, _ = synthetic_model()
        baseline = parameters()
        wanted = copy.deepcopy(baseline)
        wanted["left_hand_pose"][:, 2] = .4
        xy = hand.project(model.hand(wanted, "left"), self.camera)
        target = np.c_[xy, np.zeros(21)]
        candidate, metrics = hand.fit_hand(model, baseline, "left", target, self.camera, 80)
        self.assertTrue(metrics["candidate_gate_passed"], metrics)
        self.assertLess(metrics["after"]["local_rmse_pixels"], metrics["before"]["local_rmse_pixels"] * .8)
        self.assertFalse(metrics["training_ready"])
        hand.preserved(baseline, candidate, ("left",))
        # Relative MediaPipe z is deliberately ignored, not mixed with metric SMPL-X coordinates.
        changed_z = target.copy()
        changed_z[:, 2] = np.arange(21) * 1000
        candidate_z, _ = hand.fit_hand(model, baseline, "left", changed_z, self.camera, 80)
        np.testing.assert_array_equal(candidate["left_hand_pose"], candidate_z["left_hand_pose"])

    def test_optimizer_timeout_or_no_improvement_fails_gate(self):
        model, _ = synthetic_model()
        baseline = parameters()
        target = np.c_[hand.project(model.hand(baseline, "right"), self.camera), np.zeros(21)]
        _, metrics = hand.fit_hand(model, baseline, "right", target, self.camera)
        self.assertFalse(metrics["candidate_gate_passed"])
        target[:5, :2] += 40
        x = np.r_[baseline["right_hand_pose"].ravel(), baseline["body_pose"][20]]
        fake = types.SimpleNamespace(x=x, status=0, nfev=80, message="evaluation budget reached")
        with patch.object(hand, "least_squares", return_value=fake):
            _, metrics = hand.fit_hand(model, baseline, "right", target, self.camera)
        self.assertFalse(metrics["candidate_gate_passed"])

    def test_merged_hands_are_rechecked_and_cross_hand_regression_reverts_frame(self):
        model, _ = synthetic_model()
        baseline = parameters()
        left = copy.deepcopy(baseline)
        right = copy.deepcopy(baseline)
        left["left_hand_pose"][:, 2] = .35
        right["right_hand_pose"][:, 2] = -.35
        proposals = {"left": left, "right": right}
        targets = {side: np.c_[hand.project(model.hand(proposal, side), self.camera), np.zeros(21)]
                   for side, proposal in proposals.items()}
        def metrics():
            return [{"side": side, "candidate_gate_passed": True, "training_ready": False}
                    for side in targets]
        with patch.object(model, "tip_poses", np.zeros_like(model.tip_poses)):
            passed_metrics = metrics()
            candidate, passed = hand.merge_hand_candidates(
                model, baseline, proposals, passed_metrics, targets, self.camera)
        self.assertTrue(passed)
        self.assertTrue(all(item["applied_to_candidate"] for item in passed_metrics))
        np.testing.assert_equal(candidate["left_hand_pose"], left["left_hand_pose"])
        np.testing.assert_equal(candidate["right_hand_pose"], right["right_hand_pose"])
        native_hand = model.hand
        def coupled(params, side, prepared=None):
            points = native_hand(params, side, prepared).copy()
            if (np.any(params["left_hand_pose"]) and np.any(params["right_hand_pose"]) and side == "left"):
                # Simulate a pose-blend-shape cross-hand effect invisible in independent fits.
                points[1:, 0] += .4
            return points
        rejected_metrics = metrics()
        with patch.object(model, "hand", side_effect=coupled):
            candidate, passed = hand.merge_hand_candidates(
                model, baseline, proposals, rejected_metrics, targets, self.camera)
        self.assertFalse(passed)
        for key in baseline:
            np.testing.assert_array_equal(candidate[key], baseline[key])
        self.assertTrue(all(item["optimizer_gate_passed"] for item in rejected_metrics))
        self.assertTrue(all(not item["candidate_gate_passed"] for item in rejected_metrics))
        self.assertFalse(rejected_metrics[0]["merged_projection_gate_passed"])

    def test_failed_hand_is_not_allowed_to_regress_after_other_hand_update(self):
        model, _ = synthetic_model()
        baseline = parameters()
        left = copy.deepcopy(baseline)
        left["left_hand_pose"][:, 2] = .4
        targets = {"left": np.c_[hand.project(model.hand(left, "left"), self.camera), np.zeros(21)],
                   "right": np.c_[hand.project(model.hand(baseline, "right"), self.camera), np.zeros(21)]}
        metrics = [{"side": "left", "candidate_gate_passed": True},
                   {"side": "right", "candidate_gate_passed": False}]
        native_hand = model.hand
        def coupled(params, side, prepared=None):
            points = native_hand(params, side, prepared).copy()
            if np.any(params["left_hand_pose"]) and side == "right":
                points[1:, 0] += .01
            return points
        with patch.object(model, "hand", side_effect=coupled):
            candidate, passed = hand.merge_hand_candidates(
                model, baseline, {"left": left, "right": baseline}, metrics, targets, self.camera)
        self.assertFalse(passed)
        self.assertFalse(metrics[1]["merged_projection_gate_passed"])
        for key in baseline:
            np.testing.assert_array_equal(candidate[key], baseline[key])

    def test_protected_params_and_other_hand_cannot_change(self):
        baseline = parameters()
        for key in ("global_orient", "betas", "expression", "transl", "right_hand_pose", "jaw_pose"):
            candidate = copy.deepcopy(baseline)
            candidate[key].flat[0] += .1
            with self.subTest(key=key), self.assertRaises(ValueError):
                hand.preserved(baseline, candidate, ("left",))
        candidate = copy.deepcopy(baseline)
        candidate["body_pose"][18, 0] = .1
        with self.assertRaisesRegex(ValueError, "Non-wrist"):
            hand.preserved(baseline, candidate, ("left",))
        candidate["body_pose"][18, 0] = 0
        candidate["body_pose"][19, 0] = .1
        hand.preserved(baseline, candidate, ("left",))

    def test_native_rejects_pca_missing_extra_and_nonfinite(self):
        path = self.root / "pose.npz"
        np.savez(path, **parameters())
        self.assertEqual(set(hand.read_native(path)), set(hand.SHAPES))
        for change in ("pca", "missing", "extra", "nan", "integer"):
            params = parameters()
            if change == "pca":
                params["left_hand_pose"] = np.zeros(6, dtype=np.float32)
            elif change == "missing":
                del params["transl"]
            elif change == "extra":
                params["unexpected"] = np.zeros(1)
            elif change == "nan":
                params["body_pose"][0, 0] = np.nan
            elif change == "integer":
                params["betas"] = params["betas"].astype(int)
            np.savez(path, **params)
            with self.subTest(change=change), self.assertRaises(ValueError):
                hand.read_native(path)

    def test_missing_hand_nan_and_timestamp_are_not_filled(self):
        batch = self.batch_fixture()
        selected = hand.task_cases(batch)
        task, number, sides, _, path = selected[-1]
        good = hand.load_target(path, number, number, "right", 200, 160, 25)
        self.assertEqual(good.shape, (21, 3))
        with self.assertRaisesRegex(ValueError, "No detected hand"):
            hand.load_target(path, number, number, "left", 200, 160, 25)
        with np.load(path, allow_pickle=False) as arrays:
            values = {k: arrays[k].copy() for k in arrays.files}
        for mutation in ("nan", "timestamp", "small", "mask"):
            mutated = copy.deepcopy(values)
            if mutation == "nan":
                mutated["right_hand_image"][-1, 0, 0] = np.nan
            elif mutation == "timestamp":
                mutated["timestamps_seconds"][-1] += .001
            elif mutation == "small":
                mutated["right_hand_image"][-1] = .5
            elif mutation == "mask":
                mutated["right_hand_image_detected"] = np.ones(number, dtype=int)
            np.savez(path, **mutated)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                hand.load_target(path, number, number, "right", 200, 160, 25)

    def test_batch_hash_wrong_frame_and_mean_convention_are_rejected(self):
        batch = self.batch_fixture()
        selected = hand.task_cases(batch)
        image = selected[0][3]
        original = image.read_bytes()
        image.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "Image changed"):
            hand.task_cases(batch)
        image.write_bytes(original)
        manifest = batch / selected[0][0]["frame_manifest"]
        lines = manifest.read_text().splitlines()
        frame = json.loads(lines[90])
        frame["frame_id"] = 90
        lines[90] = json.dumps(frame)
        manifest.write_text("\n".join(lines) + "\n")
        self.refresh_checksums(batch)
        with self.assertRaisesRegex(ValueError, "identity"):
            hand.task_cases(batch)
        contract = json.loads((batch / "contract.json").read_text())
        contract["fit_semantics"] = "flat_hand_mean=True"
        hand.write_json(batch / "contract.json", contract)
        self.refresh_checksums(batch)
        with self.assertRaisesRegex(ValueError, "convention"):
            hand.task_cases(batch)

    def test_path_traversal_symlinks_and_overwriting_are_rejected(self):
        source = self.root / "source"
        source.mkdir()
        file = source / "model.npz"
        file.write_bytes(b"data")
        outside = self.root / "outside.npz"
        outside.write_bytes(b"data")
        (source / "link.npz").symlink_to(outside)
        for path in ("../outside.npz", str(outside), "link.npz"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                hand.inside(source, path)
        for path in (source, source / "subdir", self.root):
            with self.subTest(output=path), self.assertRaises(ValueError):
                hand.new_output(path, [source])
        output = hand.new_output(self.root / "new", [source])
        with self.assertRaises(FileExistsError):
            hand.new_output(output, [source])

    def test_meta_from_another_segment_or_camera_is_rejected(self):
        image = self.root / "segment-a/images/000091.jpg"
        good = {"bbox_id": 0, "img_path": str(image), "focal": [1000, 1000], "princpt": [320, 240]}
        hand.native_camera(good, image)
        for patch_values in ({"img_path": str(self.root / "segment-b/images/000091.jpg")},
                             {"bbox_id": 1}, {"focal": [0, 1000]}, {"princpt": [np.nan, 240]}):
            with self.assertRaises(ValueError):
                hand.native_camera({**good, **patch_values}, image)

    def test_model_manifest_uses_actual_root_relative_layout(self):
        path = self.root / hand.MODEL_FILE
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic model bytes")
        digest = hand.sha256(path)
        info = {"schema": "signbridge-body-assets-v1", "space": "caizhongang/SMPLer-X",
                "revision": hand.BODY_REVISION, "assets": [{"path": hand.MODEL_FILE,
                "sha256": digest, "bytes": path.stat().st_size}]}
        manifest = self.root / "common/utils/human_model_files/signbridge-body-assets.json"
        hand.write_json(manifest, info)
        with patch.object(hand, "MODEL_SHA256", digest):
            self.assertEqual(hand.verify_model_assets(self.root), path)
            for mutation in ("size", "duplicate", "revision", "digest", "old-relative-path"):
                altered = copy.deepcopy(info)
                if mutation == "size":
                    altered["assets"][0]["bytes"] += 1
                elif mutation == "duplicate":
                    altered["assets"].append(altered["assets"][0])
                elif mutation == "revision":
                    altered["revision"] = "other"
                elif mutation == "digest":
                    altered["assets"][0]["sha256"] = "0" * 64
                else:
                    altered["assets"][0]["path"] = "smplx/SMPLX_NEUTRAL.npz"
                hand.write_json(manifest, altered)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    hand.verify_model_assets(self.root)

    def test_checkpoint_inventory_never_unpickles_and_needs_all_heads(self):
        heads = ["hand_regressor", "hand_position_net", "hand_roi_net", "box_net"]
        archive = self.root / "checkpoint.tar"
        def create(names):
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("checkpoint/data.pkl", pickle.dumps({"module." + n + ".layer.weight": 0 for n in names}))
        create(heads)
        with patch.object(pickle, "loads", side_effect=AssertionError("must not execute pickle")):
            inventory = hand.checkpoint_head_inventory(archive)
        self.assertEqual(set(inventory["heads"]), set(heads))
        self.assertFalse(inventory["runtime_load_verified"])
        create(heads[:-1])
        with self.assertRaisesRegex(ValueError, "missing learned head"):
            hand.checkpoint_head_inventory(archive)

    def test_native_parity_stops_before_optimizing_if_mismatch(self):
        model, _ = synthetic_model()
        params = parameters()
        joints, tips = model.forward(params)
        vertices = np.zeros((65, 3))
        vertices[model.tip_ids] = tips
        with patch.object(hand, "native_forward", return_value=(joints, vertices)):
            self.assertEqual(hand.parity(model, None, params), 0)
        vertices[55, 0] += .001
        with patch.object(hand, "native_forward", return_value=(joints, vertices)):
            with self.assertRaisesRegex(ValueError, "parity failed"):
                hand.parity(model, None, params)

    def test_diagnostic_face_colors_show_orientation_without_changing_geometry(self):
        vertices = np.array([[0., 0., 1.], [1., 0., 1.], [0., 1., 1.], [0., 0., 2.]])
        faces = np.array([[0, 2, 1], [0, 1, 2], [0, 3, 2]])
        before = vertices.copy()
        colors = hand.diagnostic_face_colors(vertices, faces)
        self.assertEqual(colors.shape, (3, 4))
        self.assertEqual(colors.dtype, np.uint8)
        self.assertTrue((colors[:, 3] == 255).all())
        self.assertGreater(len(np.unique(colors[:, :3], axis=0)), 1)
        np.testing.assert_array_equal(vertices, before)
        with self.assertRaises(ValueError):
            hand.diagnostic_face_colors(vertices, np.array([[0, 0, 0]]))

    def test_renderer_preflight_requires_real_nonempty_pixels(self):
        rendered = np.zeros((64, 64, 3), dtype=np.uint8)
        rendered[24:40, 24:40] = 200
        with patch.object(hand, "render_overlay", return_value=rendered) as render, \
             patch.dict(hand.os.environ, PYOPENGL_PLATFORM="egl"):
            result = hand.renderer_preflight()
        self.assertTrue(result["ready"])
        self.assertEqual(result["rendered_pixels"], 256)
        self.assertEqual(result["backend"], "egl")
        self.assertEqual(render.call_args.args[0].shape, (64, 64, 3))
        vertices, faces = render.call_args.args[1:3]
        self.assertTrue((vertices[:, 2] > 0).all())
        for face in faces:
            a, b, c = vertices[face]
            self.assertLess(np.cross(b - a, c - a)[2], 0)
        for invalid in (np.zeros_like(rendered), rendered.astype(float), rendered[:32]):
            with patch.object(hand, "render_overlay", return_value=invalid), \
                 patch.dict(hand.os.environ, PYOPENGL_PLATFORM="egl"), self.assertRaises(ValueError):
                hand.renderer_preflight()
        with patch.object(hand, "render_overlay", side_effect=ImportError('Library "GLU" not found.')), \
             patch.dict(hand.os.environ, PYOPENGL_PLATFORM="egl"), self.assertRaisesRegex(ImportError, "GLU"):
            hand.renderer_preflight()

    def test_diagnostic_render_uses_face_colors_and_unlit_depth_tested_flag(self):
        captured = {}
        vertices = np.asarray([[0., 0., 2.], [1., 0., 2.], [0., 1., 2.]])
        faces = np.asarray([[0, 2, 1]])
        class Mesh:
            def apply_transform(self, _):
                pass
        def mesh_factory(**kwargs):
            captured.update(kwargs)
            return Mesh()
        class Renderer:
            def __init__(self, **kwargs):
                pass
            def render(self, scene, flags):
                captured["flags"] = flags
                return np.full((20, 20, 4), 160, dtype=np.uint8), np.ones((20, 20))
            def delete(self):
                captured["deleted"] = True
        pyrender = types.SimpleNamespace(MetallicRoughnessMaterial=lambda **_: None,
            Scene=lambda **_: types.SimpleNamespace(add=lambda *args, **kwargs: None),
            Mesh=types.SimpleNamespace(from_trimesh=lambda mesh, **kwargs: captured.update(material=kwargs["material"])),
            IntrinsicsCamera=lambda **_: None, DirectionalLight=lambda **_: None,
            OffscreenRenderer=Renderer, RenderFlags=types.SimpleNamespace(RGBA=1, FLAT=2))
        trimesh = types.SimpleNamespace(Trimesh=mesh_factory,
            transformations=types.SimpleNamespace(rotation_matrix=lambda *args: np.eye(4)))
        before = vertices.copy()
        with patch.dict("sys.modules", pyrender=pyrender, trimesh=trimesh):
            image = hand.render_overlay(np.zeros((20, 20, 3), dtype=np.uint8), vertices, faces, self.camera,
                                        diagnostic=True)
        self.assertEqual(image.shape, (20, 20, 3))
        self.assertEqual(captured["flags"], 3)
        self.assertIsNone(captured["material"])
        self.assertTrue(captured["deleted"])
        np.testing.assert_array_equal(captured["face_colors"], hand.diagnostic_face_colors(vertices, faces))
        np.testing.assert_array_equal(vertices, before)

    def test_renderer_is_deleted_on_failure(self):
        class FakeMesh:
            def apply_transform(self, _):
                pass
        deleted = []
        class Renderer:
            def __init__(self, **kwargs):
                pass
            def render(self, *args, **kwargs):
                raise RuntimeError("test EGL failure")
            def delete(self):
                deleted.append(True)
        pyrender = types.SimpleNamespace(MetallicRoughnessMaterial=lambda **_: None,
                    Scene=lambda **_: types.SimpleNamespace(add=lambda *args, **kwargs: None),
                    Mesh=types.SimpleNamespace(from_trimesh=lambda *args, **kwargs: None),
                    IntrinsicsCamera=lambda **_: None, DirectionalLight=lambda **_: None,
                    OffscreenRenderer=Renderer, RenderFlags=types.SimpleNamespace(RGBA=0))
        trimesh = types.SimpleNamespace(Trimesh=lambda **_: FakeMesh(),
                        transformations=types.SimpleNamespace(rotation_matrix=lambda *args: np.eye(4)))
        with patch.dict("sys.modules", pyrender=pyrender, trimesh=trimesh):
            with self.assertRaisesRegex(RuntimeError, "EGL failure"):
                hand.render_overlay(np.zeros((20, 20, 3), dtype=np.uint8), None, None, self.camera)
        self.assertEqual(deleted, [True])

    def test_targets_only_report_never_becomes_training_ready(self):
        batch = self.batch_fixture()
        output = self.root / "targets"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hand.run(types.SimpleNamespace(command="targets", batch=batch, output=output)), 0)
        report = json.loads((output / "report.json").read_text())
        self.assertFalse(report["training_ready"])
        self.assertFalse(report["full_sequence_refined"])
        self.assertFalse(report["new_network_inference"])
        self.assertTrue(report["source_files_unchanged"])
        self.assertEqual(len(report["cases"]), 2)
        self.assertEqual([c["frame_1based"] for c in report["cases"]], [91, 159])

    def test_pilot_gate_failure_retains_original_hand_and_records_proposal(self):
        batch = self.batch_fixture()
        fits = self.root / "fits"
        fits.mkdir()
        root = self.root / "smplerx"
        model_path = root / hand.MODEL_FILE
        model_path.parent.mkdir(parents=True)
        model_path.write_bytes(b"mock model; not a licensed asset")
        (root / "common/utils/human_model_files/signbridge-body-assets.json").write_text("{}")
        checkpoint = root / "pretrained_models/smpler_x_h32.pth.tar"
        checkpoint.parent.mkdir()
        checkpoint.write_bytes(b"mock checkpoint")
        baseline = parameters()
        for task, number, _, image, _ in hand.task_cases(batch):
            folder = fits / task["segment_id"]
            (folder / "smplx").mkdir(parents=True)
            (folder / "meta").mkdir()
            np.savez(folder / "smplx" / ("%05d_0.npz" % number), **baseline)
            hand.write_json(folder / "meta" / ("%05d_0.json" % number),
                            {"bbox_id": 0, "img_path": str(image), "focal": [1000, 1000], "princpt": [100, 80]})
        hand.write_json(fits / "run.json", {"schema": "signbridge-smplerx-run-v1",
                        "status": "inferred_pending_import_audit", "completed": [c[0] for c in hand.CASES],
                        "preflight": {"actual_commit": hand.COMMIT}, "tasks_sha256": hand.sha256(batch / "tasks.jsonl")})
        model, _ = synthetic_model()
        class PoseMean:
            def detach(self):
                return self
            def cpu(self):
                return self
            def numpy(self):
                return model.mean
        torch = types.SimpleNamespace(__version__="mock-test-only", version=types.SimpleNamespace(cuda="mock"),
                                      cuda=types.SimpleNamespace(get_device_name=lambda _: "mock-test-no-GPU"))
        runtime = (torch, types.SimpleNamespace(pose_mean=PoseMean(), faces=np.zeros((1, 3), dtype=int)))
        def forward(_, params):
            joints, tips = model.forward(params)
            vertices = np.zeros((65, 3))
            vertices[model.tip_ids] = tips
            return joints, vertices
        def fake_fit(_, source, side, *args):
            proposal = copy.deepcopy(source)
            proposal[side + "_hand_pose"][0, 0] = .15
            proposal["body_pose"][hand.WRISTS[side] - 1, 0] = .05
            return proposal, {"side": side, "candidate_gate_passed": side == "left", "training_ready": False}
        output = self.root / "gpu-mocked-output"
        args = types.SimpleNamespace(command="pilot", batch=batch, fits=fits, smplerx_root=root,
                  output=output, fit_run_sha256=hand.sha256(fits / "run.json"), max_nfev=80)
        with patch.object(hand, "verify_model_assets", return_value=model_path), \
             patch.object(hand, "checkpoint_head_inventory", return_value={"runtime_load_verified": False}), \
             patch.object(hand, "SparseSMPLX", return_value=model), \
             patch.object(hand, "native_runtime", return_value=runtime), \
             patch.object(hand, "renderer_preflight", return_value={"ready": True}), \
             patch.object(hand, "native_forward", side_effect=forward), \
             patch.object(hand, "fit_hand", side_effect=fake_fit), \
             patch.object(hand, "render_overlay", side_effect=lambda image, *args: image), \
             patch.object(hand.subprocess, "check_output", return_value=hand.COMMIT + "\n"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hand.run(args), 2)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["status"], "candidate_gate_failed")
        self.assertTrue(report["source_files_unchanged"])
        self.assertFalse(report["training_ready"])
        for segment, _, _ in hand.CASES:
            candidate = hand.read_native(output / segment / "candidate.npz")
            np.testing.assert_equal(candidate["right_hand_pose"], baseline["right_hand_pose"])
            np.testing.assert_equal(candidate["body_pose"][20], baseline["body_pose"][20])
            rejected = hand.read_native(output / segment / "right-optimizer-proposal.npz")
            self.assertNotEqual(rejected["right_hand_pose"][0, 0], 0)
            self.assertTrue((output / segment / "right-hand-compare.jpg").is_file())

        # A follow-up review reuses this completed run's saved parameters, never optimizes.
        review_args = types.SimpleNamespace(command="review", batch=batch, fits=fits, smplerx_root=root,
            output=self.root / "review-output", fit_run_sha256=hand.sha256(fits / "run.json"),
            previous_results=output, previous_report_sha256=hand.sha256(output / "report.json"))
        before_hashes = {str(path): hand.sha256(path) for path in output.rglob("*") if path.is_file()}
        with patch.object(hand, "verify_model_assets", return_value=model_path), \
             patch.object(hand, "SparseSMPLX", return_value=model), \
             patch.object(hand, "native_runtime", return_value=runtime), \
             patch.object(hand, "native_forward", side_effect=forward), \
             patch.object(hand, "fit_hand", side_effect=AssertionError("review must never fit")) as no_fit, \
             patch.object(hand, "render_overlay", side_effect=lambda image, *args, **kwargs: image), \
             patch.object(hand.subprocess, "check_output", return_value=hand.COMMIT + "\n"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hand.review_saved(review_args), 0)
        no_fit.assert_not_called()
        for path, digest in before_hashes.items():
            self.assertEqual(hand.sha256(path), digest)
        review = json.loads((review_args.output / "report.json").read_text())
        self.assertEqual(review["status"], "saved_parameters_rerendered_pending_review")
        self.assertFalse(review["new_optimizer_run"])
        self.assertEqual(review["source_pilot_status"], "candidate_gate_failed")
        self.assertFalse(review["training_ready"])
        for segment, _, sides in hand.CASES:
            for side in sides:
                self.assertTrue((review_args.output / segment / (side + "-hand-review.jpg")).is_file())
        bad_args = copy.copy(review_args)
        bad_args.output = self.root / "bad-review"
        bad_args.previous_report_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "Previous report"):
            hand.review_saved(bad_args)

        # Same audited inputs, but missing GLU: this must fail before CUDA load or fitting.
        args.output = self.root / "gpu-preflight-failure"
        with patch.object(hand, "verify_model_assets", return_value=model_path), \
             patch.object(hand, "checkpoint_head_inventory", return_value={"runtime_load_verified": False}), \
             patch.object(hand, "SparseSMPLX", return_value=model), \
             patch.object(hand, "native_runtime", return_value=runtime) as native, \
             patch.object(hand, "native_forward", side_effect=forward), \
             patch.object(hand, "fit_hand", side_effect=fake_fit) as fitting, \
             patch.object(hand, "renderer_preflight", side_effect=ImportError('Library "GLU" not found.')), \
             patch.object(hand, "render_overlay", side_effect=lambda image, *args: image), \
             patch.object(hand.subprocess, "check_output", return_value=hand.COMMIT + "\n"), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ImportError, "GLU"):
                hand.run(args)
        native.assert_not_called()
        fitting.assert_not_called()
        failed = json.loads((args.output / "report.json").read_text())
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_stage"], "render_preflight")
        self.assertEqual(failed["error_type"], "ImportError")
        self.assertIn("Traceback", failed["traceback"])
        self.assertIn("GLU", failed["traceback"])
        self.assertEqual(failed["cases"], [])
        self.assertFalse(failed["training_ready"])


if __name__ == "__main__":
    unittest.main()
