"""Tutorial annotations retain observed evidence without inventing hand truth."""
import importlib.util
import json
import tempfile
import shutil
import subprocess
from types import SimpleNamespace
from unittest import mock
import unittest
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'src/tools/sign-tutorial-reference.py'


class TutorialReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = importlib.util.spec_from_file_location('tutorial_reference', SCRIPT)
        cls.m = importlib.util.module_from_spec(s)
        s.loader.exec_module(cls.m)

    def example(self):
        return {'annotation_id': 'tutorial-greeting-001', 'source_id': 'tutorial-source-01',
                'start_seconds': 1., 'end_seconds': 4., 'label': '你好',
                'sample_type': 'step_instruction', 'label_evidence': 'title_and_visible_demonstration',
                'boundary_review': 'assistant_visual', 'mirror_status': 'unknown',
                'hand_shape_note': '食指指向镜头，再伸拇指；视频中的分步讲解',
                'signer_identity': 'unconfirmed', 'human_approved': False}

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
    def test_portrait_reference_with_odd_scaled_width_encodes_even_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'portrait.mkv';output=root/'clip.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc=size=317x563:rate=25',
                '-t','0.2','-c:v','ffv1','-pix_fmt','bgr0',str(source)],check=True,capture_output=True)
            self.m.extract_reference_clip(source,output,0.,.2)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=width,height,nb_frames,r_frame_rate','-of','json',str(output)]))['streams'][0]
            self.assertEqual(probe['width']%2,0)
            self.assertEqual(probe['height']%2,0)
            self.assertEqual(probe['r_frame_rate'],'25/1')
            self.assertEqual(int(probe['nb_frames']),5)

    def test_assistant_labels_are_not_promoted_to_human_approval(self):
        r = self.m.validate_annotation(self.example(), 10.)
        self.assertFalse(r['human_approved'])
        self.assertFalse(r['training_ready'])
        self.assertEqual(r['annotator'], 'assistant_visual_review')
        self.assertEqual(r['mirror_status'], 'unknown')

    def test_instruction_and_complete_demonstration_remain_distinct(self):
        for kind in ('step_instruction','complete_demonstration','continuous_narrative','theory'):
            r = self.m.validate_annotation({**self.example(),'sample_type':kind}, 10.)
            self.assertEqual(r['sample_type'],kind)
        with self.assertRaises(ValueError):
            self.m.validate_annotation({**self.example(),'sample_type':'auto_training_pair'},10.)

    def test_invalid_ids_boundaries_missing_evidence_or_false_approval_rejected(self):
        for change in ({'annotation_id':'../escape'},{'start_seconds':float('nan')},
                       {'start_seconds':-1},{'end_seconds':12},{'end_seconds':1},
                       {'label_evidence':''},{'human_approved':True},{'mirror_status':'auto_normal'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.m.validate_annotation({**self.example(),**change},10.)

    def test_missing_or_unknown_review_provenance_cannot_claim_visual_review(self):
        for boundary in (None, 'unreviewed', 'automatic_other'):
            with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                self.m.validate_annotation({**self.example(), 'boundary_review': boundary}, 10.)

    def test_missing_label_and_nontext_evidence_rejected(self):
        for change in ({'label': ''}, {'label': None}, {'label_evidence': None},
                       {'label_evidence': ['caption']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.m.validate_annotation({**self.example(), **change}, 10.)

    def test_empty_reference_plan_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / 'originals'
            source_root.mkdir()
            manifest = root / 'sources.json'
            manifest.write_text(json.dumps({'source_root': str(source_root), 'sources': []}))
            annotations = root / 'annotations.jsonl'
            annotations.write_text('')
            output = root / 'result'
            with self.assertRaises(ValueError):
                self.m.build(SimpleNamespace(manifest=manifest, annotations=annotations, output=output))
            self.assertFalse(output.exists())

    def test_source_digest_change_prevents_all_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / 'originals'
            source_root.mkdir()
            source = source_root / 'video.mp4'
            source.write_bytes(b'changed-source')
            manifest = root / 'sources.json'
            manifest.write_text(json.dumps({'source_root': str(source_root), 'sources': [{
                'source_id': 'tutorial-source-01', 'relative_path': 'video.mp4',
                'duration_seconds': 10., 'authorization_status': 'user_reported', 'sha256': 'a' * 64}]}))
            annotations = root / 'annotations.jsonl'
            annotations.write_text(json.dumps(self.example()) + '\n')
            output = root / 'result'
            with mock.patch.object(self.m.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'hash changed'):
                    self.m.build(SimpleNamespace(manifest=manifest, annotations=annotations, output=output))
                run.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b'changed-source')

    def test_existing_delivery_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / 'originals'
            source_root.mkdir()
            manifest = root / 'sources.json'
            manifest.write_text(json.dumps({'source_root': str(source_root), 'sources': []}))
            annotations = root / 'annotations.jsonl'
            annotations.write_text(json.dumps(self.example()) + '\n')
            output = root / 'result'
            output.mkdir()
            evidence = output / 'evidence.txt'
            evidence.write_text('preserve-me')
            with self.assertRaisesRegex(ValueError, 'new output'):
                self.m.build(SimpleNamespace(manifest=manifest, annotations=annotations, output=output))
            self.assertEqual(evidence.read_text(), 'preserve-me')

    def test_failed_candidate_is_quarantined_without_temporary_overlay_and_manifested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / '.staging' / 'tutorial-greeting-001'
            staging.mkdir(parents=True)
            (staging / 'clip.mp4').write_bytes(b'partial clip')
            (staging / 'overlay-working.avi').write_bytes(b'temporary overlay')
            (staging / 'landmarks.npz').write_bytes(b'partial points')

            record = self.m.preserve_failed_candidate(
                root, 'tutorial-greeting-001', staging, RuntimeError('synthetic extractor failure'))

            failed = root / 'failed-candidates' / 'tutorial-greeting-001'
            self.assertFalse((root / 'samples' / 'tutorial-greeting-001').exists())
            self.assertTrue((failed / 'clip.mp4').is_file())
            self.assertTrue((failed / 'landmarks.npz').is_file())
            self.assertFalse((failed / 'overlay-working.avi').exists())
            self.assertTrue(record['temporary_overlay_removed'])
            self.assertFalse(record['completed'])
            manifest = [json.loads(line) for line in (root / 'failures.jsonl').read_text().splitlines()]
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]['annotation_id'], 'tutorial-greeting-001')
            self.assertEqual(manifest[0]['error_type'], 'RuntimeError')

    def test_successful_candidate_is_published_atomically_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / '.staging' / 'tutorial-greeting-001'
            staging.mkdir(parents=True)
            artifact = staging / 'clip.mp4'
            artifact.write_bytes(b'complete')

            published = self.m.publish_staged_candidate(
                root, 'tutorial-greeting-001', staging)

            self.assertEqual(published, (root / 'samples' / 'tutorial-greeting-001').resolve())
            self.assertEqual((published / 'clip.mp4').read_bytes(), b'complete')
            self.assertFalse(staging.exists())
            with self.assertRaisesRegex(ValueError, 'already exists'):
                self.m.publish_staged_candidate(root, 'tutorial-greeting-001', staging)

    def test_duplicate_hand_observations_are_masked_not_swapped(self):
        left=np.repeat(np.array([[.4,.4,0.]],dtype=np.float32),21,axis=0)
        left[[5,9,13,17],0]+=.04
        right=left.copy()
        result=self.m.reference_hand_flags(left,right,True,True,1280,720)
        self.assertFalse(result['left']['eligible_for_2d_fit'])
        self.assertFalse(result['right']['eligible_for_2d_fit'])
        self.assertEqual(result['reason'],'overlapping_hand_observations')
        np.testing.assert_array_equal(left,right)

    def test_missing_side_does_not_fill_keypoints(self):
        left=np.full((21,3),np.nan,dtype=np.float32)
        right=np.zeros((21,3),dtype=np.float32);right[:,:2]=.5;right[[5,9,13,17],0]+=.06
        result=self.m.reference_hand_flags(left,right,False,True,1280,720)
        self.assertFalse(result['left']['eligible_for_2d_fit'])
        self.assertTrue(result['right']['eligible_for_2d_fit'])
        self.assertTrue(np.isnan(left).all())

    def test_reference_flags_reject_nonboolean_and_invalid_shape(self):
        p=np.zeros((21,3),dtype=np.float32)
        with self.assertRaises(ValueError):self.m.reference_hand_flags(p,p,1,True,1280,720)
        with self.assertRaises(ValueError):self.m.reference_hand_flags(p[:10],p,True,True,1280,720)

    def test_caption_index_distinguishes_title_and_instruction(self):
        def row(t,title,subtitle):
            return {'source_seconds_nominal':t,'image':'frame.jpg','image_sha256':'a'*64,'lines':[
                {'text':title,'bounding_box':[.3,.82,.3,.06],'confidence':.5},
                {'text':subtitle,'bounding_box':[.1,.1,.8,.06],'confidence':.9},
                {'text':'bilibili','bounding_box':[.02,.93,.25,.04],'confidence':.5}]}
        rows=[row(4.,'你好','伸出食指'),row(5.,'你好','再伸拇指'),row(7.,'再见','手掌摆动'),row(8.,'再见','手掌摆动')]
        spans=self.m.title_spans(rows,10.,1.)
        self.assertEqual([s['label_candidate'] for s in spans],['你好','再见'])
        self.assertEqual(spans[0]['start_seconds'],3.5)
        self.assertFalse(spans[0]['human_approved'])
        self.assertEqual(spans[0]['boundary_status'],'sparse_caption_window')
        self.assertTrue(all('bilibili' not in s['label_candidate'] for s in spans))

    def test_single_sparse_observation_does_not_become_a_demonstration(self):
        rows=[{'source_seconds_nominal':4.,'image':'a.jpg','image_sha256':'a'*64,
               'lines':[{'text':'你好','bounding_box':[.3,.8,.3,.08],'confidence':1.}]}]
        self.assertEqual(self.m.title_spans(rows,10.,1.),[])

    def test_indexed_candidates_do_not_claim_assistant_visual_verification(self):
        r=self.m.validate_annotation({**self.example(),'sample_type':'word_candidate',
            'boundary_review':'sparse_ocr_window','label_evidence':'sampled_ocr_title'},10.)
        self.assertEqual(r['annotator'],'automatic_caption_index')
        self.assertFalse(r['human_approved'])


if __name__=='__main__':
    unittest.main()
