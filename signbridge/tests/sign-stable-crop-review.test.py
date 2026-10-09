"""Stable-crop comparisons never confuse crop-coordinate change with model improvement."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-stable-crop-review.py'


class StableCropReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('stable_crop_review',SCRIPT)
        cls.review=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.review)

    def test_depth_comparison_separates_raw_and_same_camera_baseline(self):
        r=self.review.depth_summary([10,12,14],[10,10,10],[10,10.2,10.1],[88,89,90])
        self.assertEqual(r['original_raw_max_adjacent_depth_step'],2.)
        self.assertEqual(r['original_rebased_max_adjacent_depth_step'],0.)
        self.assertAlmostEqual(r['stable_crop_max_adjacent_depth_step'],.2)
        self.assertFalse(r['improved_vs_rebased_max_step'])
        self.assertFalse(r['training_ready'])

    def test_hand_projection_compares_all_same_identity_joints_in_pixels(self):
        original=np.zeros((21,2));stable=np.ones((21,2));wilor=np.ones((21,2))
        result=self.review.projection_comparison(original,stable,wilor)
        self.assertEqual(result['stable_crop']['absolute_rmse_pixels'],0.)
        self.assertEqual(result['original']['absolute_rmse_pixels'],1.)
        self.assertFalse(result['independent_ground_truth'])
        with self.assertRaises(ValueError):
            self.review.projection_comparison(original,stable,np.zeros((5,2)))

    def test_incomplete_unordered_or_nonfinite_timelines_are_rejected(self):
        for ids,raw,common,stable in (([88,90],[1,2],[1,2],[1,2]),
                                    ([90,89],[1,2],[1,2],[1,2]),
                                    ([88,89],[1,np.nan],[1,2],[1,2]),
                                    ([88,89],[1,2],[1],[1,2])):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                self.review.depth_summary(raw,common,stable,ids)

    def test_report_never_replaces_fits_or_promotes_training(self):
        r=self.review.contract()
        self.assertFalse(r['training_ready'])
        self.assertFalse(r['source_fits_modified'])
        self.assertFalse(r['full_sequence_refined'])
        self.assertEqual(r['status'],'stable_crop_comparison_pending_review')


class StableCropReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('review_runtime',SCRIPT)
        self.review=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.review)
        spec=importlib.util.spec_from_file_location('review_camera_fixture',SCRIPT.parents[2]/'tests/sign-camera-audit.test.py')
        fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
        self.fixture=fixtures.CameraReportTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.windows={s:tuple(range(1,4)) for s in f.counts}
        self.new=f.root/'stable/results';self.new.mkdir(parents=True)
        self.wi=f.root/'wilor/results';self.wi.mkdir(parents=True)
        cases=[];wcases=[];sources={}
        plan={'schema':'signbridge-stable-crop-plan-v1','training_ready':False,'windows':{}}
        for name in ('contract.json','tasks.jsonl','SHA256SUMS'):
            sources['/remote/batch/'+name]=self.review.evidence.digest(f.batch/name)
        for s,ids in self.windows.items():
            fixed=[80.,40.,192.,256.]
            plan['windows'][s]={'fixed_bbox':fixed,'frames':list(ids)}
            sides=['left','right'] if 'greeting' in s else ['right']
            for frame in ids:
                rel=s+'/meta/%05d_0.json'%frame
                native=s+'/smplx/%05d_0.npz'%frame
                image='samples/'+s+'/images/%06d.jpg'%frame
                for path in (rel,native):
                    src=f.source/path;dst=self.new/path
                    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(src.read_bytes())
                    sources['/remote/fits/'+path]=self.review.evidence.digest(src)
                sources['/remote/batch/'+image]=self.review.evidence.digest(f.batch/image)
                cases.append({'segment_id':s,'frame_1based':frame,'parameters_file':native,'camera_file':rel,
                              'native_parity_max_metres':1e-7,'training_ready':False})
                wc={'segment_id':s,'frame_1based':frame,'output_relative':s+'/%06d'%frame,'hands':[]}
                for side in sides:
                    folder=self.wi/wc['output_relative'];folder.mkdir(parents=True,exist_ok=True)
                    target=f.helper.project(f.model.hand(f.params,side),{'focal':np.array([5000.,5000.]),'princpt':np.array([176.,168.])})
                    np.savez_compressed(folder/(side+'-00.npz'),right=np.asarray(side=='right'),projected_joints=target)
                    wc['hands'].append({'side':side,'parameters_file':side+'-00.npz'})
                wcases.append(wc)
        (self.new.parent/'plan.json').write_text(json.dumps(plan))
        sources['/remote/plan.json']=self.review.evidence.digest(self.new.parent/'plan.json')
        (self.new/'report.json').write_text(json.dumps({'schema':'signbridge-stable-crop-pilot-v1',
            'status':'inferred_pending_stable_crop_review','training_ready':False,'source_files_unchanged':True,
            'scope':{s:list(ids) for s,ids in self.windows.items()},'cases':cases,'source_sha256':sources}))
        (self.wi/'report.json').write_text(json.dumps({'schema':'signbridge-wilor-keyframe-pilot-v1',
            'training_ready':False,'cases':wcases,'source_sha256':sources}))
        f.write_manifest(self.new.parent);f.write_manifest(self.wi.parent)
        self.args=SimpleNamespace(fit_source=f.source,batch=f.batch,stable_results=self.new,wilor_results=self.wi,
            smplerx_root=f.model_root,output=f.root/'review',
            stable_report_sha256=self.review.evidence.digest(self.new/'report.json'),
            wilor_report_sha256=self.review.evidence.digest(self.wi/'report.json'))

    def run_review(self):
        f=self.fixture
        with patch.object(self.review.stable,'WINDOWS',self.windows), \
             patch.object(self.review.stable,'FIT_SHA',self.review.evidence.digest(f.source/'run.json')), \
             patch.object(self.review.stable.hand,'MODEL_SHA256',f.model_sha), \
             patch.object(self.review.stable.hand,'SparseSMPLX',return_value=f.model):
            return self.review.review(self.args)

    def rewrite_run(self, change):
        p=self.new/'report.json';r=json.loads(p.read_text());change(r)
        p.write_text(json.dumps(r));self.fixture.write_manifest(self.new.parent)
        self.args.stable_report_sha256=self.review.evidence.digest(p)

    def test_full_review_has_three_depth_tracks_media_and_preserved_input_hashes(self):
        f=self.fixture
        before={p:self.review.evidence.digest(p) for root in (f.source,self.new.parent,self.wi.parent)
                for p in root.rglob('*') if p.is_file()}
        p=self.run_review();r=json.loads(p.read_text())
        self.assertFalse(r['training_ready'])
        self.assertEqual({p:self.review.evidence.digest(p) for p in before},before)
        for segment,w in r['windows'].items():
            self.assertIn('original_rebased_max_adjacent_depth_step',w['depth'])
            self.assertTrue((p.parent/segment/'stable-crop-review.jpg').exists())
            self.assertTrue((p.parent/segment/'stable-crop-metrics.png').exists())
        self.review.evidence.verify_manifest(p.parent,p.parent/'SHA256SUMS')

    def test_missing_scope_wrong_hash_and_existing_output_are_rejected(self):
        self.rewrite_run(lambda r:r['cases'].pop())
        with self.assertRaisesRegex(ValueError,'scope'):
            self.run_review()
        self.assertFalse(self.args.output.exists())
        self.args.output.mkdir();marker=self.args.output/'keep';marker.write_text('keep')
        with self.assertRaisesRegex(ValueError,'separate'):
            self.run_review()
        self.assertEqual(marker.read_text(),'keep')

    def test_wrong_report_hash_and_training_ready_input_are_rejected(self):
        expected=self.args.stable_report_sha256
        self.args.stable_report_sha256='0'*64
        with self.assertRaisesRegex(ValueError,'unexpected'):
            self.run_review()
        self.assertFalse(self.args.output.exists())
        self.args.stable_report_sha256=expected
        self.rewrite_run(lambda r:r.update(training_ready=True))
        with self.assertRaisesRegex(ValueError,'unexpected'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_failed_native_parity_cannot_be_treated_as_valid_candidate(self):
        self.rewrite_run(lambda r:r['cases'][0].update(native_parity_max_metres=.1))
        with self.assertRaisesRegex(ValueError,'parity'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_frame_camera_cannot_change_from_frozen_plan(self):
        p=self.new/'pilot-greeting-hello-001/meta/00001_0.json'
        r=json.loads(p.read_text());r['bbox'][0]+=10.;r['princpt'][0]+=10.
        p.write_text(json.dumps(r));self.fixture.write_manifest(self.new.parent)
        with self.assertRaisesRegex(ValueError,'fixed|crop'):
            self.run_review()
        self.assertFalse(self.args.output.exists())


if __name__=='__main__':
    unittest.main()
