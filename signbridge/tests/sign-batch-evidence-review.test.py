"""Missing evidence is never a successful reconstruction or a continuous track."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-batch-evidence-review.py'


class EvidenceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = None
        if TOOL.exists():
            spec = importlib.util.spec_from_file_location('evidence_review', TOOL)
            cls.tool = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.tool)

    def test_tool_available(self):
        self.assertIsNotNone(self.tool)

    def test_nonfinite_parameter_is_error(self):
        if not self.tool: self.skipTest('Not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.npz'
            np.savez(path, hand_pose=np.full((15, 3), np.nan))
            result = self.tool.check_npz(path)
            self.assertIn('nonfinite:hand_pose', result['errors'])

    def test_bad_rotation_matrix_is_error(self):
        if not self.tool: self.skipTest('Not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.npz'
            np.savez(path, hand_pose=np.ones((15, 3, 3), np.float32))
            self.assertIn('invalid_SO3:hand_pose', self.tool.check_npz(path)['errors'])

    def test_explicit_missing_observations_are_not_nonfinite_fits(self):
        if not self.tool: self.skipTest('Not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'missing-observation.npz'
            np.savez(path, mediapipe_slot_xy=np.full((21, 2), np.nan, np.float32))
            result = self.tool.check_npz(path)
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['missing_observations'], ['mediapipe_slot_xy'])

    def test_token_range_and_length(self):
        if not self.tool: self.skipTest('Not implemented')
        self.assertEqual(self.tool.token_errors(np.zeros((1, 5), np.int64), 17, 16), [])
        self.assertIn('token_range', self.tool.token_errors(np.full((1, 5), 16), 17, 16))
        self.assertIn('token_shape', self.tool.token_errors(np.zeros((1, 4), np.int64), 17, 16))

    def test_checksum_mismatch_detected(self):
        if not self.tool: self.skipTest('Not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'x').write_text('changed')
            (root / 'SHA256SUMS').write_text('0' * 64 + '  x\n')
            result = self.tool.check_manifest(root / 'SHA256SUMS', {})
            self.assertEqual(result['mismatches'], ['x'])

    def test_checksum_escape_rejected(self):
        if not self.tool: self.skipTest('Not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'SHA256SUMS').write_text('0' * 64 + '  ../x\n')
            self.assertEqual(self.tool.check_manifest(root / 'SHA256SUMS', {})['unsafe_paths'], ['../x'])


if __name__ == '__main__': unittest.main()
