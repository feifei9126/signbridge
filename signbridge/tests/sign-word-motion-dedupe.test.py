import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-word-motion-dedupe.py'


def module():
    spec = importlib.util.spec_from_file_location('word_motion_dedupe', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class WordMotionDedupeTests(unittest.TestCase):
    def test_exact_clip_duplicates_become_one_fit_job_with_all_unapproved_aliases(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clips = root / 'assets'
            clips.mkdir()
            content = b'exact identical candidate video bytes'
            clip = clips / 'same.mp4'
            clip.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            rows = [
                {'id': 'candidate_b', 'proposed_text': '我们', 'source_id': 'source-b',
                 'source_sha256': 'b' * 64, 'source_absolute_path': '/source-b.mp4',
                 'source_batch': '5', 'source_window_seconds': [4., 6.],
                 'clip_sha256': digest, 'reference_clip': 'assets/same.mp4',
                 'decoded_video': {'frames': 50, 'fps': 25.}, 'human_approved': False,
                 'training_ready': False, 'model_training_ready': False, 'text_verified': ''},
                {'id': 'candidate_a', 'proposed_text': '我', 'source_id': 'source-a',
                 'source_sha256': 'a' * 64, 'source_absolute_path': '/source-a.mp4',
                 'source_batch': '4', 'source_window_seconds': [8., 10.],
                 'clip_sha256': digest, 'reference_clip': 'assets/same.mp4',
                 'decoded_video': {'frames': 50, 'fps': 25.}, 'human_approved': False,
                 'training_ready': False, 'model_training_ready': False, 'text_verified': ''},
            ]
            groups = tool.deduplicate_candidates(rows, root)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]['canonical']['id'], 'candidate_a')
            self.assertEqual([r['id'] for r in groups[0]['aliases']], ['candidate_a', 'candidate_b'])
            self.assertEqual({r['proposed_text'] for r in groups[0]['aliases']}, {'我', '我们'})
            self.assertTrue(all(r['human_approved'] is False for r in groups[0]['aliases']))

    def test_different_clip_hashes_never_merge_by_label_or_source(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'one.mp4').write_bytes(b'one')
            (root / 'two.mp4').write_bytes(b'two')
            rows = [{'id': f'id-{i}', 'proposed_text': '谢谢', 'source_id': 'same',
                     'source_sha256': 'a' * 64, 'source_window_seconds': [i, i + 1],
                     'reference_clip': f'{name}.mp4', 'clip_sha256': hashlib.sha256(content).hexdigest(),
                     'decoded_video': {'frames': 25, 'fps': 25.}, 'human_approved': False,
                     'training_ready': False, 'model_training_ready': False, 'text_verified': ''}
                    for i, (name, content) in enumerate([('one', b'one'), ('two', b'two')])]
            self.assertEqual(len(tool.deduplicate_candidates(rows, root)), 2)

    def test_clip_hash_mismatch_or_path_escape_fails_closed(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'clip.mp4').write_bytes(b'clip')
            base = {'id': 'candidate', 'proposed_text': '我', 'source_id': 'source',
                    'source_sha256': 'a' * 64, 'source_window_seconds': [0., 1.],
                    'reference_clip': 'clip.mp4', 'decoded_video': {'frames': 25, 'fps': 25.},
                    'human_approved': False, 'training_ready': False, 'model_training_ready': False}
            with self.assertRaises(ValueError):
                tool.deduplicate_candidates([{**base, 'clip_sha256': '0' * 64}], root)
            with self.assertRaises(ValueError):
                tool.deduplicate_candidates([{**base, 'reference_clip': '../clip.mp4',
                    'clip_sha256': hashlib.sha256(b'clip').hexdigest()}], root)

    def test_clip_symlink_escape_fails_closed(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            root = parent / 'candidate'
            root.mkdir()
            outside = parent / 'outside.mp4'
            outside.write_bytes(b'outside')
            (root / 'link.mp4').symlink_to(outside)
            row = {'id': 'candidate', 'proposed_text': '我', 'source_id': 'source',
                   'source_sha256': 'a' * 64, 'source_window_seconds': [0., 1.],
                   'reference_clip': 'link.mp4', 'clip_sha256': hashlib.sha256(b'outside').hexdigest(),
                   'decoded_video': {'frames': 25, 'fps': 25.}, 'human_approved': False,
                   'training_ready': False, 'model_training_ready': False, 'text_verified': ''}
            with self.assertRaises(ValueError):
                tool.deduplicate_candidates([row], root)

    def test_identical_pose_arrays_are_reported_but_not_auto_deleted(self):
        tool = module()
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            poses = np.zeros((4, 55, 3), np.float32).tolist()
            rows = []
            for identity, label in [('a', '我'), ('b', '我们')]:
                path = root / f'{identity}.json'
                path.write_text(json.dumps({'poses': poses}))
                rows.append({'id': identity, 'proposed_text': label, 'native_asset': path.name,
                             'native_asset_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            groups = tool.native_pose_exact_duplicates(rows, root)
            self.assertEqual(len(groups), 1)
            self.assertEqual({x['candidate_id'] for x in groups[0]['members']}, {'a', 'b'})

    def test_package_builder_preserves_originals_and_binds_aliases_and_hashes(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'input'
            source.mkdir()
            clip = source / 'clip.mp4'
            clip.write_bytes(b'portable video fixture')
            clip_hash = hashlib.sha256(clip.read_bytes()).hexdigest()
            rows = [{'id': identifier, 'proposed_text': label, 'source_id': 'source',
                     'source_sha256': 'a' * 64, 'source_absolute_path': '/original.mp4',
                     'source_batch': '4', 'source_window_seconds': [0., 1.],
                     'reference_clip': 'clip.mp4', 'clip_sha256': clip_hash,
                     'decoded_video': {'frames': 25, 'fps': 25.},
                     'native_3d_available': False, 'native_asset': None,
                     'human_approved': False, 'training_ready': False, 'model_training_ready': False,
                     'text_verified': '', 'evidence_kind': 'caption_short_candidate',
                     'language_scope_status': 'CSL_source_scope_unconfirmed'}
                    for identifier, label in [('candidate_a', '我'), ('candidate_b', '我们')]]
            source_report = source / 'report.json'
            source_report.write_text(json.dumps({'summary': {'candidates': 2}, 'candidates': rows}))
            (source / 'candidates.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            source_sums = source / 'SHA256SUMS'
            source_sums.write_text(f'{hashlib.sha256(source_report.read_bytes()).hexdigest()}  report.json\n'
                                   f'{hashlib.sha256((source / "candidates.jsonl").read_bytes()).hexdigest()}  candidates.jsonl\n'
                                   f'{clip_hash}  clip.mp4\n')
            output = root / 'package'
            result = tool.build_package(source_report, source_sums, source, output)
            self.assertEqual(result['sequence_count'], 1)
            self.assertEqual(result['candidate_alias_count'], 2)
            self.assertFalse(rows[0]['human_approved'])
            self.assertEqual(clip.read_bytes(), b'portable video fixture')
            alias_rows = [json.loads(line) for line in (output / 'aliases.jsonl').read_text().splitlines()]
            self.assertEqual({row['candidate_id'] for row in alias_rows}, {'candidate_a', 'candidate_b'})
            self.assertTrue(all(row['text_verified'] == '' and not row['training_ready'] for row in alias_rows))
            manifest, cases, keyframes, _ = tool.runner.validate_package(output)
            self.assertEqual(manifest['sequence_count'], 1)
            self.assertEqual(len(cases), 1)
            self.assertEqual(keyframes, [])

    def test_chunk_packages_cover_each_unique_sequence_once_and_preserve_aliases(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / 'master'
            clips = master / 'clips'
            clips.mkdir(parents=True)
            sequences, aliases = [], []
            for index in range(5):
                identity = f'fit_{index:032x}'
                relative = f'clips/{identity}/clip.mp4'
                path = master / relative
                path.parent.mkdir(parents=True)
                content = f'video-{index}'.encode()
                path.write_bytes(content)
                sequences.append({'annotation_id': identity, 'source_id': f'source-{index}',
                    'source_sha256': f'{index:064x}', 'label_candidate': f'词{index}',
                    'text_verified': '', 'start_seconds': 0., 'end_seconds': 1., 'frames': 25,
                    'fps': 25., 'clip': relative, 'clip_sha256': hashlib.sha256(content).hexdigest(),
                    'language': 'unconfirmed', 'mirror_status': 'unknown', 'signer_identity': 'unconfirmed',
                    'sample_type': 'sentence_candidate', 'human_approved': False,
                    'training_ready': False, 'mano_keyframes': []})
                aliases.append({'fit_sequence_id': identity, 'candidate_id': f'candidate-{index}',
                    'label_candidate': f'词{index}', 'text_verified': '', 'human_approved': False,
                    'training_ready': False, 'model_training_ready': False})
            tool.write_jsonl(master / 'sequences.jsonl', sequences)
            tool.write_jsonl(master / 'keyframes.jsonl', [])
            tool.write_jsonl(master / 'aliases.jsonl', aliases)
            tool.write_json(master / 'manifest.json', {'schema': 'signbridge-smplerx-candidate-sequences-v1',
                'sequence_count': 5, 'frames': 125, 'keyframe_count': 0, 'training_ready': False,
                'training_started': False})
            tool.write_json(master / 'dedup-report.json', {'candidate_rows': 5})
            tool.write_checksums(master)
            output = root / 'chunks'
            index = tool.split_package(master, output, chunk_size=2)
            self.assertEqual([row['sequence_count'] for row in index['chunks']], [2, 2, 1])
            all_ids, all_alias_ids = [], []
            for item in index['chunks']:
                chunk = output / item['path']
                _, chunk_tasks, _, _ = tool.runner.validate_package(chunk)
                all_ids.extend(row['annotation_id'] for row in chunk_tasks)
                all_alias_ids.extend(row['candidate_id'] for row in tool.read_rows(chunk / 'aliases.jsonl'))
            self.assertEqual(all_ids, [row['annotation_id'] for row in sequences])
            self.assertEqual(all_alias_ids, [row['candidate_id'] for row in aliases])
            self.assertEqual(len(set(all_ids)), 5)
            self.assertEqual((master / 'clips' / sequences[0]['annotation_id'] / 'clip.mp4').read_bytes(), b'video-0')


if __name__ == '__main__':
    unittest.main()
