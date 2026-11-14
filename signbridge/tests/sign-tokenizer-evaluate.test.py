"""Frozen-clip evaluation must not imply independent-source sign accuracy."""

import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-tokenizer-evaluate.py"


class TokenizerEvaluateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("tokenizer_evaluate", SCRIPT)
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def row(self, segment, source="course-a", signer="person-a", group="textbook"):
        return {"segment_id": segment, "source_id": source, "source_sha256": source + "hash",
                "signer_id": signer, "split_group": group, "frames": 70}

    def test_same_source_clips_are_disjoint_only_at_clip_level(self):
        result = self.m.evaluation_scope([self.row("train-a")], [self.row("eval-b")])
        self.assertTrue(result["segment_disjoint"])
        self.assertEqual(result["shared_recorded_groups"]["source_id"], ["course-a"])
        self.assertFalse(result["independent_final_test"])
        self.assertFalse(result["person_independence_verified"])
        self.assertFalse(result["evaluation_used_for_weight_updates"])

    def test_different_courses_with_shared_signer_are_not_independent(self):
        result = self.m.evaluation_scope([self.row("train-a", "s1", "p1", "g1")],
                                         [self.row("eval-b", "s2", "p1", "g2")])
        self.assertEqual(result["shared_recorded_groups"]["signer_id"], ["p1"])
        self.assertFalse(result["independent_final_test"])

    def test_unknown_actual_identities_cannot_gain_test_qualification(self):
        result = self.m.evaluation_scope([self.row("train-a", "s1", "p1", "g1")],
                                         [self.row("eval-b", "s2", "p2", "g2")])
        self.assertEqual(result["shared_recorded_groups"]["source_id"], [])
        self.assertFalse(result["independent_final_test"])

    def test_overlapping_duplicate_and_unsafe_clip_ids_are_rejected(self):
        for train, evaluation in (([self.row("a")], [self.row("a")]),
                                  ([self.row("a"), self.row("a")], [self.row("b")]),
                                  ([self.row("a")], [self.row("b"), self.row("b")]),
                                  ([], [self.row("b")]),
                                  ([self.row("a")], [self.row("../escape")])):
            with self.subTest(train=train, evaluation=evaluation), self.assertRaises(ValueError):
                self.m.evaluation_scope(train, evaluation)

    def test_checkpoint_training_metadata_must_match_verified_report(self):
        rows = [self.row("a"), self.row("b")]
        report = {"schema": "signbridge-tokenizer-smoke-v1",
                  "status": "research_smoke_trained_not_deployable", "checkpoint_reload_passed": True,
                  "research_only": True, "training_ready": False,
                  "sequences": [{"segment_id": r["segment_id"], "frames": r["frames"]} for r in rows]}
        checkpoint = {"train_segments": ["a", "b"]}
        self.m.verify_training_scope(report, checkpoint, rows)
        for changes in ({"train_segments": ["a"]}, {"train_segments": ["b", "a"]}, {}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.m.verify_training_scope(report, changes, rows)
        report["checkpoint_reload_passed"] = False
        with self.assertRaises(ValueError):
            self.m.verify_training_scope(report, checkpoint, rows)

    def test_summarized_errors_weight_valid_values_not_clip_counts(self):
        samples = []
        for count, mse, rmse in ((10, 1., 1.), (30, 3., 2.)):
            samples.append({"metrics": {part: {"valid_values": count, "normalized_mse": mse,
                "raw_rmse": rmse, "mean_baseline_normalized_mse": 4.}
                for part in self.m.PARTS}})
        result = self.m.summarize_metrics(samples)
        self.assertAlmostEqual(result["all"]["normalized_mse"], 2.5)
        self.assertAlmostEqual(result["all"]["raw_rmse"], np.sqrt(3.25))
        self.assertAlmostEqual(result["all"]["mean_baseline_improvement_percent"], 37.5)

    def test_unobserved_part_has_no_fabricated_metric(self):
        sample = {"metrics": {part: {"valid_values": 0, "normalized_mse": None,
            "raw_rmse": None, "mean_baseline_normalized_mse": None} for part in self.m.PARTS}}
        result = self.m.summarize_metrics([sample])
        self.assertIsNone(result["left_hand"]["raw_rmse"])
        self.assertIsNone(result["all"]["mean_baseline_improvement_percent"])

    def test_rotation_error_uses_geodesic_not_axis_angle_difference(self):
        truth = np.zeros((4, 133), dtype=np.float32)
        prediction = truth.copy()
        truth[:, 30:33] = [0, 0, np.pi - .01]
        prediction[:, 30:33] = [0, 0, -np.pi + .01]
        mask = np.ones_like(truth, dtype=bool)
        result = self.m.rotation_errors(prediction, truth, mask)
        self.assertLess(result["left_hand"]["max_degrees"], 1.2)
        self.assertEqual(result["right_hand"]["mean_degrees"], 0.)

    def test_rotation_masks_and_nonfinite_targets_are_rejected(self):
        truth = np.zeros((4, 133), dtype=np.float32)
        mask = np.ones_like(truth, dtype=bool)
        mask[:, 30:75] = False
        result = self.m.rotation_errors(truth, truth, mask)
        self.assertEqual(result["left_hand"]["valid_rotations"], 0)
        self.assertIsNone(result["left_hand"]["mean_degrees"])
        truth[0, 0] = np.nan
        with self.assertRaises(ValueError):
            self.m.rotation_errors(truth, truth, mask)

    def integration_fixture(self, root):
        training, train_motions, reference = (root / name for name in ("training", "train-motions", "reference"))
        training.mkdir()
        for folder, segment in ((train_motions, "train-a"), (reference, "eval-b")):
            path = folder / "samples" / segment / "features-133.npy"
            path.parent.mkdir(parents=True)
            np.save(path, np.ones((70, 133), dtype=np.float32))
            row = {**self.row(segment), "features": str(path.relative_to(folder)),
                   "representation": "soke-smplx-133-v1", "dimensions": 133,
                   "model_training_ready": False, "motion_review_status": "needs_review",
                   "content_reviewed": True, "text_verified": "confirmed content"}
            (folder / "motions.jsonl").write_text(json.dumps(row) + "\n")
            (folder / "verification.json").write_text(json.dumps({"converted": 1, "rejected": [],
                "training_ready": False, "soke_commit": self.m.smoke.SOKE_COMMIT}))
            (folder / "SHA256SUMS").write_text("".join(self.m.evidence.digest(p) + "  " +
                str(p.relative_to(folder)) + "\n" for p in sorted(folder.rglob("*")) if p.is_file()))
        train_rows, arrays, masks, hashes = self.m.load_motion_inputs(train_motions)
        mean, std = self.m.smoke.normalization(arrays, masks)
        checkpoint = training / "tokenizer-smoke.pt"
        checkpoint.write_bytes(b"fixture checkpoint verified before mocked load")
        report = {"schema": "signbridge-tokenizer-smoke-v1",
                  "status": "research_smoke_trained_not_deployable", "checkpoint_reload_passed": True,
                  "research_only": True, "training_ready": False, "input_sha256": hashes,
                  "checkpoint_sha256": self.m.evidence.digest(checkpoint),
                  "sequences": [{"segment_id": "train-a", "frames": 70}]}
        report_path = training / "report.json"
        report_path.write_text(json.dumps(report))
        saved = {"schema": "signbridge-tokenizer-smoke-checkpoint-v1", "train_segments": ["train-a"],
                 "soke_commit": self.m.smoke.SOKE_COMMIT, "training_ready": False, "research_only": True,
                 "mean": mean, "std": std, "step": 1000,
                 "model_configs": [{"nfeats": 43}, {"nfeats": 45}, {"nfeats": 45}]}
        args = types.SimpleNamespace(training_results=training, training_motions=train_motions,
            evaluation_motions=reference, soke_root=root / "soke",
            training_report_sha256=self.m.evidence.digest(report_path), output=root / "out")
        return args, saved

    def test_full_evaluation_verifies_scope_hashes_and_never_trains(self):
        with tempfile.TemporaryDirectory() as folder:
            args, saved = self.integration_fixture(Path(folder))
            calls = []
            def infer(value):
                calls.append(value)
                value.output.mkdir(parents=True)
                np.save(value.output / "reconstructed-133.npy", np.load(value.features, allow_pickle=False))
            fake_torch = types.SimpleNamespace(__version__="2.2.2", Tensor=type("Tensor", (), {}),
                                               load=lambda *a, **k: saved)
            with patch.dict("sys.modules", {"torch": fake_torch}), patch.object(self.m.inference, "infer", infer):
                report_path = self.m.evaluate(args)
            report = json.loads(report_path.read_text())
            self.assertEqual(len(calls), 1)
            self.assertEqual(report["summary"]["all"]["normalized_mse"], 0.)
            self.assertEqual(report["training_weight_updates"], 0)
            self.assertFalse(report["scope"]["independent_final_test"])
            self.assertTrue(report["source_files_unchanged"])
            self.m.evidence.verify_manifest(args.output, args.output / "SHA256SUMS")
            with self.assertRaises(ValueError):
                self.m.evaluate(args)

    def test_tampered_reference_rejected_before_any_checkpoint_unpickling(self):
        with tempfile.TemporaryDirectory() as folder:
            args, _ = self.integration_fixture(Path(folder))
            feature = args.evaluation_motions / "samples/eval-b/features-133.npy"
            feature.write_bytes(b"changed reference")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                self.m.evaluate(args)
            self.assertFalse(args.output.exists())

    def test_input_mutation_during_inference_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            args, saved = self.integration_fixture(Path(folder))
            def infer(value):
                value.output.mkdir(parents=True)
                np.save(value.output / "reconstructed-133.npy", np.load(value.features, allow_pickle=False))
                (args.evaluation_motions / "motions.jsonl").write_text("mutated")
            fake_torch = types.SimpleNamespace(__version__="2.2.2", Tensor=type("Tensor", (), {}),
                                               load=lambda *a, **k: saved)
            with patch.dict("sys.modules", {"torch": fake_torch}), patch.object(self.m.inference, "infer", infer):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    self.m.evaluate(args)
            self.assertFalse((args.output / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
