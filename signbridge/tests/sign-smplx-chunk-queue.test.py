import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-smplx-chunk-queue.py'


def module():
    spec = importlib.util.spec_from_file_location('smplx_chunk_queue', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class SmplxChunkQueueTests(unittest.TestCase):
    def test_disk_reserve_scales_with_chunk_frames(self):
        queue = module()
        self.assertEqual(queue.required_free_bytes(100, 1), (1 << 30) + 10_000_000)
        with self.assertRaises(ValueError):
            queue.required_free_bytes(0)

    def test_completed_report_requires_exact_sequence_frame_and_training_flags(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = {'annotation_id': 'fit-one', 'frames': 2}
            (root / 'sequences.jsonl').write_text(json.dumps(case) + '\n')
            (root / 'manifest.json').write_text(json.dumps({'frames': 2}))
            (root / 'logs').mkdir()
            (root / 'logs/fit-one.log').write_text('log')
            (root / 'report.json').write_text(json.dumps({
                'schema': 'signbridge-smplerx-candidate-sequences-run-v1',
                'status': 'smplerx_sequences_completed_pending_quality_review',
                'training_started': False, 'training_ready': False, 'human_approved': False,
                'input_manifest_sha256': queue.sha(root / 'manifest.json'),
                'sequence_count': 1, 'completed_sequences': 1, 'frames_expected': 2,
                'completed_frames': 2,
                'candidate_records': [{'annotation_id': 'fit-one', 'frames_expected': 2,
                  'smplx_parameter_files': 2, 'render_frames': 2, 'smplx_missing_detection_frames': [],
                  'mano_keyframes_missing_smplx_fit': [], 'log_sha256': queue.sha(root / 'logs/fit-one.log')}] }))
            (root / 'fits/fit-one/smplx').mkdir(parents=True)
            (root / 'fits/fit-one/meta').mkdir(parents=True)
            (root / 'fits/fit-one/img').mkdir(parents=True)
            for i in range(1, 3):
                (root / f'fits/fit-one/smplx/{i:05d}_0.npz').write_bytes(b'x')
                (root / f'fits/fit-one/meta/{i:05d}_0.json').write_text('{}')
                (root / f'fits/fit-one/img/{i:06d}.jpg').write_bytes(b'x')
            (root / 'SHA256SUMS').write_text(''.join(
                hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(root).as_posix() + '\n'
                for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))
            chunk = {'path': 'chunk-001', 'chunk_index_1based': 1}
            passed = queue.validate_completed_attempt(chunk, root, root)
            self.assertEqual(passed['frames'], 2)
            self.assertFalse(passed['training_ready'])
            data = json.loads((root / 'report.json').read_text())
            data['completed_frames'] = 1
            (root / 'report.json').write_text(json.dumps(data))
            (root / 'SHA256SUMS').write_text(''.join(
                hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(root).as_posix() + '\n'
                for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))
            with self.assertRaises(ValueError):
                queue.validate_completed_attempt(chunk, root, root)

    def test_index_rejects_missing_or_reordered_chunks_and_wrong_manifest(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); chunks = root / 'chunks';chunks.mkdir()
            index_path = root / 'chunk-index.json'
            base = {'schema': 'signbridge-smplerx-candidate-chunk-index-v1',
                    'partition_exactly_once': True, 'training_ready': False, 'training_started': False,
                    'sequence_count': 0, 'candidate_alias_count': 0, 'frame_count': 0, 'chunks': []}
            index_path.write_text(json.dumps(base))
            with self.assertRaises(ValueError):
                queue.validate_chunk_index(index_path, chunks)


if __name__ == '__main__':
    unittest.main()
