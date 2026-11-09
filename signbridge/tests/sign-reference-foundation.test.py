"""Reproducible Demo acceptance cannot grant CSL training approval."""

from pathlib import Path
import copy
import importlib.util
import unittest

spec = importlib.util.spec_from_file_location('reference', Path(__file__).resolve().parents[1] / 'src/tools/sign-reference-foundation.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class ReferenceGateTests(unittest.TestCase):
    def record(self):
        return {'status': 'passed', 'checks': {name: True for name in reference.CHECKS},
                'binding': {**{name: 'a' * 64 for name in reference.BINDINGS[:-1]},
                            'source_frame_range_1based': [17, 250]},
                'human_approved': False, 'training_ready': False, 'model_training_ready': False,
                'semantic_certified': False,
                'acceptance_scope': 'automated_demo_stability_and_same_version_reproducibility_not_standard_CSL_certification'}

    def test_matching_success_is_demo_only_not_training_permission(self):
        row = self.record()
        gate = reference.demo_gate(row, copy.deepcopy(row))
        self.assertTrue(gate['demo_reference_accepted'])
        self.assertFalse(gate['training_allowed'])
        self.assertFalse(gate['complete_CSL_certification'])

    def test_two_identical_failures_never_pass(self):
        row = self.record()
        row['status'] = 'not_passed'
        self.assertFalse(reference.demo_gate(row, row)['demo_reference_accepted'])

    def test_any_check_false_or_missing_blocks_even_identical_results(self):
        for name in reference.CHECKS:
            for missing in [False, True]:
                row = self.record()
                if missing:
                    del row['checks'][name]
                else:
                    row['checks'][name] = False
                self.assertFalse(reference.demo_gate(row, row)['demo_reference_accepted'])

    def test_changed_source_action_annotation_or_range_invalidates_rounds(self):
        for key in reference.BINDINGS:
            row = self.record()
            second = copy.deepcopy(row)
            second['binding'][key] = 'b' * 64
            self.assertFalse(reference.demo_gate(row, second)['demo_reference_accepted'])

    def test_missing_bindings_or_promoted_flags_block(self):
        for key in reference.BINDINGS:
            row = self.record()
            del row['binding'][key]
            self.assertFalse(reference.demo_gate(row, row)['demo_reference_accepted'])
        for key in ['human_approved', 'training_ready', 'model_training_ready', 'semantic_certified']:
            row = self.record()
            row[key] = True
            self.assertFalse(reference.demo_gate(row, row)['demo_reference_accepted'])

    def test_malformed_hash_and_invalid_or_boolean_source_range_block(self):
        row = self.record()
        row['binding']['annotation_sha256'] = 'not-a-digest'
        self.assertFalse(reference.demo_gate(row, row)['demo_reference_accepted'])
        for bad in [None, [], [2, 1], [True, 4], [0, 20], '17-250']:
            row = self.record()
            row['binding']['source_frame_range_1based'] = bad
            self.assertFalse(reference.demo_gate(row, row)['demo_reference_accepted'])

    def test_reference_identity_cannot_write_outside_library(self):
        self.assertEqual(reference.reference_id('new-abc-cap-0028'), 'new-abc-cap-0028')
        for value in ['../escape', '/tmp/escape', 'a/b', '.', '', None, 'a' * 122]:
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                reference.reference_id(value)


if __name__ == '__main__':
    unittest.main()
