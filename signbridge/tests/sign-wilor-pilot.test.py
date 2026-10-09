"""Offline contracts for a bounded WiLoR inference-only pilot."""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
