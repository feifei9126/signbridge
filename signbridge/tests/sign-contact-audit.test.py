"""Observation audit tests; fingertip proximity never labels true contact."""

import importlib.util
import json
import io
import contextlib
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-contact-audit.py"
spec = importlib.util.spec_from_file_location("contact_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ContactObservationAuditTests(unittest.TestCase):

    def test_fingertip_indices_reject_fractional_or_coerced_values(self):
        for pair in ([8.9, 12], ["8", 12], [True, 12]):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                audit.openpose_pair_labels(pair)

    def test_hand_scale_uses_chain_lengths_and_is_translation_invariant(self):
        points = np.zeros((21, 3))
        for finger in range(5):
            for depth in range(4):
                points[1 + 4 * finger + depth] = [finger * .01, (depth + 1) * .02, 0.]
        value = audit.hand_geometry_metrics(points, "m")
        moved = audit.hand_geometry_metrics(points + [1., 2., 3.], "m")
        np.testing.assert_allclose(list(value["finger_chain_lengths"].values()), list(moved["finger_chain_lengths"].values()))
        self.assertAlmostEqual(value["finger_chain_lengths"]["thumb"], .08)

    def test_pairwise_distance_matrix_keeps_all_five_fingers_and_units(self):
        left = np.asarray([[float(i), 0.] for i in range(5)])
        right = np.asarray([[10., float(i)] for i in range(5)])
        result = audit.pairwise_observation(left, right, unit="px")
        self.assertEqual(result["unit"], "px")
        self.assertEqual(result["distance_matrix"], np.linalg.norm(
            left[:, None, :] - right[None, :, :], axis=-1).tolist())
        self.assertEqual(result["left_finger_order"], list(audit.FINGERS))
        self.assertEqual(result["right_finger_order"], list(audit.FINGERS))

    def test_openpose_tip_indices_map_to_named_fingers_without_guessing(self):
        self.assertEqual(audit.openpose_pair_labels([8, 12]), ["index", "middle"])
        with self.assertRaises(ValueError):
            audit.openpose_pair_labels([7, 12])

    def test_nearest_pair_disagreement_is_reported_not_resolved(self):
        values = audit.compare_pair_labels({
            "mediapipe": ["middle", "middle"],
            "wilor": ["middle", "index"],
            "smplx_3d": ["middle", "middle"],
        })
        self.assertTrue(values["pair_disagreements"]["mediapipe_vs_wilor_disagree"])
        self.assertFalse(values["pair_disagreements"]["mediapipe_vs_smplx_3d_disagree"])
        self.assertFalse(values["contact_inferred"])

    def test_pairwise_minimum_returns_anatomical_pair_not_assumed_fixed_middle(self):
        left = np.asarray([[0., 0.], [2., 0.]])
        right = np.asarray([[10., 0.], [1., 0.]])
        values = audit.pairwise_minimum(left, right, labels=("index", "middle"))
        self.assertEqual(values["left_finger"], "index")
        self.assertEqual(values["right_finger"], "middle")
        self.assertEqual(values["distance"], 1.)

    def test_missing_or_invalid_observations_are_explicit_not_interpolated(self):
        result = audit.observation_pair(None, np.zeros((5, 2)))
        self.assertEqual(result["status"], "missing_left_hand_observation")
        with self.assertRaises(ValueError):
            audit.pairwise_minimum(np.zeros((4, 2)), np.zeros((5, 2)))
        with self.assertRaises(ValueError):
            audit.pairwise_minimum(np.full((5, 2), np.nan), np.zeros((5, 2)))

    def test_missing_and_degenerate_geometry_have_no_invented_scale(self):
        self.assertEqual(audit.hand_geometry_metrics(None, "m")["status"], "missing_hand_observation")
        result = audit.hand_geometry_metrics(np.zeros((21, 3)), "m")
        self.assertEqual(result["status"], "degenerate_palm_scale")
        self.assertTrue(all(value is None for value in result["finger_chain_over_palm"].values()))
        with self.assertRaises(ValueError):
            audit.hand_geometry_metrics(np.zeros((20, 3)), "m")
        with self.assertRaises(ValueError):
            audit.pairwise_distance_matrix(np.zeros((5, 4)), np.zeros((5, 4)))
        with self.assertRaises(ValueError):
            audit.openpose_pair_labels([8])
        value = audit.compare_pair_labels({"mediapipe": None, "wilor": ["middle", "index"]})
        self.assertIsNone(value["pair_disagreements"]["mediapipe_vs_wilor_disagree"])

    def test_report_cannot_promote_contact_or_training(self):
        value = audit.report_contract([{"frame": 88, "mediapipe": {"status": "ok"}}])
        self.assertFalse(value["contact_ground_truth"])
        self.assertFalse(value["contact_approved"])
        self.assertFalse(value["training_ready"])
        self.assertIn("mirror_status_unknown", value["limitations"])


class ContactAuditIntegrationTests(unittest.TestCase):
    """Whole report path without licensed models, GPU access or private video files."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        spec = importlib.util.spec_from_file_location(
            "synthetic_hand_fixture", SCRIPT.parents[2] / "tests/sign-hand-refine.test.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        self.helper = audit.load_model_helper()
        self.model, _ = fixture.synthetic_model()
        self.params = fixture.parameters()
        self.batch = self.root / "batch"
        self.batch.mkdir()
        self.write_json(self.batch / "contract.json", {
            "schema": "signbridge-smplerx-input-v1", "model_training_ready": False})
        sample = self.batch / "samples" / audit.SEGMENT
        sample.mkdir(parents=True)
        task = {"segment_id": audit.SEGMENT, "frames": 166, "fps": 25.,
                "frame_manifest": "samples/" + audit.SEGMENT + "/frames.jsonl",
                "mirror_status": "unknown", "model_training_ready": False}
        (self.batch / "tasks.jsonl").write_text(json.dumps(task) + "\n")
        rows = []
        for frame in range(1, 167):
            relative = "samples/" + audit.SEGMENT + "/images/%06d.jpg" % frame
            image = self.batch / relative
            if frame in audit.FRAME_IDS:
                image.parent.mkdir(exist_ok=True)
                Image.new("RGB", (384, 288), "white").save(image)
            rows.append({"frame_id": frame, "image": relative,
                         "sha256": audit.digest(image) if image.exists() else "0" * 64,
                         "clip_seconds": (frame - 1) / 25.})
        (sample / "frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        tracks = {"timestamps_seconds": np.arange(166) / 25.}
        for side in ("left", "right"):
            tracks[side + "_hand_image"] = np.full((166, 21, 3), .5, dtype=np.float32)
            tracks[side + "_hand_image_detected"] = np.ones(166, dtype=bool)
        tracks["right_hand_image"][89] = np.nan
        tracks["right_hand_image_detected"][89] = False
        np.savez_compressed(sample / "observations.npz", **tracks)
        self.refresh_manifest(self.batch)
        self.model_root = self.root / "smplerx"
        model_file = self.model_root / self.helper.MODEL_FILE
        model_file.parent.mkdir(parents=True)
        model_file.write_bytes(b"synthetic-model-used-by-test-double")
        self.model_sha = audit.digest(model_file)
        self.wilor_root = self.root / "wilor-code"
        wrapper = self.wilor_root / "wilor/models/mano_wrapper.py"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("def mapping():\n    mano_to_openpose = " +
                           repr([0, 13, 14, 15, 16, 1, 2, 3, 17, 4, 5, 6, 18, 10, 11, 12, 19, 7, 8, 9, 20]) + "\n")
        self.window, self.fusion, self.contact = [self.root / name / "results"
                                                for name in ("wi", "fu", "co")]
        for root in (self.window, self.fusion, self.contact):
            root.mkdir(parents=True)
        cases = []
        for segment, frames in audit.WINDOW_CASES.items():
            for frame in sorted(frames):
                rel = segment + "/%06d" % frame
                row = {"segment_id": segment, "frame_1based": frame, "output_relative": rel,
                       "required_sides": ["left", "right"] if segment == audit.SEGMENT else ["right"],
                       "training_ready": False, "hands": []}
                if segment == audit.SEGMENT:
                    wi_folder = self.window / rel
                    fu_folder = self.fusion / rel
                    wi_folder.mkdir(parents=True)
                    fu_folder.mkdir(parents=True)
                    np.savez_compressed(fu_folder / "candidate.npz", **self.params)
                    for side in ("left", "right"):
                        xyz = self.model.hand(self.params, side)
                        vertices = np.zeros((778, 3))
                        vertices[[744, 320, 443, 554, 671]] = xyz[list(audit.FINGERTIP_IDS)]
                        file = side + "-00.npz"
                        np.savez_compressed(wi_folder / file, projected_joints=xyz[:, :2] * 100 + [192, 144],
                            joints=xyz, image_joints=xyz, vertices=vertices, image_vertices=vertices,
                            image_size=np.array([384, 288]), right=np.asarray(side == "right"))
                        row["hands"].append({"side": side, "parameters_file": file})
                cases.append(row)
        source_map = {"/remote/batch/" + name: audit.digest(self.batch / name)
                      for name in ("contract.json", "tasks.jsonl", "SHA256SUMS")}
        source_map["/remote/SMPLer-X/" + self.helper.MODEL_FILE] = self.model_sha
        source_map["/remote/wilor/wilor/models/mano_wrapper.py"] = audit.digest(wrapper)
        frame_rel = "samples/" + audit.SEGMENT + "/frames.jsonl"
        source_map["/remote/batch/" + frame_rel] = audit.digest(self.batch / frame_rel)
        observation_rel = "samples/" + audit.SEGMENT + "/observations.npz"
        source_map["/remote/batch/" + observation_rel] = audit.digest(self.batch / observation_rel)
        for frame in audit.FRAME_IDS:
            image_rel = "samples/" + audit.SEGMENT + "/images/%06d.jpg" % frame
            source_map["/remote/batch/" + image_rel] = audit.digest(self.batch / image_rel)
        self.write_json(self.window / "report.json", {
            "schema": "signbridge-wilor-keyframe-pilot-v1", "training_ready": False,
            "source_sha256": source_map, "cases": cases})
        self.refresh_manifest(self.window.parent)
        self.write_json(self.fusion / "report.json", {
            "schema": "signbridge-mano-smplx-alignment-v1", "training_ready": False,
            "source_sha256": source_map, "wilor_report_sha256": audit.digest(self.window / "report.json"),
            "cases": cases})
        self.refresh_manifest(self.fusion.parent)
        for frame in audit.FRAME_IDS:
            folder = self.contact / ("%06d" % frame)
            folder.mkdir()
            candidate = self.fusion / audit.SEGMENT / ("%06d" % frame) / "candidate.npz"
            (folder / "saved-candidate.npz").write_bytes(candidate.read_bytes())
            (folder / "previous-fusion.npz").write_bytes(candidate.read_bytes())
        self.write_json(self.contact / "report.json", {
            "schema": "signbridge-contact-hypothesis-pilot-v1", "training_ready": False,
            "scope": "greeting 88-91 only; no network inference, no finger or camera fitting",
            "status": "contact_proposals_rejected", "contact_approved": False,
            "original_fits_overwritten": False, "source_sha256": source_map,
            "wilor_report_sha256": audit.digest(self.window / "report.json"),
            "fusion_report_sha256": audit.digest(self.fusion / "report.json"),
            "cases": [{"frame_1based": f, "output_relative": "%06d" % f,
                       "tip_pair_openpose_indices": [12, 12], "candidate_gate_passed": False,
                       "training_ready": False, "pair_selection": "frozen experimental hypothesis"}
                      for f in audit.FRAME_IDS]})
        self.refresh_manifest(self.contact.parent)
        self.args = SimpleNamespace(batch=self.batch, wilor_results=self.window,
            fusion_results=self.fusion, contact_results=self.contact,
            wilor_report_sha256=audit.digest(self.window / "report.json"),
            fusion_report_sha256=audit.digest(self.fusion / "report.json"),
            contact_report_sha256=audit.digest(self.contact / "report.json"),
            smplerx_root=self.model_root, wilor_root=self.wilor_root, output=self.root / "output")

    def write_json(self, path, value):
        path.write_text(json.dumps(value) + "\n")

    def refresh_manifest(self, root):
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (root / "SHA256SUMS").write_text("".join(
            audit.digest(p) + "  " + str(p.relative_to(root)) + "\n" for p in files))

    def run_audit(self):
        with patch.object(audit, "load_model_helper", return_value=self.helper), \
             patch.object(self.helper, "MODEL_SHA256", self.model_sha), \
             patch.object(self.helper, "SparseSMPLX", return_value=self.model):
            return audit.audit(self.args)

    def test_full_report_preserves_missing_observation_and_does_not_modify_sources(self):
        before = {p: audit.digest(p) for root in (self.batch, self.window, self.fusion, self.contact)
                  for p in root.rglob("*") if p.is_file()}
        output = self.run_audit()
        report = json.loads(output.read_text())
        self.assertEqual([row["frame_1based"] for row in report["frames"]], list(audit.FRAME_IDS))
        missing = report["frames"][2]["sources"]["mediapipe_2d"]
        self.assertEqual(missing["status"], "missing_right_hand_observation")
        self.assertIsNone(missing["distance_matrix"])
        self.assertFalse(missing["interpolated"])
        self.assertFalse(report["training_ready"])
        self.assertFalse(report["contact_approved"])
        self.assertEqual({p: audit.digest(p) for p in before}, before)
        self.assertTrue(report["mapping_audit"]["wilor_tip_vertex_checks_passed"])
        for row in report["frames"]:
            for source in ("wilor_2d", "smplx_fusion_3d"):
                self.assertEqual(np.shape(row["sources"][source]["distance_matrix"]), (5, 5))
        audit.verify_manifest(self.args.output, self.args.output / "SHA256SUMS")
        self.assertTrue((self.args.output / "review-sheet.jpg").is_file())
        self.assertEqual(report["status"], "audited_pending_correspondence_review")

    def test_batch_self_consistent_but_from_different_run_is_rejected(self):
        contract = json.loads((self.batch / "contract.json").read_text())
        contract["different_run"] = True
        self.write_json(self.batch / "contract.json", contract)
        self.refresh_manifest(self.batch)
        with self.assertRaisesRegex(ValueError, "source.*(hash|digest|differs|mismatch)"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_output_cannot_be_inside_any_evidence_bundle(self):
        self.args.output = self.window.parent / "new-audit"
        with self.assertRaisesRegex(ValueError, "separate"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def change_report(self, root, field, value):
        path = root / "report.json"
        report = json.loads(path.read_text())
        report[field] = value
        self.write_json(path, report)
        self.refresh_manifest(root.parent)
        setattr(self.args, {self.window: "wilor_report_sha256", self.fusion: "fusion_report_sha256",
                            self.contact: "contact_report_sha256"}[root], audit.digest(path))

    def change_npz(self, path, change):
        with np.load(path, allow_pickle=False) as arrays:
            values = {key: arrays[key].copy() for key in arrays.files}
        change(values)
        np.savez_compressed(path, **values)
        root = next(root for root in (self.window, self.fusion, self.contact) if root in path.parents)
        self.refresh_manifest(root.parent)

    def test_manifest_rejects_duplicates_tampering_and_escape(self):
        root = self.root / "manifest-fixture"
        root.mkdir()
        file = root / "one.txt"
        file.write_text("one")
        manifest = root / "SHA256SUMS"
        line = audit.digest(file) + "  one.txt\n"
        for content in (line + line, "not-a-digest  one.txt\n", "bad line\n", "", "0" * 64 + "  one.txt\n"):
            manifest.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                audit.verify_manifest(root, manifest)
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        manifest.write_text(audit.digest(outside) + "  ../outside.txt\n")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            audit.verify_manifest(root, manifest)
        with self.assertRaises(ValueError):
            audit.contained_file(root, str(outside))

    def test_report_hash_mismatch_leaves_no_partial_output(self):
        self.args.contact_report_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "report hash"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_foreign_schema_and_training_ready_report_are_rejected(self):
        self.change_report(self.contact, "schema", "different-contact-schema")
        with self.assertRaisesRegex(ValueError, "schema"):
            self.run_audit()
        self.change_report(self.contact, "schema", "signbridge-contact-hypothesis-pilot-v1")
        self.change_report(self.contact, "training_ready", True)
        with self.assertRaisesRegex(ValueError, "training-ready"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_wrong_report_link_and_approved_contact_are_rejected(self):
        self.change_report(self.contact, "fusion_report_sha256", "0" * 64)
        with self.assertRaisesRegex(ValueError, "linkage"):
            self.run_audit()
        self.change_report(self.contact, "fusion_report_sha256", self.args.fusion_report_sha256)
        self.change_report(self.contact, "contact_approved", True)
        with self.assertRaisesRegex(ValueError, "read-only"):
            self.run_audit()

    def test_wilor_fingertip_vertex_permutation_is_rejected(self):
        path = self.window / audit.SEGMENT / "000088/left-00.npz"
        def corrupt(values):
            values["vertices"][744] += .01
        self.change_npz(path, corrupt)
        with self.assertRaisesRegex(ValueError, "correspondence mismatch"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_wilor_side_or_image_size_mismatch_is_rejected(self):
        path = self.window / audit.SEGMENT / "000088/left-00.npz"
        self.change_npz(path, lambda values: values.update(right=np.asarray(True)))
        with self.assertRaisesRegex(ValueError, "side identity"):
            self.run_audit()
        self.change_npz(path, lambda values: values.update(right=np.asarray(False), image_size=np.array([384, 287])))
        with self.assertRaisesRegex(ValueError, "image dimensions"):
            self.run_audit()

    def test_rejected_contact_cannot_change_saved_candidate(self):
        path = self.contact / "000088/saved-candidate.npz"
        def corrupt(values):
            values["left_hand_pose"][0, 0] += .01
        self.change_npz(path, corrupt)
        with self.assertRaisesRegex(ValueError, "differs from previous fusion"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_duplicate_or_missing_scope_is_rejected(self):
        row = {"segment_id": audit.SEGMENT, "frame_1based": 88}
        for cases in ([row, row], []):
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                audit.keyed_cases({"cases": cases}, audit.SEGMENT, {88})

    def test_mapping_source_requires_unique_digest_and_actual_index_order(self):
        report = {"source_sha256": {"/remote/wilor/models/mano_wrapper.py": "0" * 64}}
        with self.assertRaisesRegex(ValueError, "source digest"):
            audit.verify_mano_mapping(self.wilor_root, report)
        wrapper = self.wilor_root / "wilor/models/mano_wrapper.py"
        wrapper.write_text("mano_to_openpose = [0]\n")
        report["source_sha256"]["/remote/wilor/models/mano_wrapper.py"] = audit.digest(wrapper)
        with self.assertRaisesRegex(ValueError, "mapping differs"):
            audit.verify_mano_mapping(self.wilor_root, report)

    def test_cli_success_exit_code_and_output_path(self):
        options = []
        for key, value in vars(self.args).items():
            options.extend(["--" + key.replace("_", "-"), str(value)])
        with patch.object(sys, "argv", [str(SCRIPT)] + options), \
             patch.object(audit, "audit", return_value=self.args.output / "report.json"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(audit.main(), 0)
        self.assertIn(str(self.args.output / "report.json"), output.getvalue())

    def test_missing_frame90_mask_is_not_coerced_from_numeric(self):
        path = self.batch / "samples" / audit.SEGMENT / "observations.npz"
        with np.load(path, allow_pickle=False) as arrays:
            values = {key: arrays[key].copy() for key in arrays.files}
        values["right_hand_image_detected"] = values["right_hand_image_detected"].astype(np.int8)
        np.savez_compressed(path, **values)
        self.refresh_manifest(self.batch)
        # Provenance points to these malformed but faithfully recorded observations.
        for root in (self.window, self.fusion, self.contact):
            report = json.loads((root / "report.json").read_text())
            report["source_sha256"]["/remote/batch/SHA256SUMS"] = audit.digest(self.batch / "SHA256SUMS")
            report["source_sha256"]["/remote/batch/samples/" + audit.SEGMENT + "/observations.npz"] = audit.digest(path)
            self.change_report(root, "source_sha256", report["source_sha256"])
        self.change_report(self.fusion, "wilor_report_sha256", self.args.wilor_report_sha256)
        self.change_report(self.contact, "wilor_report_sha256", self.args.wilor_report_sha256)
        self.change_report(self.contact, "fusion_report_sha256", self.args.fusion_report_sha256)
        with self.assertRaisesRegex(ValueError, "observation shape"):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_existing_output_is_preserved(self):
        self.args.output.mkdir()
        marker = self.args.output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "new and separate"):
            self.run_audit()
        self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
