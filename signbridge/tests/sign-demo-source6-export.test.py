"""Source-6 native candidate motions can be previewed without creating approvals."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

import numpy as np

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'src/tools/sign-demo-source6-export.py'


class Source6ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT.is_file():
            cls.export = None
            return
        spec = importlib.util.spec_from_file_location('source6_export', SCRIPT)
        cls.export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.export)

    def test_candidate_export_available(self):
        self.assertIsNotNone(self.export, 'Need a candidate-only native motion exporter')

    def test_exact_native_display_mapping_and_mean_once(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        native = {name: np.ones(shape, np.float32) for name, shape in self.export.audit.NATIVE_SHAPES.items()}
        mean = np.zeros((55, 3), np.float32)
        mean[25:55] = 2.
        before = {k: v.copy() for k, v in native.items()}
        poses = self.export.display_pose(native, mean)
        self.assertEqual(poses.shape, (55, 3))
        self.assertTrue(np.all(poses[:12] == 0))
        self.assertTrue(np.all(poses[12:22] == 1))
        self.assertTrue(np.all(poses[25:55] == 3))
        for k, v in native.items():
            np.testing.assert_array_equal(v, before[k])

    def test_native_nonfinite_and_shape_rejected(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        native = {name: np.zeros(shape, np.float32) for name, shape in self.export.audit.NATIVE_SHAPES.items()}
        native['left_hand_pose'][0, 0] = np.nan
        with self.assertRaises(ValueError):
            self.export.display_pose(native, np.zeros((55, 3), np.float32))
        native['left_hand_pose'] = np.zeros((15, 3), np.float32)
        native['body_pose'] = np.zeros((1, 63), np.float32)
        with self.assertRaises(ValueError):
            self.export.display_pose(native, np.zeros((55, 3), np.float32))

    def test_no_mean_in_unmapped_joints(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        native = {name: np.zeros(shape, np.float32) for name, shape in self.export.audit.NATIVE_SHAPES.items()}
        with self.assertRaises(ValueError):
            self.export.display_pose(native, np.ones((55, 3), np.float32))

    def test_incomplete_native_sequence_cannot_be_exported(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            with self.assertRaisesRegex(ValueError, 'complete single-person'):
                self.export.read_sequence(p, 4, np.zeros((55, 3), np.float32))

    def test_quality_gate_is_candidate_only(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        row = {'annotation_id': 'sample', 'label_candidate': '请问这里可以拍照吗？', 'text_verified': '',
               'human_approved': False, 'training_ready': False, 'model_training_ready': False,
               'frames_expected': 4, 'native_parameter_inventory': {'complete_single_person': True}}
        self.export.validate_candidate(row)
        for key, value in [('human_approved', True), ('training_ready', True),
                           ('model_training_ready', True), ('text_verified', row['label_candidate'])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.export.validate_candidate({**row, key: value})

    def test_read_sequence_keeps_exact_frames_and_native_digests(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            values = {name: np.zeros(shape, np.float32) for name, shape in self.export.audit.NATIVE_SHAPES.items()}
            expected = []
            for number in range(1, 5):
                values['body_pose'][11, 0] = number / 10
                path = folder / f'{number:05d}_0.npz'
                np.savez(path, **values)
                expected.append({'file': path.name, 'sha256': self.export.audit.sha(path)})
            poses, manifest = self.export.read_sequence(folder, 4, np.zeros((55, 3), np.float32))
            self.assertEqual(poses.shape, (4, 55, 3))
            np.testing.assert_allclose(poses[:, 12, 0], [.1, .2, .3, .4])
            self.assertEqual(manifest, expected)
            for item in manifest:
                self.assertEqual(item['sha256'], self.export.audit.sha(folder / item['file']))

    def test_local_source6_export_keeps_full_candidate_scope_and_provenance(self):
        if self.export is None:
            self.skipTest('Exporter not implemented')
        project = SCRIPT.parents[3]
        base = project / 'local-data/data-expansion-20261015/source-6/avatar-preview-20261016-hjzppz64/motions-v1'
        if not base.is_dir():
            self.skipTest('Authorized local source-6 preview assets not installed')
        index = json.loads((base / 'experimental-index.json').read_text())
        self.assertEqual(index['export_tool_sha256'], self.export.audit.sha(SCRIPT))
        self.assertEqual(len(index['clips']), 12)
        self.assertEqual(sum(row['frames'] for row in index['clips']), 2779)
        self.assertFalse(index['training_weights_updated'])
        self.assertEqual(self.export.audit.verify_checksums(base), 25)
        for row in index['clips']:
            path = base / row['asset']
            self.assertEqual(self.export.audit.sha(path), row['sha256'])
            clip = json.loads(path.read_text())
            self.assertEqual(np.asarray(clip['poses']).shape, (row['frames'], 55, 3))
            self.assertTrue(np.isfinite(clip['poses']).all())
            for flag in ['human_approved', 'training_ready', 'model_training_ready', 'semantics_approved', 'boundaries_approved']:
                self.assertFalse(clip[flag])
            self.assertEqual(clip['text_verified'], '')
            self.assertTrue(clip['preview_only'])
            provenance = json.loads((base / 'provenance' / (row['id'] + '.json')).read_text())
            self.assertEqual(len(provenance['native_files']), row['frames'])
            self.assertEqual(provenance['native_manifest_sha256'], row['fitted_sha256'])


if __name__ == '__main__':
    unittest.main()
