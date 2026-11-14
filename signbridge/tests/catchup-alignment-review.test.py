"""MANO/SMPL-X alignment review must never promote failed or sparse candidates."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-source-catchup-review.py'
spec = importlib.util.spec_from_file_location('catchup_alignment_review', SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class AlignmentReviewTests(unittest.TestCase):
    def report(self):
        return {'status': 'alignment_candidates_pending_visual_review', 'frames': 3,
                'training_ready': False, 'human_approved': False, 'training_started': False,
                'cases': [
                    {'case_id': 'one', 'combined_projection_gate_passed': True,
                     'all_candidate_gates_passed': True, 'candidate_alternatives': [{}], 'training_ready': False},
                    {'case_id': 'two', 'combined_projection_gate_passed': False,
                     'all_candidate_gates_passed': False, 'candidate_alternatives': [{}], 'training_ready': False},
                    {'case_id': 'three', 'combined_projection_gate_passed': True,
                     'all_candidate_gates_passed': False, 'candidate_alternatives': [], 'training_ready': False},
                ]}

    def test_gate_summary_preserves_failures_and_pending_state(self):
        summary = review.alignment_summary(self.report())
        self.assertEqual(summary['cases'], 3)
        self.assertEqual(summary['combined_gate_passed'], 2)
        self.assertEqual(summary['all_candidates_gate_passed'], 1)
        self.assertEqual(summary['combined_gate_failed'], 1)
        self.assertEqual(summary['no_mano_candidate_cases'], 1)
        self.assertFalse(summary['training_ready'])
        self.assertFalse(summary['human_approved'])

    def test_incomplete_or_promoted_report_is_rejected(self):
        value = self.report()
        value['cases'] = value['cases'][:1]
        with self.assertRaises(ValueError):
            review.alignment_summary(value)
        value = self.report()
        value['cases'][0]['training_ready'] = True
        with self.assertRaises(ValueError):
            review.alignment_summary(value)
        value = self.report()
        value['status'] = 'failed'
        with self.assertRaises(ValueError):
            review.alignment_summary(value)


if __name__ == '__main__':
    unittest.main()
