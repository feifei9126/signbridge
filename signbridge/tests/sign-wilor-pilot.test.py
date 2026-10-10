"""Offline contracts for a bounded WiLoR inference-only pilot."""

import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-wilor-pilot.py"
spec = importlib.util.spec_from_file_location("wilor_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class WiLoRPilotTests(unittest.TestCase):
    def plan_fixture(self, path, cases):
        value = {'schema': 'signbridge-wilor-explicit-cases-v1', 'batch_tasks_sha256': 'a' * 64,
                 'training_ready': False, 'cases': cases}
        path.write_text(json.dumps(value))
        return pilot.sha256(path)

    def test_explicit_case_plan_is_digest_bound_and_does_not_expand_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            sha = self.plan_fixture(path, [{'segment_id': 'pilot-greeting-lunch-006',
                'frame_1based': 57, 'sides': ['left', 'right']}])
            self.assertEqual(pilot.read_case_plan(path, sha, 'a' * 64),
                             [('pilot-greeting-lunch-006', 57, ('left', 'right'))])
            with self.assertRaises(ValueError):pilot.read_case_plan(path, '0' * 64, 'a' * 64)
            with self.assertRaises(ValueError):pilot.read_case_plan(path, sha, 'b' * 64)

    def test_case_plan_duplicate_invalid_frames_or_sides_are_rejected(self):
        good = {'segment_id': 'pilot-greeting-lunch-006', 'frame_1based': 57, 'sides': ['right']}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            for cases in ([], [good, good], [{**good, 'segment_id': '../escape'}],
                          [{**good, 'frame_1based': 0}], [{**good, 'frame_1based': True}],
                          [{**good, 'sides': []}], [{**good, 'sides': ['right', 'right']}],
                          [{**good, 'sides': ['unknown']}], [good] * 31):
                sha = self.plan_fixture(path, cases)
                with self.subTest(cases=cases), self.assertRaises(ValueError):
                    pilot.read_case_plan(path, sha, 'a' * 64)

    def test_perspective_projection_matches_camera_not_normalized_crop(self):
        points = np.asarray([[1., -2., 5.], [0., 0., 3.]])
        xy = pilot.project_full(points, focal=1000., width=1280, height=720)
        np.testing.assert_allclose(xy, [[840, -40], [640, 360]])
        for bad in ([[0., 0., -1.]], [[np.nan, 0., 1.]], [[0., 0., 0.]]):
            with self.assertRaises(ValueError):
                pilot.project_full(np.asarray(bad), focal=1000., width=1280, height=720)

    def test_left_reflection_reverses_faces_without_touching_right_mesh(self):
        v = np.asarray([[1., 2., 3.], [2., 3., 4.], [4., 5., 6.]])
        j = v.copy()
        f = np.asarray([[0, 1, 2]])
        left, joints, faces = pilot.to_image_handedness(v, j, f, is_right=False)
        np.testing.assert_array_equal(left[:, 0], -v[:, 0])
        np.testing.assert_array_equal(joints[:, 0], -j[:, 0])
        np.testing.assert_array_equal(faces, [[0, 2, 1]])
        right, _, right_faces = pilot.to_image_handedness(v, j, f, is_right=True)
        np.testing.assert_array_equal(right, v)
        np.testing.assert_array_equal(right_faces, f)
        np.testing.assert_array_equal(v[0], [1, 2, 3])

    def test_asset_hash_mismatch_rejected_before_loading_torch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weight.pt"
            path.write_bytes(b"test")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                pilot.check_asset(path, expected_bytes=4, expected_sha="0" * 64)
            self.assertEqual(pilot.check_asset(path, 4, pilot.sha256(path)), pilot.sha256(path))

    def test_native_outputs_require_rotation_matrices_and_finite_real_mesh(self):
        shapes = {"vertices": (778, 3), "joints": (21, 3), "global_orient": (1, 3, 3),
                  "hand_pose": (15, 3, 3), "betas": (10,), "camera_translation": (3,)}
        arrays = {key: np.zeros(shape, dtype=np.float32) for key, shape in shapes.items()}
        arrays["global_orient"][:] = np.eye(3)
        arrays["hand_pose"][:] = np.eye(3)
        pilot.check_outputs(arrays)
        bad = {**arrays, "hand_pose": np.zeros((15, 3), dtype=np.float32)}
        with self.assertRaises(ValueError):
            pilot.check_outputs(bad)
        bad = {**arrays, "vertices": arrays["vertices"].copy()}
        bad["vertices"][0, 0] = np.nan
        with self.assertRaises(ValueError):
            pilot.check_outputs(bad)
        bad = {**arrays, "hand_pose": np.zeros((15, 3, 3), dtype=np.float32)}
        with self.assertRaisesRegex(ValueError, "rotation"):
            pilot.check_outputs(bad)

    def test_handedness_rejects_invalid_detector_classes_and_nonfinite_input(self):
        vertices = np.ones((778, 3))
        joints = np.ones((21, 3))
        faces = np.asarray([[0, 1, 2]])
        with self.assertRaises(ValueError):
            pilot.to_image_handedness(vertices, joints, faces, is_right=3)
        vertices[0, 0] = np.nan
        with self.assertRaises(ValueError):
            pilot.to_image_handedness(vertices, joints, faces, is_right=True)

    def test_checkpoint_binding_rejects_changed_native_python_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "wilor/models/mano_wrapper.py"
            path.parent.mkdir(parents=True)
            path.write_text("original source\n")
            expected = {"wilor/models/mano_wrapper.py": pilot.sha256(path)}
            with patch.object(pilot, "SOURCE_DIGESTS", expected):
                pilot.check_source(root)
                path.write_text("modified source\n")
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    pilot.check_source(root)

    def test_render_mask_must_fit_analytical_vertex_projection(self):
        original = np.zeros((100, 100, 3), dtype=np.uint8)
        result = original.copy()
        result[45:56, 45:56] = 200
        vertices = np.array([[-.1, -.1, 2.], [.1, -.1, 2.], [.1, .1, 2.]])
        metrics = pilot.check_render_projection(original, result, vertices, focal=100)
        self.assertTrue(metrics["render_projection_bbox_passed"])
        self.assertEqual(metrics["rendered_pixels"], 121)
        result[45:56, :30] = 200  # Old BLAS bug stretched the mesh to x=0.
        with self.assertRaisesRegex(ValueError, "projection"):
            pilot.check_render_projection(original, result, vertices, focal=100)
        with self.assertRaises(ValueError):
            pilot.check_render_projection(original, original.copy(), vertices, focal=100)

    def test_short_window_scope_is_14_frames_and_21_target_hand_observations(self):
        cases = pilot.short_window_cases()
        self.assertEqual(len(cases), 14)
        self.assertEqual([c[1] for c in cases[:7]], list(range(88, 95)))
        self.assertEqual([c[1] for c in cases[7:]], list(range(156, 163)))
        self.assertEqual(sum(len(c[2]) for c in cases), 21)

    def test_temporal_missing_hand_and_duplicates_are_not_filled(self):
        identity = np.repeat(np.eye(3)[None], 15, axis=0)
        def item(frame, count=1):
            return {"frame_1based": frame, "hands": [
                {"side": "right", "hand_pose": identity.copy(), "global_orient": np.eye(3)[None],
                 "projected_joints": np.zeros((21, 2))} for _ in range(count)]}
        summary = pilot.temporal_summary([item(1), item(2, 0), item(3), item(4, 2)], ("right",))
        self.assertEqual(summary["right"]["missing_frames"], [2])
        self.assertEqual(summary["right"]["ambiguous_frames"], [4])
        self.assertEqual(summary["right"]["transitions"], [])
        self.assertFalse(summary["right"]["continuity_complete"])

    def test_temporal_rotation_angle_is_geodesic_and_jumps_are_reported(self):
        from scipy.spatial.transform import Rotation
        base = np.repeat(np.eye(3)[None], 15, axis=0)
        changed = base.copy()
        changed[3] = Rotation.from_euler("z", 60, degrees=True).as_matrix()
        rows = [{"frame_1based": n, "hands": [{"side": "right", "hand_pose": pose,
                 "global_orient": np.eye(3)[None], "projected_joints": np.zeros((21, 2))}]}
                for n, pose in [(1, base), (2, changed)]]
        summary = pilot.temporal_summary(rows, ("right",))["right"]
        self.assertAlmostEqual(summary["transitions"][0]["max_finger_degrees"], 60)
        self.assertEqual(summary["suspicious_transitions"], [2])
        self.assertTrue(summary["continuity_complete"])

    def test_render_bounds_accepts_noncentral_anisotropic_camera_projection(self):
        image = np.zeros((100, 120, 3), dtype=np.uint8)
        result = image.copy()
        result[39:62, 69:92] = 200
        camera_points = np.asarray([[70., 40.], [90., 60.], [70., 60.]])
        report = pilot.check_render_bounds(image, result, camera_points)
        self.assertTrue(report["render_projection_bbox_passed"])
        result[:, :10] = 200
        with self.assertRaisesRegex(ValueError, "projection"):
            pilot.check_render_bounds(image, result, camera_points)


if __name__ == "__main__":
    unittest.main()
