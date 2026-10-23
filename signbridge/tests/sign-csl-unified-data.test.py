"""Unified research packages must preserve task identities and validation boundaries."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-unified-data.py'


def module():
    spec = importlib.util.spec_from_file_location('unified_data', TOOL)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def item(identity, text, target, task='gloss'):
    result = dict(id=identity, text=text, task=task, human_approved=False,
                  label_source='ce_csl_dataset' if task == 'gloss' else 'assistant_synthetic_chinese')
    result['gloss_sequence' if task == 'gloss' else 'tags'] = target
    return result


class UnifiedDataTests(unittest.TestCase):
    def test_conflicts_duplicates_and_heldout_overlap_are_separate(self):
        m = module()
        rows = [item('a', '我去', ['我', '去']), item('b', '我去。', ['我', '去']),
                item('c', '你去', ['你', '去']), item('d', '你去', ['去', '你']),
                item('e', '今天去', ['今天', '去'])]
        kept, rejected = m.curate(rows, 'gloss_sequence', {'今天去'})
        self.assertEqual([x['id'] for x in kept], ['a'])
        self.assertEqual({x['reason'] for x in rejected},
                         {'exact_duplicate', 'same_text_conflicting_targets', 'heldout_text_overlap'})
        self.assertFalse(kept[0]['human_approved'])

    def test_different_tasks_never_get_fake_gloss_or_role_labels(self):
        m = module()
        gloss = item('g', '我去', ['我', '去'])
        roles = item('r', '我去', [1, 3], 'roles')
        a, _ = m.curate([gloss], 'gloss_sequence', set())
        b, _ = m.curate([roles], 'tags', set())
        self.assertNotIn('tags', a[0])
        self.assertNotIn('gloss_sequence', b[0])

    def test_dev_sequence_and_source_video_overlap_are_quarantined(self):
        m = module()
        rows = [item('a', '不同文字', ['我', '去']), item('b', '另一句', ['来'])]
        rows[1]['video_sha256'] = 'a' * 64
        kept, rejected = m.curate(rows, 'gloss_sequence', set(),
                                  {('我', '去')}, {'a' * 64})
        self.assertEqual(kept, [])
        self.assertEqual({x['reason'] for x in rejected},
                         {'heldout_target_sequence_overlap', 'heldout_video_overlap'})

    def test_manifest_reads_reject_parent_symlinks_before_opening(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'actual').mkdir()
            (root / 'actual/value.json').write_text('{}')
            (root / 'linked').symlink_to(root / 'actual', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                m.regular_file(root, 'linked/value.json')

    def test_real_builder_preserves_tasks_and_does_not_read_test(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ce, roles = root / 'ce', root / 'roles'
            ce.mkdir(); roles.mkdir()
            for split, text in [('train', '我去'), ('dev', '你来')]:
                path = ce / f'splits/{split}/samples.jsonl'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(dict(id='ce-' + split, proposed_text=text,
                    source_split=split, gloss_sequence=list(text),
                    video={'sha256': ('a' if split == 'train' else 'b') * 64})))
            for split, text in [('train', '他看'), ('validation', '她买')]:
                (roles / (split + '.jsonl')).write_text(json.dumps(dict(text=text, tags=[1, 3],
                    split=split, split_group=text, label_source='assistant_synthetic_chinese',
                    human_approved=False, csl_supervision=False)))
            labels = ['O'] + [p + r for r in ['actor', 'predicate', 'patient', 'goal', 'time',
                'negation', 'modal', 'question', 'aspect', 'politeness', 'degree'] for p in ['B-', 'I-']]
            (roles / 'model.json').write_text(json.dumps(dict(
                schema='signbridge-learned-chinese-roles-v1', labels=labels)))
            for directory in [ce, roles]:
                (directory / 'test.jsonl').write_text('test must not be read')
                (directory / 'SHA256SUMS').write_text(''.join(
                    hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(directory).as_posix() + '\n'
                    for p in sorted(directory.rglob('*')) if p.is_file()))
            original = Path.open
            def guard(path, *args, **kwargs):
                self.assertNotEqual(path.name, 'test.jsonl')
                return original(path, *args, **kwargs)
            output = root / 'package'
            with patch.object(Path, 'open', guard):
                report = m.build(ce, roles, output)
            self.assertEqual(report['counts'], dict(
                **{'gloss-train': 1, 'roles-train': 1, 'gloss-dev': 1, 'roles-dev': 1}))
            self.assertFalse(report['test_read'])
            self.assertFalse(report['validation_added_to_training'])
            for task in ['gloss', 'roles']:
                row = json.loads((output / f'{task}-train.jsonl').read_text())
                self.assertEqual(row['task'], task)
                self.assertFalse(row['human_approved'])
            with self.assertRaises(FileExistsError):
                m.build(ce, roles, output)


if __name__ == '__main__':
    unittest.main()
