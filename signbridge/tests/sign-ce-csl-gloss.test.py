"""Text-to-gloss experiments cannot consume evaluation labels in their vocabulary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-ce-csl-gloss.py'


def module():
    spec = importlib.util.spec_from_file_location('ce_csl_gloss', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sample(identity, split, text, gloss, checksum='a' * 64):
    return {'id': identity, 'source_split': split, 'proposed_text': text,
            'gloss_sequence': gloss, 'video': {'sha256': checksum}}


class GlossTests(unittest.TestCase):
    def test_vocab_is_learned_from_train_only_and_preserves_variant_ids(self):
        m = module()
        data = {'train': [sample('train1', 'train', '我考试', ['我', '考试1', '考试2'])],
                'dev': [sample('dev1', 'dev', '罕见字', ['只有评估'])], 'test': []}
        vocab = m.build_vocab(data['train'])
        self.assertNotIn('罕', vocab['source'])
        self.assertNotIn('只有评估', vocab['target'])
        self.assertIn('考试1', vocab['target'])
        self.assertIn('考试2', vocab['target'])

    def test_raw_unknown_reference_is_counted_as_error_instead_of_matching_unk(self):
        m = module()
        metric = m.metrics([['新词']], [['<unk>']])
        self.assertEqual(metric['gloss_error_rate'], 1.0)
        self.assertEqual(metric['exact_match_rate'], 0.0)
        self.assertEqual(m.metrics([['我', '去']], [['我', '去']])['gloss_error_rate'], 0.0)
        self.assertEqual(m.metrics([['我', '去']], [[]])['deletions'], 2)
        self.assertEqual(m.metrics([['我']], [['我', '去']])['insertions'], 1)

    def test_nonoverlap_slice_marks_sentence_gloss_and_video_matches_separately(self):
        m = module()
        train = [sample('train1', 'train', '我去。', ['我', '去'], 'a' * 64)]
        evaluation = [sample('dev1', 'dev', '我去！', ['不同'], 'b' * 64),
                      sample('dev2', 'dev', '不同文字', ['我', '去'], 'c' * 64),
                      sample('dev3', 'dev', '另一句', ['别的'], 'a' * 64),
                      sample('dev4', 'dev', '无重叠', ['新的'], 'd' * 64)]
        result = m.overlap_flags(train, evaluation)
        self.assertEqual(result[0]['reasons'], ['normalized_source_in_train'])
        self.assertEqual(result[1]['reasons'], ['target_sequence_in_train'])
        self.assertEqual(result[2]['reasons'], ['video_bytes_in_train'])
        self.assertEqual(result[3]['reasons'], [])

    def test_literal_baseline_returns_numbered_gloss_without_learning_eval_labels(self):
        m = module()
        train = [sample('t1', 'train', '我考试', ['我', '考试1'])]
        baseline = m.LexiconBaseline(train)
        self.assertEqual(baseline.predict('我考试。'), ['我', '考试1'])
        self.assertNotEqual(baseline.predict('没见过'), ['只有评估'])

    def test_read_data_rejects_wrong_split_or_changed_file_digest(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = []
            for split in ['train', 'dev', 'test']:
                path = root / 'splits' / split / 'samples.jsonl'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(sample(split, split, '我去', ['我', '去'])) + '\n')
                manifest.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(root).as_posix())
            (root / 'SHA256SUMS').write_text('\n'.join(manifest) + '\n')
            data, inputs = m.read_data(root)
            self.assertEqual(len(data['train']), 1)
            self.assertEqual(len(inputs), 3)
            path.write_text(path.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.read_data(root)

    def test_skip_test_verifies_digest_without_parsing_test_labels(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = []
            for split in ['train', 'dev', 'test']:
                path = root / 'splits' / split / 'samples.jsonl'
                path.parent.mkdir(parents=True)
                content = (json.dumps(sample(split, split, '我去', ['我', '去'])) + '\n'
                           if split != 'test' else '{not parsed by test-excluded run}\n')
                path.write_text(content)
                manifest.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(root).as_posix())
            (root / 'SHA256SUMS').write_text('\n'.join(manifest) + '\n')

            data, inputs = m.read_data(root, include_test=False)

            self.assertEqual(len(data['train']), 1)
            self.assertEqual(len(data['dev']), 1)
            self.assertEqual(data['test'], [])
            self.assertIn('splits/test/samples.jsonl', inputs)
            path.write_text(content + 'changed')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.read_data(root, include_test=False)

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'Optional training runtime not installed')
    def test_initialization_loads_only_digest_bound_compatible_weights(self):
        import torch
        m = module()
        vocab = {'source': ['<pad>', '<unk>', '<bos>', '<eos>', '我'],
                 'target': ['<pad>', '<unk>', '<bos>', '<eos>', '我']}
        config = {'width': 2, 'heads': 1, 'layers': 1, 'feedforward': 4,
                  'dropout': 0.0, 'max_source': 8, 'max_target': 8}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = torch.nn.Linear(2, 2)
            checkpoint = root / 'epoch.pt'
            torch.save(source.state_dict(), checkpoint)
            (root / 'vocab.json').write_text(json.dumps(vocab))
            (root / 'model.json').write_text(json.dumps({
                'schema': 'signbridge-ce-csl-text-to-gloss-v1',
                'research_only': True,
                'checkpoint': 'epoch.pt',
                'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                'config': config,
            }))
            (root / 'report.json').write_text(json.dumps({
                'status': 'completed',
                'checkpoint': 'epoch.pt',
                'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                'selected_epoch': 40,
                'optimizer_steps': 3120,
            }))
            target = torch.nn.Linear(2, 2)

            provenance = m.load_initial_weights(target, vocab, config, root)

            self.assertTrue(torch.equal(target.weight, source.weight))
            self.assertEqual(provenance['mode'], 'weights_only_initialization')
            self.assertFalse(provenance['optimizer_state_restored'])
            self.assertEqual(provenance['source_selected_epoch'], 40)
            self.assertEqual(provenance['source_optimizer_steps'], 3120)
            self.assertEqual(provenance['source_checkpoint_sha256'], hashlib.sha256(checkpoint.read_bytes()).hexdigest())

            changed_vocab = {**vocab, 'source': vocab['source'] + ['新字']}
            with self.assertRaisesRegex(ValueError, 'vocabulary'):
                m.load_initial_weights(torch.nn.Linear(2, 2), changed_vocab, config, root)
            changed_config = {**config, 'width': 4}
            with self.assertRaisesRegex(ValueError, 'configuration'):
                m.load_initial_weights(torch.nn.Linear(2, 2), vocab, changed_config, root)
            report_path = root / 'report.json'
            report = json.loads(report_path.read_text())
            report_path.write_text(json.dumps({**report, 'checkpoint_sha256': '0' * 64}))
            with self.assertRaisesRegex(ValueError, 'report'):
                m.load_initial_weights(torch.nn.Linear(2, 2), vocab, config, root)
            report_path.write_text(json.dumps(report))
            checkpoint.write_bytes(checkpoint.read_bytes() + b'tampered')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.load_initial_weights(torch.nn.Linear(2, 2), vocab, config, root)

    def test_empty_labels_or_overlong_sequences_are_not_silently_truncated(self):
        m = module()
        for row in [sample('bad', 'train', '我去', []),
                    sample('long', 'train', '我' * 300, ['我'])]:
            with self.assertRaises(ValueError):
                m.validate_sample(row, 'train')

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'Optional training runtime not installed')
    def test_requested_cuda_never_falls_back_to_local_cpu(self):
        m = module()
        with patch('torch.cuda.is_available', return_value=False):
            with self.assertRaisesRegex(ValueError, 'No CPU fallback'):
                m.training_device('cuda')
        with patch('torch.cuda.is_available', return_value=True):
            self.assertEqual(m.training_device('cuda').type, 'cuda')

    @unittest.skipUnless(importlib.util.find_spec('torch'), 'Optional training runtime not installed')
    def test_model_gradient_updates_and_greedy_decode_is_bounded(self):
        import torch
        m = module()
        torch.set_num_threads(2)
        torch.manual_seed(1)
        rows = [sample('t1', 'train', '我去', ['我', '去']),
                sample('t2', 'train', '你去', ['你', '去'])]
        vocab = m.build_vocab(rows)
        config = {'width': 16, 'heads': 2, 'layers': 1, 'feedforward': 32,
                  'dropout': 0.0, 'max_source': 128, 'max_target': 64}
        model = m.make_model(vocab, config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01)
        source, target = m.batch_tensors(rows, vocab, torch.device('cpu'))
        before = model.output.weight.detach().clone()
        loss = torch.nn.functional.cross_entropy(model(source, target[:, :-1]).reshape(-1, len(vocab['target'])),
                                                 target[:, 1:].reshape(-1), ignore_index=0)
        optimizer.zero_grad(); loss.backward(); optimizer.step()
        self.assertFalse(torch.equal(before, model.output.weight.detach()))
        predicted = m.greedy_decode(model, source, vocab, max_length=8)
        self.assertEqual(len(predicted), len(rows))
        self.assertTrue(all(len(p) <= 8 for p in predicted))


if __name__ == '__main__':
    unittest.main()
