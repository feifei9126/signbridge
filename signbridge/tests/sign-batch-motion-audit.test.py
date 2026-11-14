"""Cross-batch motion triage must preserve gaps and distinguish risk from approval."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json

import numpy as np

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-batch-motion-audit.py'


class BatchMotionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = None
        if TOOL.exists():
            spec = importlib.util.spec_from_file_location('batch_audit', TOOL)
            cls.tool = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.tool)

    def test_available(self):
        self.assertIsNotNone(self.tool, 'Need a reproducible cross-batch motion audit')

    def test_constant_turn_not_flagged_as_jitter(self):
        if self.tool is None:
            self.skipTest('No tool yet')
        poses = np.zeros((20, 2, 3))
        poses[:, :, 2] = np.arange(20)[:, None] * .1
        value = self.tool.temporal_metrics(poses, list(range(1, 21)))
        self.assertLess(value['midpoint_residual_p95_deg'], .01)
        self.assertEqual(value['isolated_spike_frames'], [])

    def test_rotation_wrap_not_flagged(self):
        if self.tool is None:
            self.skipTest('No tool yet')
        poses = np.zeros((3, 1, 3))
        poses[:, 0, 2] = np.deg2rad([179, -179, -177])
        result = self.tool.temporal_metrics(poses, [1, 2, 3])
        self.assertAlmostEqual(result['adjacent_p95_deg'], 2., places=4)
        self.assertLess(result['midpoint_residual_p95_deg'], .01)

    def test_isolated_jump_keeps_exact_original_frame(self):
        if self.tool is None:
            self.skipTest('No tool yet')
        poses = np.zeros((5, 1, 3))
        poses[2, 0, 0] = 2.
        original = poses.copy()
        result = self.tool.temporal_metrics(poses, [4, 5, 6, 7, 8])
        self.assertIn(6, result['isolated_spike_frames'])
        self.assertEqual(result['large_jump_frames'], [6, 7])
        np.testing.assert_array_equal(original, poses)

    def test_missing_frames_not_bridged(self):
        if self.tool is None:
            self.skipTest('No tool yet')
        poses = np.zeros((2, 1, 3)); poses[1, 0, 0] = 2.
        result = self.tool.temporal_metrics(poses, [1, 3])
        self.assertIsNone(result['adjacent_p95_deg'])
        self.assertIsNone(result['midpoint_residual_p95_deg'])

    def test_risk_flags_are_not_semantic_judgments(self):
        if self.tool is None:
            self.skipTest('No tool yet')
        self.assertEqual(self.tool.risk_level(['missing_native_frames'], []), 'technical_error')
        self.assertEqual(self.tool.risk_level([], ['rotation_spikes']), 'high_priority_review')
        self.assertEqual(self.tool.risk_level([], []), 'no_automatic_red_flag')

    def test_content_hash_maps_multiple_batch_aliases(self):
        if self.tool is None:
            self.skipTest('No tool yet')
        result = self.tool.source_batches({'aliases': ['2/video.mp4', '3/same.mp4']})
        self.assertEqual(result, [2, 3])

    def test_parameter_file_count_does_not_depend_on_orphan_metadata(self):
        if self.tool is None: self.skipTest('No tool yet')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fit = root / 'fit'
            for name in ['smplx', 'meta', 'img']: (fit / name).mkdir(parents=True, exist_ok=True)
            for name in ['poses', 'native-checksums']: (root / 'output' / name).mkdir(parents=True, exist_ok=True)
            np.savez(fit / 'smplx/00001_0.npz', **{key: np.zeros(shape, np.float32) for key, shape in self.tool.audit.NATIVE_SHAPES.items()})
            (fit / 'meta/00001_0.json').write_text(json.dumps({'img_path': '/inputs/case-1/000001.jpg', 'bbox_id': 0}))
            (fit / 'meta/orphan.json').write_text('{}')
            case = {'id': 'case-1', 'uid': 'case-1', 'fit': str(fit), 'frames': 1, 'fps': 25, 'text': 'test'}
            result = self.tool.native_case(case, np.zeros((55, 3), np.float32), root / 'output')
            self.assertEqual(result['native_parameter_files'], 1)
            self.assertIn('metadata_set_differs', result['errors'])


if __name__ == '__main__':
    unittest.main()
