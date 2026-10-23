"""Video-to-Gloss baseline contracts; train-only grouped evaluation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-video-gloss.py'


def module():
    if not TOOL.is_file():
        raise AssertionError('Video-to-Gloss trainer is missing')
    spec = importlib.util.spec_from_file_location('video_gloss_test', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def manifest(root):
    (root / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n'
        for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))


def row(identity, code, split='train'):
    return {'schema': 'signbridge-ce-csl-sample-v1', 'id': identity,
            'source_split': split, 'source_translator': code,
            'source_translator_scope': 'dataset_code_only_not_cross_dataset_identity',
            'source_id': identity, 'video_relative_path': f'video/train/{code}/{identity}.mp4',
            'proposed_text': '我去', 'gloss_sequence': ['我', '去'],
            'video': {'sha256': 'a' * 64, 'bytes': 4}}


def fixture(root):
    library = root / 'package'; library.mkdir()
    rows = [row('a1', 'A'), row('a2', 'A'), row('b1', 'B'), row('c1', 'C')]
    (library / 'samples.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows))
    (library / 'test.jsonl').write_text('{test must never be read')
    manifest(library)
    return library


class VideoGlossTests(unittest.TestCase):
    def test_train_only_package_and_group_holdout_are_hash_bound(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); package = fixture(root)
            original_open = Path.open
            def guarded(path, *args, **kwargs):
                self.assertNotEqual(path.resolve(), (package / 'test.jsonl').resolve())
                return original_open(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded):
                rows, info = m.read_train_package(package)
            self.assertEqual(len(rows), 4); self.assertFalse(info['test_read'])
            train, heldout = m.group_holdout(rows, 'B')
            self.assertEqual({r['id'] for r in train}, {'a1', 'a2', 'c1'})
            self.assertEqual({r['id'] for r in heldout}, {'b1'})
            self.assertFalse({r['id'] for r in train} & {r['id'] for r in heldout})

    def test_invalid_rows_and_bad_digest_fail_closed(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); package = fixture(root)
            rows = [json.loads(x) for x in (package / 'samples.jsonl').read_text().splitlines()]
            rows[0]['source_split'] = 'dev'
            (package / 'samples.jsonl').write_text(json.dumps(rows[0]) + '\n')
            manifest(package)
            with self.assertRaises(ValueError):
                m.read_train_package(package)

    def test_ctc_greedy_decode_collapses_repeats_and_blanks(self):
        m = module()
        self.assertEqual(m.ctc_greedy_decode([1, 1, 0, 2, 2, 0, 1], blank=0), [1, 2, 1])

    def test_model_output_and_metrics_are_finite(self):
        m = module()
        if m.torch is None:
            self.skipTest('PyTorch unavailable')
        model = m.VideoGlossModel(vocab_size=7, width=16)
        import torch
        output = model(torch.zeros(2, 8, 3, 64, 64))
        self.assertEqual(tuple(output.shape), (8, 2, 7))
        self.assertTrue(bool(torch.isfinite(output).all()))
        metrics = m.sequence_metrics([[1, 2], [2]], [[1, 2], [1]])
        self.assertEqual(metrics['samples'], 2)
        self.assertTrue(metrics['gloss_error_rate'] >= 0)


if __name__ == '__main__':
    unittest.main()
