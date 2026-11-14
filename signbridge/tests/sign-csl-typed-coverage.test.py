"""Coverage augmentation cannot move old developer diagnostics into training."""
import importlib.util
from pathlib import Path
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-typed-coverage.py'


def module():
    spec = importlib.util.spec_from_file_location('typed_coverage_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class ContractTests(unittest.TestCase):
    def test_multicharacter_entity_and_old_goal_coverage_without_prior_dev_leak(self):
        m = module(); frozen = m.b.s.cases()
        reserved = {m.b.s.normalize(r['text']) for r in frozen if r['partition'] == 'challenge'}
        dev_reserved = {m.b.s.normalize(r['text']) for r in frozen if r['partition'] == 'dev'}
        data, additions = m.expand(reserved, dev_reserved)
        self.assertTrue(all(r['text'] not in reserved | dev_reserved for r in data['train']))
        self.assertTrue(any(r['expected_kind'] == 'entity' and len(r['text']) > 1 for r in data['train']))
        self.assertTrue(any(r['expected_roles'] and r['expected_roles'].get('goal') == '公司' for r in data['train']))
        self.assertFalse({r['text'] for r in data['train']} & {r['text'] for r in data['dev']})
        self.assertFalse({r['split_group'] for r in data['train']} & {r['split_group'] for r in data['dev']})
        old = m.b.corpus(reserved, dev_reserved)
        for split in ['train', 'dev']:
            self.assertEqual(data[split][:len(old[split])], old[split])
        self.assertGreater(additions['train'], 0)

    def test_expanded_contract_only_validates_learned_roles_never_fills_them(self):
        m = module(); tag = m.b.s.base.LABELS.index
        p = m.interpret('我去公司', [tag('B-actor'), tag('B-predicate'), tag('B-goal'), tag('I-goal')], 'event')
        self.assertEqual(p['roles'], {'actor': '我', 'predicate': '去', 'goal': '公司'})
        self.assertEqual(p['status'], 'parsed')
        self.assertEqual(m.interpret('小王', [0, 0], 'entity')['status'], 'abstained')
        self.assertEqual(m.interpret('小王', [tag('B-actor'), tag('I-actor')], 'entity')['status'], 'parsed')
        self.assertEqual(m.interpret('我喝公司', [tag('B-actor'), tag('B-predicate'), tag('B-patient'), tag('I-patient')], 'event')['status'], 'abstained')

    def test_baseline_contract_disagreement_stays_visible(self):
        m = module(); tag = m.b.s.base.LABELS.index
        # Legacy fixture rejects this within its old narrow contract; the current
        # single-event Chinese contract intentionally supports it. Never change gold.
        p = m.interpret('我可以不去', [tag('B-actor'), tag('B-modal'), tag('I-modal'), tag('B-negation'), tag('B-predicate')], 'event')
        self.assertEqual(p['status'], 'parsed')
        self.assertFalse(p['can_play'])
        self.assertTrue(m.LIMITS)

    def test_malformed_raw_predictions_are_not_repaired_by_expanded_values(self):
        m = module(); tag = m.b.s.base.LABELS.index
        for tags in [[], [999, 999], ['1', '2']]:
            with self.assertRaises(ValueError): m.interpret('小王', tags, 'reject')
        self.assertEqual(m.interpret('小王', [tag('I-actor'), tag('I-actor')], 'entity')['status'], 'abstained')


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Existing optional torch required')
class TensorTests(unittest.TestCase):
    def test_coverage_training_refuses_cpu_before_any_input(self):
        import torch
        from unittest.mock import patch
        m = module()
        with patch.object(torch.cuda, 'is_available', return_value=False):
            with self.assertRaisesRegex(ValueError, 'CUDA'):
                m.train(Path('not-read'), Path('not-read'), Path('unused'))


if __name__ == '__main__': unittest.main()
