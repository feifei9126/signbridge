"""Train/dev video pairing audit contracts; test split must remain unopened."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-video-readiness.py'


def module():
    if not TOOL.is_file():
        raise AssertionError('Video readiness auditor is missing')
    spec = importlib.util.spec_from_file_location('video_readiness_test', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def manifest(root):
    (root / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}\n'
        for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))


def sample(split, translator, identity, digest, size):
    return {
        'schema': 'signbridge-ce-csl-sample-v1', 'id': f'csl_ce_csl_{split}_{identity}',
        'source_split': split, 'source_id': identity, 'source_translator': translator,
        'source_label': {'relative_path': f'label/{split}.csv', 'sha256': 'a' * 64},
        'proposed_text': '我去', 'gloss_sequence': ['我', '去'],
        'video_relative_path': f'video/{split}/{translator}/{identity}.mp4',
        'annotation_scope': 'dataset_provided_sequence_level_only', 'word_spans': [],
        'signer_id': None,
        'video': {'relative_path': f'video/{split}/{translator}/{identity}.mp4',
                  'sha256': digest, 'bytes': size,
                  'probe': {'status': 'passed', 'metadata': {
                      'width': 1920, 'height': 1080, 'fps': 30.0,
                      'duration_seconds': 1.0, 'container_reported_frames': 30}}},
    }


def fixture(root):
    tool = module()
    library = root / 'library'; library.mkdir()
    media = root / 'media'; media.mkdir()
    clips = [('train', 'A', 'train-00001'), ('dev', 'B', 'dev-00001')]
    for split, translator, identity in clips:
        path = media / 'video' / split / translator / f'{identity}.mp4'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes((identity + '-video').encode())
        row = sample(split, translator, identity, tool.sha(path), path.stat().st_size)
        target = library / 'splits' / split / 'samples.jsonl'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(row, ensure_ascii=False) + '\n')
    poison = library / 'splits/test/samples.jsonl'
    poison.parent.mkdir(parents=True); poison.write_text('{test must never be read')
    manifest(library)
    return library, media, poison


class VideoReadinessTests(unittest.TestCase):
    def test_only_train_dev_pairs_are_hash_checked_and_full_decode_is_recorded(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, media, poison = fixture(root)
            output = root / 'audit'
            original_open = Path.open

            def guarded_open(path, *args, **kwargs):
                self.assertNotEqual(path.resolve(), poison.resolve(), 'test split was opened')
                return original_open(path, *args, **kwargs)

            with patch.object(Path, 'open', guarded_open):
                report = m.run_audit(library, media, output, full_decode=True,
                    probe=lambda path: {'width': 1920, 'height': 1080, 'fps': 30.0,
                        'duration_seconds': 1.0, 'container_reported_frames': 30},
                    decode=lambda path: {'decoded_frames': 30})
            self.assertEqual(report['counts'], {'train': 1, 'dev': 1})
            self.assertTrue(report['test_read'] is False)
            self.assertTrue(report['full_decode_requested'])
            self.assertTrue(report['all_video_hashes_match'])
            self.assertTrue(report['all_full_decodes_passed'])
            self.assertFalse(report['signer_independent_split'])
            self.assertFalse(report['training_ready'])
            self.assertFalse(report['model_training_ready'])
            self.assertTrue((output / 'clips.jsonl').is_file())
            self.assertTrue((output / 'SHA256SUMS').is_file())

    def test_hash_mismatch_and_unsafe_video_paths_fail_closed(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, media, _ = fixture(root)
            path = library / 'splits/train/samples.jsonl'
            row = json.loads(path.read_text()); row['video']['sha256'] = '0' * 64
            path.write_text(json.dumps(row, ensure_ascii=False) + '\n'); manifest(library)
            report = m.run_audit(library, media, root / 'audit',
                probe=lambda _: {'width': 1920, 'height': 1080, 'fps': 30,
                    'duration_seconds': 1, 'container_reported_frames': 30})
            self.assertFalse(report['all_video_hashes_match'])
            self.assertEqual(report['status_counts']['failed'], 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, media, _ = fixture(root)
            path = library / 'splits/train/samples.jsonl'
            row = json.loads(path.read_text()); row['video_relative_path'] = '../outside.mp4'
            row['video']['relative_path'] = '../outside.mp4'
            path.write_text(json.dumps(row, ensure_ascii=False) + '\n'); manifest(library)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                m.run_audit(library, media, root / 'audit',
                    probe=lambda _: {'width': 1920, 'height': 1080, 'fps': 30,
                        'duration_seconds': 1, 'container_reported_frames': 30})
            self.assertFalse((root / 'audit').exists())

    def test_full_decode_failure_is_reported_and_cannot_mark_ready(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, media, _ = fixture(root)
            report = m.run_audit(library, media, root / 'audit', full_decode=True,
                probe=lambda _: {'width': 1920, 'height': 1080, 'fps': 30,
                    'duration_seconds': 1, 'container_reported_frames': 30},
                decode=lambda _: (_ for _ in ()).throw(ValueError('decode failed')))
            self.assertEqual(report['full_decode_failures'], 2)
            self.assertFalse(report['all_full_decodes_passed'])
            self.assertFalse(report['training_ready'])

    def test_cli_probe_and_decode_tools_keep_separate_executable_paths(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, media, _ = fixture(root)
            ffprobe, ffmpeg = root / 'ffprobe', root / 'ffmpeg'
            ffprobe.write_bytes(b'probe executable'); ffmpeg.write_bytes(b'decode executable')
            probe_paths, decode_paths = [], []
            def fake_probe(path, executable):
                probe_paths.append(str(executable))
                return {'width': 1920, 'height': 1080, 'fps': 30.0,
                        'duration_seconds': 1.0, 'container_reported_frames': 30}
            def fake_decode(path, executable):
                decode_paths.append(str(executable))
                return {'decoded': True}
            with patch.object(m, 'probe_video', side_effect=fake_probe), \
                 patch.object(m, 'decode_video', side_effect=fake_decode):
                m.run_audit(library, media, root / 'audit', full_decode=True,
                            ffprobe=ffprobe, ffmpeg=ffmpeg)
            self.assertEqual(probe_paths, [str(ffprobe.resolve())] * 2)
            self.assertEqual(decode_paths, [str(ffmpeg.resolve())] * 2)

    def test_existing_output_and_symlinked_video_are_rejected(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); library, media, _ = fixture(root)
            output = root / 'audit'; output.mkdir()
            with self.assertRaises(FileExistsError):
                m.run_audit(library, media, output)
            path = media / 'video/train/A/train-00001.mp4'
            saved = root / 'saved.mp4'; path.rename(saved); path.symlink_to(saved)
            with self.assertRaisesRegex(ValueError, '[Ss]ymlink'):
                m.run_audit(library, media, root / 'new-audit')


if __name__ == '__main__':
    unittest.main()
