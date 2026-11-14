"""Synthetic tests for read-only hand correspondence/temporal auditing."""

import importlib.util
import json
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-temporal-audit.py"
spec = importlib.util.spec_from_file_location("temporal_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class TemporalAuditTests(unittest.TestCase):
    def test_pair_sequence_counts_changes_without_inventing_single_hand_pairs(self):
        rows = [
            {"frame_1based": 1, "mediapipe": ["middle", "index"],
             "wilor": ["middle", "index"], "smplx_3d": ["middle", "middle"]},
            {"frame_1based": 2, "mediapipe": ["middle", "middle"],
             "wilor": ["middle", "index"], "smplx_3d": ["middle", "middle"]},
            {"frame_1based": 3, "mediapipe": None, "wilor": None, "smplx_3d": None},
        ]
        result = audit.summarize_pair_sequence(rows, expected_frames=[1, 2, 3], required_sides=("left", "right"))
        self.assertEqual(result["pair_changes"]["mediapipe"], [2])
        self.assertEqual(result["pair_changes"]["wilor"], [])
        self.assertEqual(result["missing_pairs"]["mediapipe"], [3])
        self.assertEqual(result["not_applicable"], [])

        single = audit.summarize_pair_sequence(
            [{"frame_1based": 1, "mediapipe": None, "wilor": None, "smplx_3d": None}],
            expected_frames=[1], required_sides=("right",))
        self.assertEqual(single["not_applicable"], [1])
        self.assertEqual(single["pair_changes"]["wilor"], [])

    def test_transition_summary_flags_only_existing_wilor_thresholds(self):
        rows = [
            {"frame_1based": 10, "hand_pose": np.tile(np.eye(3), (15, 1, 1)),
             "global_orient": np.eye(3), "wrist": np.array([0., 0.])},
            {"frame_1based": 11, "hand_pose": np.tile(np.eye(3), (15, 1, 1)),
             "global_orient": np.eye(3), "wrist": np.array([4., 3.])},
        ]
        result = audit.summarize_transitions(rows)
        self.assertEqual(result["transitions"][0]["wrist_step_pixels"], 5.)
        self.assertEqual(result["suspicious_frames"], [])
        rows[1]["wrist"] = np.array([45., 0.])
        result = audit.summarize_transitions(rows)
        self.assertEqual(result["suspicious_frames"], [11])
        self.assertFalse(result["training_ready"])

    def test_fusion_temporal_points_are_wrist_plus_five_fingertips(self):
        points = np.zeros((21, 3))
        points[19] = 999.
        selected = audit.temporal_points(points)
        self.assertEqual(selected.shape, (6, 3))
        self.assertFalse(np.any(selected == 999.))
        with self.assertRaises(ValueError):
            audit.temporal_points(np.zeros((20, 3)))

    def test_common_translation_is_retained_but_not_counted_as_local_hand_motion(self):
        points = np.arange(18, dtype=float).reshape(6, 3) * .01
        rows = [{"frame_1based": 1, "points": points, "translation": np.zeros(3)},
                {"frame_1based": 2, "points": points + [0., 0., 2.],
                 "translation": np.array([0., 0., 2.])}]
        result = audit.summarize_points(rows, "points", "m")
        self.assertAlmostEqual(result["transitions"][0]["max_point_step"], 2.)
        self.assertAlmostEqual(result["transitions"][0]["max_wrist_relative_step"], 0.)
        self.assertAlmostEqual(result["transitions"][0]["max_translation_removed_step"], 0.)
        self.assertAlmostEqual(result["transitions"][0]["translation_step"], 2.)

    def test_no_continuity_or_pair_change_is_inferred_across_a_missing_frame(self):
        points = np.zeros((6, 3))
        result = audit.summarize_points([
            {"frame_1based": 1, "points": points},
            {"frame_1based": 3, "points": points + 1}], "points", "px", expected_frames=[1, 2, 3])
        self.assertEqual(result["transitions"], [])
        self.assertFalse(result["continuity_complete"])
        pairs = audit.summarize_pair_sequence([
            {"frame_1based": 1, "mediapipe": ["index", "index"]},
            {"frame_1based": 3, "mediapipe": ["middle", "middle"]}],
            expected_frames=[1, 3], required_sides=("left", "right"))
        self.assertEqual(pairs["pair_changes"]["mediapipe"], [])

    def test_wrist_relative_coordinates_do_not_subtract_root_translation_twice(self):
        points = np.arange(18, dtype=float).reshape(6, 3) * .01
        points -= points[:1]
        rows = [{"frame_1based": 1, "wrist_relative_points": points,
                 "translation": np.zeros(3)},
                {"frame_1based": 2, "wrist_relative_points": points.copy(),
                 "translation": np.array([0., 0., 2.])}]
        result = audit.summarize_points(rows, "wrist_relative_points", "m")
        self.assertAlmostEqual(result["transitions"][0]["max_point_step"], 0.)
        self.assertNotIn("max_translation_removed_step", result["transitions"][0])
        self.assertEqual(result["coordinate_space"], "wrist_relative")

    def test_single_hand_is_not_a_missing_two_hand_pair(self):
        points = np.zeros((5, 2))
        result = audit.pair_observation(None, points, "px", required_sides=("right",))
        self.assertEqual(result["status"], "not_applicable_single_hand")
        with self.assertRaises(ValueError):
            audit.pair_observation(np.zeros(5), points, "px")

    def test_pair_sequence_rejects_duplicate_unordered_or_wrong_frame_identity(self):
        for ids, expected in (([1, 1], [1, 2]), ([2, 1], [1, 2]), ([1], [1, 2])):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                audit.summarize_pair_sequence([{"frame_1based": i} for i in ids], expected,
                                              ("left", "right"))

    def test_report_contract_cannot_promote_sequence(self):
        report = audit.report_contract({"pilot": {"pair_changes": {}}})
        self.assertEqual(report["status"], "audited_pending_visual_review")
        self.assertFalse(report["training_ready"])
        self.assertFalse(report["contact_approved"])


class TemporalAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures = audit.load_tool("contact_synthetic_fixture", SCRIPT.parents[2] / "tests/sign-contact-audit.test.py")
        self.fixture = fixtures.ContactAuditIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.args = SimpleNamespace(**{k: v for k, v in vars(f.args).items()
                                     if k not in ("contact_results", "contact_report_sha256", "wilor_root")})
        for segment, (frame_ids, sides) in audit.SEGMENTS.items():
            count = 166 if segment == "pilot-greeting-hello-001" else 218
            sample = f.batch / "samples" / segment
            (sample / "images").mkdir(parents=True, exist_ok=True)
            frame_rows = []
            for frame in range(1, count + 1):
                rel = "samples/" + segment + "/images/%06d.jpg" % frame
                path = f.batch / rel
                if frame in frame_ids:
                    Image.new("RGB", (384, 288), "white").save(path)
                frame_rows.append({"frame_id": frame, "image": rel, "clip_seconds": (frame - 1) / 25.,
                                   "sha256": audit.digest(path) if path.exists() else "0" * 64})
            (sample / "frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in frame_rows))
            if segment == "pilot-hospital-cough-003":
                tracks = {"timestamps_seconds": np.arange(count) / 25.}
                for side in ("left", "right"):
                    tracks[side + "_hand_image"] = np.full((count, 21, 3), .5 if side in sides else np.nan)
                    tracks[side + "_hand_image_detected"] = np.full(count, side in sides, dtype=bool)
                np.savez_compressed(sample / "observations.npz", **tracks)
                with (f.batch / "tasks.jsonl").open("a") as stream:
                    stream.write(json.dumps({"segment_id": segment, "frames": count, "fps": 25.,
                                             "mirror_status": "unknown", "model_training_ready": False,
                                             "frame_manifest": "samples/" + segment + "/frames.jsonl"}) + "\n")
            for frame in frame_ids:
                wi = f.window / segment / ("%06d" % frame)
                fu = f.fusion / segment / ("%06d" % frame)
                wi.mkdir(parents=True, exist_ok=True)
                fu.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(fu / "candidate.npz", **f.params)
                np.savez_compressed(fu / "baseline.npz", **f.params)
                for side in sides:
                    path = wi / (side + "-00.npz")
                    if path.exists():
                        with np.load(path, allow_pickle=False) as a:
                            values = {k: a[k].copy() for k in a.files}
                    else:
                        xyz = f.model.hand(f.params, side)
                        vertices = np.zeros((778, 3))
                        vertices[[744, 320, 443, 554, 671]] = xyz[list(audit.FINGERTIP_IDS)]
                        values = dict(joints=xyz, image_joints=xyz, vertices=vertices, image_vertices=vertices,
                                      projected_joints=xyz[:, :2] * 100 + [192, 144],
                                      right=np.asarray(side == "right"), image_size=np.array([384, 288]))
                    values.update(hand_pose=np.tile(np.eye(3), (15, 1, 1)), global_orient=np.eye(3)[None],
                                  betas=np.zeros(10), camera_translation=np.array([0., 0., 3.]))
                    np.savez_compressed(path, **values)
        f.refresh_manifest(f.batch)
        self.refresh_reports()

    def refresh_reports(self):
        f = self.fixture
        report = json.loads((f.window / "report.json").read_text())
        sources = report["source_sha256"]
        for path in f.batch.rglob("*"):
            if path.is_file():
                sources["/remote/batch/" + str(path.relative_to(f.batch))] = audit.digest(path)
        for case in report["cases"]:
            if case["segment_id"] == "pilot-hospital-cough-003":
                case["hands"] = [{"side": "right", "parameters_file": "right-00.npz"}]
        f.write_json(f.window / "report.json", report)
        f.refresh_manifest(f.window.parent)
        self.args.wilor_report_sha256 = audit.digest(f.window / "report.json")
        fusion = json.loads((f.fusion / "report.json").read_text())
        fusion.update(source_sha256=sources, wilor_report_sha256=self.args.wilor_report_sha256)
        f.write_json(f.fusion / "report.json", fusion)
        f.refresh_manifest(f.fusion.parent)
        self.args.fusion_report_sha256 = audit.digest(f.fusion / "report.json")

    def run_audit(self):
        f = self.fixture
        with patch.object(f.helper, "MODEL_SHA256", f.model_sha), \
             patch.object(f.helper, "SparseSMPLX", return_value=f.model), \
             patch.object(audit, "load_hand_tools", return_value=f.helper):
            return audit.audit(self.args)

    def test_full_report_and_media_complete_without_licensed_models_or_modified_inputs(self):
        f = self.fixture
        before = {p: audit.digest(p) for root in (f.batch, f.window.parent, f.fusion.parent)
                  for p in root.rglob("*") if p.is_file()}
        path = self.run_audit()
        r = json.loads(path.read_text())
        self.assertFalse(r["training_ready"])
        greeting = r["windows"]["pilot-greeting-hello-001"]
        self.assertEqual(greeting["missing"]["mediapipe"]["right"], [90])
        self.assertFalse(greeting["temporal"]["mediapipe"]["right"]["continuity_complete"])
        self.assertEqual(r["windows"]["pilot-hospital-cough-003"]["pair_sequence"]["not_applicable"],
                         list(range(156, 163)))
        self.assertEqual({p: audit.digest(p) for p in before}, before)
        self.assertTrue((path.parent / "temporal-review-sheet.jpg").exists())
        self.assertTrue(all(row["protected_parameters_match_baseline"]
                            for window in r["windows"].values() for row in window["frame_rows"]))
        audit.verify_manifest(path.parent)

    def test_self_consistent_foreign_batch_and_numeric_detection_masks_are_rejected(self):
        f = self.fixture
        contract = f.batch / "contract.json"
        r = json.loads(contract.read_text())
        r["other_run"] = True
        f.write_json(contract, r)
        f.refresh_manifest(f.batch)
        with self.assertRaisesRegex(ValueError, "source digest"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())
        self.refresh_reports()
        obs = f.batch / "samples/pilot-greeting-hello-001/observations.npz"
        with np.load(obs, allow_pickle=False) as a:
            values = {k: a[k].copy() for k in a.files}
        values["right_hand_image_detected"] = values["right_hand_image_detected"].astype(np.int8)
        np.savez_compressed(obs, **values)
        f.refresh_manifest(f.batch)
        self.refresh_reports()
        with self.assertRaisesRegex(ValueError, "observation"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_duplicate_wilor_hand_is_rejected(self):
        f = self.fixture
        path = f.window / "report.json"
        r = json.loads(path.read_text())
        r["cases"][0]["hands"].append(dict(r["cases"][0]["hands"][0]))
        f.write_json(path, r)
        self.refresh_reports()
        with self.assertRaisesRegex(ValueError, "hand identity"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_changed_fusion_root_translation_cannot_be_blamed_on_baseline(self):
        f = self.fixture
        path = f.fusion / "pilot-greeting-hello-001/000088/candidate.npz"
        with np.load(path, allow_pickle=False) as a:
            values = {key: a[key].copy() for key in a.files}
        values["transl"][0, 2] += 1.
        np.savez_compressed(path, **values)
        f.refresh_manifest(f.fusion.parent)
        with self.assertRaisesRegex(ValueError, "Protected parameter modified: transl"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_missing_required_wilor_hand_fails_before_report_or_rendering(self):
        f = self.fixture
        path = f.window / "report.json"
        r = json.loads(path.read_text())
        r["cases"][0]["hands"] = []
        f.write_json(path, r)
        self.refresh_reports()
        with self.assertRaisesRegex(ValueError, "Missing required WiLoR hand"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_existing_output_and_nested_input_outputs_are_preserved(self):
        self.args.output.mkdir()
        marker = self.args.output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "separate"):
            self.run_audit()
        self.assertEqual(marker.read_text(), "keep")
        self.args.output = self.fixture.window.parent / "new-audit"
        with self.assertRaisesRegex(ValueError, "separate"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())


if __name__ == "__main__":
    unittest.main()
