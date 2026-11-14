"""Structural decoding must not manufacture semantic correctness or erase repeats."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-guarded-decoding.py'


def module():
    spec = importlib.util.spec_from_file_location('guarded_decoding_test', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ContractTests(unittest.TestCase):
    def test_repeat_limit_uses_training_only_and_keeps_legal_triples(self):
        m = module()
        self.assertEqual(m.repeat_limit([{'gloss_sequence': ['走', '走', '走']}]), 3)
        p = {'predicted': ['走', '走', '走'], 'terminated': True, 'representation_errors': []}
        self.assertEqual(m.assess(p, 3)['status'], 'research_candidate')
        bad = dict(p, predicted=['走'] * 4)
        self.assertEqual(m.assess(bad, 3)['reasons'], ['repetition_beyond_training_support'])
        self.assertEqual(bad['predicted'], ['走'] * 4)

    def test_malformed_outputs_abstain_without_rewriting_raw_prediction(self):
        m = module()
        p = {'predicted': ['都', '<invalid_gloss>:eos'], 'terminated': False,
             'representation_errors': ['missing_eos']}
        report = m.assess(p, 3)
        self.assertEqual(report['status'], 'abstained')
        self.assertIn('missing_eos', report['reasons'])
        self.assertFalse(report['can_play'])
        self.assertFalse(report['semantics_approved'])
        self.assertEqual(p['predicted'], ['都', '<invalid_gloss>:eos'])

    def test_no_semantic_promotion_for_valid_syntax(self):
        m = module()
        result = m.assess({'predicted': ['你'], 'terminated': True, 'representation_errors': []}, 3)
        self.assertEqual(result['status'], 'research_candidate')
        for key in ['can_play', 'human_approved', 'training_ready', 'model_training_ready', 'semantics_approved']:
            self.assertIs(result[key], False)

    def test_input_rejects_bad_types_empty_controls_and_overlong_before_tokenization(self):
        m = module()
        for text in [None, 4, '', '  ', '？！', '我\x00', '我' * 127]:
            with self.assertRaises(ValueError): m.input_text(text)
        self.assertEqual(m.input_text(' 我，要去。 '), '我要去')

    def test_result_requires_every_prediction_and_recomputed_guardrail(self):
        m = module()
        rows = [{'id': 'a', 'text': '我', 'gloss_sequence': ['我']},
                {'id': 'b', 'text': '不', 'gloss_sequence': ['不']}]
        vocab = {'target': ['<pad>', '<unk>', '<bos>', '<eos>', '<gloss_end>', '我', '不']}
        predictions = [m.record(r, {'tokens': [i + 5, 4, 3], 'score': -1., 'length': 3}, vocab, 3)
                       for i, r in enumerate(rows)]
        baseline = {'selected_metrics': m.t.c.metrics(rows, predictions)}
        saved = [{k: v for k, v in p.items() if k not in ('search', 'quality', 'score_is_calibrated_confidence')} for p in predictions]
        data = {'selection': rows}
        plan = {'repeat_limit_from_train': 3}
        state = (None, None, data, vocab, plan, baseline, saved, {})
        metrics = m.score(rows, predictions)
        gates = {**m.f.adoption_gates(metrics, baseline['selected_metrics']), 'no_structural_abstentions': True}
        report = {**m.GATES, 'schema': m.SCHEMA, 'status': 'completed', 'inputs': {}, 'plan': plan,
                  'weights_unchanged': True, 'optimizer_steps': 0, 'baseline_reproduced': True,
                  'reference_free_baseline_reproduced': True, 'tool_sha256': m.source_hashes(),
                  'preferred_research_decoder': 'syntax-greedy',
                  'results': {name: {'metrics': metrics, **({'guardrails': gates} if name != 'raw-greedy' else {})}
                              for name in ['raw-greedy', 'syntax-greedy', 'syntax-beam4']}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            def write(value):
                m.u.base.write_json(root / 'report.json', value)
                m.u.seal(root)
            for name in report['results']:
                m.u.base.write_json(root / (name + '-predictions.json'), predictions)
            write(report)
            self.assertEqual(m.read_result(root, state)[0], 'syntax-greedy')
            for field in ['baseline_reproduced', 'reference_free_baseline_reproduced', 'tool_sha256']:
                write(dict(report, **{field: False}))
                with self.assertRaises(ValueError): m.read_result(root, state)
            bad = json.loads(json.dumps(report)); bad['results']['syntax-greedy']['guardrails'] = {}
            write(bad)
            with self.assertRaises(ValueError): m.read_result(root, state)
            bad = json.loads(json.dumps(report)); bad['results']['syntax-greedy']['metrics']['raw_gloss']['gloss_error_rate'] = .1
            write(bad)
            with self.assertRaises(ValueError): m.read_result(root, state)
            write(report)
            missing = root / 'syntax-beam4-predictions.json'
            missing.unlink(); m.u.seal(root)
            with self.assertRaises(ValueError): m.read_result(root, state)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Existing optional torch required')
class TensorTests(unittest.TestCase):
    def test_grammar_scores_preserve_original_probabilities_and_valid_eos(self):
        import torch
        m = module()
        logits = torch.zeros((3, 8))
        previous = torch.tensor([2, 5, 4])
        scores = m.grammar_scores(logits, previous, 4)
        for i in [0, 1, 2]: self.assertTrue(torch.isneginf(scores[:, i]).all())
        self.assertTrue(torch.isneginf(scores[0, 3:5]).all())
        self.assertTrue(torch.isneginf(scores[1, 3]))
        self.assertTrue(torch.isfinite(scores[1, 4]))
        self.assertTrue(torch.isfinite(scores[2, 3]))
        self.assertTrue(torch.isneginf(scores[2, 4]))
        self.assertAlmostEqual(float(scores[2, 3]), float(torch.log_softmax(logits, -1)[2, 3]))

    def test_no_forced_eos_at_budget_and_reference_never_used(self):
        import torch
        m = module()
        class Model:
            def eval(self): return self
            def encode(self, source): return source[:, :, None].float()
            def decode(self, target, memory, padding):
                logits = torch.full((*target.shape, 7), -20.)
                logits[:, -1, 5] = 20.
                return logits
        source = torch.tensor([[2, 5, 3]])
        raw = m.search(Model(), source, 7, end_id=4, width=1, max_steps=5)[0]
        self.assertNotIn(3, raw['tokens'])
        vocab = {'target': ['<pad>', '<unk>', '<bos>', '<eos>', '<gloss_end>', '都', '我']}
        record = m.record({'id': 'a', 'text': '我', 'gloss_sequence': ['我']}, raw, vocab, 3)
        self.assertFalse(record['terminated'])
        self.assertEqual(record['quality']['status'], 'abstained')
        self.assertIn('missing_eos', record['representation_errors'])

    def test_greedy_keeps_three_repeats_and_stops_at_real_eos(self):
        import torch
        m = module()
        class Model:
            def eval(self): return self
            def encode(self, source): return source[:, :, None].float()
            def decode(self, target, memory, padding):
                plan = [5, 4, 5, 4, 5, 4, 3]
                logits = torch.full((*target.shape, 8), -20.)
                logits[:, -1, plan[min(target.size(1)-1, len(plan)-1)]] = 20.
                return logits
        source = torch.tensor([[2, 6, 3]])
        candidate = m.search(Model(), source, 8, 4, 1, 15)[0]
        self.assertEqual(candidate['tokens'], [5, 4, 5, 4, 5, 4, 3])
        self.assertEqual(candidate['length'], 7)

    def test_beams_keep_endings_and_length_instead_of_appending_fake_words(self):
        import torch
        m = module()
        class Model:
            def eval(self): return self
            def encode(self, source): return source[:, :, None].float()
            def decode(self, target, memory, padding):
                logits = torch.full((*target.shape, 8), -20.)
                for i, seq in enumerate(target.tolist()):
                    if seq[-1] == 2: logits[i, -1, 5:7] = torch.tensor([2., 1.9])
                    elif seq[-1] in [5, 6]: logits[i, -1, 4] = 10.
                    else: logits[i, -1, 3] = 10.
                return logits
        source = torch.tensor([[2, 6, 3], [2, 7, 3]])
        a = m.search(Model(), source, 8, 4, 4, 15)
        self.assertEqual(len(a), 2)
        for p in a:
            self.assertEqual(p['tokens'], [5, 4, 3])
            self.assertEqual(p['length'], 3)
            self.assertTrue(torch.isfinite(torch.tensor(p['score'])))

    def test_source_generation_has_no_reference_or_target_dependency(self):
        import torch
        m = module()
        class Tokenizer:
            pad_token_id = 0
            def __call__(self, text, **kwargs):
                return {'input_ids': torch.tensor([[2, 5, 3] for _ in text])}
        a = m.source_batch([{'text': '我', 'gloss_sequence': ['未知'] * 300}], Tokenizer(), 'cpu')
        b = m.source_batch([{'text': '我'}], Tokenizer(), 'cpu')
        self.assertTrue(torch.equal(a, b))

    def test_nonfinite_and_bad_search_contract_fail_closed(self):
        import torch
        m = module()
        with self.assertRaisesRegex(ValueError, 'Nonfinite'):
            m.grammar_scores(torch.tensor([[float('nan')] * 7]), torch.tensor([2]), 4)
        for width, max_steps in [(0, 63), (2, 63), (4, 64), (1, 0)]:
            with self.assertRaises(ValueError):
                m.search(None, torch.tensor([[2, 3]]), 8, 4, width, max_steps)


if __name__ == '__main__': unittest.main()
