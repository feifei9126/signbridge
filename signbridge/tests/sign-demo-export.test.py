import importlib.util
import unittest
from pathlib import Path

import numpy as np

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-demo-export.py'
spec = importlib.util.spec_from_file_location('sign_demo_export', TOOL)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoPoseContractTest(unittest.TestCase):
    def test_133d_layout_and_hand_mean_applied_once_without_mutating_inputs(self):
        values = np.arange(266, dtype=np.float32).reshape(2, 133) / 100
        mean = np.zeros((55, 3), dtype=np.float32)
        mean[25:40] = 0.1
        mean[40:55] = -0.2
        before = values.copy()
        before_mean = mean.copy()
        poses = demo.assemble_pose(values, mean)
        self.assertEqual(poses.shape, (2, 55, 3))
        np.testing.assert_array_equal(poses[:, 12:22], values[:, :30].reshape(2, 10, 3))
        np.testing.assert_allclose(poses[:, 25:40], values[:, 30:75].reshape(2, 15, 3) + 0.1)
        np.testing.assert_allclose(poses[:, 40:55], values[:, 75:120].reshape(2, 15, 3) - 0.2)
        np.testing.assert_array_equal(poses[:, 22], values[:, 120:123])
        np.testing.assert_array_equal(poses[:, :12], 0)
        np.testing.assert_array_equal(poses[:, 23:25], 0)
        np.testing.assert_array_equal(values, before)
        np.testing.assert_array_equal(mean, before_mean)

    def test_invalid_shape_and_nonfinite_features_rejected(self):
        for values in [np.zeros((2, 132)), np.full((2, 133), np.nan), np.zeros(133)]:
            with self.assertRaises(ValueError):
                demo.assemble_pose(values, np.zeros((55, 3)))
        with self.assertRaises(ValueError):
            demo.assemble_pose(np.zeros((2, 133)), np.zeros((54, 3)))

    def test_local_frozen_export_keeps_research_provenance(self):
        import json
        file = TOOL.parents[3] / 'local-data/demo-20261012/t08-motion.json'
        if not file.exists():
            self.skipTest('Local authorized reference asset is not distributed in Git')
        data = json.loads(file.read_text())
        self.assertEqual(data['checkpoint_sha256'], demo.T08_SHA)
        self.assertEqual(data['smplx_rest_model_sha256'], demo.MODEL_SHA)
        self.assertEqual(data['soke_commit'], demo.SOKE_COMMIT)
        self.assertEqual(data['checkpoint_step'], 1000)
        self.assertEqual(data['export_tool_sha256'], demo.sha(TOOL))
        self.assertEqual(len(data['clips']), 14)
        self.assertFalse(data['text_to_sign_trained'])
        for clip in data['clips']:
            self.assertEqual(clip['model_output'], 'token_decode')
            self.assertFalse(clip['text_to_sign_generated'])
            self.assertFalse(clip['human_motion_quality_approved'])
            self.assertLess(clip['token_decode_parity_max'], 1e-4)
            self.assertEqual(len(clip['feature_sha256']), 64)


if __name__ == '__main__':
    unittest.main()
