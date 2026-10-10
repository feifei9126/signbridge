"""Automatic observation screening never approves signing or fills absent hands."""
import importlib.util
import json
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-hand-quality.py'


class HandQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('hand_quality', SCRIPT)
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def observation(self):
        rng = np.random.default_rng(12)
        points = rng.uniform(.3, .6, (21, 3)).astype(np.float32)
        points[0, :2] = [.4, .6]
        return points

    def test_exact_projection_is_only_automatic_candidate_not_human_approval(self):
        points = self.observation()
        r = self.m.hand_screen(points, True, points[:, :2] * [1280, 720], 1280, 720)
        self.assertTrue(r['eligible_for_research_loss'])
        self.assertFalse(r['hand_shape_approved'])
        self.assertEqual(r['mean_error_pixels'], 0.)

    def test_missing_mask_keeps_nan_and_excludes_supervision(self):
        r = self.m.hand_screen(np.full((21, 3), np.nan), False,
                               np.zeros((21, 2)), 1280, 720)
        self.assertEqual(r['reason'], 'missing_observation')
        self.assertFalse(r['eligible_for_research_loss'])
        self.assertIsNone(r['mean_error_pixels'])

    def test_nonfinite_out_of_image_and_small_hands_are_excluded(self):
        for kind in ('nan', 'outside', 'small'):
            p = self.observation()
            if kind == 'nan': p[1, 0] = np.nan
            if kind == 'outside': p[1, 0] = 1.5
            if kind == 'small': p[:] = .5
            r = self.m.hand_screen(p, True, np.zeros((21, 2)), 1280, 720)
            self.assertFalse(r['eligible_for_research_loss'])

    def test_large_wrist_and_projection_errors_do_not_pass(self):
        p = self.observation()
        r = self.m.hand_screen(p, True, p[:, :2] * [1280, 720] + 200, 1280, 720)
        self.assertFalse(r['eligible_for_research_loss'])
        self.assertEqual(r['reason'], 'projection_disagreement')

    def test_missing_neighbors_do_not_form_a_stable_training_target(self):
        p = self.observation()
        r = self.m.hand_screen(p, True, p[:, :2] * [1280, 720], 1280, 720)
        mask = self.m.stable_hand_mask([r, {**r, 'eligible_for_research_loss': False}, r])
        self.assertEqual(mask.tolist(), [False, False, False])
        self.assertFalse(r['hand_shape_approved'])

    def test_three_adjacent_observed_frames_keep_only_the_center(self):
        p = self.observation()
        r = self.m.hand_screen(p, True, p[:, :2] * [1280, 720], 1280, 720)
        np.testing.assert_array_equal(self.m.stable_hand_mask([r, r, r]), [False, True, False])

    def test_feature_mask_keeps_hands_whole_and_body_model_estimates(self):
        masks = self.m.feature_mask(np.array([False, True]), np.array([True, False]))
        self.assertEqual(masks.shape, (2, 133))
        self.assertEqual(masks.dtype, bool)
        self.assertTrue(masks[:, :30].all())
        self.assertTrue(masks[:, 120:].all())
        self.assertFalse(masks[0, 30:75].any())
        self.assertTrue(masks[0, 75:120].all())

    def test_coincident_left_right_observations_are_ambiguous_not_swapped(self):
        points = self.observation()
        left = self.m.hand_screen(points, True, points[:, :2] * [1280, 720], 1280, 720)
        right = dict(left)
        a, b = self.m.exclude_duplicate_hands(points, points, left, right, 1280, 720)
        self.assertFalse(a['eligible_for_research_loss'])
        self.assertFalse(b['eligible_for_research_loss'])
        self.assertEqual(a['reason'], 'ambiguous_overlapping_observations')
        self.assertTrue(a['side_assignment_unchanged'])
        self.assertTrue(left['eligible_for_research_loss'])

    def test_separate_hands_or_missing_side_do_not_trigger_duplicate_gate(self):
        left = self.observation()
        right = left.copy()
        right[:, 0] += .3
        a = self.m.hand_screen(left, True, left[:, :2] * [1280, 720], 1280, 720)
        b = self.m.hand_screen(right, True, right[:, :2] * [1280, 720], 1280, 720)
        after = self.m.exclude_duplicate_hands(left, right, a, b, 1280, 720)
        self.assertTrue(all(r['eligible_for_research_loss'] for r in after))
        missing = {**b, 'observed': False, 'eligible_for_research_loss': False}
        after = self.m.exclude_duplicate_hands(left, np.full((21, 3), np.nan), a, missing, 1280, 720)
        self.assertTrue(after[0]['eligible_for_research_loss'])

    def test_invalid_shapes_nonboolean_flags_and_tolerance_escalation_rejected(self):
        p = self.observation()
        for detected in (1, 'true'):
            with self.assertRaises(ValueError):
                self.m.hand_screen(p, detected, np.zeros((21, 2)), 1280, 720)
        with self.assertRaises(ValueError):
            self.m.hand_screen(p[:10], True, np.zeros((21, 2)), 1280, 720)
        with self.assertRaises(ValueError):
            self.m.feature_mask(np.ones(2), np.ones(2))

    def fixture(self, root):
        from PIL import Image
        delivery, batch = root / 'delivery', root / 'batch'
        segment, count = 'pilot-test-001', 5
        source = delivery / 'verified/motions'
        folder = source / 'samples' / segment
        folder.mkdir(parents=True)
        features = np.ones((count, 133), dtype=np.float32)
        np.save(folder / 'features-133.npy', features)
        (folder / 'quality.json').write_text('{}')
        (source / 'verification.json').write_text(json.dumps({'converted': 1, 'rejected': [],
            'training_ready': False, 'soke_commit': self.m.motion.SOKE_COMMIT}))
        row = {'segment_id': segment, 'frames': count, 'source_id': 'source-a', 'source_sha256': 'hash',
            'fps': 25., 'features': 'samples/'+segment+'/features-133.npy'}
        (source / 'motions.jsonl').write_text(json.dumps(row)+'\n')
        training = delivery / 'verified/training'
        training.mkdir()
        (training / 'report.json').write_text(json.dumps({'sequences': [{'segment_id': segment}]}))
        images = batch / 'samples' / segment / 'images'
        images.mkdir(parents=True)
        Image.new('RGB', (1280, 720)).save(images / '000001.jpg')
        task = {**row, 'images': 'samples/'+segment+'/images'}
        (batch / 'tasks.jsonl').write_text(json.dumps(task)+'\n')
        points = np.repeat(self.observation()[None], count, axis=0)
        arrays = {'timestamps_seconds': np.arange(count)/25.,
                  'source_timestamps_seconds': np.arange(count)/25.}
        for name, shape in {'pose_image':(33,4), 'pose_world':(33,4), 'face_image':(468,3)}.items():
            arrays[name]=np.full((count,*shape),np.nan,dtype=np.float32)
            arrays[name+'_detected']=np.zeros(count,dtype=bool)
        for side in ('left','right'):
            arrays[side+'_hand_image']=points.copy()
            if side == 'right':
                arrays[side+'_hand_image'][:,:,0] += .3
            arrays[side+'_hand_image_detected']=np.ones(count,dtype=bool)
        np.savez(images.parent/'observations.npz',**arrays)
        projection = np.stack((points[:,:,:2]*[1280,720],points[:,:,:2]*[1280,720]),axis=1)
        media = delivery / 'review-media-v2'
        media.mkdir()
        np.savez(media/(segment+'-joints.npz'),frame_ids=np.arange(1,count+1),
                 left_hand_projection=projection,right_hand_projection=projection + [384, 0])
        (delivery/'SHA256SUMS').write_text(''.join(self.m.evidence.digest(p)+'  '+
            str(p.relative_to(delivery))+'\n' for p in sorted(delivery.rglob('*')) if p.is_file()))
        return SimpleNamespace(training_delivery=delivery,batch=batch,output=root/'audit'), task, features

    def test_full_audit_copies_features_exactly_and_changes_only_loss_eligibility(self):
        with tempfile.TemporaryDirectory() as folder:
            args, task, expected = self.fixture(Path(folder))
            with patch.object(self.m.motion,'verify_pack',return_value=[task]):
                report_path=self.m.audit(args)
            result=json.loads(report_path.read_text())
            self.assertFalse(result['parameters_modified'])
            self.assertFalse(result['hand_shape_approved'])
            masked=args.output/'masked-motions'
            np.testing.assert_array_equal(np.load(masked/task['features']),expected)
            mask=np.load((masked/task['features']).with_name('feature-valid-mask.npy'))
            self.assertFalse(mask[0,30:120].any())
            self.assertTrue(mask[1:-1].all())
            self.assertFalse(mask[-1,30:120].any())
            self.m.evidence.verify_manifest(args.output,args.output/'SHA256SUMS')

    def test_changed_projection_digest_rejected_before_creating_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            args,task,_=self.fixture(Path(folder))
            p=args.training_delivery/'review-media-v2'/(task['segment_id']+'-joints.npz')
            p.write_bytes(b'tampered')
            with patch.object(self.m.motion,'verify_pack',return_value=[task]),self.assertRaisesRegex(ValueError,'digest mismatch'):
                self.m.audit(args)
            self.assertFalse(args.output.exists())


if __name__ == '__main__':
    unittest.main()
