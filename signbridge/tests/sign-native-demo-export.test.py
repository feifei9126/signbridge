import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-native-demo-export.py'


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file())
        spec = importlib.util.spec_from_file_location('native_export_test', TOOL)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def arrays(self):
        values = {key: np.zeros((5, *shape), dtype=np.float32) for key, shape in self.tool.SHAPES.items()}
        values['frame_ids_1based'] = np.arange(1, 6)
        return values

    def test_hand_mean_once_upper_body_mapping_and_static_display_policy(self):
        source = self.arrays()
        source['body_pose'][:, 11:21] = 0.1
        source['global_orient'][:] = 0.3
        source['left_hand_pose'][:] = 0.2
        original = {key: value.copy() for key, value in source.items()}
        mean = np.zeros((55, 3))
        mean[25:40] = 0.15
        pose = self.tool.display_pose(source, mean)
        np.testing.assert_allclose(pose[:, 12:22], 0.1)
        np.testing.assert_allclose(pose[:, 25:40], 0.35)
        np.testing.assert_array_equal(pose[:, :12], 0)
        np.testing.assert_array_equal(pose[:, 22:25], 0)
        for key in source:
            np.testing.assert_array_equal(source[key], original[key])

    def test_missing_frames_nan_integer_or_wrong_shapes_rejected(self):
        for kind in ('missing', 'nan', 'integer', 'shape'):
            arrays = self.arrays()
            if kind == 'missing':
                arrays['frame_ids_1based'][2] = 99
            elif kind == 'nan':
                arrays['body_pose'][1, 2, 0] = np.nan
            elif kind == 'integer':
                arrays['left_hand_pose'] = arrays['left_hand_pose'].astype(np.int32)
            else:
                arrays['body_pose'] = arrays['body_pose'][:, :20]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.tool.display_pose(arrays, np.zeros((55, 3)))

    def test_all_aliases_remain_candidates_and_no_features_claim(self):
        row = {'annotation_id': 'fit_test', 'label_candidate': '我', 'aliases': [
            {'label_candidate': '我'}, {'label_candidate': '本人'}], 'fps': 25,
            'frames_expected': 5, 'native_asset_sha256': 'a' * 64, 'source_sha256': 'b' * 64,
            'uid': 'chunk:fit_test', 'human_approved': False, 'training_ready': False,
            'model_training_ready': False, 'text_verified': ''}
        clip = self.tool.clip_metadata(row)
        self.assertEqual(clip['aliases'], ['我', '本人'])
        self.assertEqual(clip['source'], 'native')
        self.assertEqual(clip['text_verified'], '')
        self.assertFalse(clip['human_approved'])
        self.assertNotIn('feature_sha256', clip)
        row['human_approved'] = True
        with self.assertRaises(ValueError):
            self.tool.clip_metadata(row)


if __name__ == '__main__':
    unittest.main()
