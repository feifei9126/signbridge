"""Completed holdout evidence must retain train-only normalization and metrics provenance."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-heldout-review.py'


class HeldoutReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s=importlib.util.spec_from_file_location('heldout_review',SCRIPT)
        cls.review=importlib.util.module_from_spec(s);s.loader.exec_module(cls.review)

    def rows(self):
        return [{'segment_id':'greeting','source_id':'s1','source_sha256':'a'*64,'signer_id':'p1','split_group':'g1','frames':166},
                {'segment_id':'cough','source_id':'s2','source_sha256':'b'*64,'signer_id':'p2','split_group':'g2','frames':218}]

    def report(self):
        rows=self.rows()
        folds=[]
        for i in (0,1):
            folds.append({'fold_id':i+1,'train_segments':[rows[1-i]['segment_id']],
                'evaluation_segments':[rows[i]['segment_id']],
                'train_source_ids':[rows[1-i]['source_id']],'evaluation_source_ids':[rows[i]['source_id']],
                'normalization_frame_count':rows[1-i]['frames'],'checkpoint_reload_passed':True,
                'evaluation_used_for_weight_updates':False,'evaluation_used_for_checkpoint_selection':False,
                'recorded_split_disjoint':True,'heldout_metrics_computed':True})
        return {'schema':'signbridge-leave-source-out-tokenizer-v1',
                'status':'leave_source_out_experiments_complete_pending_quality_review','evaluation_completed':True,
                'training_ready':False,'source_files_unchanged':True,'fresh_weights_per_fold':True,'folds':folds}

    def test_valid_report_has_each_recorded_source_held_out_exactly_once(self):
        self.review.validate_finished_report(self.report(),self.rows())

    def test_test_selection_training_exposure_and_incomplete_reload_are_rejected(self):
        for key,value in (('evaluation_used_for_weight_updates',True),('evaluation_used_for_checkpoint_selection',True),
                          ('normalization_frame_count',384),('checkpoint_reload_passed',False)):
            r=self.report();r['folds'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.review.validate_finished_report(r,self.rows())

    def test_reusing_or_relabeling_a_fold_cannot_count_as_two_independent_evaluations(self):
        r=self.report();r['folds'][1]=copy.deepcopy(r['folds'][0]);r['folds'][1]['fold_id']=2
        with self.assertRaisesRegex(ValueError,'scope'):
            self.review.validate_finished_report(r,self.rows())
        r=self.report();r['folds'][0]['train_source_ids']=['s1']
        with self.assertRaisesRegex(ValueError,'source'):
            self.review.validate_finished_report(r,self.rows())

    def test_mean_baseline_comparison_reports_regression_as_well_as_improvement(self):
        self.assertAlmostEqual(self.review.relative_improvement(9.,10.),10.)
        self.assertAlmostEqual(self.review.relative_improvement(11.,10.),-10.)
        self.assertIsNone(self.review.relative_improvement(0.,0.))


class HeldoutReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('heldout_review_runtime',SCRIPT)
        self.r=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.r)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.motions=self.root/'curated-motions';self.batch=self.root/'batch'
        self.results=self.root/'evidence/results';self.cpu=self.root/'cpu'
        for root in (self.motions,self.batch,self.results,self.cpu):root.mkdir(parents=True)
        self.rows=[];arrays=[];masks=[]
        for i,segment in enumerate(self.r.smoke.SEGMENTS):
            folder=self.motions/'samples'/segment;folder.mkdir(parents=True)
            values=np.ones((70,133),dtype=np.float32)*(i+1)
            values[:,0]+=np.arange(70,dtype=np.float32)*.01
            mask=np.ones_like(values,dtype=bool);mask[:10,30:75]=False
            np.save(folder/'features-133.npy',values,allow_pickle=False)
            np.save(folder/'feature-valid-mask.npy',mask,allow_pickle=False)
            self.rows.append({'segment_id':segment,'source_id':'s'+str(i),'source_sha256':str(i)*64,
                'signer_id':'p'+str(i),'split_group':'g'+str(i),'frames':70,'features':'samples/'+segment+'/features-133.npy',
                'representation':'soke-smplx-133-v1','dimensions':133,'motion_review_status':'needs_review',
                'model_training_ready':False})
            arrays.append(values);masks.append(mask)
        (self.motions/'motions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
        (self.motions/'verification.json').write_text(json.dumps({'schema':'signbridge-full-fusion-export-v1',
            'converted':2,'rejected':[],'training_ready':False,'soke_commit':self.r.smoke.SOKE_COMMIT}))
        self.manifest(self.motions)
        (self.batch/'tasks.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
        (self.batch/'contract.json').write_text('{}');self.manifest(self.batch)
        self.report={'schema':'signbridge-leave-source-out-tokenizer-v1',
            'status':'leave_source_out_experiments_complete_pending_quality_review','evaluation_completed':True,
            'training_ready':False,'source_files_unchanged':True,'fresh_weights_per_fold':True,'folds':[],
            'previous_mixed_checkpoint_exposure':self.r.evaluation.exposure_audit(self.rows,[r['segment_id'] for r in self.rows]),
            'source_group_components':self.r.evaluation.group_components(self.rows),
            'limitations':['synthetic pipeline test'],
            'source_sha256':{}}
        for folder in (self.motions,self.batch):
            for p in folder.rglob('*'):
                if p.is_file():self.report['source_sha256']['/remote/'+folder.name+'/'+str(p.relative_to(folder))]=self.r.evidence.digest(p)
        self.checkpoints={}
        for i in (0,1):
            fold_id=i+1;folder=self.results/('fold-%02d'%fold_id);folder.mkdir()
            checkpoint=folder/'tokenizer-heldout.pt';checkpoint.write_bytes(('synthetic checkpoint '+str(i)).encode())
            train=[self.rows[1-i]['segment_id']];evaluation=[self.rows[i]['segment_id']]
            mean,std=self.r.smoke.normalization([arrays[1-i]],[masks[1-i]])
            self.checkpoints[checkpoint]={'schema':'signbridge-heldout-tokenizer-checkpoint-v1','training_ready':False,
                'research_only':True,'soke_commit':self.r.smoke.SOKE_COMMIT,
                'normalization_train_only':True,'mean':mean.copy(),'std':std.copy(),
                'train_segments':train,'evaluation_segments':evaluation,'step':50}
            fold={'fold_id':fold_id,'train_segments':train,'evaluation_segments':evaluation,
                'train_source_ids':[self.rows[1-i]['source_id']],'evaluation_source_ids':[self.rows[i]['source_id']],
                'normalization_frame_count':70,'checkpoint_reload_passed':True,'heldout_metrics_computed':True,
                'recorded_split_disjoint':True,'evaluation_used_for_weight_updates':False,
                'evaluation_used_for_checkpoint_selection':False,'checkpoint_step':50,
                'checkpoint_sha256':self.r.evidence.digest(checkpoint),'sample_metrics':[]}
            for j,row in enumerate(self.rows):
                segment=row['segment_id'];sample=folder/segment;sample.mkdir()
                decoded=arrays[j]*.99
                np.save(sample/'reconstructed-133.npy',decoded,allow_pickle=False)
                for name in ('body','left','right'):np.save(sample/(name+'-tokens.npy'),np.ones((1,18),dtype=np.int64),allow_pickle=False)
                role='evaluation' if j==i else 'train'
                fold['sample_metrics'].append({'segment_id':segment,'role':role,'frames':70,
                    'metrics':self.r.evaluation.comparison_metrics(decoded,arrays[j],masks[j],mean,std)})
                if j==i:
                    cpu=self.cpu/('fold-%02d'%fold_id)/segment;cpu.mkdir(parents=True)
                    for path in sample.iterdir():(cpu/path.name).write_bytes(path.read_bytes())
                    record={'checkpoint_sha256':fold['checkpoint_sha256'],'checkpoint_role':'fresh_source_holdout_fold',
                            'train_segments':train,'evaluation_segments':evaluation,
                            'input_features_sha256':self.r.evidence.digest(self.motions/row['features']),
                            'mask_sha256':self.r.evidence.digest((self.motions/row['features']).with_name('feature-valid-mask.npy'))}
                    (cpu/'report.json').write_text(json.dumps(record));self.manifest(cpu)
            self.report['folds'].append(fold)
        self.write_report()
        self.args=SimpleNamespace(results=self.results,motions=self.motions,batch=self.batch,cpu_inference=self.cpu,
                                  output=self.root/'review',report_sha256=self.r.evidence.digest(self.results/'report.json'))

    def manifest(self,folder):
        files=sorted(p for p in folder.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
        (folder/'SHA256SUMS').write_text(''.join(self.r.evidence.digest(p)+'  '+str(p.relative_to(folder))+'\n' for p in files))

    def write_report(self):
        (self.results/'report.json').write_text(json.dumps(self.report));self.manifest(self.results)
        if hasattr(self,'args'):self.args.report_sha256=self.r.evidence.digest(self.results/'report.json')

    def run_review(self):
        with patch.object(self.r,'load_fold_checkpoint',side_effect=lambda path:self.checkpoints[path]):
            return self.r.review(self.args)

    def test_full_review_recomputes_both_folds_without_changing_evidence(self):
        before={p:self.r.evidence.digest(p) for root in (self.results,self.motions,self.batch,self.cpu)
                for p in root.rglob('*') if p.is_file()}
        path=self.run_review();r=json.loads(path.read_text())
        self.assertEqual(len(r['folds']),2);self.assertFalse(r['training_ready'])
        self.assertTrue(all(f['normalization_train_only_verified'] for f in r['folds']))
        self.assertTrue(all(f['cpu_gpu_parity'][0]['token_arrays_identical'] for f in r['folds']))
        self.assertEqual({p:self.r.evidence.digest(p) for p in before},before)
        self.assertTrue((path.parent/'heldout-comparison.png').is_file())
        self.r.evidence.verify_manifest(path.parent,path.parent/'SHA256SUMS')

    def test_wrong_normalization_or_saved_metric_stops_before_any_report(self):
        key=next(iter(self.checkpoints));self.checkpoints[key]['mean'][0]+=2.
        with self.assertRaisesRegex(ValueError,'normalization'):
            self.run_review()
        self.checkpoints[key]['mean'][0]-=2.
        self.report['folds'][0]['sample_metrics'][0]['metrics']['all']['normalized_mse']+=10.
        self.write_report()
        with self.assertRaisesRegex(ValueError,'metric differs'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_cpu_token_or_feature_mismatch_is_rejected(self):
        fold=self.report['folds'][0];segment=fold['evaluation_segments'][0]
        folder=self.cpu/'fold-01'/segment
        file=folder/'left-tokens.npy'
        np.save(file,np.zeros((1,18),dtype=np.int64),allow_pickle=False);self.manifest(folder)
        with self.assertRaisesRegex(ValueError,'token arrays differ'):
            self.run_review()
        self.assertFalse(self.args.output.exists())
        np.save(file,np.ones((1,18),dtype=np.int64),allow_pickle=False)
        path=folder/'report.json';r=json.loads(path.read_text());r['input_features_sha256']='0'*64
        path.write_text(json.dumps(r));self.manifest(folder)
        with self.assertRaisesRegex(ValueError,'source/checkpoint'):
            self.run_review()
        self.assertFalse(self.args.output.exists())

    def test_wrong_hash_or_existing_output_is_preserved(self):
        self.args.report_sha256='0'*64
        with self.assertRaisesRegex(ValueError,'digest'):
            self.run_review()
        self.assertFalse(self.args.output.exists())
        self.args.output.mkdir();p=self.args.output/'keep';p.write_text('keep')
        with self.assertRaisesRegex(ValueError,'separate'):
            self.run_review()
        self.assertEqual(p.read_text(),'keep')


if __name__=='__main__':unittest.main()
