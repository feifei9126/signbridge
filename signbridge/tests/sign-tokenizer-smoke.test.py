"""Offline input-contract tests; not proof of GPU training or sign quality."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/sign-tokenizer-smoke.py"
spec = importlib.util.spec_from_file_location("tokenizer_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class TokenizerSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        records = []
        for segment in smoke.SEGMENTS:
            path = self.root / "samples" / segment / "features-133.npy"
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, np.ones((70, 133), dtype=np.float32))
            records.append({"segment_id": segment, "features": str(path.relative_to(self.root)),
                            "frames": 70, "representation": "soke-smplx-133-v1", "dimensions": 133,
                            "model_training_ready": False, "motion_review_status": "needs_review",
                            "content_reviewed": True, "text_verified": "reviewed text"})
        (self.root / "motions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
        (self.root / "verification.json").write_text(json.dumps({"converted": 2, "rejected": [],
            "training_ready": False, "soke_commit": smoke.SOKE_COMMIT}))
        return records

    def test_unreviewed_inputs_require_explicit_smoke_acknowledgement(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, "research-only"):
            smoke.load_inputs(self.root, acknowledged=False)
        rows, arrays, hashes = smoke.load_inputs(self.root, acknowledged=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual([a.shape for a in arrays], [(70, 133), (70, 133)])
        self.assertEqual(len(hashes), 4)
        self.assertFalse(rows[0]["model_training_ready"])

    def test_source_paths_wrong_frames_and_nonfinite_are_rejected(self):
        rows = self.fixture()
        for mutation in ("path", "absolute_path", "frames", "nan", "width", "representation", "approval"):
            rows = self.fixture()
            path = self.root / rows[0]["features"]
            if mutation == "path":
                rows[0]["features"] = "../escape.npy"
            elif mutation == "absolute_path":
                rows[0]["features"] = str(path)
            elif mutation == "frames":
                rows[0]["frames"] = 71
            elif mutation == "nan":
                values = np.ones((70, 133), dtype=np.float32)
                values[0, 0] = np.nan
                np.save(path, values)
            elif mutation == "width":
                np.save(path, np.ones((70, 120), dtype=np.float32))
            elif mutation == "representation":
                rows[0]["representation"] = "landmarks"
            else:
                rows[0]["model_training_ready"] = True
            (self.root / "motions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                smoke.load_inputs(self.root, acknowledged=True)

    def test_rejected_or_incomplete_import_is_not_accepted_for_smoke(self):
        for changes in ({"converted": 1}, {"rejected": [{"segment_id": "bad"}]},
                        {"training_ready": True}, {"soke_commit": "wrong"}):
            self.fixture()
            path = self.root / "verification.json"
            path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                smoke.load_inputs(self.root, acknowledged=True)

    def custom_fixture(self):
        rows = self.fixture()
        scope = ["pilot-greeting-answer-002", "pilot-greeting-how-004", "pilot-hospital-rest-010"]
        custom = []
        for index, segment in enumerate(scope):
            row = dict(rows[index % len(rows)])
            row.update(segment_id=segment, content_reviewed=True, text_verified="reviewed text")
            path = self.root / "samples" / segment / "features-133.npy"
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, np.ones((70, 133), dtype=np.float32))
            row["features"] = str(path.relative_to(self.root))
            custom.append(row)
        (self.root / "motions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in custom))
        (self.root / "verification.json").write_text(json.dumps({"converted": len(custom),
            "rejected": [], "skipped": [{"segment_id": "pilot-greeting-hello-001"}],
            "training_ready": False, "soke_commit": smoke.SOKE_COMMIT}))
        return scope, custom

    def test_explicit_scope_loads_only_exact_reviewed_custom_batch(self):
        scope, _ = self.custom_fixture()
        rows, arrays, hashes = smoke.load_inputs(self.root, True, segment_ids=scope)
        self.assertEqual([r["segment_id"] for r in rows], scope)
        self.assertEqual(len(arrays), 3)
        self.assertEqual(len(hashes), 5)
        with self.assertRaises(ValueError):
            smoke.load_inputs(self.root, True)
        with self.assertRaisesRegex(ValueError, "research-only"):
            smoke.load_inputs(self.root, False, segment_ids=scope)

    def test_custom_scope_rejects_duplicates_missing_extra_and_wrong_order(self):
        scope, _ = self.custom_fixture()
        for selected in ([], scope[:2], scope + ["unexpected"], scope[::-1],
                         [scope[0], scope[0], scope[2]], ["../escape"], ["."],
                         ["two words"], [None], [[]]):
            with self.subTest(scope=selected), self.assertRaises(ValueError):
                smoke.load_inputs(self.root, True, segment_ids=selected)

    def test_custom_batch_rejects_unreviewed_content_and_missing_text(self):
        for changes in ({"content_reviewed": False}, {"text_verified": ""}):
            scope, rows = self.custom_fixture()
            rows[0].update(changes)
            (self.root / "motions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                smoke.load_inputs(self.root, True, segment_ids=scope)

    def test_custom_batch_does_not_accept_rejected_imports(self):
        scope, _ = self.custom_fixture()
        path = self.root / "verification.json"
        report = json.loads(path.read_text())
        report["rejected"] = [{"segment_id": scope[0]}]
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            smoke.load_inputs(self.root, True, segment_ids=scope)

    def test_selected_segment_cannot_also_be_listed_as_skipped(self):
        scope, _ = self.custom_fixture()
        path = self.root / "verification.json"
        report = json.loads(path.read_text())
        report["skipped"] = [{"segment_id": scope[0]}]
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            smoke.load_inputs(self.root, True, segment_ids=scope)

    def test_parts_roundtrip_and_window_contract(self):
        array = np.arange(140 * 133, dtype=np.float32).reshape(140, 133)
        parts = smoke.split_parts(array)
        self.assertEqual([part.shape[-1] for part in parts], [43, 45, 45])
        np.testing.assert_array_equal(parts[0][:, 30:], array[:, 120:])
        np.testing.assert_array_equal(parts[1], array[:, 30:75])
        np.testing.assert_array_equal(parts[2], array[:, 75:120])
        np.testing.assert_array_equal(smoke.combine_parts(parts), array)
        windows = smoke.make_windows([array])
        self.assertEqual(windows.shape[1:], (64, 133))
        np.testing.assert_array_equal(windows[-1], array[-64:])

    def test_constant_feature_scales_remain_finite_and_source_immutable(self):
        arrays = [np.ones((65, 133), dtype=np.float32), np.ones((67, 133), dtype=np.float32)]
        mean, std = smoke.normalization(arrays)
        self.assertTrue((std >= .05).all())
        self.assertTrue(np.isfinite((arrays[0] - mean) / std).all())
        self.assertEqual(arrays[0][0, 0], 1)

    def test_masked_normalization_ignores_unaccepted_hand_targets(self):
        values=np.ones((70,133),dtype=np.float32)
        values[:35,30:75]=999.
        mask=np.ones_like(values,dtype=bool);mask[:35,30:75]=False
        mean,std=smoke.normalization([values],[mask])
        np.testing.assert_allclose(mean,1.)
        self.assertTrue((std>=.05).all())
        self.assertEqual(values[0,30],999.)
        model_input=smoke.normalized_model_input(values,mean,std,mask)
        self.assertTrue((model_input[:35,30:75]==0.).all())
        self.assertEqual(values[0,30],999.)

    def test_normalized_model_input_rejects_shape_and_mask_type_mismatch(self):
        v=np.zeros((2,133),dtype=np.float32)
        with self.assertRaises(ValueError):
            smoke.normalized_model_input(v,np.zeros(133),np.ones(133),np.ones((2,133),dtype=np.int8))
        with self.assertRaises(ValueError):
            smoke.normalized_model_input(v,np.zeros(132),np.ones(133),np.ones((2,133),dtype=bool))

    def test_full_fusion_smoke_requires_saved_mask_and_rejects_numeric_mask(self):
        rows=self.fixture()
        path=self.root/'verification.json';v=json.loads(path.read_text());v['schema']='signbridge-full-fusion-export-v1';path.write_text(json.dumps(v))
        for row in rows:
            file=self.root/row['features'];np.save(file.with_name('feature-valid-mask.npy'),np.ones((70,133),dtype=bool))
        masks,hashes=smoke.load_quality_masks(self.root,rows,required=True)
        self.assertEqual(len(masks),2);self.assertEqual(len(hashes),2)
        np.save((self.root/rows[0]['features']).with_name('feature-valid-mask.npy'),np.ones((70,133),dtype=np.int8))
        with self.assertRaisesRegex(ValueError,'mask'):
            smoke.load_quality_masks(self.root,rows,required=True)


if __name__ == "__main__":
    unittest.main()
