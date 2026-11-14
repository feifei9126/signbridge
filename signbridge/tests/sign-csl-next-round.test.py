"""Next-round preparation is train-only augmentation, not motion approval."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-next-round.py'


def module():
    if not TOOL.is_file():
        raise AssertionError('Next-round preparation tool is missing')
    spec = importlib.util.spec_from_file_location('next_round_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class PreparationTests(unittest.TestCase):
    def test_frozen_cases_cover_scope_swap_transfer_and_rejection_without_csl_labels(self):
        m = module(); rows = m.contrasts()
        self.assertEqual(len(rows), len({r['id'] for r in rows}))
        self.assertEqual(len(rows), len({r['text'] for r in rows}))
        self.assertTrue({'role_swap', 'lexical_transfer', 'time_paraphrase', 'operator_scope',
                         'event_status', 'unsupported_or_ambiguous'} <= {r['template_group'] for r in rows})
        by_text = {r['text']: r for r in rows}
        self.assertNotEqual(by_text['我们不想跑步']['expected_operators'],
                            by_text['我们想不跑步']['expected_operators'])
        self.assertNotEqual(by_text['我帮你']['expected_roles'], by_text['你帮我']['expected_roles'])
        for row in rows:
            self.assertFalse(row['human_approved']); self.assertFalse(row['csl_supervision'])

    def test_augmentation_groups_and_challenge_are_disjoint_and_tags_are_exact(self):
        m = module(); fixture = m.contrasts(); reserved = {r['text'] for r in fixture}
        train, dev = m.augment(reserved)
        self.assertTrue(train and dev)
        self.assertFalse({r['text'] for r in train} & {r['text'] for r in dev})
        self.assertFalse(reserved & {r['text'] for r in train + dev})
        self.assertFalse({r['split_group'] for r in train} & {r['split_group'] for r in dev})
        for row in train + dev:
            self.assertEqual(row['label_source'], 'assistant_synthetic_chinese')
            self.assertFalse(row['human_approved']); self.assertFalse(row['csl_supervision'])
            self.assertEqual(len(row['text']), len(row['tags']))
            parsed = m.unified.parse_roles(row['text'], row['tags'], m.unified.ROLE_LABELS)
            self.assertFalse(parsed['uncertainty'], row['text'])
            self.assertNotIn('没有', row['text'])

    def test_unknown_scope_and_wrong_supported_acceptance_are_not_high_accuracy(self):
        m = module()
        rows = [next(r for r in m.contrasts() if r['text'] == '我帮你'),
                next(r for r in m.contrasts() if r['expected_roles'] is None)]
        class Reject:
            def predict(self, text):
                return {'status': 'unsupported', 'roles': {}, 'spans': [], 'raw_tags': []}
        class Wrong:
            def predict(self, text):
                return {'status': 'research_candidate_only', 'roles': {'actor': '你'}, 'spans': [], 'raw_tags': []}
        rejected = m.evaluate(Reject(), rows)
        wrong = m.evaluate(Wrong(), rows)
        self.assertEqual(rejected['metrics']['correct_supported_parse_rate'], 0)
        self.assertIsNone(rejected['metrics']['selective_accuracy'])
        self.assertEqual(wrong['wrong_accepts'], 2)
        self.assertEqual(wrong['metrics']['false_accepts'], 1)

    def test_equivalent_home_event_is_not_reported_as_wrong_meaning(self):
        m = module()
        row = next(r for r in m.contrasts() if r['text'] == '我回家')
        class Decomposed:
            def predict(self, text):
                return {'status': 'research_candidate_only', 'roles': {'actor': '我', 'predicate': '回', 'goal': '家'},
                        'spans': [], 'raw_tags': []}
        out = m.evaluate(Decomposed(), [row])
        self.assertEqual(out['metrics']['correct_parses'], 1)
        self.assertEqual(out['strict_role_exact'], 0)
        self.assertEqual(out['wrong_accepts'], 0)

    def test_augmentation_respects_historical_group_assignments(self):
        m = module()
        train, dev = m.augment(set(), {'我|帮|你': 'dev', '你|帮|我': 'train'})
        self.assertNotIn('我|帮|你', {r['split_group'] for r in train})
        self.assertNotIn('你|帮|我', {r['split_group'] for r in dev})

    def test_package_preserves_gloss_bytes_does_not_open_test_and_is_hash_bound(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve(); source = parent / 'source'; source.mkdir()
            for task in ['gloss', 'roles']:
                for split, text in [('train', '我去'), ('dev', '你来')]:
                    row = {'id': task + split, 'text': text, 'task': task,
                           'human_approved': False, 'label_source': 'ce_csl_dataset' if task == 'gloss' else 'assistant_synthetic_chinese',
                           'gloss_sequence' if task == 'gloss' else 'tags': [text] if task == 'gloss' else [1, 3]}
                    (source / f'{task}-{split}.jsonl').write_text(json.dumps(row, ensure_ascii=False) + '\n')
            m.unified.base.write_json(source / 'role-labels.json', m.unified.ROLE_LABELS)
            m.unified.base.write_json(source / 'report.json', {'test_read': False, 'training_ready': False,
                'model_training_ready': False, 'human_approved': False})
            m.seal(source)
            (source / 'test.jsonl').write_text('{DO NOT OPEN')
            original = Path.open
            def guarded(path, *args, **kwargs):
                if path.name == 'test.jsonl':
                    self.fail('test was opened')
                return original(path, *args, **kwargs)
            out = parent / 'new'
            with patch.object(Path, 'open', guarded):
                report = m.prepare(source, out)
            self.assertFalse(report['training_started'])
            for split in ['train', 'dev']:
                name = f'gloss-{split}.jsonl'
                self.assertEqual((source / name).read_bytes(), (out / 'package' / name).read_bytes())
            m.unified.read_package(out / 'package')
            self.assertEqual(len(m.read_frozen(out)['rows']), len(m.contrasts()))
            with self.assertRaises(FileExistsError):
                m.prepare(source, out)
            with (out / 'package/roles-train.jsonl').open('a') as stream:
                stream.write(' ')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.unified.read_package(out / 'package')
            with (out / 'contrasts.json').open('a') as stream:
                stream.write(' ')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.benchmark(out, parent / 'not-opened-model', parent / 'not-opened-roles', parent / 'benchmark')


if __name__ == '__main__':
    unittest.main()
