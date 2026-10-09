"""Source-group holdout must not leak through shared signer/course/content identity."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
import numpy as np
SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-heldout-eval.py'

class HeldoutEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('heldout_eval',SCRIPT);cls.e=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.e)

    def row(self,segment,source,signer,group):
        return {'segment_id':segment,'source_id':source,'source_sha256':source+'sha',
                'signer_id':signer,'split_group':group,'frames':100}

    def test_group_components_are_transitive_across_source_person_and_course(self):
        rows=[self.row('a','s1','p1','g1'),self.row('b','s1','p2','g1'),
              self.row('c','s2','p2','g2'),self.row('d','s3','p3','g3')]
        groups=self.e.group_components(rows)
        self.assertEqual([g['segments'] for g in groups],[['a','b','c'],['d']])
        self.assertEqual(self.e.holdout_fold_indices(rows),[(0,1,2),(3,)])

    def test_source_or_signer_crossing_proposed_sets_is_rejected(self):
        a=self.row('a','s1','p1','g1');b=self.row('b','s1','p2','g2')
        with self.assertRaisesRegex(ValueError,'leakage'):
            self.e.assert_disjoint([a],[b])
        b=self.row('b','s2','p1','g2')
        with self.assertRaisesRegex(ValueError,'leakage'):
            self.e.assert_disjoint([a],[b])
        b=self.row('b','s2','p2','g2')
        self.e.assert_disjoint([a],[b])

    def test_normalization_uses_only_training_masked_targets(self):
        train=np.ones((80,133),dtype=np.float32)
        validation=np.ones((80,133),dtype=np.float32)*50
        valid=np.ones_like(train,dtype=bool)
        mean,std=self.e.smoke.normalization([train],[valid])
        np.testing.assert_allclose(mean,1.)
        prepared=self.e.smoke.normalized_model_input(validation,mean,std,valid)
        self.assertTrue((prepared>900).all())
        self.assertEqual(train[0,0],1.)

    def test_proposed_test_cannot_reuse_previously_exposed_source(self):
        rows=[self.row('a','s1','p1','g1'),self.row('b','s1','p2','g1'),self.row('c','s2','p3','g2')]
        exposure=self.e.exposure_audit(rows,['a','c'])
        self.assertEqual(exposure['source_independent_remaining_segments'],[])
        self.assertEqual(exposure['same_source_remaining_segments'],['b'])
        self.assertFalse(exposure['current_checkpoint_has_independent_source_test'])

    def test_missing_or_duplicate_id_cannot_create_a_fake_holdout(self):
        rows=[self.row('a','s1','p1','g1'),self.row('a','s2','p2','g2')]
        with self.assertRaises(ValueError):self.e.group_components(rows)
        row=self.row('a','s1','p1','g1');row['signer_id']=''
        with self.assertRaises(ValueError):self.e.group_components([row])

    def test_masked_error_and_training_mean_baseline_are_computed_separately(self):
        y=np.ones((3,133),dtype=np.float32);p=y.copy();p[:,30:75]=100.
        valid=np.ones_like(y,dtype=bool);valid[:,30:75]=False
        r=self.e.comparison_metrics(p,y,valid,np.zeros(133),np.ones(133))
        self.assertEqual(r['all']['normalized_mse'],0.)
        self.assertEqual(r['all']['mean_baseline_normalized_mse'],1.)
        self.assertEqual(r['left_hand']['valid_values'],0)
        self.assertIsNone(r['left_hand']['raw_rmse'])
        self.assertFalse(r['independent_human_ground_truth'])

    def test_metrics_reject_nonfinite_prediction_and_nonboolean_mask(self):
        y=np.ones((3,133),dtype=np.float32);p=y.copy();p[0,0]=np.nan
        with self.assertRaises(ValueError):
            self.e.comparison_metrics(p,y,np.ones_like(y,dtype=bool),np.zeros(133),np.ones(133))
        with self.assertRaises(ValueError):
            self.e.comparison_metrics(y,y,np.ones_like(y,dtype=np.int8),np.zeros(133),np.ones(133))
        with self.assertRaises(ValueError):
            self.e.comparison_metrics(y,y,np.ones_like(y,dtype=bool),np.zeros(133),np.zeros(133))

    def test_source_hash_collision_with_different_ids_still_prevents_split(self):
        a=self.row('a','s1','p1','g1');b=self.row('b','s2','p2','g2')
        b['source_sha256']=a['source_sha256']
        self.assertEqual(len(self.e.group_components([a,b])),1)
        with self.assertRaisesRegex(ValueError,'leakage'):
            self.e.assert_disjoint([a],[b])
        with self.assertRaisesRegex(ValueError,'two'):
            self.e.holdout_fold_indices([a,b])

if __name__=='__main__':unittest.main()
