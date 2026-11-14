import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-word-motion-library.py'


def module():
    spec = importlib.util.spec_from_file_location('word_motion_library', TOOL)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class WordMotionLibraryTests(unittest.TestCase):
    def test_candidate_windows_require_finite_ordered_source_time(self):
        tool = module()
        for window in [(-1, 2), (3, 2), (0, 12), (0, float('nan'))]:
            with self.assertRaises(ValueError):
                tool.valid_window(window, 10)
        self.assertEqual(tool.valid_window([1, 2.5], 10), [1.0, 2.5])

    def test_caption_is_not_split_into_arbitrarily_timed_word_actions(self):
        tool = module()
        source = {'sha256': 'a' * 64, 'path': '/source.mp4', 'batch': '1', 'duration_seconds': 50}
        row = {'text_candidate': '我们今天去医院看朋友', 'start_seconds': 3, 'end_seconds': 11,
               'observed_times': [4, 6, 8, 10], 'source_sha256': 'a' * 64}
        result = tool.caption_candidate(row, source, 'captions.jsonl')
        self.assertEqual(result['evidence_kind'], 'caption_context')
        self.assertFalse(result['materialize_requested'])
        self.assertEqual(result['word_spans'], [])
        self.assertFalse(result['native_3d_available'])
        self.assertEqual(result['source_window_seconds'], [3, 11])

    def test_caption_source_hash_mismatch_cannot_attach_wrong_video(self):
        tool = module()
        with self.assertRaises(ValueError):
            tool.caption_candidate({'text_candidate': '我', 'start_seconds': 1, 'end_seconds': 3,
                                    'source_sha256': 'b' * 64},
                                   {'sha256': 'a' * 64, 'duration_seconds': 10, 'path': '/v.mp4', 'batch': '2'}, 'x')

    def test_quoted_instruction_has_subunit_evidence_but_never_approval(self):
        tool = module()
        source = {'sha256': 'a' * 64, 'path': '/source.mp4', 'batch': '2', 'duration_seconds': 120}
        parent = {'annotation_id': 'hello', 'source_window_seconds': [4, 11.6], 'label': '你好',
                  'source_instruction_evidence': [
                      {'source_seconds': 7, 'instruction_text_raw': ['指向前面表示“你”']},
                      {'source_seconds': 8, 'instruction_text_raw': ['指向前面表示“你”']},
                      {'source_seconds': 10, 'instruction_text_raw': ['表示', '“好”']}],
                  'human_approved': True, 'training_ready': True}
        results = tool.instruction_candidates(parent, source, 'annotation.jsonl')
        you = next(r for r in results if r['proposed_text'] == '你')
        self.assertEqual(you['source_window_seconds'], [6.5, 8.5])
        self.assertEqual(you['text_verified'], '')
        self.assertFalse(you['human_approved'])
        self.assertFalse(you['training_ready'])
        self.assertFalse(you['word_boundaries_verified'])

    def test_unquoted_commentary_cannot_create_instructional_word_alignment(self):
        tool = module()
        parent = {'annotation_id': 'x', 'source_window_seconds': [0, 8],
                  'source_instruction_evidence': [{'source_seconds': 4, 'instruction_text_raw': ['今天我们要学习很多词语']}]}
        source = {'sha256': 'a' * 64, 'path': '/source.mp4', 'batch': '2', 'duration_seconds': 10}
        self.assertEqual(tool.instruction_candidates(parent, source, 'x'), [])

    def test_dedup_preserves_alternate_demonstrations_and_provenance(self):
        tool = module()
        base = {'proposed_text': '你好', 'source_sha256': 'a' * 64,
                'source_window_seconds': [0, 3], 'evidence': [{'path': 'one'}]}
        other = {**base, 'evidence': [{'path': 'two'}]}
        alternate = {**base, 'source_window_seconds': [10, 13]}
        result = tool.deduplicate_candidates([base, other, alternate])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]['evidence']), 2)

    def test_short_caption_remains_an_unapproved_coarse_window(self):
        tool = module()
        row = {'text_candidate': '我们', 'start_seconds': 3, 'end_seconds': 7,
               'observed_times': [4, 6], 'source_sha256': 'a' * 64}
        source = {'sha256': 'a' * 64, 'duration_seconds': 10, 'path': '/v.mp4', 'batch': '6'}
        candidate = tool.caption_candidate(row, source, 'caption.jsonl')
        self.assertEqual(candidate['evidence_kind'], 'caption_short_candidate')
        self.assertTrue(candidate['materialize_requested'])
        self.assertFalse(candidate['word_boundaries_verified'])
        self.assertFalse(candidate['human_approved'])
        self.assertFalse(candidate['model_training_ready'])

    def test_single_caption_sample_is_context_not_materialized_as_motion(self):
        tool = module()
        row = {'text_candidate': '谢谢', 'start_seconds': 4, 'end_seconds': 6,
               'observed_times': [5], 'source_sha256': 'a' * 64}
        source = {'sha256': 'a' * 64, 'duration_seconds': 10, 'path': '/v.mp4', 'batch': '6'}
        candidate = tool.caption_candidate(row, source, 'caption.jsonl')
        self.assertEqual(candidate['evidence_kind'], 'caption_short_unconfirmed')
        self.assertFalse(candidate['materialize_requested'])
        self.assertIn('single_caption_observation', candidate['review_flags'])

    def test_wide_sparse_caption_window_is_not_materialized_as_a_word_clip(self):
        tool = module()
        row = {'text_candidate': '我们', 'start_seconds': 3, 'end_seconds': 15,
               'observed_times': [4, 8, 12], 'source_sha256': 'a' * 64}
        source = {'sha256': 'a' * 64, 'duration_seconds': 20, 'path': '/v.mp4', 'batch': '5'}
        candidate = tool.caption_candidate(row, source, 'caption.jsonl')
        self.assertFalse(candidate['materialize_requested'])
        self.assertIn('coarse_window_too_wide_for_lexical_clip', candidate['review_flags'])

    def test_quoted_instruction_extracts_child_without_relabeling_parent_window(self):
        tool = module()
        source = {'sha256': 'a' * 64, 'path': '/source.mp4', 'batch': '2', 'duration_seconds': 120}
        parent = {'annotation_id': 'parent', 'label': '我很好', 'category': 'word',
                  'source_window_seconds': [95, 105],
                  'source_instruction_evidence': [
                      {'source_seconds': 96, 'instruction_text_raw': ['“我”就是用食指']},
                      {'source_seconds': 97, 'instruction_text_raw': ['指一下自己']}]}
        children = tool.instruction_candidates(parent, source, 'annotation.jsonl')
        self.assertEqual([item['proposed_text'] for item in children], ['我'])
        self.assertEqual(children[0]['source_window_seconds'], [95.5, 96.5])
        self.assertFalse(children[0]['word_boundaries_verified'])
        self.assertIn('instruction_timestamp_not_true_motion_onset', children[0]['review_flags'])

    def test_persistent_watermark_candidate_is_not_materialized(self):
        tool = module()
        rows = []
        for index, start in enumerate([0, 2, 4, 6]):
            row = {'source_sha256': 'a' * 64, 'source_batch': '4',
                   'proposed_text': '手语星球', 'source_window_seconds': [start, start + 2],
                   'evidence_kind': 'caption_short_candidate', 'materialize_requested': True,
                   'review_flags': [], 'evidence': []}
            rows.append(row)
        tool.suppress_persistent_overlays(rows, {'a' * 64: {'duration_seconds': 10}})
        self.assertTrue(all(not row['materialize_requested'] for row in rows))
        self.assertTrue(all('persistent_overlay_or_watermark_suspected' in row['review_flags'] for row in rows))

    def test_title_span_remains_a_sparse_candidate_with_source_evidence(self):
        tool = module()
        span = {'label_candidate': '我们', 'observed_times': [10, 11], 'start_seconds': 9.5,
                'end_seconds': 11.5, 'evidence': [{'source_seconds': 10, 'image_sha256': 'a' * 64}]}
        source = {'sha256': 'a' * 64, 'duration_seconds': 20, 'path': '/v.mp4', 'batch': '2'}
        candidate = tool.title_span_candidate(span, source, 'title-spans.json')
        self.assertTrue(candidate['materialize_requested'])
        self.assertEqual(candidate['evidence_kind'], 'title_span_candidate')
        self.assertFalse(candidate['word_boundaries_verified'])

    def test_excluded_source_classes_do_not_create_csl_word_candidates(self):
        tool = module()
        source = {'content_classes': ['non_sign_language'], 'path': '/v.mp4'}
        self.assertEqual(tool.source_scope(source), 'excluded_non_CSL_or_performative')
        source['content_classes'] = ['regional_natural_sign_candidate']
        self.assertEqual(tool.source_scope(source), 'regional_variant_candidate_separate')

    def test_native_pose_crop_requires_exact_video_hash_and_complete_window(self):
        tool = module()
        candidate = {'source_sha256': 'a' * 64, 'source_window_seconds': [2.0, 3.0]}
        poses = [[[float(frame), 0., 0.] for _ in range(55)] for frame in range(100)]
        sequence = {'source_sha256': 'a' * 64, 'source_window_seconds': [0.0, 4.0],
                    'sequence_uid': 'sequence', 'annotation_id': 'annotation',
                    'effective_pose_sha256': 'b' * 64,
                    'source_duration_seconds': 10.0,
                    'fps': 25.0, 'total_frames': 100, 'cpu_whole_window_technically_exportable': True,
                    'missing_native_frames_1based': [], 'effective_pose_verified': True}
        crop = tool.crop_native_pose_candidate(candidate, sequence, poses)
        self.assertIsNotNone(crop)
        self.assertEqual(crop['frames'], 25)
        self.assertIn('original source PTS equivalence not verified', crop['source_frame_mapping'])
        self.assertFalse(crop['word_alignment_verified'])
        self.assertIsNone(tool.crop_native_pose_candidate({**candidate, 'source_sha256': 'b' * 64}, sequence, poses))
        self.assertIsNone(tool.crop_native_pose_candidate(candidate, {**sequence, 'missing_native_frames_1based': [52]}, poses))

    def test_native_pose_crop_fails_closed_on_wrong_pose_shape_or_nonfinite(self):
        tool = module()
        candidate = {'source_sha256': 'a' * 64, 'source_window_seconds': [0., 1.]}
        sequence = {'source_sha256': 'a' * 64, 'source_window_seconds': [0., 2.],
                    'sequence_uid': 'sequence', 'annotation_id': 'annotation',
                    'effective_pose_sha256': 'b' * 64,
                    'source_duration_seconds': 10.0,
                    'fps': 25., 'total_frames': 50, 'cpu_whole_window_technically_exportable': True,
                    'missing_native_frames_1based': [], 'effective_pose_verified': True}
        with self.assertRaises(ValueError):
            tool.crop_native_pose_candidate(candidate, sequence, [[[0., 0., 0.]]])
        poses = [[[0., 0., 0.] for _ in range(55)] for _ in range(50)]
        poses[5][4][0] = float('nan')
        with self.assertRaises(ValueError):
            tool.crop_native_pose_candidate(candidate, sequence, poses)

    def test_per_source_index_binds_hashless_caption_rows_and_rejects_mismatch(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'caption-spans.json'
            path.write_text(json.dumps([{'text_candidate': '我'}]))
            entry = {'path': str(path), 'source_sha256': 'a' * 64}
            self.assertEqual(tool.bound_index_rows(entry)[0]['source_sha256'], 'a' * 64)
            path.write_text(json.dumps([{'source_sha256': 'b' * 64}]))
            with self.assertRaises(ValueError):
                tool.bound_index_rows(entry)

    def test_per_source_index_does_not_invent_a_hash_for_unbound_rows(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rows.json'
            path.write_text('[{"text_candidate":"你"}]')
            with self.assertRaises(ValueError):
                tool.bound_index_rows(str(path))

    def test_native_crop_rejects_a_window_that_extends_beyond_existing_fit(self):
        tool = module()
        candidate = {'source_sha256': 'a' * 64, 'source_window_seconds': [0., 2.04]}
        sequence = {'source_sha256': 'a' * 64, 'source_window_seconds': [0., 2.],
                    'sequence_uid': 's', 'annotation_id': 'a', 'effective_pose_sha256': 'b' * 64,
                    'source_duration_seconds': 3., 'fps': 25., 'total_frames': 50,
                    'cpu_whole_window_technically_exportable': True,
                    'effective_pose_verified': True, 'missing_native_frames_1based': []}
        poses = [[[0., 0., 0.] for _ in range(55)] for _ in range(50)]
        self.assertIsNone(tool.crop_native_pose_candidate(candidate, sequence, poses))

    def test_fingerspelling_tutorial_reference_stays_in_a_separate_scope(self):
        tool = module()
        row = {'annotation_id': 'a', 'source_sha256': 'a' * 64, 'label': 'A',
               'source_window_seconds': [1., 3.], 'category': 'finger_spelling'}
        source = {'sha256': 'a' * 64, 'path': '/source.mp4', 'batch': '2', 'duration_seconds': 10.}
        candidate = tool.tutorial_candidate(row, source, Path('/index.jsonl'))
        self.assertEqual(candidate['language_scope_status'], 'fingerspelling_candidate_separate')
        self.assertFalse(candidate['human_approved'])

    def test_recipe_preserves_bound_canonical_caption_and_teaching_indexes(self):
        tool = module()
        video = {'sha256': 'a' * 64, 'canonical_caption_span_paths': [
            '/captions/caption-spans.json', '/teaching/title-spans.json'],
            'caption_index_paths': ['/teaching/subtitle-reading.json']}
        recipe = tool.recipe_from_inventory({'videos': [video, video]}, '/inventory.json',
                                            '/dictionary.json', '/native.json', ['/tutorial.jsonl'])
        self.assertEqual(recipe['caption_indexes'], [{'path': '/captions/caption-spans.json', 'source_sha256': 'a' * 64}])
        self.assertEqual(len(recipe['title_span_indexes']), 1)
        self.assertEqual(len(recipe['subtitle_indexes']), 1)

    def test_lexical_coverage_does_not_count_context_as_a_native_word(self):
        tool = module()
        rows = [{'id': 'a', 'proposed_text': '你', 'native_3d_available': False,
                 'reference_clip': 'assets/a/clip.mp4'}]
        context = [{'id': 'b', 'proposed_text': '我们', 'native_3d_available': True}]
        coverage = tool.lexical_coverage(rows, context, [{'id': 'csl_we', 'gloss': '我们', 'texts': ['我们']}])
        we = next(r for r in coverage if r['label'] == '我们')
        self.assertEqual(we['candidate_count'], 0)
        self.assertEqual(we['native_candidate_count'], 0)
        self.assertEqual(we['context_only_count'], 1)
        self.assertFalse(we['training_ready'])
        self.assertEqual(we['gap'], 'no_standalone_candidate_video')

    def test_native_asset_records_unapproved_display_projection_not_full_smplx(self):
        tool = module()
        candidate = {'source_sha256': 'a' * 64, 'source_window_seconds': [0., 1.]}
        sequence = {'source_sha256': 'a' * 64, 'source_window_seconds': [0., 2.],
                    'sequence_uid': 's', 'annotation_id': 'a', 'effective_pose_sha256': 'b' * 64,
                    'source_duration_seconds': 3., 'fps': 25., 'total_frames': 50,
                    'cpu_whole_window_technically_exportable': True,
                    'effective_pose_verified': True, 'missing_native_frames_1based': []}
        asset = tool.crop_native_pose_candidate(candidate, sequence, [[[0., 0., 0.]] * 55] * 50)
        self.assertEqual(asset['text_verified'], '')
        self.assertEqual(asset['parameter_scope'], 'existing_effective_upper_body_display_projection')
        self.assertFalse(asset['full_native_smplx_parameters'])

    def test_manifest_verification_detects_changed_extra_and_escaping_files(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data.json').write_text('{}')
            (root / 'SHA256SUMS').write_text(tool.sha(root / 'data.json') + '  data.json\n')
            self.assertEqual(tool.verify_manifest(root)['files_verified'], 1)
            (root / 'extra.txt').write_text('unexpected')
            with self.assertRaises(ValueError):
                tool.verify_manifest(root)
            (root / 'extra.txt').unlink()
            (root / 'data.json').write_text('{"changed":true}')
            with self.assertRaises(ValueError):
                tool.verify_manifest(root)
            (root / 'SHA256SUMS').write_text('a' * 64 + '  ../outside.json\n')
            with self.assertRaises(ValueError):
                tool.verify_manifest(root)

    def test_temporal_metrics_use_rotation_geodesics_across_axis_angle_wrap(self):
        tool = module()
        import math
        poses = [[[0., 0., math.pi - .01]] * 55,
                 [[0., 0., -math.pi + .01]] * 55,
                 [[0., 0., -math.pi + .03]] * 55]
        metrics = tool.pose_quality(poses)
        self.assertLess(metrics['adjacent_rotation_degrees_max'], 2.)
        self.assertEqual(metrics['frames'], 3)

    def test_spatial_caption_keeps_its_observations_and_no_approval(self):
        tool = module()
        row = {'source_sha256': 'a' * 64, 'label_candidate': '我们',
               'start_seconds_nominal': 3., 'end_seconds_nominal': 5.,
               'sampled_seconds_nominal': [3.5, 4., 4.5], 'sample_interval_seconds': .5,
               'extraction_rule': 'left_panel_caption_candidate',
               'evidence': [{'source_seconds': 4., 'image_sha256': 'b' * 64}]}
        source = {'sha256': 'a' * 64, 'path': '/v.mp4', 'batch': '5', 'duration_seconds': 10.}
        candidate = tool.spatial_caption_candidate(row, source, '/spatial.jsonl')
        self.assertTrue(candidate['materialize_requested'])
        self.assertEqual(candidate['evidence'][0]['spatial_rule'], 'left_panel_caption_candidate')
        self.assertEqual(candidate['evidence'][0]['ocr_evidence'], row['evidence'])
        self.assertFalse(candidate['word_boundaries_verified'])

    def test_input_snapshots_are_content_addressed_and_exclude_original_videos(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            meta, video = root / 'input.json', root / 'original.mp4'
            meta.write_text('{}')
            video.write_bytes(b'video')
            out = root / 'output'
            out.mkdir()
            snapshots = tool.snapshot_inputs({str(meta): tool.sha(meta), str(video): tool.sha(video)}, out, {str(video)})
            self.assertEqual(set(snapshots), {str(meta)})
            self.assertEqual((out / snapshots[str(meta)]).read_text(), '{}')

    def test_effective_pose_identity_uses_batch_qualified_sequence_uid(self):
        tool = module()
        local_data = TOOL.parents[3] / 'local-data'
        # local-data is gitignored, so a clean checkout (CI) has none yet.
        local_data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_data, prefix='word-motion-test-') as folder:
            path = Path(folder) / 'pose.json'
            path.write_text(json.dumps({'id': 'batch--annotation', 'frames': 2, 'fps': 25.,
                                        'experimental': True, 'poses': [[[0., 0., 0.]] * 55] * 2}))
            sequence = {'sequence_uid': 'batch--annotation', 'annotation_id': 'annotation',
                        'total_frames': 2, 'fps': 25., 'effective_pose_path': str(path),
                        'effective_pose_sha256': tool.sha(path)}
            self.assertEqual(tool._load_effective_pose(sequence, {}, {}).shape, (2, 55, 3))

    def test_native_crop_rejects_unavailable_slots_inside_nominal_window(self):
        tool = module()
        candidate = {'source_sha256': 'a' * 64, 'source_window_seconds': [47.44, 47.6]}
        sequence = {'source_sha256': 'a' * 64, 'source_window_seconds': [41., 47.6],
                    'sequence_uid': 's', 'annotation_id': 'a', 'effective_pose_sha256': 'b' * 64,
                    'source_duration_seconds': 100., 'fps': 25., 'total_frames': 163,
                    'cpu_whole_window_technically_exportable': True,
                    'effective_pose_verified': True, 'missing_native_frames_1based': []}
        self.assertTrue(tool.crop_native_pose_candidate(candidate, sequence, [[[0., 0., 0.]] * 55] * 163) is None)

    def test_reused_tutorial_paths_reject_parent_and_absolute_paths(self):
        tool = module()
        source = {'sha256': 'a' * 64, 'path': '/s.mp4', 'batch': '2', 'duration_seconds': 10.}
        for relative in ['../outside.mp4', '/outside.mp4']:
            with self.assertRaises(ValueError):
                tool.tutorial_candidate({'label': '你', 'annotation_id': 'a', 'source_window_seconds': [1., 3.],
                    'artifacts': {'clip.mp4': {'relative_path': relative, 'sha256': 'b' * 64}}}, source, Path('/index.jsonl'))

    def test_completion_gate_rejects_failed_requests_but_allows_metadata_only(self):
        tool = module()
        row = {'id': 'a', 'materialize_requested': True, 'materialization_status': 'failed_preserved',
               'reference_clip': None}
        with self.assertRaises(ValueError):
            tool.require_complete_materialization([row])
        tool.require_complete_materialization([{**row, 'materialize_requested': False, 'materialization_status': 'metadata_only'}])

    def test_native_provenance_checks_unsampled_file_hash_metadata_and_manifest(self):
        tool = module()
        import numpy as np
        local_data = TOOL.parents[3] / 'local-data'
        # local-data is gitignored, so a clean checkout (CI) has none yet.
        local_data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_data, prefix='word-native-test-') as folder:
            root = Path(folder)
            for sub in ('smplx', 'meta'):
                (root / sub).mkdir()
            files = []
            for frame in range(1, 4):
                path = root / 'smplx' / f'{frame:05d}_0.npz'
                np.savez(path, **{key: np.zeros(shape, np.float32) for key, shape in tool.NATIVE_SHAPES.items()})
                meta = root / 'meta' / f'{frame:05d}_0.json'
                meta.write_text(json.dumps({'bbox_id': 0, 'img_path': f'/remote/annotation/images/{frame:06d}.jpg'}))
                files.extend([{'path': str(p), 'sha256': tool.sha(p)} for p in (path, meta)])
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(files))
            frames = root / 'frames.jsonl'
            frames.write_text(''.join(json.dumps({'frame_id': i, 'source_seconds_nominal': (i - 1)/25})+'\n' for i in range(1, 4)))
            evidence = {'annotation_id': 'annotation', 'sequence_uid': 'batch--annotation',
                        'fit_path': str(root), 'total_frames': 3, 'fps': 25., 'source_window_seconds': [0., .12],
                        'native_frame_count': 3, 'metadata_mapping_errors': [], 'missing_native_frames_1based': [],
                        'frozen_manifest_path': str(manifest), 'frozen_manifest_sha256': tool.sha(manifest),
                        'reference_frames_manifest': {'path': str(frames), 'sha256': tool.sha(frames)}}
            self.assertEqual(tool.verify_native_sequence(evidence, {})['frames_verified'], 3)
            with self.assertRaises(ValueError):
                tool.verify_native_sequence({**evidence, 'native_frame_count': 0}, {})
            with self.assertRaises(ValueError):
                tool.verify_native_sequence({**evidence, 'frozen_manifest_sha256': '0'*64}, {})
            middle = root / 'meta/00002_0.json'
            middle.write_text('{"bbox_id":1,"img_path":"/wrong.jpg"}')
            with self.assertRaises(ValueError):
                tool.verify_native_sequence(evidence, {})
            files[3]['sha256'] = tool.sha(middle)
            manifest.write_text(json.dumps(files))
            with self.assertRaises(ValueError):
                tool.verify_native_sequence({**evidence, 'frozen_manifest_sha256': tool.sha(manifest)}, {})
            (root / 'smplx/00002_0.npz').unlink()
            with self.assertRaises(ValueError):
                tool.verify_native_sequence(evidence, {})

    def test_legacy_timing_descriptor_uses_real_source_binding_and_verified_clip(self):
        tool = module()
        import subprocess
        local_data = TOOL.parents[3] / 'local-data'
        # local-data is gitignored, so a clean checkout (CI) has none yet.
        local_data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_data, prefix='word-legacy-test-') as folder:
            root = Path(folder)
            clip = root / 'clip.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'color=c=blue:s=32x32:r=25:d=0.12', '-an', str(clip)], check=True, capture_output=True)
            row = {'annotation_id': 'annotation', 'source_sha256': 'a' * 64,
                   'start_seconds': 1., 'end_seconds': 1.12, 'frames': 3, 'fps': 25.,
                   'clip': 'clip.mp4', 'clip_sha256': tool.sha(clip)}
            descriptor = root / 'sequences.jsonl'
            descriptor.write_text(json.dumps(row) + '\n')
            evidence = {'annotation_id': 'annotation', 'source_sha256': 'a' * 64,
                        'source_window_seconds': [1., 1.12], 'fps': 25., 'total_frames': 3,
                        'metadata_source_path': str(descriptor), 'reference_frames_manifest': None,
                        'metadata_source_sha256': tool.sha(descriptor),
                        'clip_timebase_verification': {'sha256': tool.sha(clip)}}
            result = tool.verify_legacy_timing(evidence, {})
            self.assertEqual(result['reference_clip_frames_decoded'], 3)
            self.assertFalse(result['original_input_jpeg_hashes_verified'])
            self.assertFalse(result['original_pts_measured'])
            with self.assertRaises(ValueError):
                tool.verify_legacy_timing({**evidence, 'source_sha256': 'b' * 64}, {})
            row['clip_sha256'] = '0' * 64
            descriptor.write_text(json.dumps(row) + '\n')
            with self.assertRaises(ValueError):
                tool.verify_legacy_timing(evidence, {})

    def test_verified_reuse_requires_same_id_source_window_and_clip_hash(self):
        tool = module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'clip.mp4').write_bytes(b'fixture')
            base = {'id': 'a', 'source_sha256': 'a'*64, 'source_window_seconds': [1., 2.],
                    'proposed_text': '你', 'reference_clip': 'clip.mp4', 'materialization_status': 'extracted_candidate',
                    'clip_sha256': tool.sha(root / 'clip.mp4')}
            target = {k: v for k, v in base.items() if k not in ('reference_clip', 'clip_sha256')}
            self.assertTrue(tool.attach_verified_reuse(target, {'a': base}, root))
            self.assertEqual(target['_reuse_clip']['sha256'], base['clip_sha256'])
            with self.assertRaises(ValueError):
                tool.attach_verified_reuse({**target, 'source_window_seconds': [1., 3.]}, {'a': base}, root)

    def test_low_confidence_caption_keeps_relaxed_threshold_warning_and_raw_evidence(self):
        tool = module()
        row = {'text_candidate': '我', 'start_seconds': 1., 'end_seconds': 3.,
               'observed_times': [1.5, 2.], 'spatial_rule_thresholds_relaxed_locally': True,
               'ocr_confidence_min': .3, 'evidence': [{'image_sha256': 'b'*64}]}
        source = {'sha256': 'a'*64, 'path': '/v.mp4', 'batch': '5', 'duration_seconds': 5.}
        result = tool.caption_candidate(row, source, '/index.json')
        self.assertIn('raw_ocr_retained_below_generic_confidence_or_margin_gate', result['review_flags'])
        self.assertEqual(result['evidence'][0]['ocr_evidence'], row['evidence'])
        self.assertEqual(result['evidence'][0]['ocr_confidence_min'], .3)


if __name__ == '__main__':
    unittest.main()
