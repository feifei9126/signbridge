import importlib.util
import json
import hashlib
import fcntl
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-smplx-chunk-queue.py'


def module():
    spec = importlib.util.spec_from_file_location('smplx_chunk_queue', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def seal(root):
    (root / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(root).as_posix() + '\n'
        for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))


def fixture(queue, package, attempt, missing=(), name='fit-one'):
    package.mkdir(parents=True, exist_ok=True)
    attempt.mkdir(parents=True, exist_ok=True)
    case = {'annotation_id': name, 'frames': 3, 'source_id': 'source-one',
            'source_sha256': 'a' * 64, 'label_candidate': 'candidate', 'mano_keyframes': []}
    (package / 'sequences.jsonl').write_text(json.dumps(case) + '\n')
    (package / 'manifest.json').write_text(json.dumps({
        'frames': 3, 'sequence_count': 1, 'candidate_alias_count': 1, 'training_started': False}))
    seal(package)
    (attempt / 'logs').mkdir(exist_ok=True)
    (attempt / f'logs/{name}.log').write_text('finished inference\n')
    for directory in ('smplx', 'meta', 'img'):
        (attempt / 'fits' / name / directory).mkdir(parents=True, exist_ok=True)
    (attempt / 'input-frames' / name).mkdir(parents=True, exist_ok=True)
    for i in range(1, 4):
        (attempt / f'fits/{name}/img/{i:06d}.jpg').write_bytes(b'render')
        (attempt / f'input-frames/{name}/{i:06d}.jpg').write_bytes(b'input')
        if i not in missing:
            (attempt / f'fits/{name}/smplx/{i:05d}_0.npz').write_bytes(b'parameter')
            (attempt / f'fits/{name}/meta/{i:05d}_0.json').write_text('{}')
    record = {'annotation_id': name, 'frames_expected': 3,
              'source_id': case['source_id'], 'source_sha256': case['source_sha256'],
              'label_candidate': 'candidate', 'text_verified': '',
              'training_ready': False, 'human_approved': False,
              'smplx_parameter_files': 3 - len(missing), 'render_frames': 3,
              'smplx_missing_detection_frames': list(missing), 'mano_keyframes_missing_smplx_fit': [],
              'log_sha256': queue.sha(attempt / f'logs/{name}.log')}
    (attempt / 'report.json').write_text(json.dumps({
        'schema': 'signbridge-smplerx-candidate-sequences-run-v1',
        'status': 'smplerx_sequences_completed_pending_quality_review',
        'training_started': False, 'training_ready': False, 'human_approved': False,
        'input_manifest_sha256': queue.sha(package / 'manifest.json'),
        'sequence_count': 1, 'completed_sequences': 1, 'frames_expected': 3,
        'completed_frames': 3, 'candidate_records': [record]}))
    seal(attempt)
    return {'path': 'chunk-001', 'chunk_index_1based': 1}, case


def queue_fixture(queue, root):
    chunks = root / 'chunks'; attempts = root / 'attempts'
    entries = []
    for number in (1, 2):
        fixture(queue, chunks / f'chunk-{number:03d}', attempts / f'chunk-{number:03d}-attempt-1',
                missing=(2,) if number == 1 else (), name=f'fit-{number}')
        entries.append({'path': f'chunk-{number:03d}', 'chunk_index_1based': number,
            'sequence_count': 1, 'candidate_alias_count': 1, 'frames': 3,
            'package_manifest_sha256': queue.sha(chunks / f'chunk-{number:03d}/SHA256SUMS')})
    shutil.rmtree(attempts / 'chunk-002-attempt-1')
    index = {'schema': 'signbridge-smplerx-candidate-chunk-index-v1',
             'partition_exactly_once': True, 'training_ready': False, 'training_started': False,
             'sequence_count': 2, 'candidate_alias_count': 2, 'frame_count': 6,
             'parent_package_manifest_sha256': 'b' * 64, 'chunks': entries}
    index_path = chunks / 'chunk-index.json'; index_path.write_text(json.dumps(index))
    smplerx = root / 'SMPLer-X'; (smplerx / 'main').mkdir(parents=True)
    (smplerx / 'main/inference.py').write_text('# test fixture\n')
    return SimpleNamespace(chunk_root=chunks, chunk_index=index_path, runner=TOOL,
        smplerx_root=smplerx, python=Path(sys.executable), output_root=attempts,
        queue_root=root / 'queue', model='smpler_x_h32', reserve_gib=1,
        expected_commit='frozen-revision', quarantine_missing_detections=True)


class SmplxChunkQueueTests(unittest.TestCase):
    def test_missing_detections_remain_rejected_by_default(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            chunk, _ = fixture(queue, root / 'package', root / 'attempt', missing=(2,))
            with self.assertRaises(ValueError):
                queue.validate_completed_attempt(chunk, root / 'package', root / 'attempt')

    def test_explicit_quarantine_preserves_missing_frames_and_excludes_full_sequence(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); package = root / 'package'; attempt = root / 'attempt'
            chunk, _ = fixture(queue, package, attempt, missing=(2,))
            before = queue.sha(attempt / 'SHA256SUMS')
            result = queue.validate_completed_attempt(
                chunk, package, attempt, quarantine_missing_detections=True)
            self.assertEqual(result['sequences'], 0)
            self.assertEqual(result['frames'], 0)
            self.assertEqual(result['sequences_accounted'], 1)
            self.assertEqual(result['parameter_files'], 2)
            self.assertEqual(result['quarantined_candidates'][0]['missing_frames_1based'], [2])
            self.assertFalse(result['quarantined_candidates'][0]['feature_extraction_allowed'])
            self.assertFalse(result['quarantined_candidates'][0]['human_approved'])
            self.assertFalse(result['model_training_ready'])
            self.assertEqual(queue.sha(attempt / 'SHA256SUMS'), before)
            self.assertFalse((attempt / 'fits/fit-one/smplx/00002_0.npz').exists())

    def test_hash_verified_runner_runtime_evidence_is_not_an_extra_candidate(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); package = root / 'package'; attempt = root / 'attempt'
            chunk, _ = fixture(queue, package, attempt, missing=(2,))
            runtime = attempt / 'fits/runtime/fit-one_20261029_060000'
            runtime.mkdir(parents=True)
            (runtime / 'config.py').write_text('frozen runtime configuration\n')
            seal(attempt)
            result = queue.validate_completed_attempt(
                chunk, package, attempt, quarantine_missing_detections=True)
            self.assertEqual(result['sequences_accounted'], 1)
            self.assertEqual(len(result['quarantined_candidates']), 1)
            (runtime / 'config.py').write_text('corrupt runtime configuration')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                queue.validate_completed_attempt(
                    chunk, package, attempt, quarantine_missing_detections=True)

    def test_quarantine_never_excuses_hash_or_frame_set_damage(self):
        queue = module()
        mutations = ['hash', 'render', 'input', 'metadata', 'extra_person', 'unreported_gap', 'log']
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); package = root / 'package'; attempt = root / 'attempt'
                chunk, _ = fixture(queue, package, attempt, missing=(2,))
                if mutation == 'hash':
                    (attempt / 'fits/fit-one/smplx/00001_0.npz').write_bytes(b'changed')
                elif mutation == 'render':
                    (attempt / 'fits/fit-one/img/000002.jpg').unlink()
                elif mutation == 'input':
                    (attempt / 'input-frames/fit-one/000002.jpg').unlink()
                elif mutation == 'metadata':
                    (attempt / 'fits/fit-one/meta/00001_0.json').unlink()
                elif mutation == 'extra_person':
                    (attempt / 'fits/fit-one/smplx/00001_1.npz').write_bytes(b'extra')
                elif mutation == 'unreported_gap':
                    data = json.loads((attempt / 'report.json').read_text())
                    data['candidate_records'][0]['smplx_missing_detection_frames'] = []
                    (attempt / 'report.json').write_text(json.dumps(data))
                else:
                    (attempt / 'logs/fit-one.log').write_text('changed log')
                if mutation != 'hash':
                    seal(attempt)
                with self.assertRaises(ValueError):
                    queue.validate_completed_attempt(
                        chunk, package, attempt, quarantine_missing_detections=True)

    def test_quarantine_does_not_permit_approval_or_count_conflicts(self):
        queue = module()
        mutations = {'human_approved': True, 'text_verified': 'approved',
                     'smplx_parameter_files': 3, 'render_frames': 2,
                     'smplx_missing_detection_frames': [2, 2]}
        for key, value in mutations.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); package = root / 'package'; attempt = root / 'attempt'
                chunk, _ = fixture(queue, package, attempt, missing=(2,))
                data = json.loads((attempt / 'report.json').read_text())
                data['candidate_records'][0][key] = value
                (attempt / 'report.json').write_text(json.dumps(data)); seal(attempt)
                with self.assertRaises(ValueError):
                    queue.validate_completed_attempt(
                        chunk, package, attempt, quarantine_missing_detections=True)

    def test_quarantine_rejects_inconsistent_total_or_unreported_candidate_directory(self):
        queue = module()
        for mutation in ('total_frames', 'extra_candidate', 'model_training_ready'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); package = root / 'package'; attempt = root / 'attempt'
                chunk, _ = fixture(queue, package, attempt, missing=(2,))
                data = json.loads((attempt / 'report.json').read_text())
                if mutation == 'total_frames':
                    manifest = json.loads((package / 'manifest.json').read_text())
                    manifest['frames'] = 4
                    (package / 'manifest.json').write_text(json.dumps(manifest)); seal(package)
                    data.update(frames_expected=4, completed_frames=4,
                                input_manifest_sha256=queue.sha(package / 'manifest.json'))
                elif mutation == 'extra_candidate':
                    (attempt / 'fits/unreported-candidate').mkdir()
                else:
                    data['model_training_ready'] = True
                (attempt / 'report.json').write_text(json.dumps(data)); seal(attempt)
                with self.assertRaises(ValueError):
                    queue.validate_completed_attempt(
                        chunk, package, attempt, quarantine_missing_detections=True)

    def test_process_probe_detects_other_queues_but_not_itself(self):
        queue = module()
        output = (f'{os.getpid()} python /tools/sign-smplx-chunk-queue.py\n'
                  '987654 python /tools/v2/sign-smplx-chunk-queue.py\n')
        with mock.patch.object(queue.subprocess, 'run', return_value=SimpleNamespace(stdout=output)):
            active = queue.active_inference_processes()
        self.assertEqual(len(active), 1)
        self.assertIn('987654', active[0])

    def test_existing_output_lock_prevents_duplicate_dispatch(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with (output / '.queue.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, 'lock'):
                    queue.run_queue(SimpleNamespace(output_root=output))

    def test_queue_adopts_quarantine_and_resumes_at_next_unprocessed_chunk(self):
        queue = module()
        with tempfile.TemporaryDirectory() as folder:
            args = queue_fixture(queue, Path(folder))
            launches = []
            def command(argv, **kwargs):
                if argv[:2] == ['git', 'rev-parse']:
                    return SimpleNamespace(stdout='frozen-revision\n', returncode=0)
                launches.append(argv)
                package = Path(argv[argv.index('--package') + 1])
                attempt = Path(argv[argv.index('--output') + 1])
                fixture(queue, package, attempt, name='fit-2')
                return SimpleNamespace(returncode=0)
            with mock.patch.object(queue, 'active_inference_processes', return_value=[]), \
                    mock.patch.object(queue.subprocess, 'run', side_effect=command), \
                    mock.patch.object(queue.shutil, 'disk_usage', return_value=SimpleNamespace(free=10 << 30)):
                self.assertEqual(queue.run_queue(args), 0)
                self.assertEqual(queue.run_queue(args), 0)
            self.assertEqual(len(launches), 1)
            self.assertIn('chunk-002', ' '.join(launches[0]))
            state = json.loads((args.queue_root / 'queue-state.json').read_text())
            self.assertEqual(state['status'], 'completed_with_quarantined_candidates')
            self.assertEqual(state['complete_sequences'], 1)
            self.assertEqual(state['accounted_sequences'], 2)
            self.assertEqual(state['quarantined_sequences'], 1)
            self.assertEqual(len(state['completed']), 2)
            ledger = json.loads((args.queue_root / 'quarantined-candidates.json').read_text())
            self.assertEqual(ledger['candidates'][0]['annotation_id'], 'fit-1')
            self.assertEqual(ledger['candidates'][0]['missing_frames_1based'], [2])
            self.assertFalse(ledger['model_training_ready'])
            args.quarantine_missing_detections = False
            with self.assertRaisesRegex(ValueError, 'policy|provenance'):
                queue.run_queue(args)

    def test_low_disk_nonzero_exit_and_corruption_still_pause_without_retry(self):
        queue = module()
        for reason in ('low_disk', 'runner_failure', 'corruption'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as folder:
                args = queue_fixture(queue, Path(folder)); launches = []
                first = args.output_root / 'chunk-001-attempt-1'
                if reason == 'corruption':
                    (first / 'fits/fit-1/smplx/00001_0.npz').write_bytes(b'corrupt')
                def command(argv, **kwargs):
                    if argv[:2] == ['git', 'rev-parse']:
                        return SimpleNamespace(stdout='frozen-revision\n', returncode=0)
                    launches.append(argv)
                    attempt = Path(argv[argv.index('--output') + 1]); attempt.mkdir()
                    (attempt / 'failed.log').write_text('preserved failure evidence')
                    return SimpleNamespace(returncode=2)
                with mock.patch.object(queue, 'active_inference_processes', return_value=[]), \
                        mock.patch.object(queue.subprocess, 'run', side_effect=command), \
                        mock.patch.object(queue.shutil, 'disk_usage', return_value=SimpleNamespace(
                            free=0 if reason == 'low_disk' else 10 << 30)):
                    if reason == 'corruption':
                        with self.assertRaisesRegex(ValueError, 'SHA256'):
                            queue.run_queue(args)
                    else:
                        self.assertEqual(queue.run_queue(args), 75 if reason == 'low_disk' else 2)
                state = json.loads((args.queue_root / 'queue-state.json').read_text())
                expected_status = {'low_disk': 'paused_low_disk', 'runner_failure': 'paused_fit_failure',
                                   'corruption': 'paused_audit_failure'}[reason]
                self.assertEqual(state['status'], expected_status)
                self.assertEqual(len(launches), 1 if reason == 'runner_failure' else 0)
                self.assertFalse(state['training_ready'])
                if reason == 'runner_failure':
                    self.assertTrue((args.output_root / 'chunk-002-attempt-1/failed.log').is_file())

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
