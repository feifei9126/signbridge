"""MANO-to-SMPL-X input contracts keep sides and model estimates explicit."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-tutorial-mano-align.py'
spec = importlib.util.spec_from_file_location('tutorial_mano_align_test', SCRIPT)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)


class TutorialManoAlignTests(unittest.TestCase):
    def fixture(self, right=True):
        rotations = np.repeat(np.eye(3, dtype=np.float32)[None], 15, axis=0)
        wrist = np.eye(3, dtype=np.float32)[None]
        target = np.zeros((21, 2), dtype=np.float64)
        target[:, 0] = np.linspace(80, 160, 21)
        target[:, 1] = np.linspace(90, 190, 21)
        return {'hand_pose': rotations, 'global_orient': wrist, 'projected_joints': target,
                'right': np.asarray(right), 'detector_confidence': np.asarray(.91)}

    def test_valid_candidate_retains_predicted_side_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mano.npz'
            for side_field in ('right', 'detector_right'):
                row = self.fixture()
                if side_field == 'detector_right':
                    row['detector_right'] = row.pop('right')
                np.savez_compressed(path, **row)
                fingers, wrist, target, confidence = align.load_mano_candidate(path, 'right')
                self.assertEqual(fingers.shape, (15, 3, 3))
                self.assertEqual(wrist.shape, (1, 3, 3))
                self.assertEqual(target.shape, (21, 3))
                self.assertTrue(np.all(target[:, 2] == 0))
                self.assertEqual(confidence, .91)

    def test_side_mismatch_missing_arrays_and_nan_targets_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mano.npz'
            np.savez_compressed(path, **self.fixture(right=False))
            with self.assertRaises(ValueError):
                align.load_mano_candidate(path, 'right')
            bad = self.fixture()
            bad['projected_joints'][0, 0] = np.nan
            np.savez_compressed(path, **bad)
            with self.assertRaises(ValueError):
                align.load_mano_candidate(path, 'right')
            np.savez_compressed(path, projected_joints=np.zeros((21, 2)))
            with self.assertRaises(ValueError):
                align.load_mano_candidate(path, 'left')


if __name__ == '__main__':
    unittest.main()
