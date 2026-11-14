"""Train-only grouped fold generation for CE-CSL; dev/test source files stay unopened."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-grouped-folds.py'


def module():
    if not TOOL.is_file():
        raise AssertionError('Grouped fold builder is missing')
    spec = importlib.util.spec_from_file_location('grouped_folds_test', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def write_manifest(root):
    (root / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n'
        for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))


def row(identity, code, split='train'):
    return {'schema': 'signbridge-ce-csl-sample-v1', 'id': identity,
            'source_split': split, 'source_translator': code,
            'source_translator_scope': 'dataset_code_only_not_cross_dataset_identity',
            'source_id': identity, 'video_relative_path': f'video/{split}/{code}/{identity}.mp4',
            'gloss_sequence': ['我', '去'], 'proposed_text': '我去'}


def fixture(root):
    m = module(); library = root / 'library'; library.mkdir()
    split = library / 'splits/train/samples.jsonl'; split.parent.mkdir(parents=True)
    split.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in [
        row('a1', 'A'), row('a2', 'A'), row('b1', 'B'), row('c1', 'C')]))
    poison_dev = library / 'splits/dev/samples.jsonl'; poison_dev.parent.mkdir(parents=True)
    poison_dev.write_text('{dev must never be read')
    poison_test = library / 'splits/test/samples.jsonl'; poison_test.parent.mkdir(parents=True)
    poison_test.write_text('{test must never be read')
    write_manifest(library)
    return library, split, poison_dev, poison_test


class GroupedFoldTests(unittest.TestCase):
    def test_leave_one_source_code_out_is_disjoint_and_reads_only_train(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, _, dev, test = fixture(root)
            original_open = Path.open
            def guarded_open(path, *args, **kwargs):
                self.assertNotIn(path.resolve(), {dev.resolve(), test.resolve()}, 'held-out split was opened')
                return original_open(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded_open):
                report = m.build_folds(library, root / 'folds')
            self.assertEqual(report['fold_count'], 3)
            self.assertFalse(report['test_read']); self.assertFalse(report['official_dev_read'])
            self.assertFalse(report['signer_identity_verified']); self.assertFalse(report['signer_independent_claim'])
            folds = json.loads((root / 'folds/folds.json').read_text())['folds']
            seen = []
            for fold in folds:
                train_ids = {row['id'] for row in fold['train_samples']}
                dev_ids = {row['id'] for row in fold['dev_samples']}
                self.assertFalse(train_ids & dev_ids)
                self.assertEqual(dev_ids, {x for x in ['a1', 'a2', 'b1', 'c1']
                                           if x.startswith(fold['heldout_source_code'].lower())})
                seen.extend(dev_ids)
            self.assertCountEqual(seen, ['a1', 'a2', 'b1', 'c1'])
            self.assertTrue((root / 'folds/SHA256SUMS').is_file())

    def test_digest_mismatch_duplicate_ids_and_single_group_are_rejected(self):
        m = module()
        for case in ['digest', 'duplicate', 'single_group']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); library, train, _, _ = fixture(root)
                rows = [json.loads(line) for line in train.read_text().splitlines()]
                if case == 'digest':
                    train.write_text(train.read_text() + ' ')
                elif case == 'duplicate':
                    rows[-1]['id'] = rows[0]['id']
                    train.write_text(''.join(json.dumps(r) + '\n' for r in rows)); write_manifest(library)
                else:
                    for item in rows: item['source_translator'] = 'A'
                    train.write_text(''.join(json.dumps(r) + '\n' for r in rows)); write_manifest(library)
                with self.assertRaises(ValueError):
                    m.build_folds(library, root / 'folds')
                self.assertFalse((root / 'folds').exists())

    def test_existing_output_is_never_overwritten(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, _, _, _ = fixture(root)
            output = root / 'folds'; output.mkdir()
            with self.assertRaises(FileExistsError):
                m.build_folds(library, output)


if __name__ == '__main__':
    unittest.main()
