"""Math/invariant tests; pose correspondence is not sign-language acceptance."""

import copy
import importlib.util
import unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "align", ROOT / "src/tools/sign-mano-align.py"
)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
spec = importlib.util.spec_from_file_location(
    "fixtures", ROOT / "tests/sign-hand-refine.test.py"
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class MANOAlignTests(unittest.TestCase):
    def test_left_pose_uses_matrix_conjugation_not_simple_axis_angle_negation(self):
        rotation = Rotation.from_rotvec([0.4, -0.2, 0.7]).as_matrix()[None]
        right = align.image_side_rotations(rotation, "right")
        left = align.image_side_rotations(rotation, "left")
        mirror = np.diag([-1.0, 1.0, 1.0])
        np.testing.assert_allclose(right, rotation)
        np.testing.assert_allclose(left, mirror @ rotation @ mirror)
        np.testing.assert_allclose(
            left @ left.transpose(0, 2, 1), np.eye(3)[None], atol=1e-12
        )
        with self.assertRaises(ValueError):
            align.image_side_rotations(np.zeros((15, 3)), "left")

    def test_finger_mean_subtracted_once_wrist_relative_to_original_parent(self):
        model, _ = fixtures.synthetic_model()
        source = fixtures.parameters()
        model.parents[20] = 18
        model.parents[18] = 16
        source["global_orient"][0] = [0.3, -0.1, 0.05]
        source["body_pose"][17] = [0.1, 0.2, -0.1]
        model.mean[25:40] = 0.08
        fingers = Rotation.from_rotvec(np.tile([0.2, 0.1, 0.3], (15, 1))).as_matrix()
        wrist = Rotation.from_rotvec([0.8, -0.3, 0.1]).as_matrix()[None]
        target = align.map_pose(model, source, "left", fingers, wrist)
        effective = Rotation.from_rotvec(
            target["left_hand_pose"] + model.mean[25:40]
        ).as_matrix()
        np.testing.assert_allclose(
            effective, align.image_side_rotations(fingers, "left"), atol=1e-12
        )
        rotations = align.global_rotations(model, target)
        np.testing.assert_allclose(
            rotations[20], align.image_side_rotations(wrist, "left")[0], atol=1e-12
        )
        fixtures.hand.preserved(source, target, ("left",))
        np.testing.assert_array_equal(source["body_pose"][17], target["body_pose"][17])

    def test_invalid_or_improper_rotations_are_rejected_before_pose_mapping(self):
        for value in (
            np.full((15, 3, 3), np.nan),
            np.zeros((15, 3, 3)),
            np.repeat(np.diag([-1.0, 1.0, 1.0])[None], 15, axis=0),
        ):
            with self.assertRaises(ValueError):
                align.image_side_rotations(value, "right")
        with self.assertRaises(ValueError):
            align.image_side_rotations(np.eye(3)[None], "unknown")

    def test_elbow_fit_keeps_fingers_global_wrist_and_other_side_frozen(self):
        model, _ = fixtures.synthetic_model()
        model.parents[20] = 18
        model.parents[18] = 16
        model.rest_joints[18] = [0.16, -0.15, 0]
        source = fixtures.parameters()
        fingers = Rotation.from_rotvec(np.tile([0.0, 0.0, 0.4], (15, 1))).as_matrix()
        wrist = np.eye(3)[None]
        mapped = align.map_pose(model, source, "left", fingers, wrist)
        wanted = copy.deepcopy(source)
        wanted["body_pose"][17, 2] = 0.12
        wanted = align.map_pose(model, wanted, "left", fingers, wrist)
        camera = {
            "focal": np.asarray([1000.0, 1000.0]),
            "princpt": np.asarray([320.0, 240.0]),
        }
        points = fixtures.hand.project(model.hand(wanted, "left"), camera)
        fitted, metrics = align.fit_alignment(
            model, source, "left", fingers, wrist, points, camera
        )
        self.assertLess(
            metrics["wrist_error_after_pixels"], metrics["wrist_error_before_pixels"]
        )
        self.assertLessEqual(metrics["elbow_change_degrees"], 15.00001)
        np.testing.assert_allclose(fitted["left_hand_pose"], mapped["left_hand_pose"])
        np.testing.assert_allclose(
            align.global_rotations(model, fitted)[20], np.eye(3), atol=1e-6
        )
        fixtures.hand.preserved(source, fitted, ("left",), allow_elbow=True)

    def test_window_prior_cases_require_exact_frame_scope_and_unique_side(self):
        def report():
            return {
                "cases": [
                    {
                        "segment_id": segment,
                        "frame_1based": n,
                        "output_relative": segment + "/%06d" % n,
                        "required_sides": list(sides),
                        "hands": [
                            {"side": side, "parameters_file": side + "-00.npz"}
                            for side in sides
                        ],
                    }
                    for segment, n, sides in align.wilor.short_window_cases()
                ]
            }

        value = report()
        index = align.prior_case_index(value, short_window=True)
        self.assertEqual(len(index), 14)
        for mutation in (
            "missing",
            "duplicate",
            "wrong_path",
            "wrong_sides",
            "ambiguous",
        ):
            value = report()
            if mutation == "missing":
                value["cases"].pop()
            elif mutation == "duplicate":
                value["cases"].append(value["cases"][0])
            elif mutation == "wrong_path":
                value["cases"][0]["output_relative"] += "/../000089"
            elif mutation == "wrong_sides":
                value["cases"][0]["required_sides"] = ["right"]
            else:
                value["cases"][0]["hands"].append(value["cases"][0]["hands"][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                align.prior_case_index(value, short_window=True)

    def test_series_preserves_baseline_fallback_timestamps_and_mask(self):
        records = []
        for frame in (88, 89, 90):
            source = fixtures.parameters()
            candidate = copy.deepcopy(source)
            if frame != 89:
                candidate["left_hand_pose"][0, 0] = 0.1
            records.append(
                {
                    "frame_1based": frame,
                    "fps": 25.0,
                    "sides": ("left", "right"),
                    "baseline": source,
                    "candidate": candidate,
                    "decisions": {"left": frame != 89, "right": False},
                }
            )
        packed = align.pack_series(records)
        self.assertEqual(packed["candidate_body_pose"].shape, (3, 21, 3))
        np.testing.assert_array_equal(packed["frame_ids"], [88, 89, 90])
        np.testing.assert_allclose(packed["timestamps_seconds"], [3.48, 3.52, 3.56])
        np.testing.assert_array_equal(
            packed["candidate_applied_mask"],
            [[True, False], [False, False], [True, False]],
        )
        np.testing.assert_array_equal(
            packed["candidate_left_hand_pose"][1],
            records[1]["baseline"]["left_hand_pose"],
        )
        records[1]["frame_1based"] = 95
        with self.assertRaisesRegex(ValueError, "contiguous"):
            align.pack_series(records)

    def test_series_rejects_unreported_changes_and_protected_params(self):
        source = fixtures.parameters()
        row = {
            "frame_1based": 88,
            "fps": 25.0,
            "sides": ("right",),
            "baseline": source,
            "candidate": copy.deepcopy(source),
            "decisions": {"right": False},
        }
        row["candidate"]["right_hand_pose"][0, 0] = 0.1
        with self.assertRaisesRegex(ValueError, "Rejected hand"):
            align.pack_series([row])
        row["decisions"]["right"] = True
        row["candidate"]["global_orient"][0, 0] = 0.1
        with self.assertRaisesRegex(ValueError, "Protected"):
            align.pack_series([row])

    def test_series_rejects_approval_for_an_unobserved_side(self):
        source = fixtures.parameters()
        row = {
            "frame_1based": 156,
            "fps": 25.0,
            "sides": ("right",),
            "baseline": source,
            "candidate": copy.deepcopy(source),
            "decisions": {"left": True, "right": False},
        }
        with self.assertRaisesRegex(ValueError, "selection mask"):
            align.pack_series([row])

    def test_fingertip_contact_distance_is_diagnostic_not_approval(self):
        import types

        points = {"left": np.zeros((21, 3)), "right": np.zeros((21, 3))}
        points["left"][:, 2] = 2
        points["right"][:, 2] = 2
        points["right"][:, 0] = 0.02
        camera = {
            "focal": np.array([1000.0, 1000.0]),
            "princpt": np.array([320.0, 240.0]),
        }
        model = types.SimpleNamespace(hand=lambda params, side: points[side])
        result = align.fingertip_contact_diagnostic(model, {}, camera)
        self.assertAlmostEqual(result["minimum_index_middle_tip_distance_metres"], 0.02)
        self.assertAlmostEqual(result["minimum_index_middle_tip_distance_pixels"], 10.0)
        self.assertFalse(result["contact_approved"])
        self.assertFalse(result["surface_collision_evaluated"])
        points["right"][:] = points["left"]
        result = align.fingertip_contact_diagnostic(model, {}, camera)
        self.assertEqual(result["minimum_index_middle_tip_distance_metres"], 0.0)
        self.assertFalse(result["contact_approved"])


if __name__ == "__main__":
    unittest.main()
