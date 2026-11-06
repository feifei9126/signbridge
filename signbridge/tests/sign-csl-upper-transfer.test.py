"""Warm continuation control vs adapting only the last two BERT blocks."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-upper-transfer.py'


def module():
    spec = importlib.util.spec_from_file_location('upper_transfer_test', TOOL)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class ContractTests(unittest.TestCase):
    def test_fixed_paired_budget_and_distinct_learning_rates(self):
        m = module()
        self.assertEqual(m.SETTINGS['epochs'], 8)
        self.assertEqual(m.SETTINGS['expected_steps_per_arm'], 552)
        self.assertEqual(m.SETTINGS['decoder_lr'], .0002)
        self.assertEqual(m.SETTINGS['encoder_lr'], .00002)
        self.assertEqual(m.ARMS, ['frozen-continuation', 'upper2-adaptation'])
        for key in ['training_ready', 'model_training_ready', 'can_play', 'test_read', 'holdout_H_read', 'human_approved']:
            self.assertIs(m.GATES[key], False)

    def test_lower_total_error_cannot_hide_missing_negation_or_more_deletions(self):
        m = module()
        baseline = {'raw_gloss': {'gloss_error_rate': .7, 'deletions': 10},
                    'slices': {'person': {'gloss_error_rate': .6}, 'negation': {'gloss_error_rate': .5}}}
        metrics = {**baseline, 'malformed_rows': 0, 'empty_prediction_rows': 0, 'missing_eos_rows': 0, 'abstained_rows': 0}
        good = {'metrics': metrics, 'guardrails': m.guardrails(metrics, baseline)}
        worse = {**metrics, 'raw_gloss': {'gloss_error_rate': .65, 'deletions': 11}}
        results = {'frozen-continuation': good,
                   'upper2-adaptation': {'metrics': worse, 'guardrails': m.guardrails(worse, baseline)}}
        self.assertEqual(m.preferred_arm(results, baseline), 'frozen-continuation')
        results['upper2-adaptation']['guardrails'] = {}
        with self.assertRaises(ValueError): m.preferred_arm(results, baseline)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Existing optional torch required')
class TensorTests(unittest.TestCase):
    def fake_encoder(self):
        import torch
        class Encoder(torch.nn.Module):
            def __init__(self):
                super().__init__(); self.config = SimpleNamespace(hidden_size=768)
                self.embeddings = torch.nn.Embedding(8, 768)
                self.encoder = torch.nn.Module()
                self.encoder.layer = torch.nn.ModuleList([torch.nn.Linear(1, 1) for _ in range(12)])
            def forward(self, input_ids, attention_mask, return_dict):
                hidden = self.embeddings(input_ids)
                for layer in self.encoder.layer: hidden = hidden + layer(hidden[:, :, :1])
                return SimpleNamespace(last_hidden_state=hidden)
        return Encoder()

    def test_only_final_two_blocks_receive_gradients_while_lower_blocks_stay_frozen(self):
        import torch
        m = module(); vocab = {'source': m.g.u.base.SPECIALS + ['我'], 'target': m.g.u.base.SPECIALS + ['<gloss_end>', '我', '不']}
        model = m.make_model(self.fake_encoder(), vocab, True); model.train()
        self.assertFalse(model.encoder.training)
        self.assertTrue(all(not layer.training for layer in model.encoder.encoder.layer))
        self.assertFalse(model.encoder.embeddings.weight.requires_grad)
        self.assertTrue(all(p.requires_grad for layer in model.encoder.encoder.layer[-2:] for p in layer.parameters()))
        before = m.frozen_hash(model)
        out = model(torch.tensor([[2, 4, 3]]), torch.tensor([[2, 5]])); out.mean().backward()
        self.assertTrue(any(p.grad is not None for p in model.encoder.encoder.layer[-1].parameters()))
        self.assertTrue(all(p.grad is None for layer in model.encoder.encoder.layer[:-2] for p in layer.parameters()))
        self.assertTrue(all(p.grad is None for p in model.encoder.embeddings.parameters()))
        self.assertEqual(before, m.frozen_hash(model))

    def test_control_has_no_encoder_gradients_and_checkpoint_cannot_cross_arms(self):
        import torch
        m = module(); vocab = {'source': m.g.u.base.SPECIALS + ['我'], 'target': m.g.u.base.SPECIALS + ['<gloss_end>', '我']}
        control = m.make_model(self.fake_encoder(), vocab, False)
        self.assertTrue(all(not p.requires_grad for p in control.encoder.parameters()))
        adapted = m.make_model(self.fake_encoder(), vocab, True)
        state = m.trainable_state(adapted); m.load_trainable(adapted, state)
        self.assertTrue(any(k.startswith('encoder.encoder.layer.10.') for k in state))
        self.assertFalse(any(k.startswith('encoder.encoder.layer.9.') for k in state))
        with self.assertRaises(ValueError): m.load_trainable(control, state)
        key = next(iter(state)); bad = dict(state); bad[key] = state[key].double()
        with self.assertRaises(ValueError): m.load_trainable(adapted, bad)
        bad = dict(state); bad[key] = torch.full_like(state[key], float('nan'))
        with self.assertRaises(ValueError): m.load_trainable(adapted, bad)

    def test_training_refuses_cpu_before_reading_any_input(self):
        from unittest.mock import patch
        import torch
        m = module()
        with patch.object(torch.cuda, 'is_available', return_value=False):
            with self.assertRaisesRegex(ValueError, 'CUDA'):
                m.train(Path('not-read'), Path('not-read'), Path('unused'))


if __name__ == '__main__': unittest.main()
