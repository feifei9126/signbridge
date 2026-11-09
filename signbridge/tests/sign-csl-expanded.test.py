"""Expansion preserves source meanings and never treats labels as certified motion."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-expanded.py'
spec = importlib.util.spec_from_file_location('expanded', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ExpansionTests(unittest.TestCase):
    def test_exact_spelling_and_structure_preserved(self):
        self.assertNotEqual(m.entry_key('word', '看1'), m.entry_key('word', '看2'))
        self.assertNotEqual(m.entry_key('sentence', '你好？'), m.entry_key('sentence', '你好。'))
        self.assertNotEqual(m.entry_key('word', '好'), m.entry_key('sentence', '好'))

    def test_duplicate_labels_keep_source_specific_meanings(self):
        entries = {}
        a = m.add_unit(entries, 'word', '我', {'id': 'source-a', 'meaning': '自己'})
        b = m.add_unit(entries, 'word', '我', {'id': 'source-b', 'meaning': '本句说话者'})
        self.assertIs(a, b)
        self.assertEqual(len(a['source_senses']), 2)
        self.assertFalse(a['training_ready'])

    def test_word_is_not_created_from_characters(self):
        entries = {}
        m.add_unit(entries, 'word', '我们', {'id': 'x'})
        self.assertEqual([x['text'] for x in entries.values()], ['我们'])

    def test_foundation_id_and_unreviewed_status_survive(self):
        entries = {}
        row = m.add_unit(entries, 'word', '你', {'id': 'f'}, base_id='basic-you')
        self.assertEqual(row['id'], 'basic-you')
        self.assertEqual(row['base_foundation_ids'], ['basic-you'])
        self.assertFalse(row['human_approved'])

    def test_conflicting_ids_or_types_cannot_silently_replace(self):
        entries = {}
        m.add_unit(entries, 'word', '你', {'id': 'f'}, base_id='one')
        with self.assertRaises(ValueError):
            m.add_unit(entries, 'word', '你', {'id': 'g'}, base_id='two')

    def test_excluded_header_has_no_effective_lexical_type(self):
        source = {'id': 'header', 'clean_text': '第七课', 'refined_unit_type': 'lesson_section', 'lexicon_eligible': False}
        self.assertEqual(m.caption_classification(source, []), (None, None))

    def test_caption_classification_uses_same_whitespace_policy_as_entry_keys(self):
        source = {'id': 'c', 'clean_text': ' 你家在哪里 ', 'refined_unit_type': 'word_candidate'}
        foundation = [{'id': 'f', 'text': '你家在哪里', 'unit_type': 'sentence', 'source_caption_ids': ['c']}]
        self.assertEqual(m.caption_classification(source, foundation)[0], 'sentence')

    def test_review_cannot_write_inside_frozen_inputs_even_through_symlink(self):
        import json
        import tempfile
        spec = importlib.util.spec_from_file_location('expanded_review', SCRIPT.with_name('sign-csl-expanded-review.py'))
        review = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(review)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            database, base, reference = [root / name for name in ['db', 'base', 'reference']]
            for path in [database, base, reference]:
                path.mkdir()
            (database / 'report.json').write_text(json.dumps({'base': str(base), 'reference': str(reference)}))
            for path in [database, base, reference]:
                with self.assertRaises(ValueError):
                    review.build(database, path / 'new-review')
                self.assertFalse((path / 'new-review').exists())
            (root / 'alias').symlink_to(base, target_is_directory=True)
            with self.assertRaises(ValueError):
                review.build(database, root / 'alias' / 'new-review')
            self.assertFalse((base / 'new-review').exists())

    def test_same_source_caption_uses_existing_foundation_sentence_classification(self):
        source = {'id': 'caption-q', 'clean_text': '你家在哪里', 'refined_unit_type': 'word_candidate'}
        foundation = [{'id': 'base-question', 'text': '你家在哪里', 'unit_type': 'sentence', 'source_caption_ids': ['caption-q']}]
        kind, proof = m.caption_classification(source, foundation)
        self.assertEqual(kind, 'sentence')
        self.assertEqual(proof['original_candidate_type'], 'word_candidate')
        self.assertFalse(proof['motion_or_word_boundary_approval'])
        source['id'] = 'different-source'
        self.assertEqual(m.caption_classification(source, foundation), ('word', None))

    def test_gloss_occurrences_keep_splits_and_quarantine(self):
        samples = [
            {'id': 'a', 'dataset_id': 'CE-CSL', 'source_split': 'train', 'status': 'retained', 'gloss_sequence': ['看1', '我']},
            {'id': 'b', 'dataset_id': 'CE-CSL', 'source_split': 'test', 'status': 'quarantined_label_conflict', 'gloss_sequence': ['看2']},
        ]
        rows = {x['text']: x for x in m.gloss_index(samples, [])}
        self.assertEqual(rows['看1']['occurrences_retained_by_split'], {'train': 1})
        self.assertEqual(rows['看2']['quarantined_sample_ids'], ['b'])
        self.assertEqual(rows['看2']['sample_ids'], ['b'])
        self.assertEqual(rows['看2']['retained_sample_ids'], [])
        self.assertEqual(rows['看1']['retained_sample_ids'], ['a'])
        self.assertFalse(rows['看2']['training_ready'])
        self.assertNotEqual(rows['看1']['id'], rows['看2']['id'])

    def test_gloss_label_without_word_boundary_remains_dataset_unit(self):
        row = m.gloss_index([{'id': 'a', 'dataset_id': 'CE-CSL', 'source_split': 'train', 'status': 'retained', 'gloss_sequence': ['我们']}], [])[0]
        self.assertEqual(row['unit_type'], 'dataset_gloss')
        self.assertFalse(row['word_boundary_verified'])

    def test_no_native_or_unknown_round_cannot_be_accepted(self):
        status = m.motion_status(None)
        self.assertEqual(status['full_action_two_round_passes'], 0)
        self.assertFalse(status['passed'])
        self.assertIn('missing_native_action', status['reasons'])

    def test_two_matching_unknown_rounds_still_fail(self):
        fields = {k: 'a' * 64 for k in ['source_sha256', 'clip_sha256', 'action_version_sha256', 'annotation_sha256']}
        action = {**fields, 'validation_rounds': [{'round': i, **fields, 'method_sha256': str(i) * 64, 'result': 'passed', 'checks': {}, 'evidence_scope': 'full_action_all_source_frames'} for i in [1, 2]]}
        self.assertFalse(m.motion_status(action)['passed'])

    def test_annotation_change_invalidates_both_rounds(self):
        fields = {k: 'a' * 64 for k in ['source_sha256', 'clip_sha256', 'action_version_sha256', 'annotation_sha256']}
        checks = {k: 'passed' for k in m.foundation.CHECKS}
        action = {**fields, 'validation_rounds': [{'round': i, **fields, 'method_sha256': str(i) * 64, 'result': 'passed', 'checks': checks, 'evidence_scope': 'full_action_all_source_frames'} for i in [1, 2]]}
        self.assertTrue(m.motion_status(action)['passed'])
        action['annotation_sha256'] = 'b' * 64
        self.assertFalse(m.motion_status(action)['passed'])
        self.assertEqual(m.motion_status(action)['full_action_two_round_passes'], 0)


if __name__ == '__main__':
    unittest.main()
