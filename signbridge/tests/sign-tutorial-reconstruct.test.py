"""Tutorial native-MANO candidates cannot become anatomical or training approval."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-tutorial-reconstruct.py'


class TutorialReconstructTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('tutorial_reconstruct_test', SCRIPT)
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def points(self, x=.4):
        points = np.full((21, 2), .5, dtype=np.float32)
        points[:, 0] = x
        points[[5, 9, 13, 17], 1] += .08
        return points

    def test_pixel_agreement_is_not_anatomical_or_training_approval(self):
        left = self.points()
        missing = np.full((21, 2), np.nan, dtype=np.float32)
        result = self.m.compare_observations(left * [720, 960], left, missing, True, False, 720, 960)
        self.assertAlmostEqual(result['estimated_slots']['left']['median_error_pixels'], 0.)
        self.assertIsNone(result['estimated_slots']['right'])
        self.assertFalse(result['handedness_verified'])
        self.assertFalse(result['training_ready'])

    def test_missing_or_out_of_image_observations_are_not_filled(self):
        projected = self.points() * [720, 960]
        invalid = self.points(); invalid[4, 0] = 2.
        missing = np.full((21, 2), np.nan, dtype=np.float32)
        result = self.m.compare_observations(projected, invalid, missing, True, False, 720, 960)
        self.assertEqual(result['estimated_slots'], {'left': None, 'right': None})
        self.assertTrue(np.isnan(missing).all())

    def test_two_observation_slots_are_both_reported_without_side_swapping(self):
        left, right = self.points(.4), self.points(.8)
        result = self.m.compare_observations(left * [720, 960], left, right, True, True, 720, 960)
        self.assertGreater(result['estimated_slots']['right']['median_error_pixels'], 0)
        self.assertFalse(result['handedness_verified'])
        np.testing.assert_array_equal(right, self.points(.8))

    def test_projection_shape_and_nonfinite_outputs_are_rejected(self):
        p = self.points()
        for projected in (np.zeros((20, 2)), np.full((21, 2), np.nan)):
            with self.assertRaises(ValueError):
                self.m.compare_observations(projected, p, p, True, True, 720, 960)

    def plan_fixture(self, directory):
        root = Path(directory)
        reference = root / 'reference'
        reference.mkdir()
        original = root / 'source.mp4'
        original.write_bytes(b'original-tutorial')
        source_hash = self.m.wilor.sha256(original)
        index = reference / 'fitting-reference-index.jsonl'
        index.write_text(json.dumps({'annotation_id': 'example', 'source_id': 'tutorial-source',
            'source_sha256': source_hash, 'source_absolute_path': str(original),
            'source_window_seconds': [1., 2.], 'reference_fps': 25., 'frames': 25}) + '\n')
        inputs = root / 'inputs'
        inputs.mkdir()
        image = inputs / 'image.jpg'
        image.write_bytes(b'derived-frame')
        observations = inputs / 'observations.npz'
        np.savez_compressed(observations, left=self.points(), right=self.points(.8),
                            left_detected=np.array(True), right_detected=np.array(True))
        case = {'case_id': 'example-f000001', 'annotation_id': 'example', 'source_id': 'tutorial-source',
            'source_sha256': source_hash, 'frame_1based': 1, 'source_seconds_nominal': 1.,
            'image': 'image.jpg', 'image_sha256': self.m.wilor.sha256(image),
            'observations': 'observations.npz', 'observations_sha256': self.m.wilor.sha256(observations),
            'mirror_status': 'unknown', 'anatomical_handedness': 'unverified',
            'human_approved': False, 'training_ready': False}
        plan = {'schema': 'signbridge-tutorial-native-hands-plan-v1', 'training_ready': False,
            'reference_root': str(reference), 'reference_index_sha256': self.m.wilor.sha256(index),
            'cases': [case]}
        path = inputs / 'plan.json'
        path.write_text(json.dumps(plan))
        return path, plan, original, index

    def test_changed_original_or_reference_index_is_rejected(self):
        for asset in ('source', 'index'):
            with self.subTest(asset=asset), tempfile.TemporaryDirectory() as directory:
                path, plan, original, index = self.plan_fixture(directory)
                self.m.check_plan(path, self.m.wilor.sha256(path))
                (original if asset == 'source' else index).write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    self.m.check_plan(path, self.m.wilor.sha256(path))

    def test_invalid_source_frame_or_nominal_time_is_rejected(self):
        for change in ({'frame_1based': 26}, {'source_seconds_nominal': 1.4}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path, plan, _, _ = self.plan_fixture(directory)
                plan['cases'][0].update(change)
                path.write_text(json.dumps(plan))
                with self.assertRaises(ValueError):
                    self.m.check_plan(path, self.m.wilor.sha256(path))

    def test_plan_state_and_input_digest_cannot_be_promoted_or_changed(self):
        for change in ({'human_approved': True}, {'mirror_status': 'normal'},
                       {'anatomical_handedness': 'verified'}, {'image_sha256': 'a' * 64}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path, plan, _, _ = self.plan_fixture(directory)
                plan['cases'][0].update(change)
                path.write_text(json.dumps(plan))
                with self.assertRaises(ValueError):
                    self.m.check_plan(path, self.m.wilor.sha256(path))

    def test_keyframe_order_is_explicit_and_bounded(self):
        for order in ([], [1, 1], [-1, 3], [0, 5]):
            with self.subTest(order=order), self.assertRaises(ValueError):
                self.m.validate_keyframe_order(order)
        self.assertEqual(self.m.validate_keyframe_order([1, 4, 0, 2, 3]), [1, 4, 0, 2, 3])

    def test_case_ids_are_bounded_and_unique(self):
        for ids in ([], ['../escape'], ['same', 'same'], ['valid'] * 9):
            with self.assertRaises(ValueError):
                self.m.validate_ids(ids)
        self.assertEqual(self.m.validate_ids(['one', 'two']), ['one', 'two'])


if __name__ == '__main__':
    unittest.main()
