"""Camera coordinate experiments never approve physical motion or training labels."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-camera-audit.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CameraMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = load('camera_audit', SCRIPT)

    def test_reference_camera_changes_only_translation_and_preserves_pelvis_pixel(self):
        camera = self.camera
        fixture = load('camera_math_fixture', SCRIPT.parents[2] / 'tests/sign-hand-refine.test.py')
        model, _ = fixture.synthetic_model()
        params = fixture.parameters()
        before = {k: v.copy() for k, v in params.items()}
        old = {'focal': np.array([1000., 1000.]), 'princpt': np.array([345., 270.])}
        reference = {'focal': np.array([800., 800.]), 'princpt': np.array([320., 240.])}
        proposal, stats, projected = camera.rebase_translation(model, params, old, reference)
        for key in params:
            np.testing.assert_array_equal(params[key], before[key])
            if key != 'transl':
                np.testing.assert_array_equal(proposal[key], before[key])
        self.assertLess(stats['pelvis_projection_error_pixels'], 1e-10)
        self.assertEqual(projected['original'].shape, (65, 2))
        self.assertFalse(stats['physical_motion_approved'])

    def test_same_camera_is_identity_and_common_focal_scaling_can_cancel_crop_depth(self):
        fixture = load('camera_scale_fixture', SCRIPT.parents[2] / 'tests/sign-hand-refine.test.py')
        model, _ = fixture.synthetic_model()
        params = fixture.parameters()
        camera = {'focal': np.array([1000., 1000.]), 'princpt': np.array([320., 240.])}
        identity, stats, _ = self.camera.rebase_translation(model, params, camera, camera)
        np.testing.assert_allclose(identity['transl'], params['transl'], atol=1e-12)
        self.assertLess(stats['max_projection_error_pixels'], 1e-10)
        scaled = {k: v.copy() for k, v in params.items()}
        scaled['transl'] *= 2
        crop = {'focal': np.array([2000., 2000.]), 'princpt': camera['princpt']}
        rebased, _, _ = self.camera.rebase_translation(model, scaled, crop, camera)
        self.assertAlmostEqual(rebased['transl'][0, 2], params['transl'][0, 2])

    def test_negative_depth_and_inconsistent_camera_scales_are_rejected(self):
        fixture = load('camera_bad_fixture', SCRIPT.parents[2] / 'tests/sign-hand-refine.test.py')
        model, _ = fixture.synthetic_model()
        params = fixture.parameters()
        c = {'focal': np.array([1000., 1000.]), 'princpt': np.array([320., 240.])}
        bad = {'focal': np.array([1000., 900.]), 'princpt': c['princpt']}
        with self.assertRaises(ValueError):
            self.camera.rebase_translation(model, params, c, bad)
        params['transl'][0, 2] = -3
        with self.assertRaises(ValueError):
            self.camera.rebase_translation(model, params, c, c)

    def test_metadata_validates_virtual_focal_bbox_and_frame_identity(self):
        meta = {'bbox_id': 0, 'bbox': [80., 40., 192., 256.],
                'bbox_mmdet': [100., 70., 140., 190.], 'focal': [5000., 5000.],
                'princpt': [176., 168.], 'img_path': '/remote/batch/samples/s/images/000001.jpg'}
        self.camera.validate_meta(meta, meta['img_path'])
        with self.assertRaises(ValueError):
            self.camera.validate_meta(meta, '/remote/batch/samples/s/images/000002.jpg')
        meta['focal'][0] = 4500.
        with self.assertRaises(ValueError):
            self.camera.validate_meta(meta, meta['img_path'])


class CameraReportTests(unittest.TestCase):
    def setUp(self):
        self.camera = load('camera_report_audit', SCRIPT)
        fixture = load('camera_report_fixture', SCRIPT.parents[2] / 'tests/sign-hand-refine.test.py')
        self.model, _ = fixture.synthetic_model()
        self.params = fixture.parameters()
        self.params['transl'][0, 2] = 30.
        self.helper = self.camera.evidence.load_model_helper()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.batch = self.root / 'batch'
        self.source = self.root / 'capture'
        self.fusion = self.root / 'fusion/results'
        self.model_root = self.root / 'smplerx'
        for p in (self.batch, self.source, self.fusion):
            p.mkdir(parents=True)
        model_file = self.model_root / self.helper.MODEL_FILE
        model_file.parent.mkdir(parents=True)
        model_file.write_bytes(b'synthetic licensed-model substitute')
        self.model_sha = self.camera.evidence.digest(model_file)
        self.counts = {'pilot-greeting-hello-001': 3, 'pilot-hospital-cough-003': 3}
        jobs = []
        tasks = []
        cases = []
        provenance = {}
        for segment, n in self.counts.items():
            rel = 'samples/' + segment + '/images'
            jobs.append({'segment_id': segment, 'argv': ['inference.py', '--img_path', '/remote/batch/' + rel]})
            tasks.append({'segment_id': segment, 'frames': n, 'fps': 25., 'model_training_ready': False,
                          'frame_manifest': 'samples/' + segment + '/frames.jsonl'})
            rows = []
            for frame in range(1, n+1):
                image = self.batch / rel / ('%06d.jpg' % frame)
                image.parent.mkdir(parents=True, exist_ok=True)
                Image.new('RGB', (640, 480), 'white').save(image)
                rows.append({'frame_id': frame, 'image': str(image.relative_to(self.batch)),
                             'clip_seconds': (frame-1)/25., 'sha256': self.camera.evidence.digest(image)})
                folder = self.source / segment
                for part in ('meta', 'smplx'):
                    (folder / part).mkdir(parents=True, exist_ok=True)
                meta = {'bbox_id': 0, 'bbox': [80., 40., 192., 256.], 'bbox_mmdet': [100., 70., 140., 190.],
                        'focal': [5000., 5000.], 'princpt': [176., 168.], 'img_path': '/remote/batch/' + rows[-1]['image']}
                (folder / 'meta' / ('%05d_0.json' % frame)).write_text(json.dumps(meta))
                np.savez_compressed(folder / 'smplx' / ('%05d_0.npz' % frame), **self.params)
                if frame == 2:
                    output_relative = segment + '/000002'
                    f = self.fusion / output_relative
                    f.mkdir(parents=True)
                    np.savez_compressed(f / 'baseline.npz', **self.params)
                    np.savez_compressed(f / 'candidate.npz', **self.params)
                    cases.append({'segment_id': segment, 'frame_1based': frame,
                                  'output_relative': output_relative, 'training_ready': False,
                                  'required_sides': ['left','right'] if 'greeting' in segment else ['right']})
                    for part, ext in (('meta', 'json'), ('smplx', 'npz')):
                        relative = segment + '/' + part + '/%05d_0.%s' % (frame, ext)
                        provenance['/remote/fits/' + relative] = self.camera.evidence.digest(self.source / relative)
            (self.batch / tasks[-1]['frame_manifest']).write_text(''.join(json.dumps(x)+'\n' for x in rows))
        (self.batch / 'tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in tasks))
        (self.batch / 'contract.json').write_text(json.dumps({'schema':'signbridge-smplerx-input-v1','model_training_ready':False}))
        self.write_manifest(self.batch)
        run = {'schema':'signbridge-smplerx-run-v1', 'model':'smpler_x_h32', 'jobs':jobs,
               'status':'inferred_pending_import_audit', 'completed': list(self.counts),
               'tasks_sha256': self.camera.evidence.digest(self.batch / 'tasks.jsonl'),
               'preflight':{'actual_commit':self.helper.COMMIT,'expected_commit':self.helper.COMMIT}}
        (self.source / 'run.json').write_text(json.dumps(run))
        fit_sha = self.camera.evidence.digest(self.source/'run.json')
        (self.source/'capture.json').write_text(json.dumps({'schema':'signbridge-camera-source-capture-v1',
            'remote_fits':'/remote/fits','fit_run_sha256':fit_sha,'source_files_modified':False,'training_ready':False}))
        self.write_manifest(self.source)
        for name in ('contract.json','tasks.jsonl','SHA256SUMS'):
            provenance['/remote/batch/'+name] = self.camera.evidence.digest(self.batch/name)
        provenance['/remote/SMPLer-X/'+self.helper.MODEL_FILE] = self.model_sha
        (self.fusion/'report.json').write_text(json.dumps({'schema':'signbridge-mano-smplx-alignment-v1',
            'training_ready':False,'fit_run_sha256':fit_sha,'source_sha256':provenance,'cases':cases}))
        self.write_manifest(self.fusion.parent)
        self.args = SimpleNamespace(fit_source=self.source,fit_run_sha256=fit_sha,batch=self.batch,
            fusion_results=self.fusion,fusion_report_sha256=self.camera.evidence.digest(self.fusion/'report.json'),
            smplerx_root=self.model_root,output=self.root/'result')

    def write_manifest(self, root):
        paths = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
        (root/'SHA256SUMS').write_text(''.join(self.camera.evidence.digest(p)+'  '+str(p.relative_to(root))+'\n' for p in paths))

    def run_audit(self):
        with patch.object(self.camera, 'COUNTS', self.counts), \
             patch.object(self.camera.evidence, 'load_model_helper', return_value=self.helper), \
             patch.object(self.helper, 'MODEL_SHA256', self.model_sha), \
             patch.object(self.helper, 'SparseSMPLX', return_value=self.model):
            return self.camera.audit(self.args)

    def test_full_report_contains_independent_proposals_and_hashes_without_source_changes(self):
        before = {p:self.camera.evidence.digest(p) for root in (self.source,self.batch,self.fusion)
                  for p in root.rglob('*') if p.is_file()}
        path = self.run_audit()
        r = json.loads(path.read_text())
        self.assertFalse(r['training_ready'])
        self.assertFalse(r['physical_motion_approved'])
        self.assertEqual(r['status'], 'reference_camera_proposals_pending_review')
        self.assertEqual(r['frames_evaluated'], 6)
        self.assertEqual({p:self.camera.evidence.digest(p) for p in before}, before)
        for segment in self.counts:
            with np.load(path.parent/segment/'camera-proposals.npz',allow_pickle=False) as a:
                self.assertEqual(a['proposal_translation'].shape, (3,3))
                self.assertFalse(bool(a['training_ready']))
            self.assertTrue((path.parent/segment/'camera-depth.png').is_file())
        self.camera.evidence.verify_manifest(path.parent,path.parent/'SHA256SUMS')

    def test_existing_output_foreign_capture_or_tampered_evidence_are_rejected(self):
        self.args.output.mkdir()
        marker = self.args.output/'keep.txt'; marker.write_text('keep')
        with self.assertRaisesRegex(ValueError,'separate'):
            self.run_audit()
        self.assertEqual(marker.read_text(),'keep')
        self.args.output = self.root/'other-result'
        meta = self.source/'pilot-greeting-hello-001/meta/00001_0.json'
        meta.write_text('{}')
        with self.assertRaisesRegex(ValueError,'digest mismatch'):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_unlisted_camera_metadata_cannot_enter_the_audit(self):
        manifest = self.source/'SHA256SUMS'
        lines = manifest.read_text().splitlines()
        manifest.write_text('\n'.join(x for x in lines if not x.endswith('pilot-greeting-hello-001/meta/00001_0.json'))+'\n')
        with self.assertRaisesRegex(ValueError, 'Unlisted source file'):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_foreign_frame_camera_is_rejected_even_with_valid_file_checksums(self):
        path = self.source/'pilot-greeting-hello-001/meta/00001_0.json'
        r = json.loads(path.read_text()); r['img_path'] = '/remote/other/images/000001.jpg'
        path.write_text(json.dumps(r)); self.write_manifest(self.source)
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_changed_fusion_shape_is_rejected_without_promoting_or_overwriting(self):
        path = self.fusion/'pilot-greeting-hello-001/000002/candidate.npz'
        with np.load(path,allow_pickle=False) as a:
            values = {key:a[key].copy() for key in a.files}
        values['betas'][0,0] += 1.
        np.savez_compressed(path, **values); self.write_manifest(self.fusion.parent)
        with self.assertRaisesRegex(ValueError, 'Protected parameter modified: betas'):
            self.run_audit()
        self.assertFalse(self.args.output.exists())

    def test_fit_hash_and_fusion_report_hash_must_match_supplied_sources(self):
        self.args.fit_run_sha256 = '0'*64
        with self.assertRaisesRegex(ValueError, 'Fit run digest mismatch'):
            self.run_audit()
        self.args.fit_run_sha256 = self.camera.evidence.digest(self.source/'run.json')
        self.args.fusion_report_sha256 = '0'*64
        with self.assertRaisesRegex(ValueError, 'Fusion report digest mismatch'):
            self.run_audit()

    def test_nested_output_cannot_change_evidence_bundle(self):
        self.args.output = self.fusion.parent/'new-audit'
        with self.assertRaisesRegex(ValueError, 'separate'):
            self.run_audit()
        self.assertFalse(self.args.output.exists())


if __name__ == '__main__':
    unittest.main()
