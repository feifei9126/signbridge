"""Catch-up delivery rejects altered media and maintains incomplete stage labels."""
import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-source-catchup-review.py'


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('catchup_review', SCRIPT)
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def test_asset_digest_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); asset = root / 'clip.mp4'; asset.write_bytes(b'original')
            entries = {'clip': {'relative_path': 'clip.mp4', 'sha256': hashlib.sha256(b'original').hexdigest()}}
            self.m.verify_named_artifacts(root, entries)
            asset.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                self.m.verify_named_artifacts(root, entries)

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'delivery'; root.mkdir()
            asset = root.parent / 'clip.mp4'; asset.write_bytes(b'outside')
            entries = {'clip': {'relative_path': '../clip.mp4', 'sha256': hashlib.sha256(b'outside').hexdigest()}}
            with self.assertRaises(ValueError):
                self.m.verify_named_artifacts(root, entries)

    def test_five_frame_sampling_never_becomes_full_video_completion(self):
        record = {'source_id': 'test', 'sha256': 'a' * 64, 'aliases': ['one.mp4'],
                  'stage': 'caption_screened_pending_reference', 'cached_ocr': 'ocr.jsonl',
                  'prior_reference_windows': [], 'prior_continuous_motions': [], 'language_hint': 'unconfirmed'}
        value = self.m.stage_badges(record, {'test': {'samples': 5}}, [])
        self.assertEqual(value['new_independent_observation_frames'], 5)
        self.assertEqual(value['new_sentence_windows'], 0)
        self.assertFalse(value['training_ready'])
        self.assertGreater(len(value['remaining']), 0)


    def test_gpu_pack_preserves_unapproved_state_and_rejects_duplicate_cases(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'plan'; source.mkdir()
            (source / 'image.jpg').write_bytes(b'image')
            (source / 'obs.npz').write_bytes(b'obs')
            case = {'case_id': 'case-one', 'image': 'image.jpg', 'observations': 'obs.npz',
                    'image_sha256': hashlib.sha256(b'image').hexdigest(),
                    'observations_sha256': hashlib.sha256(b'obs').hexdigest(),
                    'training_ready': False, 'human_approved': False}
            plan = source / 'plan.json'
            plan.write_text(json.dumps({'cases': [case], 'training_ready': False}))
            value = self.m.prepare_gpu_inputs(plan, root / 'output')
            self.assertFalse(value['frames_are_temporally_contiguous'])
            self.assertFalse(value['training_ready'])
            self.assertEqual(value['status'], 'prepared_not_dispatched')
            plan.write_text(json.dumps({'cases': [case, case], 'training_ready': False}))
            with self.assertRaises(ValueError):
                self.m.prepare_gpu_inputs(plan, root / 'duplicate-output')

    def test_gpu_pack_rejects_a_case_promoted_to_approval(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'plan'; source.mkdir()
            plan = source / 'plan.json'
            plan.write_text(json.dumps({'cases': [{'case_id': 'one', 'training_ready': True, 'human_approved': False}], 'training_ready': False}))
            with self.assertRaises(ValueError):
                self.m.prepare_gpu_inputs(plan, root / 'output')


if __name__ == '__main__':
    unittest.main()
