"""Consistency resolution may change kind only, never learned BIO or rejection."""
import copy
import importlib.util
from pathlib import Path
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-semantic-consistency.py'


def module():
    spec = importlib.util.spec_from_file_location('semantic_consistency_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class ContractTests(unittest.TestCase):
    def test_conflicting_kind_with_complete_learned_actor_can_resolve_to_entity(self):
        m = module(); tag = m.c.b.s.base.LABELS.index
        p = {'id': 'a', 'text': '你们', 'raw_kind': 'event', 'raw_BIO': [tag('B-actor'), tag('I-actor')]}
        p['prediction'] = m.c.interpret(p['text'], p['raw_BIO'], p['raw_kind'])
        old = copy.deepcopy(p); result = m.resolve(p)
        self.assertEqual(p, old)
        self.assertEqual(result['prediction']['roles'], {'actor': '你们'})
        self.assertEqual(result['prediction']['kind'], 'entity')
        self.assertEqual(result['raw_kind'], 'event'); self.assertEqual(result['raw_BIO'], old['raw_BIO'])
        self.assertTrue(result['kind_resolved_by_explicit_structure'])
        self.assertFalse(result['prediction']['can_play'])
        self.assertEqual(result['original_prediction'], old['prediction'])

    def test_reject_unresolved_bad_bio_or_invalid_argument_never_repaired(self):
        m = module(); tag = m.c.b.s.base.LABELS.index
        for text, kind, tags in [('你们', 'reject', [tag('B-actor'), tag('I-actor')]),
                                 ('你们', 'event', [0, 0]),
                                 ('我喝书', 'event', [tag('B-actor'), tag('B-predicate'), tag('B-patient')]),
                                 ('去我', 'entity', [tag('B-predicate'), tag('B-actor')])]:
            p = {'id': 'a', 'text': text, 'raw_kind': kind, 'raw_BIO': tags}
            p['prediction'] = m.c.interpret(text, tags, kind)
            out = m.resolve(p)
            self.assertEqual(out['prediction']['status'], 'abstained')
            self.assertFalse(out['kind_resolved_by_explicit_structure'])

    def test_valid_original_scope_remains_distinct_and_graph_unchanged(self):
        m = module(); tag = m.c.b.s.base.LABELS.index
        graphs = []
        for text, tags in [('我不想去', [tag('B-actor'), tag('B-negation'), tag('B-modal'), tag('B-predicate')]),
                           ('我想不去', [tag('B-actor'), tag('B-modal'), tag('B-negation'), tag('B-predicate')])]:
            p = {'id': text, 'text': text, 'raw_kind': 'event', 'raw_BIO': tags}
            p['prediction'] = m.c.interpret(text, tags, 'event')
            out = m.resolve(p)
            self.assertEqual(out['prediction'], p['prediction']); self.assertFalse(out['kind_resolved_by_explicit_structure'])
            graphs.append(out['prediction']['event_key'])
        self.assertNotEqual(*graphs)

    def test_forged_raw_prediction_is_rejected(self):
        m = module(); tag = m.c.b.s.base.LABELS.index
        p = {'id': 'a', 'text': '你们', 'raw_kind': 'event', 'raw_BIO': [tag('B-actor'), tag('I-actor')],
             'prediction': {'status': 'parsed', 'roles': {'actor': '我'}}}
        with self.assertRaises(ValueError): m.resolve(p)

    def test_explicit_rejection_marker_cannot_bypass_raw_evidence_validation(self):
        m = module(); tag = m.c.b.s.base.LABELS.index
        valid = {'text': '我。去', 'explicit_contract_rejection': True,
                 'prediction': {**m.c.b.GATES, 'status': 'abstained', 'kind': 'reject', 'roles': {}, 'spans': [],
                                'operators': [], 'reasons': ['outside_single_clause_Chinese_character_contract']}}
        self.assertEqual(m.resolve(valid)['prediction']['status'], 'abstained')
        for marker in [True, 1, 'false']:
            forged = {'text': '我', 'explicit_contract_rejection': marker,
                      'prediction': {**valid['prediction'], 'status': 'parsed', 'roles': {'actor': '我'}}}
            with self.subTest(marker=marker), self.assertRaises(ValueError): m.resolve(forged)
        for marker in [1, 'false']:
            with self.assertRaises(ValueError): m.resolve(dict(valid, explicit_contract_rejection=marker))
        with self.assertRaises(ValueError):
            m.resolve(dict(valid, raw_kind='event', raw_BIO=[tag('B-actor')]))


if __name__ == '__main__': unittest.main()
