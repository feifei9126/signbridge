import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-demo-apply-motion-approval.py'
spec = importlib.util.spec_from_file_location('apply_motion_approval', TOOL)
approval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approval)


def digest(value):
    return hashlib.sha256(value).hexdigest()


class ApplyMotionApprovalTests(unittest.TestCase):
    def make_source(self, root):
        (root / 'experimental').mkdir()
        clips = []
        for index in range(83):
            identity = f'fit-{index:03d}'
            metadata = {
                'id': identity,
                'text': f'测试词{index}',
                'aliases': [f'测试词{index}'],
                'fps': 25,
                'frames': 4,
                'experimental': True,
                'model_output': 'smplx_fit_demo',
                'source_sha256': f'{index:064x}',
                'feature_sha256': f'{index + 1:064x}',
                'fitted_sha256': f'{index + 2:064x}',
                'source_id': f'source-{index:03d}',
                'training_data_member': False,
                'training_ready': False,
                'model_training_ready': False,
                'human_approved': False,
                'motion_review_status': 'needs_review',
                'mirror_status': 'unknown',
                'signer_id': 'unconfirmed',
                'quality_warning': False,
                'review_attestation_sha256': 'a' * 64,
                'max_adjacent_rotation_degrees': 10.0,
            }
            clip = {
                'schema': 'signbridge-experimental-clip-v1',
                **metadata,
                'poses': [[[0, 0, 0] for _ in range(55)] for _ in range(4)],
            }
            asset = f'experimental/{identity}.json'
            raw = json.dumps(clip, ensure_ascii=False, separators=(',', ':')).encode()
            (root / asset).write_bytes(raw)
            clips.append({**metadata, 'asset': asset, 'sha256': digest(raw)})
        index = {
            'schema': 'signbridge-experimental-motion-index-v1',
            'representation': 'effective-smplx-55-axis-angle',
            'smplx_rest_model_sha256': approval.MODEL_SHA,
            'training_weights_updated': False,
            'text_to_sign_trained': False,
            'training_ready': False,
            'model_training_ready': False,
            'research_only': True,
            'parents': [-1, *range(54)],
            'restJoints': [[0, 0, 0] for _ in range(55)],
            'clips': clips,
        }
        (root / 'experimental-index.json').write_text(json.dumps(index))
        return index

    def test_promotes_exact_83_without_changing_input_or_training_gates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            original = self.make_source(source)
            original_bytes = (source / 'experimental-index.json').read_bytes()
            result = approval.promote(source, root / 'approved')
            output = root / 'approved'
            index = json.loads((output / 'experimental-index.json').read_text())
            record_bytes = (output / 'experimental/motion-approval.json').read_bytes()
            record = json.loads(record_bytes)

            self.assertEqual(result['clips'], 83)
            self.assertEqual(result['frames'], 332)
            self.assertEqual(len(index['clips']), 83)
            self.assertEqual(len(record['clips']), 83)
            self.assertEqual(record['source_index_sha256'], digest(original_bytes))
            self.assertEqual(index['motion_approval']['sha256'], digest(record_bytes))
            self.assertFalse(index['training_ready'])
            self.assertFalse(index['model_training_ready'])
            self.assertEqual({clip['motion_review_status'] for clip in index['clips']},
                             {'approved_for_demo_motion'})
            self.assertTrue(all(clip['human_approved'] for clip in index['clips']))
            self.assertTrue(all(not clip['training_data_member'] and not clip['training_ready']
                                and not clip['model_training_ready'] for clip in index['clips']))
            self.assertEqual((source / 'experimental-index.json').read_bytes(), original_bytes)
            with self.assertRaises(FileExistsError):
                approval.promote(source, output)

    def test_rejects_modified_input_asset_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            self.make_source(source)
            index = json.loads((source / 'experimental-index.json').read_text())
            clip_path = source / index['clips'][0]['asset']
            clip_path.write_text(clip_path.read_text() + ' ')
            output = root / 'approved'
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                approval.promote(source, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
