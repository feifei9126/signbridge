"""Full-clip scopes and missing-hand fallbacks remain explicit, never fabricated tracks."""

import importlib.util
import unittest
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def load(name,relative):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class FullSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.align=load('full_align','src/tools/sign-mano-align.py')
        cls.stable=load('full_stable','src/tools/sign-stable-crop.py')
        cls.fixture=load('full_fixture','tests/sign-hand-refine.test.py')

    def test_full_scope_is_exact_two_clips_and_all_384_frame_ids(self):
        cases=self.align.hand.full_sequence_cases()
        self.assertEqual(len(cases),384)
        self.assertEqual([f for s,f,_ in cases if s=='pilot-greeting-hello-001'],list(range(1,167)))
        self.assertEqual([f for s,f,_ in cases if s=='pilot-hospital-cough-003'],list(range(1,219)))
        self.assertTrue(all(sides==('left','right') for _,_,sides in cases))

    def test_missing_and_ambiguous_hands_are_not_chosen_by_confidence(self):
        case={'hands':[{'side':'left','confidence':.9},{'side':'left','confidence':.8},
                       {'side':'right','confidence':.7}]}
        self.assertEqual(self.align.unique_observed_sides(case),('right',))
        self.assertEqual(self.align.unique_observed_sides({'hands':[]}),())

    def test_variable_observation_masks_preserve_complete_baseline_frames(self):
        source=self.fixture.parameters();records=[]
        for frame,sides in ((1,('left',)),(2,()),(3,('right',))):
            records.append({'frame_1based':frame,'fps':25.,'sides':sides,'baseline':source,
                            'candidate':{k:v.copy() for k,v in source.items()},
                            'decisions':{side:False for side in sides}})
        packed=self.align.pack_series(records,allow_variable_sides=True)
        np.testing.assert_array_equal(packed['observed_hand_mask'],[[True,False],[False,False],[False,True]])
        self.assertFalse(packed['candidate_applied_mask'].any())
        self.assertEqual(packed['candidate_body_pose'].shape,(3,21,3))
        records[1]['candidate']['right_hand_pose'][0,0]=.1
        with self.assertRaises(ValueError):
            self.align.pack_series(records,allow_variable_sides=True)

    def test_full_prior_allows_missing_hands_but_requires_complete_image_scope(self):
        cases=self.align.hand.full_sequence_cases()
        prior={'cases':[{'segment_id':s,'frame_1based':f,'output_relative':s+'/%06d'%f,
                         'required_sides':list(sides),'hands':[]} for s,f,sides in cases]}
        self.assertEqual(len(self.align.prior_case_index(prior,full_sequence=True)),384)
        prior['cases'].pop()
        with self.assertRaises(ValueError):
            self.align.prior_case_index(prior,full_sequence=True)

    def test_full_prior_still_rejects_invalid_side_and_unsafe_parameter_path(self):
        def prior():
            return {'cases':[{'segment_id':s,'frame_1based':f,'output_relative':s+'/%06d'%f,
                'required_sides':list(sides),'hands':[]} for s,f,sides in self.align.hand.full_sequence_cases()]}
        a=prior();a['cases'][0]['hands']=[{'side':'left','parameters_file':'../left-00.npz'}]
        with self.assertRaises(ValueError):self.align.prior_case_index(a,full_sequence=True)
        a=prior();a['cases'][0]['hands']=[{'side':'unknown','parameters_file':'unknown-00.npz'}]
        with self.assertRaises(ValueError):self.align.prior_case_index(a,full_sequence=True)

    def test_full_series_rejects_approval_for_an_unobserved_side_and_variable_fps(self):
        source=self.fixture.parameters()
        rows=[{'frame_1based':i,'fps':25.,'sides':(), 'baseline':source,
               'candidate':{k:v.copy() for k,v in source.items()},'decisions':{}} for i in (1,2)]
        rows[1]['decisions']['left']=True
        with self.assertRaises(ValueError):self.align.pack_series(rows,allow_variable_sides=True)
        rows[1]['decisions']={};rows[1]['fps']=30.
        with self.assertRaises(ValueError):self.align.pack_series(rows,allow_variable_sides=True)

    def test_coverage_crop_grows_about_same_center_and_never_shrinks(self):
        boxes=[[0.,0.,192.,256.],[4.,5.,192.,256.]]
        original=self.stable.stable_box(boxes)
        larger=self.stable.scaled_fixed_box(boxes,1.5)
        np.testing.assert_allclose(original[:2]+original[2:]/2,larger[:2]+larger[2:]/2)
        np.testing.assert_allclose(larger[2:],original[2:]*1.5)
        for scale in (.5,float('nan'),5.):
            with self.subTest(scale=scale),self.assertRaises(ValueError):
                self.stable.scaled_fixed_box(boxes,scale)

    def test_full_report_records_inference_scope_without_motion_approval(self):
        report=self.stable.report_contract(full_sequence=True)
        self.assertEqual(sum(len(ids) for ids in report['scope'].values()),384)
        self.assertTrue(report['full_sequence_inferred'])
        self.assertFalse(report['training_ready'])
        self.assertFalse(report['full_sequence_refined'])


if __name__=='__main__':
    unittest.main()
