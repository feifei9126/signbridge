"""Source-motion metrics keep unknowns missing and never imply sign correctness."""
from pathlib import Path
import importlib.util
import unittest
import tempfile
import json
import numpy as np


def load(name):
    p=Path(__file__).resolve().parents[1]/'src/tools'/name;s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


observe=load('sign-csl-foundation-observe.py')
compare=load('sign-csl-foundation-compare.py')
foundation=load('sign-csl-foundation.py')


class FoundationMetricTests(unittest.TestCase):
    def arrays(self,n=4):
        a={}
        for name,shape in observe.SHAPES.items():a[name]=np.full((n,*shape),np.nan,np.float32);a[name+'_detected']=np.zeros(n,bool)
        return a

    def test_empty_metric_is_unknown_not_zero(self):
        s=observe.summary([np.nan,np.nan]);self.assertIsNone(s['p95']);self.assertEqual(s['measured'],0);self.assertEqual(s['missing'],2)

    def test_missing_arrays_need_nan_and_exact_mask(self):
        a=self.arrays();observe.validate_arrays(a,4);a['left_hand_image'][0]=0
        with self.assertRaises(ValueError):observe.validate_arrays(a,4)
        a['left_hand_image_detected'][0]=True;observe.validate_arrays(a,4)

    def test_constant_native_rotation_has_zero_step_including_handmean(self):
        p=np.zeros((4,15,3));p[:]=[.4,.2,-.1];a=compare.angular_change(p,np.full((15,3),.1));self.assertTrue(np.allclose(a,0,atol=1e-10))

    def test_angle_wraparound_is_not_358degrees(self):
        aa=np.zeros((3,1,3));aa[:,0,2]=np.deg2rad([179,-179,-177]);self.assertTrue(np.allclose(compare.angular_change(aa),2,atol=1e-10))

    def test_translation_shift_changes_absolute_but_not_local_error(self):
        target=np.arange(4*21*2,dtype=float).reshape(4,21,2);native=target+[20,10];r=compare.spatial_errors(native,target,np.ones(4,bool))
        self.assertGreater(r['absolute_rmse_pixels']['p95'],0);self.assertEqual(r['local_hand_rmse_pixels']['p95'],0);self.assertAlmostEqual(r['wrist_error_pixels']['p95'],np.sqrt(500))

    def test_unobserved_hand_does_not_get_perfect_matching_score(self):
        a=np.zeros((4,21,2));r=compare.spatial_errors(a,a,np.zeros(4,bool));self.assertIsNone(r['local_hand_rmse_pixels']['p95']);self.assertEqual(r['source_valid_frames'],0)

    def test_opposite_movement_is_reported_independently_of_spatial_error(self):
        s=np.zeros((4,21,2));s[:,:,0]=np.arange(4)[:,None]*3;n=s.copy();n[:,:,0]*=-1;r=compare.compare_velocity(n,s,np.ones(4,bool));self.assertEqual(r['opposite_direction_transitions'],3)

    def test_all_missing_geometry_does_not_claim_normal_motion(self):
        r=observe.motion_metrics(self.arrays(),640,360);self.assertIn('body_geometry_unavailable',r['risk_flags']);self.assertFalse(r['no_jitter_guarantee']);self.assertEqual(r['actual_3d_collision'],'not_tested_from_2d')

    def full_rounds(self):
        action={k:'a'*64 for k in ['source_sha256','clip_sha256','action_version_sha256','annotation_sha256']}
        rows=[{'round':i,'method_sha256':str(i)*64,**action,'evidence_scope':'full_action_all_source_frames','result':'passed','checks':{k:'passed' for k in foundation.CHECKS}} for i in [1,2]]
        return action,rows

    def test_gate_accepts_only_complete_distinct_same_version_rounds(self):
        action,rows=self.full_rounds();self.assertTrue(foundation.gate(action,rows)['training_allowed'])
        rows[1]['method_sha256']=rows[0]['method_sha256'];self.assertFalse(foundation.gate(action,rows)['training_allowed'])

    def test_changed_action_or_annotation_invalidates_both_passes(self):
        action,rows=self.full_rounds();action['annotation_sha256']='b'*64;self.assertFalse(foundation.gate(action,rows)['training_allowed'])
        action,rows=self.full_rounds();action['action_version_sha256']='b'*64;self.assertFalse(foundation.gate(action,rows)['training_allowed'])

    def test_technical_pass_and_unknown_dimension_cannot_open_training(self):
        action,rows=self.full_rounds();rows[1]['checks']['handshape']='unknown';self.assertFalse(foundation.gate(action,rows)['training_allowed'])
        action,rows=self.full_rounds();rows[1]['evidence_scope']='keyframe_only';self.assertFalse(foundation.gate(action,rows)['training_allowed'])
        action,rows=self.full_rounds();action['action_version_sha256']=None;self.assertFalse(foundation.gate(action,rows)['training_allowed'])

    def test_text_normalization_keeps_variants_and_qualifiers(self):
        self.assertNotEqual(foundation.text_key('下午2'),foundation.text_key('下午'))
        self.assertEqual(foundation.text_key('你好吗？'),'你好吗');self.assertNotEqual(foundation.text_key('家（房子）'),foundation.text_key('家'))


    def test_annotation_version_covers_meaning_refinement_and_boundaries(self):
        sample={'id':'basic-you','raw':{'Chinese Sentences':'你'},'source_sha256':'a'*64,'source_pts_seconds':[1.,1.04],'source_frame_ids_0based':[25,26]}
        lex=[{'id':'l','source_sha256':'a'*64,'canonical_text':'你','meaning':'听者'}];ref=[{'original_lexical_id':'l','meaning_clean':'对方','review_uncertainties':['手别未确认']}];target=[{'text':'你','meaning':'交谈对象'}]
        old=foundation.annotation_version(sample,lex,ref,target);ref[0]['meaning_clean']='wrongchanged';self.assertNotEqual(old,foundation.annotation_version(sample,lex,ref,target))
        old=foundation.annotation_version(sample,lex,ref,target);target[0]['meaning']='thirdperson';self.assertNotEqual(old,foundation.annotation_version(sample,lex,ref,target))
        old=foundation.annotation_version(sample,lex,ref,target);sample['source_pts_seconds']=[1.1,1.14];self.assertNotEqual(old,foundation.annotation_version(sample,lex,ref,target))

    def test_rechecking_current_native_files_invalidates_changed_asset(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for sub in ['smplx','meta','img']:(root/sub).mkdir()
            (root/'smplx/00001_0.npz').write_bytes(b'preservednative');(root/'meta/00001_0.json').write_text('{}');(root/'img/000001.jpg').write_bytes(b'render')
            inventory=compare.asset_inventory(root,1);record={'native_directory':str(root),'expected_frames':1,'source_sha256':'a'*64,'clip_sha256':'b'*64,'action_version_sha256':compare.version_digest('a'*64,'b'*64,inventory)}
            compare.verify_action(record);(root/'smplx/00001_0.npz').write_bytes(b'changed')
            with self.assertRaises(ValueError):compare.verify_action(record)

    def test_mapping_cannot_exchange_another_native_directory_with_same_proof(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();run=root/'attempt';fit=run/'fits/fit_correct';fit.mkdir(parents=True);other=run/'fits/fit_wrong';other.mkdir();clip=root/'clip.mp4';clip.write_bytes(b'clip')
            report=run/'report.json';report.write_text(json.dumps({'candidate_records':[{'annotation_id':'fit_correct','source_sha256':'a'*64,'frames_expected':4,'smplx_directory':'fits/fit_correct/smplx','metadata_directory':'fits/fit_correct/meta','render_directory':'fits/fit_correct/img'}]}))
            digest=compare.sha(clip);sample={'id':'c','source_sha256':'a'*64,'media_sha256':digest,'frames':4};aliases={'c':{'fit_sequence_id':'fit_correct','source_sha256':'a'*64,'candidate_clip_sha256':digest}};sequences={'fit_correct':{'source_sha256':'a'*64,'clip_sha256':digest,'frames':4}}
            item={'fit_sequence_id':'fit_correct','source_sha256':'a'*64,'clip_sha256':digest,'proof_path':str(report),'proof_sha256':compare.sha(report),'clip_proof':{'path':str(clip)},'native_sample_proof':{'path':str(fit/'smplx/00001_0.npz')}}
            self.assertEqual(compare.identity_chain(item,sample,aliases,sequences)[0],fit)
            item['native_sample_proof']['path']=str(other/'smplx/00001_0.npz')
            with self.assertRaises(ValueError):compare.identity_chain(item,sample,aliases,sequences)



if __name__=='__main__':unittest.main()
