import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'signbridge/src/tools/sign-demo-candidate-export.py'
spec = importlib.util.spec_from_file_location('sign_demo_candidate_export', TOOL)
candidate_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate_export)
SOURCE = ROOT / 'local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1'
ASSET = ROOT / 'local-data/demo-20261012/t08-candidates.json'


class ReviewedCandidateExportTest(unittest.TestCase):
    def test_only_the_three_user_reviewed_motion_candidates_enter_export(self):
        rows, decision = candidate_export.load_reviewed_candidates(SOURCE)
        self.assertEqual([row['segment_id'] for row in rows], [
            'new-fe2208d9680580cd-0087',
            'new-8ffc3bdb3f8d0763-0124',
            'new-58a5b3d6622ea72a-0068',
        ])
        self.assertEqual(decision['status'], 'approved_by_user')
        self.assertTrue(all(row['content_reviewed'] for row in rows))
        self.assertTrue(all(row['motion_review_status'] == 'approved' for row in rows))
        self.assertTrue(all(row['model_training_ready'] is False for row in rows))
        self.assertTrue(all(row['mirror_status'] == 'unknown' for row in rows))

    def test_exported_codebook_candidates_keep_research_and_review_gates(self):
        if not ASSET.exists():
            self.skipTest('Run sign-demo-candidate-export.py to create the local CPU asset')
        data = json.loads(ASSET.read_text())
        self.assertEqual(data['schema'], 'signbridge-t08-motion-candidates-v1')
        self.assertEqual(data['training_checkpoint_sha256'], candidate_export.T08_SHA)
        self.assertEqual(data['export_tool_sha256'], candidate_export.sha(TOOL))
        self.assertFalse(data['training_weights_updated'])
        self.assertFalse(data['training_ready'])
        self.assertEqual(len(data['clips']), 3)
        for clip in data['clips']:
            self.assertTrue(clip['runtime_candidate'])
            self.assertFalse(clip['training_data_member'])
            self.assertFalse(clip['training_ready'])
            self.assertFalse(clip['mirror_orientation_confirmed'])
            self.assertLessEqual(clip['token_decode_parity_max'], 1e-4)
            self.assertEqual(len(clip['feature_sha256']), 64)


if __name__ == '__main__':
    unittest.main()
