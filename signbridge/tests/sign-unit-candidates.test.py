import importlib.util
from pathlib import Path
import unittest
import numpy as np

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-unit-candidates.py'
class CandidateTests(unittest.TestCase):
    def module(self):
        self.assertTrue(TOOL.exists(),'candidate extractor missing')
        spec=importlib.util.spec_from_file_location('unit_candidates',TOOL);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_windows_never_bridge_missing_observations(self):
        module=self.module();xy=np.zeros((30,21,2),dtype=np.float64)
        xy[:,:,0]=np.arange(30)[:,None]*.01
        mask=np.ones(30,dtype=bool);mask[12:17]=False;xy[~mask]=np.nan
        before=xy.copy();windows=module.activity_windows(xy,mask,25)
        self.assertTrue(windows)
        for w in windows:self.assertTrue(mask[w['start_frame_1based']-1:w['end_frame_1based']].all())
        np.testing.assert_array_equal(xy,before)

    def test_missing_only_stays_missing(self):
        module=self.module()
        self.assertEqual(module.activity_windows(np.full((10,21,2),np.nan),np.zeros(10,dtype=bool),25),[])

    def test_wrong_shapes_or_nonfinite_detected_observations_rejected(self):
        module=self.module()
        with self.assertRaises(ValueError):module.activity_windows(np.zeros((10,20,2)),np.ones(10,dtype=bool),25)
        with self.assertRaises(ValueError):module.activity_windows(np.full((10,21,2),np.nan),np.ones(10,dtype=bool),25)

    def test_candidate_reuse_does_not_grant_approval_or_claim_3d(self):
        module=self.module();row={'annotation_id':'test','label':'来','category':'word','sample_type':'step_instruction','source_window_seconds':[4,6], 'source_sha256':'a'*64,'hand_shape_note':'prior note','source_absolute_path':'source.mp4','source_id':'source','time_contract':'nominal only','anatomical_handedness':'unverified','mirror_status':'unknown'}
        out=module.candidate_record(row,50,25,{'left':[],'right':[]},{'left':[],'right':list(range(1,51))})
        self.assertFalse(out['human_approved']);self.assertFalse(out['model_training_ready']);self.assertEqual(out['text_verified'],'')
        self.assertFalse(out['native_3d_available']);self.assertFalse(out['word_boundaries_verified'])
        self.assertEqual(out['source_window_seconds'],[4,6])

if __name__=='__main__':unittest.main()
