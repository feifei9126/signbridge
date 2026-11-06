"""Typed Chinese semantic heads must stay separate from CSL and model promotion."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-typed-semantics.py'


def module():
    spec = importlib.util.spec_from_file_location('typed_semantics_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class ContractTests(unittest.TestCase):
    def test_expanded_data_has_entities_compound_scopes_and_rejections_in_each_split(self):
        m = module(); data = m.corpus(set())
        for split in ['train', 'dev']:
            rows = data[split]
            self.assertGreater(len(rows), 100)
            self.assertEqual({r['expected_kind'] for r in rows}, {'entity', 'event', 'reject'})
            self.assertTrue(any(r['expected_operators'] == ['negation:不', 'modal:想'] for r in rows))
            self.assertTrue(any(r['expected_operators'] == ['modal:想', 'negation:不'] for r in rows))
            self.assertTrue(any(r['expected_kind'] == 'entity' for r in rows))
        self.assertFalse({r['text'] for r in data['train']} & {r['text'] for r in data['dev']})
        self.assertFalse({r['split_group'] for r in data['train']} & {r['split_group'] for r in data['dev']})
        self.assertTrue(any(r['text'] == '我们' for r in data['dev']))
        self.assertTrue(all(r['human_approved'] is False and r['csl_supervision'] is False for rows in data.values() for r in rows))
        m.validate_data(data, set())

    def test_reservation_excludes_known_challenges_and_never_invents_gloss_targets(self):
        m = module(); reserved = {'我不想去', '我想不去', '我帮你', '我们'}
        data = m.corpus(reserved)
        self.assertTrue(all(r['text'] not in reserved and 'gloss_sequence' not in r for rows in data.values() for r in rows))
        for split in data:
            for row in data[split]:
                if row['expected_kind'] == 'reject': self.assertIsNone(row['tags'])
                else: self.assertEqual(len(row['text']), len(row['tags']))

    def test_prior_dev_texts_cannot_enter_train_but_plural_entities_stay_dev(self):
        m = module(); reserved_train = {'我不能学习', '你来了', '我们'}
        data = m.corpus(set(), reserved_train)
        self.assertFalse({r['text'] for r in data['train']} & reserved_train)
        self.assertIn('我们', {r['text'] for r in data['dev']})

    def test_ordered_operators_and_entity_predictions_come_from_tags_not_text_lookup(self):
        m = module(); labels = m.s.base.LABELS
        tag = lambda name: labels.index(name)
        a = m.interpret('我不想去', [tag('B-actor'), tag('B-negation'), tag('B-modal'), tag('B-predicate')], 'event')
        b = m.interpret('我想不去', [tag('B-actor'), tag('B-modal'), tag('B-negation'), tag('B-predicate')], 'event')
        self.assertEqual(a['status'], 'parsed'); self.assertEqual(b['status'], 'parsed')
        self.assertNotEqual(a['event_key'], b['event_key'])
        self.assertEqual(a['operators'], ['negation:不', 'modal:想'])
        entity = m.interpret('我们', [tag('B-actor'), tag('I-actor')], 'entity')
        self.assertEqual(entity['roles'], {'actor': '我们'})
        self.assertEqual(entity['kind'], 'entity'); self.assertFalse(entity['can_play'])
        # Blank learned tag output may not be replaced by a lexical answer.
        bad = m.interpret('我们', [0, 0], 'entity')
        self.assertEqual(bad['status'], 'abstained')

    def test_illegal_bio_duplicates_and_kind_mismatch_abstain(self):
        m = module(); tag = m.s.base.LABELS.index
        for text, tags, kind in [('我们', [tag('I-actor'), tag('I-actor')], 'entity'),
                                 ('我你', [tag('B-actor'), tag('B-actor')], 'entity'),
                                 ('我去', [tag('B-actor'), tag('B-predicate')], 'entity'),
                                 ('我们', [tag('B-actor'), tag('I-actor')], 'event')]:
            self.assertEqual(m.interpret(text, tags, kind)['status'], 'abstained')

    def test_structural_counts_cannot_approve_reversed_roles_bad_arguments_or_operators(self):
        m = module(); tag = m.s.base.LABELS.index
        for text, tags in [('我喝书', [tag('B-actor'), tag('B-predicate'), tag('B-patient')]),
                           ('去我', [tag('B-predicate'), tag('B-actor')]),
                           ('我不去想', [tag('B-actor'), tag('B-negation'), tag('B-predicate'), tag('B-modal')])]:
            self.assertEqual(m.interpret(text, tags, 'event')['status'], 'abstained')

    def test_learned_reject_must_retain_valid_raw_bio_evidence(self):
        m = module()
        for tags in [[], [999], ['1']]:
            with self.assertRaises(ValueError): m.interpret('我', tags, 'reject')

    def test_quality_gate_requires_coverage_rejection_entity_and_pair_gains(self):
        m = module()
        good = {'supported_correct_rate': .99, 'wrong_accepts': 0, 'unsupported_false_accepts': 0,
                'entity_correct_rate': 1., 'scope_correct_rate': .99, 'complete_pairs_pass_rate': 1.}
        self.assertTrue(all(m.quality_gates(good).values()))
        for key, value in [('supported_correct_rate', 0), ('wrong_accepts', 1), ('unsupported_false_accepts', 1),
                           ('entity_correct_rate', .5), ('scope_correct_rate', .4), ('complete_pairs_pass_rate', .7)]:
            self.assertFalse(all(m.quality_gates(dict(good, **{key: value})).values()))

    def test_missing_required_metric_is_failure_not_type_error_or_implicit_pass(self):
        m = module()
        empty = {'supported_correct_rate': None, 'wrong_accepts': 0, 'unsupported_false_accepts': 0,
                 'entity_correct_rate': None, 'scope_correct_rate': None, 'complete_pairs_pass_rate': None}
        self.assertFalse(all(m.quality_gates(empty).values()))

    def test_single_clause_validation_does_not_erase_internal_punctuation(self):
        m = module()
        self.assertEqual(m.input_text(' 我想去。 '), '我想去')
        for text in ['我。去', '我；去', '我\x00去', '', None, '我' * 65, 'hello']:
            with self.assertRaises(ValueError): m.input_text(text)

    def test_reconstruction_rejects_forged_prediction_and_false_eos_equivalents(self):
        m = module(); labels = m.s.base.LABELS
        row = m.sample([('actor', '我们')], 'group', 'dev', 'entity')
        p = {'id': row['id'], 'text': row['text'], 'raw_kind': 'entity',
             'raw_BIO': [labels.index('B-actor'), labels.index('I-actor')]}
        p['prediction'] = m.interpret(p['text'], p['raw_BIO'], p['raw_kind'])
        m.validate_predictions([row], [p])
        forged = json.loads(json.dumps(p)); forged['prediction']['roles']['actor'] = '我'
        with self.assertRaises(ValueError): m.validate_predictions([row], [forged])

    def test_preparation_retains_legacy_and_excludes_all_previous_development_texts_from_train(self):
        m = module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); prior = root / 'prior'; prior.mkdir()
            fixture = {**m.s.GATES, 'schema': m.s.SCHEMA, 'frozen_before_current_round_evaluation': True, 'rows': m.s.cases()}
            m.u.base.write_json(prior / 'frozen-cases.json', fixture); m.u.seal(prior)
            legacy = Path(__file__).parent / 'fixtures/semantic-contrast-v1.json'
            with patch.object(m.t, 'check_encoder', return_value={}):
                m.prepare(prior, legacy, root / 'encoder-not-read', root / 'prepared')
            data, rows, plan, _ = m.read_prepared(root / 'prepared')
            old_dev = {r['text'] for r in fixture['rows'] if r['partition'] == 'dev'}
            self.assertFalse(old_dev & {r['text'] for r in data['train']})
            self.assertEqual(sum(r['partition'] == 'legacy_diagnostic' for r in rows), 76)
            self.assertEqual((root / 'prepared/legacy-diagnostic.json').read_bytes(), legacy.read_bytes())
            reserved = json.loads((root / 'prepared/reserved-texts.json').read_text())
            reserved.pop()
            m.u.base.write_json(root / 'prepared/reserved-texts.json', reserved); m.u.seal(root / 'prepared')
            with self.assertRaises(ValueError): m.read_prepared(root / 'prepared')


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Existing optional torch required')
class TensorTests(unittest.TestCase):
    def test_padded_features_do_not_change_predictions_and_gradients_are_finite(self):
        import torch
        m = module(); torch.manual_seed(2); model = m.make_model(); model.eval()
        features = torch.randn((2, 4, 768)); lengths = torch.tensor([2, 4])
        a = model(features, lengths)
        padded = features.clone(); padded[0, 2:] = 1000
        b = model(padded, lengths)
        self.assertTrue(torch.equal(a[0], b[0]))
        self.assertTrue(torch.equal(a[1][0, :2], b[1][0, :2]))
        self.assertEqual(tuple(a[0].shape), (2, 3))
        self.assertEqual(tuple(a[1].shape), (2, 4, len(m.s.base.LABELS)))
        loss = a[0].square().mean() + a[1].square().mean(); loss.backward()
        self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))

    def test_checkpoint_dtype_shape_finite_contract(self):
        import torch
        m = module(); model = m.make_model(); state = {k: v.clone() for k, v in model.state_dict().items()}
        m.restore(model, state)
        for kind in ['missing', 'dtype', 'nan']:
            bad = dict(state); key = next(iter(bad))
            if kind == 'missing': bad.pop(key)
            elif kind == 'dtype': bad[key] = bad[key].double()
            else: bad[key] = torch.full_like(bad[key], float('nan'))
            with self.assertRaises(ValueError): m.restore(model, bad)

    def test_train_refuses_cpu_before_input_read(self):
        from unittest.mock import patch
        import torch
        m = module()
        with patch.object(torch.cuda, 'is_available', return_value=False):
            with self.assertRaisesRegex(ValueError, 'CUDA'):
                m.train(Path('not-read'), Path('not-read'), Path('unused'))


if __name__ == '__main__': unittest.main()
