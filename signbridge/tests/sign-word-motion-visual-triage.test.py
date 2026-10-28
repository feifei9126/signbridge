"""Real generated image fixtures for the CPU-only, non-semantic triage sidecar."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np


TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-word-motion-visual-triage.py'


def module():
    assert TOOL.is_file(), 'The visual triage tool has not been implemented'
    spec = importlib.util.spec_from_file_location('word_motion_visual_triage', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class VisualTriageTests(unittest.TestCase):
    def setUp(self):
        base = os.environ.get('SIGNBRIDGE_TRIAGE_TEST_TMPDIR')
        self.temp = tempfile.TemporaryDirectory(prefix='visual-triage-fixture-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'candidates'
        self.inputs.mkdir()

    def candidate(self, levels=(0, 0, 0), title=False, identifier='fixture'):
        folder = self.inputs / 'assets' / identifier
        folder.mkdir(parents=True)
        clip = folder / 'clip.mp4'
        clip.write_bytes(b'Unmodified reference bytes; contact-sheet mode never decodes video.')
        cells = []
        for level in levels:
            cell = np.full((312, 320, 3), 245, np.uint8)
            image = np.full((240, 320, 3), level, np.uint8)
            if title:
                cv2.putText(image, 'TITLE ONLY', (35, 125), cv2.FONT_HERSHEY_SIMPLEX,
                            .8, (255, 255, 255), 2)
            cell[20:260, :320] = image
            cv2.putText(cell, 'frame / nominal time', (10, 300),
                        cv2.FONT_HERSHEY_SIMPLEX, .4, (30, 30, 30), 1)
            cells.append(cell)
        sheet = folder / 'keyframes.jpg'
        self.assertTrue(cv2.imwrite(str(sheet), np.hstack(cells)))
        return {'id': identifier, 'proposed_text': '我', 'source_sha256': 'a' * 64,
                'source_window_seconds': [10.25, 11.25], 'source_pts_measured': False,
                'reference_clip': str(clip.relative_to(self.inputs)),
                'keyframes': str(sheet.relative_to(self.inputs)),
                'keyframes_sha256': digest(sheet), 'clip_sha256': digest(clip),
                'decoded_video': {'width': 640, 'height': 480, 'frames': 25, 'fps': 25.0},
                'selected_keyframes_1based': [6, 13, 20],
                'evidence_kind': 'title_span_candidate' if title else 'caption_short_candidate',
                'human_approved': False, 'training_ready': False, 'model_training_ready': False,
                'semantics_approved': False, 'word_boundaries_verified': False, 'word_spans': [],
                'native_asset': None, 'review_flags': ['source_flag_preserved']}

    def report(self, rows):
        path = self.inputs / 'report.json'
        path.write_text(json.dumps({'summary': {'candidates': len(rows), 'materialized': len(rows),
                                               'failures': 0}, 'candidates': rows}))
        return path

    def test_black_frames_exclude_light_contact_padding_and_timestamp_footer(self):
        tool = module()
        row = self.candidate()
        before = copy.deepcopy(row)
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('off'))
        self.assertIn('dark_or_blank_keyframes', result['risk_flags'])
        self.assertEqual(result['dark_or_blank_keyframe_count'], 3)
        for image in result['keyframes']:
            self.assertLess(image['metrics']['mean_luma_0_255'], 1)
            self.assertGreater(image['metrics']['dark_fraction'], .99)
            self.assertEqual(image['contact_sheet_crop_xywh'][1:], [20, 320, 240])
            self.assertEqual(len(image['decoded_bgr_sha256']), 64)
        self.assertEqual(row, before)

    def test_generated_title_slide_is_review_risk_never_semantic_rejection(self):
        tool = module()
        row = self.candidate(title=True)
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('haar'))
        self.assertIn('teaching_title_or_static_scene_review_risk', result['risk_flags'])
        self.assertIn('signer_visibility_not_confirmed_by_face_detector', result['risk_flags'])
        self.assertFalse(result['automatic_rejection'])
        self.assertFalse(result['verified_action'])
        self.assertEqual(result['signer_visibility_status'], 'unknown')
        self.assertTrue(all(k['face_detection']['face_count'] == 0 for k in result['keyframes']))

    def test_missing_sheet_fails_closed_without_synthetic_zero_metrics(self):
        tool = module()
        row = self.candidate()
        (self.inputs / row['keyframes']).unlink()
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('haar'))
        self.assertEqual(result['status'], 'technical_evidence_unavailable')
        self.assertIn('keyframe_evidence_missing_or_unreadable', result['risk_flags'])
        self.assertIsNone(result['dark_or_blank_keyframe_count'])
        self.assertTrue(all(k['metrics'] is None for k in result['keyframes']))
        self.assertTrue(all(k['face_detection']['face_count'] is None for k in result['keyframes']))
        self.assertFalse(result['verified_action'])

    def test_corrupt_sheet_is_unknown_and_never_an_all_black_image(self):
        tool = module()
        row = self.candidate()
        path = self.inputs / row['keyframes']
        path.write_bytes(b'Not an image')
        row['keyframes_sha256'] = digest(path)
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('haar'))
        self.assertEqual(result['status'], 'technical_evidence_unavailable')
        self.assertIsNone(result['dark_or_blank_keyframe_count'])
        self.assertNotIn('dark_or_blank_keyframes', result['risk_flags'])

    def test_sheet_hash_mismatch_cannot_be_used_as_bound_evidence(self):
        tool = module()
        row = self.candidate()
        row['keyframes_sha256'] = 'b' * 64
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('off'))
        self.assertIn('keyframe_hash_mismatch', result['risk_flags'])
        self.assertTrue(all(k['metrics'] is None for k in result['keyframes']))

    def test_no_face_from_real_haar_is_unknown_not_proof_of_no_person(self):
        tool = module()
        detector = tool.FaceDetector('haar')
        detection = detector.detect(np.full((240, 320), 180, np.uint8))
        self.assertEqual(detection['face_count'], 0)
        self.assertEqual(detection['status'], 'unknown_no_face_detection')
        self.assertFalse(detection['person_absence_proven'])
        self.assertFalse(detection['signer_identity_verified'])
        self.assertFalse(cv2.ocl.useOpenCL())
        self.assertEqual(detector.metadata()['execution_device'], 'cpu')

    def test_disabled_face_detector_uses_null_not_a_fake_zero_detection(self):
        tool = module()
        row = self.candidate((150, 150, 150))
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('off'))
        self.assertTrue(all(k['face_detection']['face_count'] is None for k in result['keyframes']))
        self.assertIn('signer_visibility_not_confirmed_by_face_detector', result['risk_flags'])

    def test_fade_luma_change_does_not_create_any_new_word_bounds(self):
        tool = module()
        row = self.candidate((5, 90, 180))
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('off'))
        self.assertIn('fade_or_transition_keyframes_review_risk', result['risk_flags'])
        self.assertEqual(result['source_window_seconds'], row['source_window_seconds'])
        self.assertEqual(result['selected_keyframes_1based'], [6, 13, 20])
        self.assertEqual([k['source_seconds_nominal'] for k in result['keyframes']],
                         [10.45, 10.73, 11.01])
        self.assertFalse(result['word_boundaries_verified'])
        self.assertFalse(result['verified_action'])

    def test_wrong_sheet_layout_does_not_guess_cells(self):
        tool = module()
        row = self.candidate()
        path = self.inputs / row['keyframes']
        cv2.imwrite(str(path), np.full((100, 100, 3), 255, np.uint8))
        row['keyframes_sha256'] = digest(path)
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('off'))
        self.assertIn('unsupported_contact_sheet_layout', result['risk_flags'])
        self.assertTrue(all(k['metrics'] is None for k in result['keyframes']))

    def test_paths_cannot_escape_candidate_root(self):
        tool = module()
        row = self.candidate()
        row['keyframes'] = '../outside.jpg'
        result = tool.analyze_candidate(row, self.inputs, tool.FaceDetector('off'))
        self.assertEqual(result['status'], 'technical_evidence_unavailable')

    def test_build_writes_every_id_hashes_report_and_preserves_all_inputs(self):
        tool = module()
        rows = [self.candidate(identifier='dark'), self.candidate((160, 160, 160), identifier='bright')]
        report = self.report(rows)
        before = {str(p): digest(p) for p in self.inputs.rglob('*') if p.is_file()}
        output = self.root / 'sidecar'
        result = tool.build_report(report, output, expected_count=2, face_detector='haar')
        self.assertEqual(result['summary']['candidates_examined'], 2)
        self.assertEqual(result['summary']['keyframes_examined'], 6)
        self.assertTrue(result['input_tree_unchanged'])
        self.assertEqual(result['source_report']['sha256'], digest(report))
        self.assertEqual(result['results']['sha256'], digest(output / 'triage.jsonl'))
        self.assertEqual({r['id'] for r in map(json.loads, (output/'triage.jsonl').read_text().splitlines())}, {'dark', 'bright'})
        self.assertEqual(before, {str(p): digest(p) for p in self.inputs.rglob('*') if p.is_file()})
        with self.assertRaises(FileExistsError):
            tool.build_report(report, output, expected_count=2)

    def test_incomplete_report_or_wrong_count_is_rejected(self):
        tool = module()
        path = self.report([self.candidate()])
        with self.assertRaises(ValueError):
            tool.build_report(path, self.root/'wrong-count', expected_count=2)
        value = json.loads(path.read_text())
        value['summary']['materialized'] = 0
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            tool.build_report(path, self.root/'unfinished', expected_count=1)

    def test_hash_bound_visual_observation_remains_unapproved(self):
        tool = module()
        row = self.candidate()
        path = self.report([row])
        observations = self.root/'assistant-observations.json'
        observations.write_text(json.dumps({'samples': [{'id':row['id'],
            'contact_sheet_sha256':row['keyframes_sha256'],
            'observation':'Lowered hands during a fade; not a verified sign action.'}]}))
        output = self.root/'observed'
        tool.build_report(path,output,expected_count=1,face_detector='off',observations_path=observations)
        result = json.loads((output/'triage.jsonl').read_text().splitlines()[0])
        self.assertIn('external_visual_observation_requires_review',result['risk_flags'])
        self.assertFalse(result['verified_action'])
        self.assertFalse(result['semantics_approved'])
        self.assertEqual(result['external_visual_observation']['file_sha256'],digest(observations))


if __name__ == '__main__':
    unittest.main()
