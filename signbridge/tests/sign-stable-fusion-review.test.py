"""Stable-crop fusion audit must verify saved arrays, projection metrics and frozen roots."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-stable-fusion-review.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StableFusionReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = load('stable_fusion_review', SCRIPT)
        cls.fixture = load('fusion_math_fixture', SCRIPT.parents[2] / 'tests/sign-hand-refine.test.py')

    def test_preserved_depth_is_checked_exactly_not_by_a_smaller_motion_score(self):
        a = self.fixture.parameters()
        b = {k:v.copy() for k,v in a.items()}
        self.review.assert_frozen(a, b, ('right',))
        b['transl'][0,2] += .001
        with self.assertRaisesRegex(ValueError, 'Protected parameter modified: transl'):
            self.review.assert_frozen(a, b, ('right',))

    def test_rejected_hand_is_identical_to_baseline(self):
        a = self.fixture.parameters()
        b = {k:v.copy() for k,v in a.items()}
        row = {'frame_1based':156, 'fps':25., 'sides':('right',),
               'baseline':a, 'candidate':b, 'decisions':{'right':False}}
        self.review.align.pack_series([row])
        b['right_hand_pose'][0,0] += .1
        with self.assertRaisesRegex(ValueError,'Rejected hand'):
            self.review.align.pack_series([row])


class StableFusionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.review = load('stable_fusion_runtime', SCRIPT)
        fixture = load('fusion_comparison_fixture', SCRIPT.parents[2] / 'tests/sign-stable-crop-review.test.py')
        self.f = fixture.StableCropReviewIntegrationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.windows = self.f.windows
        base = self.f.fixture
        self.root = base.root
        self.new = self.root / 'fusion-new/results'
        self.old = self.root / 'fusion-old/results'
        self.new.mkdir(parents=True);self.old.mkdir(parents=True)
        cases=[];records={s:[] for s in self.windows};sources={}
        for name in ('contract.json','tasks.jsonl','SHA256SUMS'):
            sources['/remote/batch/'+name]=self.review.evidence.digest(base.batch/name)
        for segment,ids in self.windows.items():
            sides=('left','right') if 'greeting' in segment else ('right',)
            for frame in ids:
                path=segment+'/%06d'%frame
                meta_rel=segment+'/meta/%05d_0.json'%frame
                fit_rel=segment+'/smplx/%05d_0.npz'%frame
                sources['/remote/stable/results/'+meta_rel]=self.review.evidence.digest(self.f.new/meta_rel)
                sources['/remote/stable/results/'+fit_rel]=self.review.evidence.digest(self.f.new/fit_rel)
                row={'segment_id':segment,'frame_1based':frame,'output_relative':path,
                     'required_sides':list(sides),'training_ready':False,'hands':[],
                     'baseline_native_parity_max_metres':1e-7,'candidate_native_parity_max_metres':1e-7,
                     'all_candidate_gates_passed':False,'combined_projection_gate_passed':False}
                for root in (self.new,self.old):
                    folder=root/path;folder.mkdir(parents=True)
                    np.savez_compressed(folder/'baseline.npz',**base.params)
                    np.savez_compressed(folder/'candidate.npz',**base.params)
                for side in sides:
                    row['hands'].append({'side':side,'candidate_gate_passed':False,'applied_to_candidate':False,
                        'saved_candidate_after':{'absolute_rmse_pixels':0.,'local_rmse_pixels':0.,'fingertip_local_rmse_pixels':0.}})
                cases.append(row)
                records[segment].append({'frame_1based':frame,'fps':25.,'sides':sides,
                    'baseline':base.params,'candidate':base.params,'decisions':{s:False for s in sides}})
            np.savez_compressed(self.new/segment/'baseline-candidate-series.npz',
                                **self.review.align.pack_series(records[segment]))
        newreport={'schema':'signbridge-mano-smplx-alignment-v1','status':'alignment_candidate_gate_failed',
            'training_ready':False,'source_files_unchanged':True,'fit_source_kind':'stable_crop',
            'stable_report_sha256':self.f.args.stable_report_sha256,'wilor_report_sha256':self.f.args.wilor_report_sha256,
            'cases':cases,'source_sha256':sources}
        oldreport={'schema':'signbridge-mano-smplx-alignment-v1','training_ready':False,'source_files_unchanged':True,
                   'wilor_report_sha256':self.f.args.wilor_report_sha256,'cases':cases,'source_sha256':sources}
        (self.new/'report.json').write_text(json.dumps(newreport))
        (self.old/'report.json').write_text(json.dumps(oldreport))
        base.write_manifest(self.new.parent);base.write_manifest(self.old.parent)
        self.args=SimpleNamespace(batch=base.batch, fit_source=base.source,stable_results=self.f.new,
            stable_report_sha256=self.f.args.stable_report_sha256, fusion_results=self.new,
            fusion_report_sha256=self.review.evidence.digest(self.new/'report.json'),
            previous_fusion_results=self.old,previous_fusion_report_sha256=self.review.evidence.digest(self.old/'report.json'),
            wilor_results=self.f.wi,wilor_report_sha256=self.f.args.wilor_report_sha256,
            smplerx_root=base.model_root,output=self.root/'combined-review')

    def run_review(self):
        base=self.f.fixture
        with patch.object(self.review,'WINDOWS',self.windows), \
             patch.object(self.review.align.hand,'MODEL_SHA256',base.model_sha), \
             patch.object(self.review.align.hand,'SparseSMPLX',return_value=base.model):
            return self.review.review(self.args)

    def test_complete_report_uses_saved_fallback_masks_and_preserves_all_inputs(self):
        before={p:self.review.evidence.digest(p) for root in (self.new.parent,self.old.parent,self.f.new.parent)
                for p in root.rglob('*') if p.is_file()}
        path=self.run_review();r=json.loads(path.read_text())
        self.assertFalse(r['training_ready']);self.assertEqual(r['accepted_hands'],0)
        self.assertEqual(r['evaluated_hands'],9)
        self.assertTrue(r['root_translation_exactly_preserved'])
        self.assertEqual({p:self.review.evidence.digest(p) for p in before},before)
        for segment in self.windows:
            self.assertTrue((path.parent/segment/'fusion-comparison.jpg').exists())
            self.assertTrue((path.parent/segment/'fusion-metrics.png').exists())
        self.review.evidence.verify_manifest(path.parent,path.parent/'SHA256SUMS')

    def test_root_change_or_series_tampering_is_rejected(self):
        path=self.new/'pilot-greeting-hello-001/000001/candidate.npz'
        with np.load(path,allow_pickle=False) as a:
            values={k:a[k].copy() for k in a.files}
        values['transl'][0,2] += .1
        np.savez_compressed(path,**values);self.f.fixture.write_manifest(self.new.parent)
        with self.assertRaisesRegex(ValueError,'Protected parameter modified: transl'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_false_saved_metrics_cannot_promote_report(self):
        path=self.new/'report.json';r=json.loads(path.read_text())
        r['cases'][0]['hands'][0]['saved_candidate_after']['absolute_rmse_pixels']=10.
        path.write_text(json.dumps(r));self.f.fixture.write_manifest(self.new.parent)
        self.args.fusion_report_sha256=self.review.evidence.digest(path)
        with self.assertRaisesRegex(ValueError,'Saved.*metric'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_failed_saved_parity_and_extra_side_are_rejected(self):
        path=self.new/'report.json';r=json.loads(path.read_text())
        r['cases'][0]['candidate_native_parity_max_metres']=.1
        path.write_text(json.dumps(r));self.f.fixture.write_manifest(self.new.parent)
        self.args.fusion_report_sha256=self.review.evidence.digest(path)
        with self.assertRaisesRegex(ValueError,'parity'):
            self.run_review()
        self.assertFalse(self.args.output.exists())
        r['cases'][0]['candidate_native_parity_max_metres']=1e-7
        r['cases'][0]['hands'].append(dict(r['cases'][0]['hands'][0]))
        path.write_text(json.dumps(r));self.f.fixture.write_manifest(self.new.parent)
        self.args.fusion_report_sha256=self.review.evidence.digest(path)
        with self.assertRaisesRegex(ValueError,'hand identity'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_saved_sequence_masks_must_match_individual_frame_decisions(self):
        path=self.new/'pilot-hospital-cough-003/baseline-candidate-series.npz'
        with np.load(path,allow_pickle=False) as a:
            values={k:a[k].copy() for k in a.files}
        values['candidate_applied_mask'][0,0]=True
        np.savez_compressed(path,**values);self.f.fixture.write_manifest(self.new.parent)
        with self.assertRaisesRegex(ValueError,'series/masks'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_report_hash_and_original_source_parameters_are_verified(self):
        saved=self.args.fusion_report_sha256
        self.args.fusion_report_sha256='0'*64
        with self.assertRaisesRegex(ValueError,'digest mismatch'):
            self.run_review()
        self.args.fusion_report_sha256=saved
        path=self.old/'pilot-greeting-hello-001/000001/baseline.npz'
        with np.load(path,allow_pickle=False) as a:
            values={k:a[k].copy() for k in a.files}
        values['betas'][0,0]+=.1
        np.savez_compressed(path,**values);self.f.fixture.write_manifest(self.old.parent)
        with self.assertRaisesRegex(ValueError,'Stored baseline'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_existing_output_cannot_be_overwritten(self):
        self.args.output.mkdir();marker=self.args.output/'keep';marker.write_text('keep')
        with self.assertRaisesRegex(ValueError,'separate'):
            self.run_review()
        self.assertEqual(marker.read_text(),'keep')


if __name__=='__main__':
    unittest.main()
