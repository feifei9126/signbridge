import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-demo-motion-recovery.py'
spec = importlib.util.spec_from_file_location('motion_recovery', TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class MotionRecoveryTests(unittest.TestCase):
    def test_recovery_changes_only_display_metadata_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; (source / 'experimental').mkdir(parents=True)
            identity = 'demo-001'; pose = [[[0, 0, 0] for _ in range(55)] for _ in range(4)]
            clip = {'id': identity, 'text': '测试', 'frames': 4, 'poses': pose,
                    'human_approved': False, 'training_ready': False, 'model_training_ready': False}
            asset = source / 'experimental/demo-001.json'; asset.write_text(json.dumps(clip))
            entry = {'id': identity, 'asset': 'experimental/demo-001.json', 'frames': 4,
                     'sha256': tool.sha(asset), 'human_approved': False, 'training_ready': False,
                     'model_training_ready': False}
            index = source / 'experimental-index.json'; index.write_text(json.dumps({'clips': [entry]}))
            out = root / 'recovered'
            result = tool.recover_bundle(index, out, {identity: 'quaternion-temporal-recovery-v1'})
            changed = json.loads((out / entry['asset']).read_text())
            self.assertEqual(changed['poses'], pose)
            self.assertEqual(changed['display_stabilization_profile'], 'quaternion-temporal-recovery-v1')
            self.assertTrue(result['source_pose_arrays_unchanged'])
            self.assertNotEqual(entry['sha256'], json.loads((out / 'experimental-index.json').read_text())['clips'][0]['sha256'])
            self.assertFalse(result['training_ready'])
            self.assertFalse(result['model_training_ready'])

    def test_recovery_requires_new_output_and_known_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; (source / 'experimental').mkdir(parents=True)
            index = source / 'experimental-index.json'; index.write_text(json.dumps({'clips': []}))
            with self.assertRaisesRegex(ValueError, 'must be new'):
                tool.recover_bundle(index, source, {})
            with self.assertRaisesRegex(ValueError, 'must exist'):
                tool.recover_bundle(index, root / 'out', {'missing': 'quaternion-temporal-recovery-v1'})

    def test_incomplete_native_frames_stay_excluded_without_fabrication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package = root / 'source4' / 'smplx-fit-input-v2'
            sample = package / 'samples' / 'basic'; sample.mkdir(parents=True)
            clip = sample / 'clip.mp4'; clip.write_bytes(b'fixture')
            images = sample / 'images'; images.mkdir()
            for number in range(1, 5): (images / f'{number:06d}.jpg').write_bytes(b'jpeg')
            (package / 'tasks.jsonl').write_text(json.dumps({'segment_id': 'basic', 'frames': 4,
                'images': 'samples/basic/images', 'clip_sha256': tool.sha(clip)}) + '\n')
            fit = root / 'results' / 'fits' / 'basic'; fit.mkdir(parents=True)
            (root / 'results' / 'report.json').write_text(json.dumps({'failed': [
                {'segment_id': 'basic', 'error': 'parameter set mismatch', 'log': '/remote/fail.log'}]}))
            row = {'group': 'source4', 'kind': 'native', 'id': 'basic', 'text': '基本',
                'clip': str(clip), 'fit': str(fit), 'frames': 4, 'fitted_frames': 3,
                'missing_frames': [4], 'errors': ['missing_native_frames']}
            result = tool.incomplete_fit_status([row], {'clips': []})[0]
            self.assertEqual(result['package_missing_input_frames'], [])
            self.assertTrue(result['package_input_frame_set_complete'])
            self.assertEqual(result['status'], 'incomplete_and_excluded')
            self.assertFalse(result['automatic_repair_safe'])
            self.assertFalse(result['present_in_current_demo'])


if __name__ == '__main__': unittest.main()
