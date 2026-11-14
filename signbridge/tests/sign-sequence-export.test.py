"""Full saved motion export preserves provenance, frames and non-approval flags."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'src/tools/sign-sequence-export.py'


class SequenceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('sequence_export',SCRIPT)
        cls.e=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.e)

    def test_feature_order_matches_soke_and_excludes_root_camera_shape(self):
        p={k:np.zeros(s,dtype=np.float32) for k,s in self.e.align.hand.SHAPES.items()}
        p['body_pose']=np.arange(63,dtype=np.float32).reshape(21,3)
        p['left_hand_pose'][:]=2.;p['right_hand_pose'][:]=3.;p['jaw_pose'][:]=4.;p['expression'][:]=5.
        p['transl'][:]=999.;p['global_orient'][:]=888.;p['betas'][:]=777.
        feature=self.e.features_133([p])
        self.assertEqual(feature.shape,(1,133));self.assertEqual(feature.dtype,np.float32)
        np.testing.assert_array_equal(feature[0,:30],np.arange(33,63,dtype=np.float32))
        self.assertTrue(np.all(feature[0,30:75]==2.));self.assertTrue(np.all(feature[0,75:120]==3.))
        self.assertTrue(np.all(feature[0,120:123]==4.));self.assertTrue(np.all(feature[0,123:]==5.))
        self.assertFalse(np.isin(feature,[999.,888.,777.]).any())

    def test_quality_marks_missing_ambiguous_and_rejected_separately(self):
        rows=[{'frame_1based':1,'detection_counts':{'left':0,'right':2},'applied':{'left':False,'right':False}},
              {'frame_1based':2,'detection_counts':{'left':1,'right':1},'applied':{'left':False,'right':True}}]
        q=self.e.observation_summary(rows)
        self.assertEqual(q['left']['missing_frames'],[1]);self.assertEqual(q['right']['ambiguous_frames'],[1])
        self.assertEqual(q['left']['rejected_observed_frames'],[2]);self.assertEqual(q['right']['applied_frames'],[2])
        self.assertFalse(q['training_ready'])

    def test_rotation_jumps_use_geodesic_rotation_and_not_axis_angle_subtraction(self):
        values=np.zeros((3,15,3));values[1,:,0]=2*np.pi;values[2,:,0]=2*np.pi+.1
        r=self.e.rotation_audit(values)
        self.assertLess(r['max_adjacent_degrees'],6.)
        self.assertEqual(r['over_90_to_frame'],[])

    def test_nonfinite_or_empty_features_are_rejected(self):
        with self.assertRaises(ValueError):self.e.features_133([])
        p={k:np.zeros(s,dtype=np.float32) for k,s in self.e.align.hand.SHAPES.items()};p['body_pose'][0,0]=np.nan
        with self.assertRaises(ValueError):self.e.features_133([p])

    def test_hand_training_mask_excludes_missing_rejected_and_ambiguous_baselines(self):
        rows=[{'applied':{'left':True,'right':False}},{'applied':{'left':False,'right':True}}]
        mask=self.e.feature_valid_mask(rows)
        self.assertEqual(mask.shape,(2,133));self.assertEqual(mask.dtype,np.bool_)
        self.assertTrue(mask[0,:75].all());self.assertFalse(mask[0,75:120].any())
        self.assertFalse(mask[1,30:75].any());self.assertTrue(mask[1,75:].all())


class SequenceExportIntegrationTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('export_runtime',SCRIPT)
        self.e=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.e)
        spec=importlib.util.spec_from_file_location('export_fixture',ROOT/'tests/sign-stable-fusion-review.test.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        self.f=m.StableFusionIntegrationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        nested=self.f.f;original=nested.fixture
        self.counts={s:len(ids) for s,ids in self.f.windows.items()}
        wi_path=nested.wi/'report.json';w=json.loads(wi_path.read_text());w['source_files_unchanged']=True
        w['status']='inferred_pending_visual_review'
        wi_path.write_text(json.dumps(w));original.write_manifest(nested.wi.parent)
        path=self.f.new/'report.json';r=json.loads(path.read_text());r['full_sequence_inferred']=True
        r['wilor_report_sha256']=self.e.evidence.digest(wi_path)
        path.write_text(json.dumps(r));original.write_manifest(self.f.new.parent)
        self.args=SimpleNamespace(batch=original.batch,stable_results=nested.new,wilor_results=nested.wi,
            fusion_results=self.f.new,output=self.f.root/'export',
            stable_report_sha256=self.e.evidence.digest(nested.new/'report.json'),
            wilor_report_sha256=self.e.evidence.digest(nested.wi/'report.json'),
            fusion_report_sha256=self.e.evidence.digest(path))

    def run_export(self):
        with patch.object(self.e.align.hand,'FULL_SEQUENCE_COUNTS',self.counts):
            return self.e.audit(self.args)

    def test_export_complete_time_axis_masks_and_source_hashes(self):
        before={p:self.e.evidence.digest(p) for p in self.f.new.parent.rglob('*') if p.is_file()}
        path=self.run_export();r=json.loads(path.read_text())
        self.assertEqual(r['converted'],2);self.assertFalse(r['training_ready'])
        self.assertEqual({p:self.e.evidence.digest(p) for p in before},before)
        for segment,count in self.counts.items():
            folder=path.parent/'samples'/segment
            features=np.load(folder/'features-133.npy',allow_pickle=False)
            mask=np.load(folder/'feature-valid-mask.npy',allow_pickle=False)
            self.assertEqual(features.shape,(count,133));self.assertEqual(mask.shape,features.shape)
            self.assertFalse(mask[:,30:120].any())
            self.assertTrue((folder/'full-sequence-quality.png').exists())
        self.e.evidence.verify_manifest(path.parent,path.parent/'SHA256SUMS')

    def test_changed_root_or_existing_output_are_rejected(self):
        path=self.f.new/'pilot-greeting-hello-001/000001/candidate.npz'
        with np.load(path,allow_pickle=False) as a:values={k:a[k].copy() for k in a.files}
        values['transl'][0,2]+=.1
        np.savez_compressed(path,**values);self.f.f.fixture.write_manifest(self.f.new.parent)
        with self.assertRaisesRegex(ValueError,'Protected parameter modified'):
            self.run_export()
        self.assertFalse(self.args.output.exists())
        self.args.output.mkdir();p=self.args.output/'keep';p.write_text('keep')
        with self.assertRaisesRegex(ValueError,'separate'):
            self.run_export()
        self.assertEqual(p.read_text(),'keep')


if __name__=='__main__':unittest.main()
