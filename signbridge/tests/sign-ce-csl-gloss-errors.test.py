"""Dev-only diagnostics preserve raw labels and cannot consume the test split."""
from collections import Counter
from itertools import product
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-ce-csl-gloss-errors.py'


def module():
    spec = importlib.util.spec_from_file_location('ce_gloss_errors', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf-8')


def manifest(root):
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (root / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(root).as_posix() + '\n'
        for p in files), encoding='utf-8')


def fixture(root, m):
    library = root / 'library'
    rows = {
        'train': [dict(id='train1', source_split='train', proposed_text='我考试',
                       gloss_sequence=['我', '考试1'], video={'sha256': 'a' * 64})],
        'dev': [dict(id='dev1', source_split='dev', proposed_text='你考试',
                     gloss_sequence=['你', '考试2'], video={'sha256': 'b' * 64})],
    }
    for split, samples in rows.items():
        p = library / 'splits' / split / 'samples.jsonl'
        p.parent.mkdir(parents=True)
        p.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in samples))
    # A poison test file is present and hashed but must never be opened by analysis.
    p = library / 'splits/test/samples.jsonl'
    p.parent.mkdir(parents=True)
    p.write_text('not valid JSON: do not parse or read test bytes')
    manifest(library)
    source_hashes = {f'splits/{s}/samples.jsonl': hashlib.sha256(
        (library / f'splits/{s}/samples.jsonl').read_bytes()).hexdigest() for s in rows}
    vocab = m.gloss.build_vocab(rows['train'])
    flags = m.gloss.overlap_flags(rows['train'], rows['dev'])
    dirs = []
    for name, prediction in [('prior', ['我', '考试1']), ('continuation', ['考试1'])]:
        out = root / name
        out.mkdir()
        checkpoint = out / 'checkpoints/epoch.pt'
        checkpoint.parent.mkdir()
        checkpoint.write_bytes(b'hashed fixture, not a loadable model')
        metric = m.gloss.sliced_metrics(rows['dev'], [prediction], flags)
        save(out / 'vocab.json', vocab)
        save(out / 'report.json', dict(schema='signbridge-ce-csl-text-to-gloss-v1',
             status='completed', research_only=True, deployment_ready=False,
             source_files_sha256=source_hashes, checkpoint='checkpoints/epoch.pt',
             checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
             evaluation={'dev': {'transformer': metric}}))
        save(out / 'dev-predictions.jsonl', dict(id='dev1', text='你考试',
             reference=['你', '考试2'], predicted=prediction, overlap_reasons=[],
             can_play=False, human_approved=False))
        manifest(out)
        dirs.append(out)
    return library, *dirs


class GlossErrorTests(unittest.TestCase):
    def test_alignment_retains_substitution_deletion_and_insertion(self):
        m = module()
        for ref, hyp, expected in [(['我', '去'], ['我', '来'], (1, 0, 0)),
                                   (['我', '去'], ['我'], (0, 1, 0)),
                                   (['我'], ['我', '去'], (0, 0, 1)),
                                   (['不', '去'], [], (0, 2, 0))]:
            ops = m.align(ref, hyp)
            counts = Counter(x['operation'] for x in ops)
            self.assertEqual(tuple(counts[k] for k in ['substitution', 'deletion', 'insertion']), expected)

    def test_reorder_repetition_and_variants_are_only_diagnostic_clues(self):
        m = module()
        frequencies = Counter({'我': 10, '去': 5, '考试1': 1, '考试2': 2})
        result = m.diagnose(['我', '去'], ['去', '我'], frequencies)
        self.assertTrue(result['order_only_clue'])
        result = m.diagnose(['我', '去'], ['我', '我', '去'], frequencies)
        self.assertEqual(result['adjacent_repeat_excess'], 1)
        variant = m.diagnose(['考试1'], ['考试2'], frequencies)
        self.assertEqual(variant['variant_surface_confusions'], 1)
        self.assertEqual(variant['substitutions'], 1)
        self.assertFalse(variant['exact_match'])
        self.assertFalse(m.is_number('考试1'))
        self.assertTrue(m.is_number('10'))
        self.assertTrue(m.is_number('十二'))
        legitimate = m.diagnose(['我', '我'], ['我', '我'], frequencies)
        self.assertEqual(legitimate['adjacent_repeat_excess'], 0)
        self.assertTrue(legitimate['exact_match'])

    def test_alignment_reconstructs_raw_sequences_and_matches_metric_ties(self):
        m = module()
        sequences = [list(p) for n in range(4) for p in product(['我', '去'], repeat=n)]
        for reference, prediction in product(sequences, repeat=2):
            ops = m.align(reference, prediction)
            self.assertEqual([x['reference'] for x in ops if x['reference'] is not None], reference)
            self.assertEqual([x['predicted'] for x in ops if x['predicted'] is not None], prediction)
            counts = Counter(x['operation'] for x in ops)
            self.assertEqual(tuple(counts[k] for k in ['substitution', 'deletion', 'insertion']),
                             m.gloss.edit_counts(reference, prediction))

    def test_pooled_metrics_are_not_mean_sentence_error(self):
        m = module()
        rows = [dict(reference=['我'], predicted=[]),
                dict(reference=['去'] * 4, predicted=['去'] * 4)]
        self.assertAlmostEqual(m.pooled(rows)['gloss_error_rate'], 1 / 5)

    def test_manifest_bound_analysis_never_opens_test_or_loads_model(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library, prior, continuation = fixture(root, m)
            poison = library / 'splits/test/samples.jsonl'
            original_open = Path.open
            opened = []
            def guarded_open(path, *args, **kwargs):
                self.assertNotEqual(path.resolve(), poison.resolve(), 'test file was opened')
                opened.append(str(path))
                return original_open(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded_open):
                report = m.analyze(library, prior, continuation, root / 'analysis')
            self.assertFalse(report['test_read'])
            self.assertFalse(report['training_started'])
            self.assertEqual(report['rows_compared'], 1)
            self.assertEqual(report['comparison']['nonoverlap_with_train']['tied'], 1)
            self.assertFalse(report['training_ready'])
            self.assertTrue((root / 'analysis/cases.jsonl').is_file())
            self.assertTrue((root / 'analysis/REPORT.md').is_file())
            with self.assertRaises(FileExistsError):
                m.analyze(library, prior, continuation, root / 'analysis')

    def test_changed_prediction_digest_rejected_before_output_creation(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library, prior, continuation = fixture(root, m)
            p = continuation / 'dev-predictions.jsonl'
            p.write_text(p.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.analyze(library, prior, continuation, root / 'analysis')
            self.assertFalse((root / 'analysis').exists())

    def test_parent_symlinks_are_rejected_before_any_target_bytes_are_read(self):
        m = module()
        for kind in ['train', 'checkpoint']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                library, prior, continuation = fixture(root, m)
                if kind == 'train':
                    directory = library / 'splits/train'
                    moved = library / 'splits/original-train'
                    directory.rename(moved)
                    directory.symlink_to(library / 'splits/test', target_is_directory=True)
                    forbidden = library / 'splits/test/samples.jsonl'
                else:
                    directory = continuation / 'checkpoints'
                    moved = continuation / 'original-checkpoints'
                    directory.rename(moved)
                    directory.symlink_to(moved, target_is_directory=True)
                    forbidden = moved / 'epoch.pt'
                original_open = Path.open
                def guarded_open(path, *args, **kwargs):
                    self.assertNotEqual(path.resolve(), forbidden.resolve(),
                                        'linked target bytes were opened before rejection')
                    return original_open(path, *args, **kwargs)
                with patch.object(Path, 'open', guarded_open):
                    with self.assertRaisesRegex(ValueError, 'symlink'):
                        m.analyze(library, prior, continuation, root / 'analysis')
                self.assertFalse((root / 'analysis').exists())

    def test_mismatched_sample_reference_or_metrics_cannot_be_silently_compared(self):
        m = module()
        for field, value in [('id', 'wrong-id'), ('reference', ['考试1']),
                             ('predicted', ['only-in-dev']), ('predicted', ['我', '考试1']),
                             ('overlap_reasons', ['invented'])]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                library, prior, continuation = fixture(root, m)
                p = continuation / 'dev-predictions.jsonl'
                row = json.loads(p.read_text()); row[field] = value
                save(p, row); manifest(continuation)
                with self.assertRaises(ValueError):
                    m.analyze(library, prior, continuation, root / 'analysis')
                self.assertFalse((root / 'analysis').exists())

    def test_dataset_digest_vocab_checkpoint_path_and_output_overlap_are_checked(self):
        m = module()
        for change in ['dataset', 'vocab', 'checkpoint', 'overlap']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                library, prior, continuation = fixture(root, m)
                if change == 'dataset':
                    p = continuation / 'report.json'
                    report = json.loads(p.read_text())
                    report['source_files_sha256']['splits/dev/samples.jsonl'] = '0' * 64
                    save(p, report)
                elif change == 'vocab':
                    p = continuation / 'vocab.json'
                    vocab = json.loads(p.read_text()); vocab['target'].append('考试2')
                    save(p, vocab)
                elif change == 'checkpoint':
                    p = continuation / 'report.json'
                    report = json.loads(p.read_text())
                    report['checkpoint'] = 'checkpoints/../dev-predictions.jsonl'
                    report['checkpoint_sha256'] = hashlib.sha256(
                        (continuation / 'dev-predictions.jsonl').read_bytes()).hexdigest()
                    save(p, report)
                manifest(continuation)
                output = library / 'analysis' if change == 'overlap' else root / 'analysis'
                with self.assertRaises(ValueError):
                    m.analyze(library, prior, continuation, output)
                self.assertFalse(output.exists())

    def test_csv_cells_cannot_be_spreadsheet_formulas(self):
        m = module()
        self.assertEqual(m.csv_cell('=1+1'), "'=1+1")
        self.assertEqual(m.csv_cell('  @SUM(A1)'), "'  @SUM(A1)")
        self.assertEqual(m.csv_cell('我去'), '我去')


if __name__ == '__main__':
    unittest.main()
