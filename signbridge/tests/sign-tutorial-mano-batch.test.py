"""Evidence and order checks for the bounded native WiLoR batch."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-tutorial-mano-batch.py'
spec = importlib.util.spec_from_file_location('tutorial_mano_batch_test', SCRIPT)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class TutorialManoBatchTests(unittest.TestCase):
    def fixture(self, root):
        root = Path(root)
        (root / 'images').mkdir()
        (root / 'cases').mkdir()
        rows = []
        for index in (1, 2):
            image = root / 'images' / f'{index:06d}.jpg'
            image.write_bytes(f'image-{index}'.encode())
            case = root / 'cases' / f'case-{index}'
            case.mkdir()
            observations = case / 'observations.npz'
            observations.write_bytes(f'obs-{index}'.encode())
            rows.append({'case_id': f'case-{index}', 'gpu_input_frame_1based': index,
                         'image': str(image.relative_to(root)), 'image_sha256': batch.wilor.sha256(image),
                         'observations': str(observations.relative_to(root)),
                         'observations_sha256': batch.wilor.sha256(observations),
                         'human_approved': False, 'training_ready': False})
        return {'schema': 'signbridge-tutorial-smplerx-independent-frames-v2',
                'frames': 2, 'cases': rows}

    def test_manifest_preserves_order_and_input_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            self.assertEqual(len(batch.validate_manifest(value, root)), 2)

    def test_rejects_bad_order_duplicate_ids_and_promoted_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            value['cases'][1]['gpu_input_frame_1based'] = 1
            with self.assertRaises(ValueError):
                batch.validate_manifest(value, root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            value['cases'][1]['case_id'] = value['cases'][0]['case_id']
            with self.assertRaises(ValueError):
                batch.validate_manifest(value, root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            value['cases'][0]['training_ready'] = True
            with self.assertRaises(ValueError):
                batch.validate_manifest(value, root)

    def test_rejects_changed_assets_and_oversized_or_empty_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.fixture(root)
            (root / value['cases'][0]['image']).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                batch.validate_manifest(value, root)
        for value in ({'schema': 'signbridge-tutorial-smplerx-independent-frames-v2', 'frames': 0, 'cases': []},
                      {'schema': 'signbridge-tutorial-smplerx-independent-frames-v2', 'frames': 501, 'cases': [{}] * 501}):
            with self.subTest(frames=value['frames']), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    batch.validate_manifest(value, Path(directory))


if __name__ == '__main__':
    unittest.main()
