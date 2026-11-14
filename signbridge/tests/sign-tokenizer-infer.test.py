"""Reusable tokenizer loading requires explicit digest and retains research-only semantics."""
import importlib.util,tempfile,unittest
from pathlib import Path
import numpy as np
SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-tokenizer-infer.py'
class TokenizerInferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('tokenizer_infer',SCRIPT);cls.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.m)
    def test_frame_padding_is_removed_from_output_timeline(self):
        a=np.ones((166,133),dtype=np.float32);mask=np.ones_like(a,dtype=bool)
        padded,valid,count=self.m.prepare_sequence(a,mask)
        self.assertEqual(padded.shape,(168,133));self.assertEqual(valid.shape,padded.shape);self.assertEqual(count,166)
        np.testing.assert_array_equal(padded[-1],a[-1])
    def test_invalid_feature_width_dtype_and_mask_are_rejected(self):
        for a in (np.ones((3,132),dtype=np.float32),np.ones((3,133),dtype=np.int32),np.full((3,133),np.nan,dtype=np.float32)):
            with self.assertRaises(ValueError):self.m.prepare_sequence(a,np.ones_like(a,dtype=bool))
        with self.assertRaises(ValueError):self.m.prepare_sequence(np.ones((3,133),dtype=np.float32),np.ones((3,133),dtype=np.int8))
    def test_checkpoint_digest_is_required_before_any_torch_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'checkpoint.pt';p.write_bytes(b'not a torch pickle')
            with self.assertRaisesRegex(ValueError,'digest'):
                self.m.verify_checkpoint(p,'0'*64)
    def test_report_never_claims_text_generation_or_generalization(self):
        r=self.m.contract(166)
        self.assertFalse(r['text_to_sign_generated']);self.assertFalse(r['deployment_ready'])
        self.assertEqual(r['frames'],166);self.assertTrue(r['research_only'])
    def test_heldout_checkpoint_contract_keeps_fresh_training_source_record(self):
        saved={'schema':'signbridge-heldout-tokenizer-checkpoint-v1','training_ready':False,'research_only':True,
               'soke_commit':self.m.smoke.SOKE_COMMIT,'normalization_train_only':True,
               'train_segments':['train-a'],'evaluation_segments':['eval-b'],
               'model_configs':[{'nfeats':43},{'nfeats':45},{'nfeats':45}]}
        value=self.m.checkpoint_contract(saved)
        self.assertEqual(value['checkpoint_role'],'fresh_source_holdout_fold')
        self.assertEqual(value['train_segments'],['train-a'])
        self.assertFalse(value['evaluation_quality_approved'])
        saved['evaluation_segments']=['train-a']
        with self.assertRaisesRegex(ValueError,'overlap'):
            self.m.checkpoint_contract(saved)
    def test_checkpoint_without_research_flag_or_wrong_part_width_is_rejected(self):
        saved={'schema':'signbridge-tokenizer-smoke-checkpoint-v1','training_ready':False,
               'research_only':False,'soke_commit':self.m.smoke.SOKE_COMMIT,
               'model_configs':[{'nfeats':43},{'nfeats':45},{'nfeats':45}]}
        with self.assertRaises(ValueError):self.m.checkpoint_contract(saved)
        saved['research_only']=True;saved['model_configs'][0]['nfeats']=42
        with self.assertRaises(ValueError):self.m.checkpoint_contract(saved)
if __name__=='__main__':unittest.main()
