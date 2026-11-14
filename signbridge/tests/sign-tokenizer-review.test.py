"""Tokenizer review preserves hidden roots and does not apply predictions to missing hands."""
import importlib.util,unittest
from pathlib import Path
import numpy as np
SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-tokenizer-review.py'
class TokenizerReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s=importlib.util.spec_from_file_location('tokenizer_review',SCRIPT);cls.m=importlib.util.module_from_spec(s);s.loader.exec_module(cls.m)
    def source(self):return {k:np.zeros(shape,dtype=np.float32) for k,shape in self.m.hand.SHAPES.items()}
    def test_root_shape_and_nonrepresented_body_joints_are_preserved(self):
        p=self.source();p['transl'][0,2]=20.;p['global_orient'][0]=[1,2,3];p['betas'][0]=np.arange(10)
        features=np.ones(133,dtype=np.float32)*.1;valid=np.ones(133,dtype=bool)
        output=self.m.decode_features(p,features,valid)
        for key in ('transl','global_orient','betas','leye_pose','reye_pose'):np.testing.assert_array_equal(p[key],output[key])
        np.testing.assert_array_equal(p['body_pose'][:11],output['body_pose'][:11])
        self.assertTrue((output['body_pose'][11:]==.1).all());self.assertTrue((output['expression']==.1).all())
        self.assertTrue((p['body_pose']==0).all())
    def test_masked_hand_predictions_keep_exact_existing_pose(self):
        p=self.source();p['left_hand_pose'][:]=.3
        mask=np.ones(133,dtype=bool);mask[30:75]=False
        output=self.m.decode_features(p,np.ones(133,dtype=np.float32)*.9,mask)
        np.testing.assert_array_equal(p['left_hand_pose'],output['left_hand_pose'])
        self.assertTrue((output['right_hand_pose']==.9).all())
    def test_nonfinite_or_fractional_hand_masks_are_rejected(self):
        p=self.source();features=np.ones(133,dtype=np.float32);mask=np.ones(133,dtype=bool)
        features[0]=np.nan
        with self.assertRaises(ValueError):self.m.decode_features(p,features,mask)
        with self.assertRaises(ValueError):self.m.decode_features(p,np.ones(133),np.ones(133,dtype=np.int8))
if __name__=='__main__':unittest.main()
