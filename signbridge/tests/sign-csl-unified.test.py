"""Unified research trainer contracts; tiny CPU forwards only, never training."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-unified.py'
LABELS = ['O'] + [p + r for r in ['actor', 'predicate', 'patient', 'goal', 'time',
    'negation', 'modal', 'question', 'aspect', 'politeness', 'degree'] for p in ['B-', 'I-']]


def module():
    if not TOOL.is_file():
        raise AssertionError('Unified trainer implementation is missing')
    spec = importlib.util.spec_from_file_location('unified_test', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def row(task, identity, text, target):
    return {'id': identity, 'text': text, 'task': task, 'human_approved': False,
            'label_source': 'ce_csl_dataset' if task == 'gloss' else 'assistant_synthetic_chinese',
            'gloss_sequence' if task == 'gloss' else 'tags': target}


def manifest(m, root):
    (root / 'SHA256SUMS').write_text(''.join(f'{m.base.sha(p)}  {p.relative_to(root).as_posix()}\n'
        for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))


def package(m, root):
    for task in ['gloss', 'roles']:
        for split, text in [('train', '我去'), ('dev', '你来')]:
            target = [text[0], text[1]] if task == 'gloss' else [1, 3]
            (root / f'{task}-{split}.jsonl').write_text(
                json.dumps(row(task, task + split, text, target), ensure_ascii=False) + '\n')
    m.base.write_json(root / 'role-labels.json', LABELS)
    m.base.write_json(root / 'report.json', {'test_read': False, 'training_ready': False,
        'model_training_ready': False, 'human_approved': False})
    (root / 'test.jsonl').write_text('{MUST NEVER BE READ')
    manifest(m, root)


class DataTests(unittest.TestCase):
    def test_package_is_hash_bound_train_only_and_never_opens_test(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); package(m, root)
            original = Path.open
            def guarded(path, *args, **kwargs):
                if path.name == 'test.jsonl':
                    self.fail('test file was opened')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded):
                data, labels, inputs = m.read_package(root)
            self.assertEqual(labels, LABELS)
            vocab = m.build_vocab(data)
            self.assertIn('我', vocab['source'])
            self.assertNotIn('你', vocab['source'])
            self.assertNotIn('来', vocab['target'])
            self.assertFalse(inputs['report']['test_read'])
            with (root / 'roles-train.jsonl').open('a') as stream:
                stream.write(' ')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.read_package(root)

    def test_bad_labels_empty_split_bool_tag_and_cross_split_overlap_rejected(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for filename, value in [('role-labels.json', ['O']),
                ('roles-train.jsonl', json.dumps(row('roles', 'bad', '我去', [True, 3]))),
                ('gloss-dev.jsonl', ''),
                ('gloss-dev.jsonl', json.dumps(row('gloss', 'new', '我去', ['另']))),
                ('gloss-dev.jsonl', json.dumps(row('gloss', 'new', '别句', ['我', '去']))),
                ('report.json', {'test_read': True})]:
                with self.subTest(filename=filename, value=value):
                    package(m, root)
                    (root / filename).write_text(json.dumps(value) if isinstance(value, (list, dict)) else value)
                    manifest(m, root)
                    with self.assertRaises(ValueError):
                        m.read_package(root)

    def test_symlinked_root_parent_nested_file_and_traversal_are_rejected(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve(); root = parent / 'real'; root.mkdir(); package(m, root)
            link = parent / 'alias'; link.symlink_to(root, target_is_directory=True)
            for path in [link, link / 'unused' / '..']:
                with self.assertRaisesRegex(ValueError, 'symlink|path'):
                    m.safe_path(path)
            for name in ['../escape', '/absolute', 'x/../report.json']:
                with self.assertRaises(ValueError):
                    m.checked(root, name, {}, {})
            target = root / 'roles-train.jsonl'; saved = parent / 'saved'; target.rename(saved); target.symlink_to(saved)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                m.read_package(root)
            existing = parent / 'output'; existing.mkdir()
            with self.assertRaises(ValueError):
                m.new_output(existing, [root])
            with self.assertRaises(ValueError):
                m.new_output(root / 'nested', [root])

    def test_cli_defaults_and_cuda_only_guard(self):
        m = module()
        args = m.parser().parse_args(['train', '--package', 'p', '--initial-model', 'i', '--output', 'o'])
        self.assertEqual((args.device, args.epochs, args.batch_size, args.learning_rate,
            args.role_weight, args.seed, args.patience, args.threads), ('cuda', 30, 64, .0002, .3, 20261023, 8, 4))
        with self.assertRaisesRegex(ValueError, 'CUDA'):
            m.cuda_device('cpu')
        if importlib.util.find_spec('torch'):
            with patch('torch.cuda.is_available', return_value=False):
                with self.assertRaisesRegex(ValueError, 'CUDA'):
                    m.cuda_device('cuda')

    def test_alternating_batches_keep_both_tasks_without_dropping_tail(self):
        m = module()
        data = {'gloss': {'train': list(range(5))}, 'roles': {'train': list(range(3))}}
        batches = list(m.training_batches(data, 2))
        self.assertEqual([task for task, _ in batches], ['gloss', 'roles', 'gloss', 'roles', 'gloss'])
        for task in data:
            self.assertEqual(sorted(x for t, rows in batches if t == task for x in rows), data[task]['train'])

    def test_raw_o_invalid_bio_and_operator_scope_are_never_certified(self):
        m = module()
        support = {'orders': [['actor', 'predicate']], 'values': {'actor': ['我'], 'predicate': ['去']},
                   'arguments': {}, 'characters': list('我去')}
        good = m.parse_roles('我去', [1, 3], LABELS, support)
        self.assertEqual(good['roles'], {'actor': '我', 'predicate': '去'})
        for text, tags, reason in [('我去', [0, 3], 'unresolved_O'),
            ('我去', [2, 3], 'invalid_BIO'), ('我去', [1, 1], 'unsupported_role_structure'),
            ('我不想不去', [1, 11, 13, 11, 3], 'operator_scope_unresolved')]:
            out = m.parse_roles(text, tags, LABELS, support)
            self.assertIn(reason, out['uncertainty'])
            self.assertEqual(out['roles'], {})
            self.assertEqual(out['raw_tags'], [LABELS[t] for t in tags])
            self.assertIsNone(out['scope'])


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Existing optional PyTorch runtime required')
class ModelTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch; torch.set_num_threads(1); torch.manual_seed(7)
        self.m = module()
        self.config = {'width': 8, 'heads': 2, 'layers': 1, 'feedforward': 16,
                       'dropout': 0., 'max_source': 128, 'max_target': 64}
        self.vocab = {'source': self.m.base.SPECIALS + list('我去旧'),
                      'target': self.m.base.SPECIALS + ['我', '去', '旧']}

    def initial(self, root):
        m = self.m; checkpoint = root / 'checkpoints/epoch-040.pt'; checkpoint.parent.mkdir()
        model = m.base.make_model(self.vocab, self.config)
        self.torch.save(model.state_dict(), checkpoint)
        digest = m.base.sha(checkpoint)
        m.base.write_json(root / 'model.json', {'schema': 'signbridge-ce-csl-text-to-gloss-v1',
            'research_only': True, 'config': self.config, 'checkpoint': 'checkpoints/epoch-040.pt', 'checkpoint_sha256': digest})
        m.base.write_json(root / 'vocab.json', self.vocab)
        m.base.write_json(root / 'report.json', {'status': 'completed', 'checkpoint': 'checkpoints/epoch-040.pt',
            'checkpoint_sha256': digest, 'selected_epoch': 40})
        manifest(m, root)
        with (root / 'SHA256SUMS').open('a') as stream:
            stream.write('a' * 64 + '  historical-missing-file.json\n')
        return model, digest

    def test_pinned_initial_weights_remap_tokens_and_keep_other_parameters_exact(self):
        m = self.m; torch = self.torch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); old, digest = self.initial(root)
            with self.assertRaisesRegex(ValueError, 'checkpoint|digest'):
                m.read_initial(root)
            with patch.object(m, 'INITIAL_SHA', digest):
                initial = m.read_initial(root)
            new_vocab = {'source': m.base.SPECIALS + list('去我新'),
                         'target': m.base.SPECIALS + ['去', '我', '新']}
            model, info = m.initialize_model(new_vocab, LABELS, initial)
            self.assertEqual(info['source_tokens_added'], ['新'])
            self.assertEqual(info['source_tokens_lost'], ['旧'])
            self.assertFalse(info['optimizer_state_restored'])
            for key in ['source.weight', 'target.weight', 'output.weight', 'output.bias']:
                side = 'source' if key.startswith('source') else 'target'
                for token in set(self.vocab[side]) & set(new_vocab[side]):
                    self.assertTrue(torch.equal(old.state_dict()[key][self.vocab[side].index(token)],
                        model.state_dict()[key][new_vocab[side].index(token)]))
            for key, value in old.state_dict().items():
                if key not in ['source.weight', 'target.weight', 'output.weight', 'output.bias']:
                    self.assertTrue(torch.equal(value, model.state_dict()[key]), key)
            self.assertIsInstance(model.role_head, torch.nn.Linear)
            initial['state']['unexpected.weight'] = torch.zeros(1)
            with self.assertRaisesRegex(ValueError, 'parameters'):
                m.initialize_model(new_vocab, LABELS, initial)

    def test_initial_checkpoint_parent_symlink_and_report_tamper_rejected(self):
        m = self.m
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve(); root = parent / 'model'; root.mkdir(); _, digest = self.initial(root)
            with patch.object(m, 'INITIAL_SHA', digest):
                saved = parent / 'saved'; (root / 'checkpoints').rename(saved)
                (root / 'checkpoints').symlink_to(saved, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    m.read_initial(root)
                (root / 'checkpoints').unlink(); saved.rename(root / 'checkpoints')
                (root / 'report.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'digest'):
                    m.read_initial(root)

    def test_forward_losses_ignore_role_padding_and_share_encoder_gradients(self):
        m = self.m; torch = self.torch
        initial = {'metadata': {'config': self.config}, 'vocab': self.vocab,
                   'state': m.base.make_model(self.vocab, self.config).state_dict()}
        model, _ = m.initialize_model(self.vocab, LABELS, initial)
        roles = [row('roles', 'a', '我去', [1, 3]), row('roles', 'b', '我', [1])]
        source, target = m.task_batch(roles, 'roles', self.vocab, 'cpu')
        self.assertEqual(tuple(source.shape), (2, 4))
        self.assertEqual(target.tolist(), [[-100, 1, 3, -100], [-100, 1, -100, -100]])
        self.assertEqual(tuple(model.role_head(model.encode(source)).shape), (2, 4, 23))
        loss = m.task_loss(model, source, target, 'roles')
        self.assertEqual(loss.ndim, 0); self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertGreater(float(model.source.weight.grad.abs().sum()), 0)
        self.assertIsNone(model.target.weight.grad)
        model.zero_grad(set_to_none=True)
        source, target = m.task_batch([row('gloss', 'c', '我去', ['我', '去'])], 'gloss', self.vocab, 'cpu')
        loss = m.task_loss(model, source, target, 'gloss'); loss.backward()
        self.assertGreater(float(model.target.weight.grad.abs().sum()), 0)

    def test_cpu_inference_verifies_all_files_and_marks_unknown_structure(self):
        m = self.m; torch = self.torch
        initial = {'metadata': {'config': self.config}, 'vocab': self.vocab,
                   'state': m.base.make_model(self.vocab, self.config).state_dict()}
        model, _ = m.initialize_model(self.vocab, LABELS, initial)
        with torch.no_grad():
            model.role_head.weight.zero_(); model.role_head.bias.zero_(); model.role_head.bias[0] = 9
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); checkpoint = root / 'weights.pt'; torch.save(model.state_dict(), checkpoint)
            metadata = {'schema': m.SCHEMA, 'research_only': True, 'config': self.config,
                'checkpoint': checkpoint.name, 'checkpoint_sha256': m.base.sha(checkpoint), 'support': {}}
            m.base.write_json(root / 'model.json', metadata); m.base.write_json(root / 'vocab.json', self.vocab)
            m.base.write_json(root / 'role-labels.json', LABELS); manifest(m, root)
            out = m.infer(root, '我去')
            self.assertFalse(out['can_play']); self.assertFalse(out['human_approved'])
            self.assertEqual(out['status'], 'unsupported')
            self.assertIn('unresolved_O', out['uncertainty'])
            self.assertEqual(out['device'], 'cpu')
            unknown = m.infer(root, '😀')
            self.assertEqual(unknown['status'], 'unsupported')
            self.assertEqual(unknown['unseen_input_characters'], ['😀'])
            (root / 'vocab.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.infer(root, '我去')

    def test_recovery_checkpoint_has_optimizer_rng_and_weights_are_separate(self):
        m = self.m; torch = self.torch
        model = m.base.make_model(self.vocab, self.config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.0002)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'recovery.pt'
            m.save_recovery(path, model, optimizer, 3, 7, {'selected_epoch': 2, 'stale': 1})
            payload = torch.load(path, map_location='cpu', weights_only=True)
            self.assertEqual((payload['epoch'], payload['steps']), (3, 7))
            for key in ['model', 'optimizer', 'python_rng', 'torch_rng', 'cuda_rng', 'selection']:
                self.assertIn(key, payload)


if __name__ == '__main__':
    unittest.main()
