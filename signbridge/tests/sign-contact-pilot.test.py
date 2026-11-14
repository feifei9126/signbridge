"""Bounded contact-hypothesis tests; pixel/point fit is never semantic approval."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "contact", ROOT / "src/tools/sign-contact-pilot.py"
)
contact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contact)
spec = importlib.util.spec_from_file_location(
    "fixture", ROOT / "tests/sign-hand-refine.test.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class ContactPilotTests(unittest.TestCase):
    def test_joint_elbow_update_keeps_fingers_world_wrists_camera_and_body_fixed(self):
        model, _ = fixture.synthetic_model()
        model.parents[20] = 18
        model.parents[21] = 19
        original = fixture.parameters()
        fusion = copy.deepcopy(original)
        fusion["body_pose"][17] = [0.02, 0.03, -0.04]
        fusion["body_pose"][18] = [-0.04, 0.02, 0.02]
        fusion["left_hand_pose"][:] = 0.12
        fusion["right_hand_pose"][:] = -0.08
        wrist_world = contact.align.global_rotations(model, fusion)[[20, 21]]
        update = contact.contact_parameters(
            model, original, fusion, np.array([0.4, 0.2, -0.1, -0.3, 0.1, 0.4])
        )
        fixture.hand.preserved(fusion, update, ("left", "right"), allow_elbow=True)
        for side in ("left", "right"):
            np.testing.assert_array_equal(
                update[side + "_hand_pose"], fusion[side + "_hand_pose"]
            )
            index = fixture.hand.ELBOWS[side] - 1
            angle = (
                Rotation.from_rotvec(update["body_pose"][index])
                * Rotation.from_rotvec(original["body_pose"][index]).inv()
            ).magnitude()
            self.assertLessEqual(angle, np.deg2rad(15) + 1e-7)
        np.testing.assert_allclose(
            contact.align.global_rotations(model, update)[[20, 21]],
            wrist_world,
            atol=1e-6,
        )

    def test_zero_change_reconstructs_previous_fusion(self):
        model, _ = fixture.synthetic_model()
        model.parents[20] = 18
        model.parents[21] = 19
        original = fixture.parameters()
        fusion = copy.deepcopy(original)
        fusion["body_pose"][17] = [0.02, 0.03, -0.04]
        fusion["body_pose"][18] = [-0.04, 0.02, 0.02]
        vector = contact.initial_elbow_vector(original, fusion)
        update = contact.contact_parameters(model, original, fusion, vector)
        for key in fusion:
            np.testing.assert_allclose(update[key], fusion[key], atol=1e-6)

    def test_optimization_keeps_small_elbow_perturbations_in_float64(self):
        model, _ = fixture.synthetic_model()
        model.parents[20] = 18
        model.parents[21] = 19
        original = fixture.parameters()
        fusion = copy.deepcopy(original)
        fusion["body_pose"][17] = [0.02, 0.03, -0.04]
        vector = contact.initial_elbow_vector(original, fusion)
        before = contact.contact_parameters(model, original, fusion, vector)
        vector[0] += 1e-8
        after = contact.contact_parameters(model, original, fusion, vector)
        self.assertEqual(after["body_pose"].dtype, np.float64)
        self.assertGreater(
            np.max(np.abs(after["body_pose"] - before["body_pose"])), 1e-9
        )

    def test_small_tip_gap_alone_does_not_accept_bad_projection_or_unknown_contact(
        self,
    ):
        base = {
            "gap_metres": 0.04,
            "hands": {
                s: {"absolute_rmse_pixels": 5.0, "wrist_error_pixels": 2.0}
                for s in ("left", "right")
            },
        }
        after = {
            "gap_metres": 0.005,
            "hands": {
                s: {"absolute_rmse_pixels": 25.0, "wrist_error_pixels": 10.0}
                for s in ("left", "right")
            },
        }
        result = contact.proposal_gate(base, after, optimizer_status=1)
        self.assertFalse(result["candidate_gate_passed"])
        self.assertFalse(result["contact_approved"])
        self.assertFalse(result["training_ready"])
        after["hands"] = base["hands"]
        result = contact.proposal_gate(base, after, optimizer_status=1)
        self.assertTrue(result["candidate_gate_passed"])
        self.assertFalse(result["contact_approved"])
        self.assertFalse(
            contact.proposal_gate(base, after, optimizer_status=0)[
                "candidate_gate_passed"
            ]
        )

    def test_rejected_fit_retains_exact_fusion_and_reports_raw_proposal(self):
        model, _ = fixture.synthetic_model()
        model.parents[20] = 18
        model.parents[21] = 19
        original = fixture.parameters()
        fusion = copy.deepcopy(original)
        camera = {
            "focal": np.array([1000.0, 1000.0]),
            "princpt": np.array([320.0, 240.0]),
        }
        targets = {
            s: fixture.hand.project(model.hand(fusion, s), camera)
            for s in ("left", "right")
        }
        selected, proposal, metrics = contact.fit_contact(
            model, original, fusion, targets, camera
        )
        self.assertFalse(metrics["candidate_gate_passed"])
        for key in fusion:
            np.testing.assert_array_equal(selected[key], fusion[key])
        self.assertFalse(metrics["training_ready"])
        self.assertIn("after_proposal", metrics)

    def test_small_feasible_elbow_motion_can_reduce_contact_gap_in_fixture(self):
        model, _ = fixture.synthetic_model()
        model.parents[20] = 18
        model.parents[21] = 19
        # Independent hands with spatially separated elbows, nearly touching middle tips.
        model.rest_joints[18] = [0.07, -0.10, 0.0]
        model.rest_joints[19] = [-0.07, -0.10, 0.0]
        model.rest_joints[20] = [0.02, 0.0, 0.0]
        model.rest_joints[21] = [-0.02, 0.0, 0.0]
        for side in ("left", "right"):
            wrist = model.rest_joints[contact.hand.WRISTS[side]]
            sign = 1 if side == "left" else -1
            for finger, chain in enumerate(contact.hand.JOINTS[side]):
                for depth, index in enumerate(chain):
                    model.rest_joints[index] = wrist + [
                        sign * 0.01 * (finger - 2),
                        0.02 * (depth + 1),
                        0,
                    ]
                model.tip_template[finger + (0 if side == "left" else 5)] = (
                    model.rest_joints[chain[-1]] + [0, 0.02, 0]
                )
        source = fixture.parameters()
        camera = {
            "focal": np.array([600.0, 600.0]),
            "princpt": np.array([320.0, 240.0]),
        }
        targets = {
            s: fixture.hand.project(model.hand(source, s), camera)
            for s in ("left", "right")
        }
        selected, proposed, metrics = contact.fit_contact(
            model, source, source, targets, camera
        )
        self.assertGreater(
            metrics["before"]["gap_metres"], metrics["after_proposal"]["gap_metres"]
        )
        self.assertGreater(metrics["optimizer_status"], 0)
        for side in ("left", "right"):
            np.testing.assert_array_equal(
                proposed[side + "_hand_pose"], source[side + "_hand_pose"]
            )

    def test_prior_evidence_requires_matching_report_and_each_internal_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            report = results / "report.json"
            report.write_text(json.dumps({"training_ready": False}))
            data = results / "pose.npz"
            data.write_bytes(b"known evidence")
            manifest = root / "SHA256SUMS"
            manifest.write_text(
                contact.hand.sha256(report)
                + "  results/report.json\n"
                + contact.hand.sha256(data)
                + "  results/pose.npz\n"
            )
            value, _ = contact.verified_evidence(results, contact.hand.sha256(report))
            self.assertFalse(value["training_ready"])
            data.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Evidence file changed"):
                contact.verified_evidence(results, contact.hand.sha256(report))
            with self.assertRaisesRegex(ValueError, "report SHA-256"):
                contact.verified_evidence(results, "0" * 64)

    def test_invalid_elbow_vectors_are_rejected_before_model_update(self):
        model, _ = fixture.synthetic_model()
        p = fixture.parameters()
        for vector in (np.zeros(3), np.full(6, np.nan)):
            with self.assertRaises(ValueError):
                contact.contact_parameters(model, p, p, vector)


if __name__ == "__main__":
    unittest.main()
