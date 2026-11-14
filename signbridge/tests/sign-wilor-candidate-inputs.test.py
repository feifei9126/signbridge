"""Candidate inference must preserve source versions and approval boundaries."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location('candidate', Path(__file__).resolve().parents[1] / 'src/tools/sign-wilor-candidate-inputs.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.batch = self.root / 'batch'
        self.batch.mkdir()
        self.task = {'segment_id': 'basic-i', 'frames': 2, 'fps': 30., 'source_sha256': 'a' * 64,
                     'clip': 'samples/basic-i/clip.mp4', 'observation_artifact': 'samples/basic-i/observations.npz',
                     'frame_manifest': 'samples/basic-i/frames.jsonl', 'images': 'samples/basic-i/images',
                     'human_approved': False, 'semantics_approved': False, 'boundaries_approved': False,
                     'model_training_ready': False, 'training_ready': False}
        for name in [self.task['clip'], self.task['observation_artifact']]:
            file = self.batch / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'original')
        self.frames = []
        for number in [1, 2]:
            file = self.batch / self.task['images'] / ('%06d.jpg' % number)
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(bytes([number]))
            self.frames.append({'frame_id': number, 'image': str(file.relative_to(self.batch)),
                                'sha256': candidate.sha(file), 'clip_seconds': (number - 1) / 30.})
        self.task['clip_sha256'] = candidate.sha(self.batch / self.task['clip'])
        self.task['observation_sha256'] = candidate.sha(self.batch / self.task['observation_artifact'])
        self.contract = {'schema': 'signbridge-smplerx-input-v1', 'smplerx_commit': '064baef0e4ab5277a3297691bc1d46ea5412586f',
                         'model_training_ready': False, 'training_ready': False, 'human_approved': False,
                         'mirroring': False, 'resampling': False}
        self.plan = {'schema': 'signbridge-wilor-candidate-source-plan-v1', 'training_ready': False,
                     'model_training_ready': False, 'human_approved': False,
                     'sequences': [{k: self.task[k] for k in ['segment_id', 'frames', 'source_sha256', 'clip_sha256']}]}

    def seal(self):
        (self.batch / 'contract.json').write_text(json.dumps(self.contract))
        (self.batch / 'tasks.jsonl').write_text(json.dumps(self.task) + '\n')
        (self.batch / self.task['frame_manifest']).write_text(''.join(json.dumps(f) + '\n' for f in self.frames))
        files = sorted(p for p in self.batch.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
        (self.batch / 'SHA256SUMS').write_text(''.join(candidate.sha(p) + '  ' + str(p.relative_to(self.batch)) + '\n' for p in files))
        for name, key in [('SHA256SUMS', 'batch_manifest_sha256'), ('tasks.jsonl', 'batch_tasks_sha256'), ('contract.json', 'batch_contract_sha256')]:
            self.plan[key] = candidate.sha(self.batch / name)
        path = self.root / 'plan.json'
        path.write_text(json.dumps(self.plan))
        return path, candidate.sha(path)

    def test_unapproved_candidate_can_be_observed_without_fabricating_approval(self):
        path, digest = self.seal()
        rows = candidate.read_candidate_plan(self.batch, path, digest)
        self.assertEqual([r[1] for r in rows], [1, 2])
        self.assertFalse(rows[0][0]['human_approved'])
        self.assertNotIn('content_reviewed', rows[0][0])

    def test_changed_image_rejected(self):
        path, digest = self.seal()
        (self.batch / self.frames[0]['image']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            candidate.read_candidate_plan(self.batch, path, digest)

    def test_conflicting_task_or_batch_training_gate_rejected(self):
        self.task['training_ready'] = True
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'training gate'):
            candidate.read_candidate_plan(self.batch, path, digest)
        self.task['training_ready'] = False
        self.contract['training_ready'] = True
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'contract'):
            candidate.read_candidate_plan(self.batch, path, digest)

    def test_reordered_frames_and_bad_timestamps_rejected(self):
        self.frames.reverse()
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'mapping'):
            candidate.read_candidate_plan(self.batch, path, digest)
        self.frames.reverse()
        self.frames[1]['clip_seconds'] = .5
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'time'):
            candidate.read_candidate_plan(self.batch, path, digest)

    def test_scope_mismatch_and_changed_digest_rejected(self):
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'digest'):
            candidate.read_candidate_plan(self.batch, path, '0' * 64)
        self.plan['sequences'][0]['source_sha256'] = 'b' * 64
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'identity'):
            candidate.read_candidate_plan(self.batch, path, digest)

    def test_approvals_duplicates_and_invalid_counts_rejected(self):
        for field in ['training_ready', 'human_approved', 'model_training_ready']:
            self.plan[field] = True
            path, digest = self.seal()
            with self.assertRaisesRegex(ValueError, 'gate'):
                candidate.read_candidate_plan(self.batch, path, digest)
            self.plan[field] = False
        self.plan['sequences'] *= 2
        path, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            candidate.read_candidate_plan(self.batch, path, digest)

    def test_symlink_escape_rejected(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'original')
        path = self.batch / self.task['observation_artifact']
        path.unlink()
        path.symlink_to(outside)
        plan, digest = self.seal()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            candidate.read_candidate_plan(self.batch, plan, digest)


if __name__ == '__main__':
    unittest.main()
