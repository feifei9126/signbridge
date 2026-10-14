"""Regression checks for resumable GPU fitting and strict result import."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-source4-stream-fit.py'
spec = importlib.util.spec_from_file_location('source4_stream', SCRIPT)
stream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stream)


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        self.task = {'segment_id': 'new-a-cap-01', 'frames': 4, 'fps': 25.0,
                     'clip': 'clip.mp4', 'source_id': 'source-a', 'source_sha256': 'a'*64,
                     'text_verified': '你好', 'start_seconds': 2.0, 'end_seconds': 2.16,
                     'training_ready': False, 'model_training_ready': False}
        stream.motion.write_jsonl(self.package / 'tasks.jsonl', [self.task])
        self.preflight = {'ready': True, 'actual_commit': stream.motion.SMPLERX_COMMIT}

    def test_resumed_report_is_running_before_inference(self):
        output = self.root / 'out'
        output.mkdir()
        stream.write_json(output / 'report.json', {
            'schema': 'signbridge-source4-stream-fit-v1', 'status': 'completed_pending_import_audit',
            'completed': [], 'failed': [], 'model': 'smpler_x_h32',
            'tasks_sha256': stream.sha256_file(self.package / 'tasks.jsonl'),
            'preflight': self.preflight,
        })
        observed = []
        def fail_after_read(*args):
            observed.append(json.loads((output/'report.json').read_text())['status'])
            raise ValueError('fixture stops before running a GPU')
        args = SimpleNamespace(package=self.package, smplerx_root=self.root/'model',
                               python=Path('/python'), output=output, model='smpler_x_h32',
                               start_index=0, limit=1, stop_on_error=False)
        with patch.object(stream, 'validate_package', return_value=[self.task]), \
             patch.object(stream.motion, 'preflight', return_value=self.preflight), \
             patch.object(stream, 'extract_images', side_effect=fail_after_read), \
             contextlib.redirect_stdout(io.StringIO()):
            stream.run(args)
        self.assertEqual(observed, ['running'])

    def test_resume_rejects_changed_task_manifest(self):
        output = self.root/'out'
        output.mkdir()
        stream.write_json(output/'report.json', {
            'schema': 'signbridge-source4-stream-fit-v1', 'status': 'running',
            'completed': [], 'failed': [], 'model': 'smpler_x_h32',
            'tasks_sha256': 'b'*64, 'preflight': self.preflight,
        })
        args = SimpleNamespace(package=self.package, smplerx_root=self.root/'model',
                               python=Path('/python'), output=output, model='smpler_x_h32',
                               start_index=0, limit=1, stop_on_error=False)
        with patch.object(stream, 'validate_package', return_value=[self.task]), \
             patch.object(stream.motion, 'preflight', return_value=self.preflight), \
             patch.object(stream, 'extract_images', side_effect=AssertionError('must not infer')):
            with self.assertRaisesRegex(ValueError, 'provenance'):
                stream.run(args)

    def make_results(self):
        results = self.root/'results'
        sample = results/'fits'/self.task['segment_id']
        for name in ('smplx', 'meta', 'img'):
            (sample/name).mkdir(parents=True)
        for number in range(1, 5):
            params = {src: np.zeros(shape, np.float32) for src, _, shape in stream.motion.PARAMETERS}
            params.update({name: np.zeros((1,3),np.float32) for name in ('transl','leye_pose','reye_pose')})
            np.savez(sample/'smplx'/f'{number:05d}_0.npz', **params)
            stream.write_json(sample/'meta'/f'{number:05d}_0.json', {
                'img_path': f'/remote/out/work/{self.task["segment_id"]}/images/{number:06d}.jpg'})
            cv2.imwrite(str(sample/'img'/f'{number:06d}.jpg'), np.zeros((32,32,3),np.uint8))
        log = results/'logs'/f'{self.task["segment_id"]}.log'
        log.parent.mkdir()
        log.write_text('fixture completed')
        stream.write_json(results/'report.json', {
            'schema': 'signbridge-source4-stream-fit-v1',
            'status': 'completed_pending_import_audit', 'preflight': self.preflight,
            'completed': [self.task['segment_id']], 'failed': [], 'training_ready': False,
            'training_started': False,
            'records': [{'segment_id':self.task['segment_id'], 'frames_expected':4,
                         'parameters':4, 'renders':4, 'log_sha256':stream.sha256_file(log)}]})
        return results

    def audit(self, results):
        with patch.object(stream.motion,'verify_pack',return_value=[self.task]), \
             contextlib.redirect_stdout(io.StringIO()):
            return stream.audit_results(self.package, results, self.root/'audit', '/remote/out')

    def test_audit_exports_finite_133d_features_without_approving_quality(self):
        results = self.make_results()
        report = self.audit(results)
        self.assertEqual(report['converted'], 1)
        self.assertFalse(report['training_ready'])
        feature = self.root/'audit'/'samples'/self.task['segment_id']/'features-133.npy'
        self.assertEqual(np.load(feature,allow_pickle=False).shape, (4,133))
        motion = stream.read_jsonl(self.root/'audit'/'motions.jsonl')[0]
        self.assertEqual(motion['motion_review_status'],'needs_review')
        self.assertFalse(motion['model_training_ready'])

    def test_missing_detection_is_recorded_without_interpolation_or_features(self):
        results = self.make_results()
        (results/'fits'/self.task['segment_id']/'smplx'/'00002_0.npz').unlink()
        report = self.audit(results)
        self.assertEqual(report['converted'],0)
        self.assertEqual(report['rejected'][0]['missing_detection_frames'],[2])
        self.assertFalse(any((self.root/'audit').rglob('features-133.npy')))

    def test_audit_rejects_wrong_metadata_frame(self):
        results = self.make_results()
        stream.write_json(results/'fits'/self.task['segment_id']/'meta'/'00001_0.json',
                          {'img_path':'/remote/out/work/other/images/000001.jpg'})
        report = self.audit(results)
        self.assertEqual(report['converted'],0)
        self.assertIn('metadata', report['rejected'][0]['reason'])

    def test_audit_rejects_corrupt_render(self):
        results = self.make_results()
        (results/'fits'/self.task['segment_id']/'img'/'000001.jpg').write_bytes(b'not an image')
        report = self.audit(results)
        self.assertEqual(report['converted'],0)
        self.assertIn('render',report['rejected'][0]['reason'])


    def test_audit_records_legacy_provenance_gap(self):
        report = self.audit(self.make_results())
        self.assertTrue(report['provenance_limitations'])
        self.assertIn('task digest', ' '.join(report['provenance_limitations']))

    def test_audit_rejects_tampered_inference_log(self):
        results = self.make_results()
        (results/'logs'/f'{self.task["segment_id"]}.log').write_text('changed')
        report = self.audit(results)
        self.assertEqual(report['converted'],0)
        self.assertIn('log checksum',report['rejected'][0]['reason'])

    def test_audit_rejects_nonfinite_parameters(self):
        results = self.make_results()
        native = results/'fits'/self.task['segment_id']/'smplx'/'00001_0.npz'
        with np.load(native,allow_pickle=False) as values:
            copied = dict(values)
        copied['left_hand_pose'][0,0] = np.nan
        np.savez(native,**copied)
        report = self.audit(results)
        self.assertEqual(report['converted'],0)
        self.assertFalse(any((self.root/'audit').rglob('features-133.npy')))


if __name__ == '__main__':
    unittest.main()
