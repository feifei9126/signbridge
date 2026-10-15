import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

TOOL = Path(__file__).resolve().parents[1] / "src/tools/sign-demo-experimental-export.py"
spec = importlib.util.spec_from_file_location("experimental_export", TOOL)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class ExperimentalExportTest(unittest.TestCase):
    def test_effective_pose_preserves_each_frame_and_adds_hand_mean_once(self):
        features = np.ones((8, 133), dtype=np.float32)
        mean = np.zeros((55, 3), dtype=np.float32)
        mean[25:55] = 2
        pose = export.effective_pose(features, mean)
        self.assertEqual(pose.shape, (8, 55, 3))
        self.assertTrue(np.all(pose[:, :12] == 0))
        self.assertTrue(np.all(pose[:, 12:22] == 1))
        self.assertTrue(np.all(pose[:, 25:55] == 3))
        features[0, 0] = np.nan
        with self.assertRaises(ValueError):
            export.effective_pose(features, mean)

    def test_dedup_preserves_alternatives_without_deleting_sources(self):
        rows = [
            {"id": "noisy", "text": "你好！", "feature_sha256": "a", "max_jump": 120},
            {"id": "better", "text": "你 好", "feature_sha256": "b", "max_jump": 20},
            {"id": "unique", "text": "再见", "feature_sha256": "c", "max_jump": 30},
        ]
        selected, excluded = export.deduplicate(rows, set())
        self.assertEqual({r["id"] for r in selected}, {"better", "unique"})
        self.assertEqual(excluded[0]["id"], "noisy")
        self.assertEqual(excluded[0]["retained_id"], "better")
        self.assertEqual(len(rows), 3)
        selected, excluded = export.deduplicate(rows, {export.text_key("你好")})
        self.assertEqual([r["id"] for r in selected], ["unique"])

    def test_local_export_has_exact_complete_frames_and_preserves_quality_gate(self):
        root = TOOL.parents[3]
        output = root / "local-data/demo-experimental-20261015"
        if not output.is_dir():
            self.skipTest("Local authorized experimental export not installed")
        manifest = json.loads((output / "experimental-index.json").read_text())
        self.assertEqual(manifest["input_sequences"], 91)
        self.assertEqual(len(manifest["clips"]), 83)
        self.assertEqual(len(manifest["duplicates"]), 8)
        self.assertEqual(len(manifest["incomplete_excluded"]), 2)
        self.assertEqual(sum(c["frames"] for c in manifest["clips"]), 24900)
        self.assertEqual(manifest["export_tool_sha256"], export.sha(TOOL))
        self.assertFalse(manifest["training_weights_updated"])
        for entry in manifest["clips"]:
            path = output / entry["asset"]
            self.assertEqual(export.sha(path), entry["sha256"])
            clip = json.loads(path.read_text())
            pose = np.asarray(clip["poses"])
            self.assertEqual(pose.shape, (entry["frames"], 55, 3))
            self.assertTrue(np.isfinite(pose).all())
            self.assertFalse(clip["human_approved"])
            self.assertFalse(clip["training_ready"])
            self.assertEqual(clip["motion_review_status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
