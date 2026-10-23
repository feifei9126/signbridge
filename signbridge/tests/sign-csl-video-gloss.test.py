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

    def test_sample_tampering_after_manifest_fails_closed(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); package = fixture(root)
            with (package / 'samples.jsonl').open('a') as stream:
                stream.write('\n')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.read_train_package(package)

    def test_video_path_must_match_train_source_and_digest_is_preserved(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); package = fixture(root)
            rows = [json.loads(x) for x in (package / 'samples.jsonl').read_text().splitlines()]
            rows[0]['video_relative_path'] = 'video/test/A/a1.mp4'
            (package / 'samples.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows))
            manifest(package)
            with self.assertRaises(ValueError):
                m.read_train_package(package)

    def test_video_assets_are_hash_and_size_verified(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            video = root / 'video/train/A/a1.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(b'clip')
            record = {'id': 'a1', 'video_relative_path': 'video/train/A/a1.mp4',
                      'video_sha256': hashlib.sha256(b'clip').hexdigest(), 'video_bytes': 4}
            self.assertTrue(m.verify_video_assets([record], root)['all_video_hashes_match'])
            video.write_bytes(b'bad!')
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.verify_video_assets([record], root)

    def test_duplicate_video_bytes_are_quarantined_to_prevent_split_leakage(self):
        m = module()
        rows = [
            {'id': 'train-a', 'source_code': 'A', 'video_sha256': 'f' * 64,
             'video_relative_path': 'video/train/A/train-a.mp4', 'gloss_sequence': ['我']},
            {'id': 'holdout-b', 'source_code': 'B', 'video_sha256': 'f' * 64,
             'video_relative_path': 'video/train/B/holdout-b.mp4', 'gloss_sequence': ['你']},
            {'id': 'unique-c', 'source_code': 'C', 'video_sha256': 'e' * 64,
             'video_relative_path': 'video/train/C/unique-c.mp4', 'gloss_sequence': ['去']},
        ]
        retained, duplicate_groups = m.exclude_duplicate_videos(rows)
        self.assertEqual([row['id'] for row in retained], ['unique-c'])
        self.assertEqual(duplicate_groups[0]['ids'], ['holdout-b', 'train-a'])
        self.assertTrue(duplicate_groups[0]['label_conflict'])

    def test_ctc_capacity_accounts_for_adjacent_repeated_glosses(self):
        m = module()
        row = {'id': 'repeat', 'gloss_sequence': ['我', '我', '去']}
        self.assertEqual(m.ctc_minimum_frames(row['gloss_sequence']), 4)
        m.validate_ctc_capacity([row], frames=4)
        with self.assertRaisesRegex(ValueError, 'CTC frame capacity'):
            m.validate_ctc_capacity([row], frames=3)

    def test_minimum_gloss_frequency_collapses_rare_targets_to_unk(self):
        m = module()
        rows = [
            {'gloss_sequence': ['常见', '常见', '稀有']},
            {'gloss_sequence': ['常见', '另一个稀有']},
        ]
        vocab = m.build_vocab(rows, min_count=2)
        self.assertEqual(vocab, {'<blank>': 0, '<unk>': 1, '常见': 2})

    def test_source_partition_keeps_final_holdout_fresh_and_excluded_codes_unused(self):
        m = module()
        rows = [
            {'id': 'a', 'source_code': 'A'}, {'id': 'g', 'source_code': 'G'},
            {'id': 'f', 'source_code': 'F'}, {'id': 'h', 'source_code': 'H'},
        ]
        train, selection, final_holdout, excluded = m.grouped_partition(
            rows, selection_code='G', final_holdout_code='F', excluded_codes={'H'})
        self.assertEqual({row['id'] for row in train}, {'a'})
        self.assertEqual({row['id'] for row in selection}, {'g'})
        self.assertEqual({row['id'] for row in final_holdout}, {'f'})
        self.assertEqual({row['id'] for row in excluded}, {'h'})

    def test_cached_frames_require_matching_provenance_and_exact_hash_manifest(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); cache = root / 'cache'; cache.mkdir()
            artifact = cache / 'a.npy'; artifact.write_bytes(b'cached-frame-payload')
            manifest = root / 'cache.SHA256SUMS'
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest.write_text(f'{digest}  a.npy\n')
            source_report = root / 'source-report.json'
            source_report.write_text(json.dumps({'counts': {'eligible_after_duplicate_quarantine': 1},
                'frame_cache': {'cached_video_count': 1, 'frames': 32, 'image_size': 64,
                    'location': str(cache), 'sha256_manifest': hashlib.sha256(manifest.read_bytes()).hexdigest()}}))
            rows = [{'id': 'a', 'video_relative_path': 'video/train/A/a.mp4'}]
            result = m.verify_cached_frames(rows, cache, manifest, source_report, frames=32, image_size=64)
            self.assertTrue(result['all_cache_hashes_match'])
            stray = cache / 'stray.npy'; stray.write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                m.verify_cached_frames(rows, cache, manifest, source_report, frames=32, image_size=64)
            stray.unlink()
            artifact.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'cache digest'):
                m.verify_cached_frames(rows, cache, manifest, source_report, frames=32, image_size=64)

    def test_ctc_diagnostics_detect_blank_collapse(self):
        m = module()
        diagnostics = m.ctc_prediction_diagnostics([[0, 0, 0], [1, 1, 0]], blank=0)
        self.assertEqual(diagnostics['empty_prediction_samples'], 1)
        self.assertEqual(diagnostics['predicted_tokens'], 1)
        self.assertAlmostEqual(diagnostics['blank_frame_fraction'], 4 / 6)

    def test_ctc_blank_penalty_is_finite_and_zero_for_no_blank_probability(self):
        m = module()
        if m.torch is None:
            self.skipTest('PyTorch unavailable')
        import torch
        logits = torch.log_softmax(torch.tensor([[[0.0, 3.0], [0.0, 3.0]]]), dim=-1)
        penalty = m.ctc_blank_penalty(logits)
        self.assertTrue(bool(torch.isfinite(penalty)))
        self.assertGreater(float(penalty), 0.0)

    def test_model_can_initialize_blank_logit_below_regular_gloss_logits(self):
        m = module()
        if m.torch is None:
            self.skipTest('PyTorch unavailable')
        import torch
        model = m.VideoGlossModel(vocab_size=4, width=4, blank_logit_bias=-2.0)
        self.assertLess(float(model.head.bias.detach()[0]), float(model.head.bias.detach()[1]))
        self.assertTrue(bool(torch.isfinite(model.head.bias).all()))

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
