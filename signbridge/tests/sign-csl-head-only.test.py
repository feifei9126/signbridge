"""Tests for frozen-backbone comparison and training isolation."""
import importlib.util
from pathlib import Path
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-head-only.py'


def module():
    spec = importlib.util.spec_from_file_location('head_only_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class Cases(unittest.TestCase):
    def test_unknown_characters_are_quarantined(self):
        m = module()
        ok, blocked = m.filter_known([{'id': 'a', 'text': '我去'}, {'id': 'b', 'text': '我买醋'}],
                                     {'source': ['<pad>', '<unk>', '<bos>', '<eos>', '我', '去', '买']})
        self.assertEqual([x['id'] for x in ok], ['a'])
        self.assertEqual(blocked, [{'id': 'b', 'unknown_characters': ['醋']}])

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'Optional torch required')
    def test_backbone_frozen_only_head_receives_gradients_and_updates(self):
        import torch
        m = module(); torch.manual_seed(6)
        vocab = {'source': m.u.base.SPECIALS + list('我去'), 'target': m.u.base.SPECIALS + ['去']}
        model = m.u.base.make_model(vocab, {'width': 8, 'heads': 2, 'layers': 1, 'feedforward': 16,
                                               'dropout': .1, 'max_source': 16, 'max_target': 16})
        model.role_head = torch.nn.Linear(8, len(m.u.ROLE_LABELS))
        before = {k: v.detach().clone() for k, v in model.state_dict().items()}
        m.freeze(model)
        optimizer = torch.optim.AdamW(model.role_head.parameters(), lr=.001)
        m.step(model, optimizer, [{'id': 'a', 'text': '我去', 'tags': [1, 3]}], vocab, 'cpu')
        for k, v in model.state_dict().items():
            self.assertEqual(torch.equal(before[k], v), not k.startswith('role_head.'), k)
        self.assertTrue(all(p.grad is None for n, p in model.named_parameters() if not n.startswith('role_head.')))


if __name__ == '__main__':
    unittest.main()
