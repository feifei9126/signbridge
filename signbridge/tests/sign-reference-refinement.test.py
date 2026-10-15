import importlib.util
from pathlib import Path
import json
import tempfile
import unittest

import numpy as np

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-reference-refinement.py'
spec = importlib.util.spec_from_file_location('reference_refinement', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RefinementTests(unittest.TestCase):
    def example(self):
        return {'annotation_id':'source-a-cap-0001','revision_of_annotation_id':'source-a-cap-0001',
                'source_id':'source-a','source_sha256':'a'*64,'label':'建议文字', 'text_verified':'',
                'start_seconds':12.,'end_seconds':13.,'frames':25,'fps':25.,
                'human_approved':False,'semantics_approved':False,'boundaries_approved':False,
                'training_ready':False,'model_training_ready':False,'smplx_parameters_created':False,
                'mirror_status':'unknown','language':'unconfirmed','split':'unassigned',
                'boundary_review':'assistant_visual_coarse','boundary_note':'Visible repeat; coarse bounds.',
                'previous_label_candidate':'旧文字','previous_window_seconds':[1.,2.],
                'visual_evidence':{'path':'sheet.jpg','sha256':'c'*64}}

    def test_revision_preserves_empty_verified_text_and_explicit_coarse_provenance(self):
        value = module.validate_revision(self.example(), {'annotation_id':'source-a-cap-0001',
            'source_id':'source-a','source_sha256':'a'*64,'label':'旧文字','start_seconds':1.,'end_seconds':2.}, 20.)
        self.assertEqual(value['label'], '建议文字')
        self.assertEqual(value['text_verified'], '')
        self.assertFalse(value['human_approved'])

    def test_false_approvals_wrong_origin_or_out_of_range_revisions_rejected(self):
        old = {'annotation_id':'source-a-cap-0001','source_id':'source-a','source_sha256':'a'*64,
               'label':'旧文字','start_seconds':1.,'end_seconds':2.}
        for change in [{'human_approved':True},{'semantics_approved':True},{'text_verified':'假核验'},
                       {'training_ready':True},{'source_sha256':'b'*64},{'previous_window_seconds':[2.,3.]},
                       {'end_seconds':21.},{'start_seconds':float('nan')},{'boundary_review':'approved'},
                       {'revision_of_annotation_id':'other'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.validate_revision({**self.example(),**change}, old, 20.)

    def test_coverage_uses_actual_same_frame_masks_and_keeps_single_hand_valid(self):
        left = np.full((4,21,3),np.nan,np.float32)
        right = np.full((4,21,3),np.nan,np.float32)
        right[1:3] = .5
        right[1:3,[5,9,13,17],0] += .05
        value = module.observation_coverage(left,right,np.zeros(4,bool),np.array([False,True,True,False]),540,960)
        self.assertEqual(value['any_hand_detected_frames'],2)
        self.assertEqual(value['both_hands_detected_frames'],0)
        self.assertEqual(value['eligible_frames']['right'],2)
        self.assertFalse(value['anatomical_handedness_verified'])
        self.assertTrue(np.isnan(left).all())
        with self.assertRaises(ValueError):
            module.observation_coverage(left,right,np.ones(4,bool),np.ones(4,bool),540,960)

    def test_package_checksums_are_written_before_existing_runner_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'clips').mkdir();clip=root/'clips/clip.mp4';clip.write_bytes(b'placeholder-video')
            row={**self.example(),'clip':'clips/clip.mp4','clip_sha256':module.data.sha256_file(clip)}
            cases=module.sequence.build_case_records([row],[])
            (root/'sequences.jsonl').write_text(json.dumps(cases[0])+'\n')
            (root/'keyframes.jsonl').write_text('')
            (root/'manifest.json').write_text(json.dumps({'schema':'signbridge-smplerx-candidate-sequences-v1',
                'sequence_count':1,'keyframe_count':0,'training_ready':False,'training_started':False}))
            module.seal_candidate_package(root)
            self.assertTrue((root/'SHA256SUMS').is_file())
            clip.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                module.sequence.validate_package(root)


if __name__ == '__main__':
    unittest.main()
