"""Corrective fitting cannot bridge missing targets or change protected source arrays."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-basic-motion-correct.py'
spec=importlib.util.spec_from_file_location('basic_correct_tests',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class BasicMotionCorrectionTests(unittest.TestCase):
    def params(self):return {k:np.zeros(shape,np.float32) for k,shape in m.compare.SHAPES.items()}

    def test_neighbors_never_bridge_missing_or_rejected_frame(self):
        mask=np.array([True,False,True,True,True]);accepted=np.array([True,False,True,False,True])
        self.assertEqual(m.observed_neighbors(2,mask,accepted),[])
        self.assertEqual(m.observed_neighbors(3,mask,accepted),[2,4])
        self.assertEqual(m.observed_neighbors(0,mask,accepted),[])

    def test_other_hand_and_root_are_protected(self):
        a=self.params();b={k:v.copy() for k,v in a.items()};m.unchanged(a,b,'left')
        b['right_hand_pose'][0,0]=.01
        with self.assertRaises(ValueError):m.unchanged(a,b,'left')
        b={k:v.copy() for k,v in a.items()};b['transl'][0,0]=1
        with self.assertRaises(ValueError):m.unchanged(a,b,'left')

    def test_elbow_bound_is_relative_to_original_not_previous_candidate(self):
        a=self.params();b={k:v.copy() for k,v in a.items()};index=m.hand.ELBOWS['left']-1;b['body_pose'][index,0]=np.deg2rad(14.9);m.unchanged(a,b,'left');b['body_pose'][index,0]=np.deg2rad(16)
        with self.assertRaises(ValueError):m.unchanged(a,b,'left')

    def test_only_same_side_elbow_wrist_and_fingers_may_change(self):
        a=self.params();b={k:v.copy() for k,v in a.items()};b['body_pose'][m.hand.WRISTS['left']-1,0]=.1;b['left_hand_pose'][0,0]=.2;m.unchanged(a,b,'left');b['body_pose'][0,0]=.1
        with self.assertRaises(ValueError):m.unchanged(a,b,'left')

    def test_dtype_cannot_be_silently_promoted(self):
        a=self.params();b={k:v.copy() for k,v in a.items()};b['left_hand_pose']=b['left_hand_pose'].astype(np.float64)
        with self.assertRaises(ValueError):m.unchanged(a,b,'left')


class TemporalGateTests(unittest.TestCase):
    """Use analytic projected points; only replace the optimizer's proposed result."""

    def setUp(self):
        self.original = {k: np.zeros(shape, np.float32) for k, shape in m.compare.SHAPES.items()}
        self.original['left_hand_pose'][14, 2] = 1.
        self.initial = {k: v.copy() for k, v in self.original.items()}
        self.initial['left_hand_pose'][14, 2] = .7
        self.target = np.column_stack((np.arange(21) * 2., np.arange(21) * 3., np.ones(21)))
        self.camera = {'focal': np.ones(2), 'princpt': np.zeros(2)}
        self.model = SimpleNamespace(mean=np.full((55, 3), .03), prepared=lambda p: None, hand=self.hand)

    def hand(self, params, side, prepared=None):
        points = self.target.copy()
        points[1:, :2] += params['left_hand_pose'][14, 2]
        points[[4, 8, 12, 16, 20], :2] += params['left_hand_pose'][13, 2]
        points[:, 0] += 20. * params['body_pose'][m.hand.WRISTS[side] - 1, 0]
        return points

    def fit(self, candidate, status=2):
        x = np.r_[candidate['left_hand_pose'].ravel(), np.zeros(3), candidate['body_pose'][m.hand.WRISTS['left'] - 1]]

        def propose(residual, x0, **kwargs):
            self.assertTrue(np.isfinite(residual(x)).all())
            return SimpleNamespace(x=x, status=status, nfev=1)

        with patch.object(m, 'least_squares', side_effect=propose):
            return m.fit_temporal(self.model, self.original, self.initial, 'left', self.target, self.camera, [self.initial])

    def test_temporal_rechecks_projection_against_original(self):
        candidate = {k: v.copy() for k, v in self.initial.items()}
        candidate['left_hand_pose'][14, 2] = .95
        self.initial['left_hand_pose'][14, 2] = .79
        _, metrics = self.fit(candidate)
        self.assertFalse(metrics['numeric_candidate_retained'])

    def test_temporal_rejects_tip_regression_hidden_by_aggregate_improvement(self):
        candidate = {k: v.copy() for k, v in self.initial.items()}
        candidate['left_hand_pose'][14, 2] = .5
        candidate['left_hand_pose'][13, 2] = .55
        _, metrics = self.fit(candidate)
        self.assertLess(metrics['after']['local_rmse_pixels'], metrics['before']['local_rmse_pixels'])
        self.assertFalse(metrics['numeric_candidate_retained'])

    def test_temporal_does_not_erase_independent_fingertip_improvement(self):
        candidate = {k: v.copy() for k, v in self.initial.items()}
        candidate['left_hand_pose'][14, 2] = .5
        candidate['left_hand_pose'][13, 2] = .3
        _, metrics = self.fit(candidate)
        self.assertFalse(metrics['numeric_candidate_retained'])

    def test_temporal_rejects_geodesic_finger_limit_despite_component_bounds(self):
        candidate = {k: v.copy() for k, v in self.initial.items()}
        candidate['left_hand_pose'][0] = [2., 2., 0.]
        _, metrics = self.fit(candidate)
        self.assertFalse(metrics['numeric_candidate_retained'])

    def test_temporal_timeout_is_not_retained(self):
        _, metrics = self.fit(self.initial, status=0)
        self.assertFalse(metrics['numeric_candidate_retained'])

    def test_temporal_rechecks_wrist_position_against_original(self):
        wrist = m.hand.WRISTS['left'] - 1
        self.original['body_pose'][wrist, 0] = .2
        self.initial['body_pose'][wrist, 0] = .15
        candidate = {k: v.copy() for k, v in self.initial.items()}
        candidate['body_pose'][wrist, 0] = .21
        _, metrics = self.fit(candidate)
        self.assertTrue(metrics['source_projection_gate_passed'])
        self.assertGreater(metrics['wrist_error_after_pixels'], metrics['wrist_error_before_pixels'])
        self.assertFalse(metrics['wrist_gate_passed'])
        self.assertFalse(metrics['numeric_candidate_retained'])

    def test_valid_temporal_candidate_is_retained_without_training_approval(self):
        _, metrics = self.fit(self.initial)
        self.assertTrue(metrics['numeric_candidate_retained'])
        self.assertFalse(metrics['semantic_approval'])


class VerifyInputsTests(unittest.TestCase):
    """Build a tiny real frozen library and exercise its on-disk identity chain."""

    def setUp(self):
        import cv2

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.library = self.root / 'library'
        self.database = self.root / 'database'
        self.library.mkdir()
        self.database.mkdir()
        self.sid = 'basic-i'
        self.model = self.root / 'model.npz'
        self.model.write_bytes(b'fixture model; never loaded or trained')
        self.addCleanup(patch.stopall)
        patch.object(m.compare, 'MODEL_SHA', m.sha(self.model)).start()
        self.clip = self.library / 'clips/basic-i.mp4'
        self.clip.parent.mkdir()
        writer = cv2.VideoWriter(str(self.clip), cv2.VideoWriter_fourcc(*'mp4v'), 30., (64, 64))
        self.assertTrue(writer.isOpened())
        for i in range(3):
            writer.write(np.full((64, 64, 3), i * 40, np.uint8))
        writer.release()
        self.write('tutorial-sources/video/tutorial-fixture.mp4', b'original source bytes')
        self.sample = {'id': self.sid, 'source_id': 'tutorial-fixture',
                       'source_sha256': m.sha(self.library / 'tutorial-sources/video/tutorial-fixture.mp4'),
                       'media_sha256': m.sha(self.clip), 'frames': 3, 'reference_fps': 30.,
                       'source_pts_seconds': [1., 1.033, 1.067], 'source_frame_ids_0based': [30, 31, 32],
                       'raw': {'Chinese Sentences': '我'}, 'candidate_override': None}
        self.write_database('samples.jsonl', json.dumps(self.sample) + '\n')
        self.write_database('tutorial/lexical-evidence.jsonl', '')
        self.freeze(self.database)
        self.write('report.json', json.dumps({'base_database': str(self.database)}))
        self.write('source-input-hashes.json', json.dumps({str(self.database / n): m.sha(self.database / n) for n in ['samples.jsonl', 'SHA256SUMS']}))
        self.write('source-annotations/tutorial-refinement-main-v2.json', json.dumps({'annotations': []}))
        self.write('source-annotations/foundation-targets-v2.json', json.dumps({'records': []}))
        self.write('refined-captions.jsonl', '')
        self.observation = {'left_hand_image': np.full((3, 21, 3), .4),
                            'left_hand_image_detected': np.array([True, False, True]),
                            'source_pts_seconds': np.array(self.sample['source_pts_seconds']),
                            'source_frame_ids_0based': np.array(self.sample['source_frame_ids_0based']),
                            'reference_fps': np.array(30.)}
        self.observation['left_hand_image'][1] = np.nan
        self.observation['left_hand_image'][2] += .05
        self.save_observations()
        native = self.library / 'native-actions/basic-i'
        params = {k: np.zeros(shape, np.float32) for k, shape in m.compare.SHAPES.items()}
        for i in range(1, 4):
            self.write(f'native-actions/basic-i/meta/{i:05d}_0.json', json.dumps({'focal': [100., 100.], 'princpt': [32., 32.]}))
            self.write(f'native-actions/basic-i/img/{i:06d}.jpg', b'frozen render')
            (native / 'smplx').mkdir(exist_ok=True)
            np.savez_compressed(native / 'smplx' / f'{i:05d}_0.npz', **params)
        inventory = m.compare.asset_inventory(native, 3)
        version = m.compare.version_digest(self.sample['source_sha256'], self.sample['media_sha256'], inventory)
        self.action = {'id': self.sid, 'source_sha256': self.sample['source_sha256'], 'clip_sha256': self.sample['media_sha256'],
                       'action_version_sha256': version, 'annotation_sha256': self.annotation_digest(),
                       'frames': 3, 'fps': 30., 'clip': 'clips/basic-i.mp4', 'observations': 'observations/basic-i.npz',
                       'local_native_directory': 'native-actions/basic-i',
                       'native_comparison': {'candidate_id': self.sid, 'source_sha256': self.sample['source_sha256'],
                                             'clip_sha256': self.sample['media_sha256'], 'expected_frames': 3,
                                             'action_version_sha256': version}}
        self.save_action()
        self.freeze(self.library)
        if callable(getattr(m, 'verify_inputs', None)):
            self.assertEqual(m.verify_inputs(self.library, self.sid, self.model), self.action)

    def write(self, name, value):
        path = self.library / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode())

    def write_database(self, name, value):
        path = self.database / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def freeze(self, root):
        files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
        (root / 'SHA256SUMS').write_text(''.join(f'{m.sha(p)}  {p.relative_to(root).as_posix()}\n' for p in files))

    def annotation_digest(self):
        payload = {'sample': self.sample, 'source_lexical_records': [], 'refined_lexical_records': [],
                   'foundation_definitions': [], 'caption_refinement': None,
                   'word_boundary_and_source_mapping': {k: self.sample.get(k) for k in ['source_window_seconds_nominal', 'source_pts_seconds', 'source_frame_ids_0based', 'candidate_override']}}
        import hashlib
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def save_action(self):
        self.write('action-checks.jsonl', json.dumps(self.action) + '\n')

    def save_observations(self):
        (self.library / 'observations').mkdir(exist_ok=True)
        np.savez_compressed(self.library / 'observations/basic-i.npz', **self.observation)

    def verify(self):
        self.assertTrue(callable(getattr(m, 'verify_inputs', None)), 'verify_inputs must be exported')
        return m.verify_inputs(self.library, self.sid, self.model)

    def test_valid_library_returns_unmodified_action_without_loading_model(self):
        before = {p: m.sha(p) for p in self.root.rglob('*') if p.is_file()}
        with patch.object(m.hand, 'SparseSMPLX', side_effect=AssertionError('validation must not load model')):
            self.assertEqual(self.verify(), self.action)
        self.assertEqual({p: m.sha(p) for p in self.root.rglob('*') if p.is_file()}, before)

    def test_changed_or_unlisted_frozen_inputs_are_rejected(self):
        for name in ['action-checks.jsonl', 'clips/basic-i.mp4', 'observations/basic-i.npz',
                     'source-annotations/tutorial-refinement-main-v2.json']:
            with self.subTest(name=name):
                path = self.library / name
                raw = path.read_bytes()
                path.write_bytes(raw + b'changed')
                with self.assertRaises(ValueError): self.verify()
                path.write_bytes(raw)
        manifest = self.library / 'SHA256SUMS'
        manifest.write_text('\n'.join(l for l in manifest.read_text().splitlines() if not l.endswith('observations/basic-i.npz')) + '\n')
        with self.assertRaises(ValueError): self.verify()

    def test_wrong_model_is_rejected(self):
        self.model.write_bytes(b'different model')
        with self.assertRaises(ValueError): self.verify()

    def test_duplicate_action_id_is_rejected(self):
        self.write('action-checks.jsonl', (json.dumps(self.action) + '\n') * 2)
        self.freeze(self.library)
        with self.assertRaises(ValueError): self.verify()

    def test_nested_native_identity_must_match_action(self):
        for key, value in [('candidate_id', 'basic-you'), ('source_sha256', 'a' * 64),
                           ('clip_sha256', 'b' * 64), ('action_version_sha256', 'c' * 64), ('expected_frames', 2)]:
            with self.subTest(key=key):
                old = self.action['native_comparison'][key]
                self.action['native_comparison'][key] = value
                self.save_action(); self.freeze(self.library)
                with self.assertRaises(ValueError): self.verify()
                self.action['native_comparison'][key] = old

    def test_annotation_must_be_recomputed_from_bound_sample(self):
        self.action['annotation_sha256'] = 'd' * 64
        self.save_action(); self.freeze(self.library)
        with self.assertRaises(ValueError): self.verify()

    def test_native_parameters_and_version_are_verified(self):
        self.write('native-actions/basic-i/smplx/00001_0.npz', b'changed native')
        self.freeze(self.library)
        with self.assertRaises(ValueError): self.verify()

    def test_duplicate_fractional_or_reordered_source_ids_and_pts_are_rejected(self):
        for key, value in [('source_frame_ids_0based', [30, 30, 32]), ('source_frame_ids_0based', [30., 31.5, 32.]),
                           ('source_frame_ids_0based', [32, 31, 30]), ('source_pts_seconds', [1., 1., 1.067]),
                           ('source_pts_seconds', [1., float('nan'), 1.067]), ('source_pts_seconds', [1., 1.04, 1.067])]:
            with self.subTest(key=key, value=value):
                old = self.observation[key]
                self.observation[key] = np.array(value)
                self.save_observations(); self.freeze(self.library)
                with self.assertRaises(ValueError): self.verify()
                self.observation[key] = old

    def test_fabricated_missing_points_and_wrong_mask_shape_are_rejected(self):
        self.observation['left_hand_image'][1] = 0.
        self.save_observations(); self.freeze(self.library)
        with self.assertRaises(ValueError): self.verify()
        self.observation['left_hand_image'][1] = np.nan
        self.observation['left_hand_image_detected'] = np.array([[True, False, True]])
        self.save_observations(); self.freeze(self.library)
        with self.assertRaises(ValueError): self.verify()

    def test_static_frame_replacement_cannot_reuse_frozen_observation_identity(self):
        self.observation['left_hand_image'][2] = self.observation['left_hand_image'][0]
        self.save_observations()
        with self.assertRaises(ValueError): self.verify()

    def test_one_frame_clip_cannot_claim_full_sequence(self):
        import cv2
        writer = cv2.VideoWriter(str(self.clip), cv2.VideoWriter_fourcc(*'mp4v'), 30., (64, 64))
        writer.write(np.zeros((64, 64, 3), np.uint8)); writer.release()
        self.action['clip_sha256'] = m.sha(self.clip)
        self.action['native_comparison']['clip_sha256'] = self.action['clip_sha256']
        self.sample['media_sha256'] = self.action['clip_sha256']
        self.write_database('samples.jsonl', json.dumps(self.sample) + '\n')
        self.freeze(self.database)
        self.write('source-input-hashes.json', json.dumps({str(self.database / n): m.sha(self.database / n) for n in ['samples.jsonl', 'SHA256SUMS']}))
        self.action['annotation_sha256'] = self.annotation_digest()
        self.save_action(); self.freeze(self.library)
        with self.assertRaisesRegex(ValueError, 'clip frame count'): self.verify()

    def test_input_paths_cannot_escape_through_symlinks(self):
        observation = self.library / 'observations/basic-i.npz'
        outside = self.root / 'outside.npz'
        outside.write_bytes(observation.read_bytes())
        observation.unlink()
        observation.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Unsafe input artifact'): self.verify()

    def test_manifest_duplicate_or_traversal_entries_are_rejected(self):
        manifest = self.library / 'SHA256SUMS'
        raw = manifest.read_text()
        for extra in [raw.splitlines()[0], 'a' * 64 + '  ../escape']:
            with self.subTest(extra=extra):
                manifest.write_text(raw + extra + '\n')
                with self.assertRaises(ValueError): self.verify()


if __name__=='__main__':unittest.main()
