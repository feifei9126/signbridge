"""Extract private evidence-bound word/phrase candidates; never invent word alignment."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

import cv2
import numpy as np


SCHEMA = 'signbridge-word-motion-expansion-v1'
SHORT_TEXT = re.compile(r'[\u3400-\u9fff]{1,6}')
QUOTED = r'[“「『\"‘\']([\u3400-\u9fff]{1,6})[”」』\"’\']'
NOISE = re.compile(r'传课|专课|中国航天|中国所天|复旦音像|bilibili|圣杯|字幕|关注|点赞|转发|评论|三连|第.{0,3}课|再看一遍|完整演示|逐个解析|伸出|弯曲|掌心|拇指|食指|中指|无名指|小指|手心|手背|双手|向前|向后|向上|向下|表示疑问', re.I)
EXCLUDED = re.compile(r'美国手语|美式手语|香港手语|日本手语|国际手语|手语舞|歌曲|法语入门|感恩的心|手势舞|健身操', re.I)
EXCLUDED_CLASSES = {'cross_language_or_international_unconfirmed', 'song_or_choreography_candidate',
                    'handshape_or_alphabet_reference', 'explanation_or_service_unconfirmed',
                    'commentary_or_meta', 'non_sign_language', 'asl_separate',
                    'interpreted_program_holdout', 'performative_or_song'}
NATIVE_SHAPES = {'global_orient': (1, 3), 'body_pose': (21, 3),
                 'left_hand_pose': (15, 3), 'right_hand_pose': (15, 3),
                 'jaw_pose': (1, 3), 'leye_pose': (1, 3), 'reye_pose': (1, 3),
                 'betas': (1, 10), 'expression': (1, 10), 'transl': (1, 3)}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read_rows(path):
    path = Path(path)
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    value = json.loads(path.read_text())
    return value if isinstance(value, list) else value.get('videos', value.get('candidates', value.get('items', [])))


def index_path(entry):
    return Path(entry['path'] if isinstance(entry, dict) else entry).resolve()


def bound_index_rows(entry):
    """Per-source JSON rows inherit only the inventory's verified file→SHA join."""
    bound_sha = entry.get('source_sha256') if isinstance(entry, dict) else None
    result = []
    for row in read_rows(index_path(entry)):
        digest = row.get('source_sha256') or bound_sha
        if not digest or (bound_sha and digest != bound_sha):
            raise ValueError('Index source SHA-256 missing or conflicts with inventory binding')
        result.append({**row, 'source_sha256': digest})
    return result


def recipe_from_inventory(inventory, inventory_path, dictionary, native_map, tutorials):
    groups = {key: {} for key in ('caption_indexes', 'title_span_indexes', 'subtitle_indexes')}
    for source in inventory['videos']:
        for name in source.get('canonical_caption_span_paths', []):
            key = 'title_span_indexes' if Path(name).name == 'title-spans.json' else 'caption_indexes'
            previous = groups[key].get(name)
            if previous and previous['source_sha256'] != source['sha256']:
                raise ValueError('One caption file maps to conflicting video hashes')
            groups[key][name] = {'path': name, 'source_sha256': source['sha256']}
        for name in source.get('caption_index_paths', []):
            if Path(name).name == 'subtitle-reading.json':
                groups['subtitle_indexes'][name] = {'path': name, 'source_sha256': source['sha256']}
    spatial = sorted({name for source in inventory['videos'] for name in source.get('caption_index_paths', [])
                      if Path(name).name == 'caption-candidates.jsonl'})
    return {'schema': SCHEMA, 'video_inventory': str(inventory_path), 'spatial_caption_indexes': spatial,
            'dictionary_lexicon': str(dictionary), 'native_motion_map': str(native_map),
            'tutorial_indexes': list(map(str, tutorials)),
            **{key: [values[name] for name in sorted(values)] for key, values in groups.items()}}


def valid_window(window, duration):
    if (not isinstance(window, (list, tuple)) or len(window) != 2
            or not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in window)
            or not isinstance(duration, (float, int)) or not math.isfinite(duration)
            or not 0 <= window[0] < window[1] <= duration):
        raise ValueError('Invalid nominal source window')
    return [float(window[0]), float(window[1])]


def normalize_text(text):
    return re.sub(r'[\s，。！？、：；,.!?;:]+', '', text)


def source_scope(source):
    classes = set(source.get('content_classes') or [])
    if classes & EXCLUDED_CLASSES or EXCLUDED.search(source.get('path', '')):
        return 'excluded_non_CSL_or_performative'
    if 'regional_natural_sign_candidate' in classes:
        return 'regional_variant_candidate_separate'
    if 'fingerspelling_separate' in classes:
        return 'fingerspelling_candidate_separate'
    return 'CSL_source_scope_unconfirmed'


def crop_native_pose_candidate(candidate, sequence, poses):
    """Crop an existing verified continuous fit as an unaligned preview candidate."""
    if (candidate.get('source_sha256') != sequence.get('source_sha256')
            or sequence.get('cpu_whole_window_technically_exportable') is not True
            or sequence.get('effective_pose_verified') is not True
            or sequence.get('missing_native_frames_1based')):
        return None
    candidate_window = valid_window(candidate.get('source_window_seconds'), sequence['source_duration_seconds'])
    sequence_window = valid_window(sequence.get('source_window_seconds'), sequence['source_duration_seconds'])
    fps = sequence.get('fps')
    if not isinstance(fps, (float, int)) or isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
        return None
    poses = np.asarray(poses)
    if poses.ndim != 3 or poses.shape[1:] != (55, 3) or not np.isfinite(poses).all():
        raise ValueError('Existing effective SMPL-X pose array has an invalid shape or nonfinite values')
    if len(poses) != sequence.get('total_frames'):
        raise ValueError('Existing native pose sequence length differs from its audited frame count')
    tolerance = 1e-8
    if candidate_window[0] < sequence_window[0] - tolerance or candidate_window[1] > sequence_window[1] + tolerance:
        return None
    start_index = math.floor((candidate_window[0] - sequence_window[0]) * fps + 1e-8)
    end_index = math.ceil((candidate_window[1] - sequence_window[0]) * fps - 1e-8)
    if start_index < 0 or end_index > len(poses):
        return None
    if end_index - start_index < 2:
        return None
    crop = poses[start_index:end_index].astype(np.float32, copy=True)
    return {
        'schema': 'signbridge-native-word-motion-window-candidate-v1',
        'source_sequence_uid': sequence['sequence_uid'],
        'source_annotation_id': sequence['annotation_id'],
        'source_sha256': sequence['source_sha256'],
        'source_window_seconds_candidate': candidate_window,
        'source_sequence_window_seconds_nominal': sequence_window,
        'fps': float(fps), 'frames': len(crop),
        'poses': crop.tolist(),
        'native_pose_asset_sha256': sequence['effective_pose_sha256'],
        'native_array_representation': 'effective-axis-angle-55-radians-float32-copy',
        'parameter_scope': 'existing_effective_upper_body_display_projection',
        'full_native_smplx_parameters': False,
        'parameter_limitations': 'Existing display projection omits native root/lower-body/eyes/shape/expression/translation; source native files remain unchanged.',
        'crop_start_frame_1based': start_index + 1,
        'crop_end_frame_1based_inclusive': end_index,
        'rounded_frame_slot_window_seconds_nominal': [sequence_window[0] + start_index / fps,
                                                      sequence_window[0] + end_index / fps],
        'source_frame_mapping': 'nominal fit start plus frame_index/fps; original source PTS equivalence not verified',
        'word_alignment_verified': False,
        'text_verified': '',
        'human_approved': False, 'training_ready': False, 'model_training_ready': False,
    }


def index_native_sequences(path, current_sources):
    evidence = json.loads(Path(path).read_text())
    metadata_hashes = {item['path']: item['sha256'] for item in evidence.get('input_metadata_hashes', [])}
    by_sha = {source['sha256']: source for source in current_sources}
    indexed = defaultdict(list)
    rejected = Counter()
    for row in evidence.get('native_sequences', []):
        digest = row.get('source_sha256')
        poses = row.get('effective_pose_json') or {}
        if digest not in by_sha:
            rejected['source_sha_not_in_current_video_inventory'] += 1
            continue
        if not row.get('source_sha256_verified_now'):
            rejected['source_sha_not_recently_verified'] += 1
            continue
        if row.get('cpu_whole_window_technically_exportable') is not True:
            rejected['whole_sequence_fit_not_complete'] += 1
            continue
        if row.get('missing_native_frames_1based'):
            rejected['native_fit_has_missing_frames'] += 1
            continue
        if row.get('native_frame_count') != row.get('total_frames') or row.get('metadata_mapping_errors'):
            rejected['native_count_or_metadata_errors'] += 1
            continue
        if poses.get('verified') is not True or not poses.get('path') or not poses.get('sha256'):
            rejected['effective_pose_mapping_not_verified'] += 1
            continue
        indexed[digest].append({
            'sequence_uid': row['sequence_uid'], 'annotation_id': row['annotation_id'],
            'source_sha256': digest,
            'source_window_seconds': row['source_window_seconds'],
            'source_duration_seconds': by_sha[digest]['duration_seconds'],
            'total_frames': row['total_frames'], 'fps': row['fps'],
            'cpu_whole_window_technically_exportable': True,
            'missing_native_frames_1based': [], 'effective_pose_verified': True,
            'effective_pose_path': poses['path'], 'effective_pose_sha256': poses['sha256'],
            'batch': row.get('batch'), 'label_candidate': row.get('label'),
            '_native_evidence': {**row, 'metadata_source_sha256': metadata_hashes.get(row.get('metadata_source_path'))},
        })
    for digest in indexed:
        indexed[digest].sort(key=lambda row: (row['total_frames'], row['sequence_uid']))
    return indexed, {'schema': evidence.get('schema'), 'summary': evidence.get('summary'),
                     'input_metadata_hashes': evidence.get('input_metadata_hashes'),
                     'native_sequences': [r for values in indexed.values() for r in values],
                     'excluded_counts': dict(rejected)}, evidence


def candidate_record(label, source, window, kind, evidence):
    window = valid_window(window, source['duration_seconds'])
    if not isinstance(label, str) or not label.strip():
        raise ValueError('Nonempty candidate text required')
    identity = json.dumps([source['sha256'], window, label], ensure_ascii=False, separators=(',', ':'))
    return {
        'schema': SCHEMA, 'id': 'csl_candidate_' + hashlib.sha256(identity.encode()).hexdigest()[:20],
        'proposed_text': label.strip(), 'source_id': source.get('source_id', 'source-' + source['sha256'][:16]),
        'source_sha256': source['sha256'], 'source_absolute_path': source['path'],
        'source_batch': str(source.get('batch', 'unknown')), 'source_window_seconds': window,
        'source_content_classes': source.get('content_classes', []),
        'language_scope_status': source_scope(source),
        'evidence_kind': kind, 'label_status': 'candidate_only', 'text_verified': '',
        'word_boundaries_verified': False, 'word_spans': [], 'native_3d_available': False,
        'human_approved': False, 'training_ready': False, 'model_training_ready': False,
        'semantics_approved': False, 'mirror_status': 'unknown', 'signer_id': 'unconfirmed',
        'split': 'unassigned', 'source_pts_measured': False,
        'time_contract': 'nominal original-video seconds; caption/instruction time is not word alignment',
        'reference_clip': None, 'keyframes': None, 'native_asset': None,
        'materialize_requested': False, 'review_flags': [], 'evidence': [evidence],
        'notes': 'Candidate evidence only. Do not equate a caption with the signing meaning.',
    }


def caption_candidate(row, source, evidence_path):
    if row.get('source_sha256') and row.get('source_sha256') != source['sha256']:
        raise ValueError('Caption source SHA-256 mismatch')
    text = str(row.get('text_candidate', '')).strip()
    window = valid_window([row['start_seconds'], row['end_seconds']], source['duration_seconds'])
    short = bool(SHORT_TEXT.fullmatch(normalize_text(text))) and not NOISE.search(text)
    repeated = len(row.get('observed_times', [])) >= 2
    narrow = window[1] - window[0] <= 8
    materialize = short and repeated and narrow
    kind = ('caption_short_candidate' if materialize else
            'caption_short_unconfirmed' if short else 'caption_context')
    result = candidate_record(text, source, window,
                              kind,
                              {'path': str(evidence_path), 'segment_id': row.get('segment_id'),
                               'observed_times': row.get('observed_times', []),
                               'sampling_interval_seconds': row.get('sampling_interval_seconds'),
                               'raw_text': text})
    result['materialize_requested'] = materialize
    result['review_flags'] = ['sparse_caption_window_not_word_boundary']
    if not repeated:
        result['review_flags'].append('single_caption_observation')
    if not narrow:
        result['review_flags'].append('coarse_window_too_wide_for_lexical_clip')
    result['evidence'][0].update(ocr_evidence=row.get('evidence', []),
                                ocr_confidence_min=row.get('ocr_confidence_min'),
                                ocr_confidence_mean=row.get('ocr_confidence_mean'),
                                extraction_rule=row.get('extraction_rule'))
    if row.get('spatial_rule_thresholds_relaxed_locally'):
        result['review_flags'].append('raw_ocr_retained_below_generic_confidence_or_margin_gate')
    return result


def title_span_candidate(row, source, evidence_path):
    text = str(row.get('label_candidate', row.get('text_candidate', ''))).strip()
    if not text:
        raise ValueError('Title-span candidate text is empty')
    result = caption_candidate({
        'source_sha256': source['sha256'], 'text_candidate': text,
        'start_seconds': row['start_seconds'], 'end_seconds': row['end_seconds'],
        'observed_times': row.get('observed_times', []),
        'sampling_interval_seconds': row.get('sampling_interval_seconds'),
        'segment_id': row.get('segment_id'),
    }, source, evidence_path)
    if result['materialize_requested']:
        result['evidence_kind'] = 'title_span_candidate'
    result['evidence'][0]['title_span_evidence'] = row.get('evidence', [])
    result['review_flags'].append('sparse_title_span_not_word_boundary')
    return result


def spatial_caption_candidate(row, source, evidence_path):
    result = caption_candidate({
        'source_sha256': row['source_sha256'], 'text_candidate': row['label_candidate'],
        'start_seconds': row['start_seconds_nominal'], 'end_seconds': row['end_seconds_nominal'],
        'observed_times': row.get('sampled_seconds_nominal', []),
        'sampling_interval_seconds': row.get('sample_interval_seconds'),
        'segment_id': row.get('annotation_id'),
    }, source, evidence_path)
    result['evidence'][0].update(spatial_rule=row.get('extraction_rule'), ocr_evidence=row.get('evidence', []))
    if result['materialize_requested']:
        result['evidence_kind'] = 'spatial_caption_candidate'
    return result


def attach_dictionary_coverage(rows, lexicon):
    keys = {}
    for sign in lexicon:
        for alias in [sign.get('gloss', ''), *(sign.get('texts') or [])]:
            normalized = normalize_text(str(alias))
            if normalized:
                keys.setdefault(normalized, set()).add(sign['id'])
    for row in rows:
        matched = sorted(keys.get(normalize_text(row['proposed_text']), set()))
        row['existing_dictionary_match'] = bool(matched)
        row['existing_dictionary_ids'] = matched
    return rows


def lexical_coverage(rows, context, lexicon):
    labels = {row['proposed_text'] for row in rows + context}
    labels.update(('我', '你', '他', '她', '我们', '你们', '他们', '她们', '大家', '自己'))
    labels.update(sign['gloss'] for sign in lexicon)
    candidates, contexts = defaultdict(list), Counter()
    for row in rows:
        candidates[row['proposed_text']].append(row)
    for row in context:
        contexts[row['proposed_text']] += 1
    result = []
    dictionary = attach_dictionary_coverage([{'proposed_text': word} for word in sorted(labels)], lexicon)
    for item in dictionary:
        word = item['proposed_text']
        examples = candidates[word]
        native = sum(row.get('native_3d_available') is True for row in examples)
        videos = sum(bool(row.get('reference_clip')) for row in examples)
        result.append({'label': word, 'candidate_count': len(examples),
                       'candidate_ids': [row['id'] for row in examples],
                       'video_candidate_count': videos, 'native_candidate_count': native,
                       'context_only_count': contexts[word],
                       'existing_dictionary_ids': item['existing_dictionary_ids'],
                       'gap': 'unverified_native_candidate' if native else
                       'video_only_requires_continuous_3d_fit_and_word_review' if videos else
                       'no_standalone_candidate_video',
                       'verified_word_units': 0, 'text_verified': '',
                       'human_approved': False, 'training_ready': False, 'model_training_ready': False})
    return result


def instruction_candidates(parent, source, evidence_path):
    parent_window = valid_window(parent['source_window_seconds'], source['duration_seconds'])
    grouped = defaultdict(list)
    for evidence in parent.get('source_instruction_evidence', []):
        text = ''.join(evidence.get('instruction_text_raw', []))
        labels = re.findall(r'(?:表示|代表|意思是|就是)' + QUOTED, text)
        labels += re.findall(QUOTED + r'(?:就是|是用|是先)', text)
        time = evidence.get('source_seconds')
        if not isinstance(time, (int, float)) or not math.isfinite(time):
            continue
        for label in set(labels):
            if parent_window[0] <= time < parent_window[1]:
                grouped[label].append(evidence)
    output = []
    for label, evidence in sorted(grouped.items()):
        runs = []
        for item in sorted(evidence, key=lambda e: e['source_seconds']):
            if not runs or item['source_seconds'] - runs[-1][-1]['source_seconds'] > 1.01:
                runs.append([])
            runs[-1].append(item)
        for run in runs:
            start = max(parent_window[0], run[0]['source_seconds'] - 0.5)
            end = min(parent_window[1], run[-1]['source_seconds'] + 0.5)
            if end <= start:
                continue
            result = candidate_record(label, source, [start, end], 'instruction_subunit',
                                      {'path': str(evidence_path), 'annotation_id': parent.get('annotation_id'),
                                       'instruction_samples': run})
            result['materialize_requested'] = True
            result['review_flags'] = ['instruction_timestamp_not_true_motion_onset',
                                      'may_include_instruction_or_partial_demonstration']
            output.append(result)
    return output


def tutorial_candidate(row, source, path):
    window = row.get('source_window_seconds', [row.get('start_seconds'), row.get('end_seconds')])
    result = candidate_record(row['label'], source, window, 'tutorial_reference',
                              {'path': str(path), 'annotation_id': row['annotation_id'],
                               'prior_category': row.get('category'), 'prior_sample_type': row.get('sample_type')})
    result['materialize_requested'] = True
    result['review_flags'] = ['prior_coarse_tutorial_window_not_verified_word_boundary']
    result['notes'] = row.get('hand_shape_note', result['notes'])
    result['category'] = row.get('category', 'unconfirmed')
    if result['category'] == 'finger_spelling':
        result['language_scope_status'] = 'fingerspelling_candidate_separate'
        result['review_flags'].append('alphabet_or_fingerspelling_not_a_CSL_lexical_sign')
    info = row.get('artifacts', {}).get('clip.mp4')
    if isinstance(info, dict) and info.get('sha256'):
        reference = contained_file(path.parent, info['relative_path'])
        result['_reuse_clip'] = {'path': str(reference), 'sha256': info['sha256'],
                                 'allowed_root': str(path.parent.resolve())}
    result['existing_reference_evidence'] = row.get('artifacts', {})
    return result


def deduplicate_candidates(rows):
    seen = {}
    for row in rows:
        key = (row['source_sha256'], tuple(row['source_window_seconds']), normalize_text(row['proposed_text']))
        if key not in seen:
            seen[key] = {**row, 'evidence': list(row.get('evidence', []))}
        else:
            for item in row.get('evidence', []):
                if item not in seen[key]['evidence']:
                    seen[key]['evidence'].append(item)
            seen[key]['materialize_requested'] = seen[key].get('materialize_requested', False) or row.get('materialize_requested', False)
    return list(seen.values())


def suppress_persistent_overlays(rows, sources_by_sha):
    by_label_source = defaultdict(list)
    for row in rows:
        by_label_source[(row['source_sha256'], row['proposed_text'])].append(row)
    for (digest, _label), group in by_label_source.items():
        if not all(row['evidence_kind'] == 'caption_short_candidate' for row in group):
            continue
        duration = sources_by_sha[digest]['duration_seconds']
        intervals = sorted(row['source_window_seconds'] for row in group)
        covered = 0.0
        last_end = -1.0
        for start, end in intervals:
            covered += max(0.0, end - max(start, last_end))
            last_end = max(last_end, end)
        if len(group) >= 4 and covered / duration >= 0.65:
            for row in group:
                row['materialize_requested'] = False
                row['evidence_kind'] = 'caption_short_unconfirmed'
                row['review_flags'].append('persistent_overlay_or_watermark_suspected')
    return rows


def probe(path):
    command = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
               '-show_entries', 'stream=nb_read_frames,avg_frame_rate,width,height:format=duration',
               '-of', 'json', str(path)]
    process = subprocess.run(command, capture_output=True, check=True, text=True, timeout=180)
    info = json.loads(process.stdout)
    stream = info['streams'][0]
    frames = int(stream['nb_read_frames'])
    ratio = stream['avg_frame_rate'].split('/')
    fps = int(ratio[0]) / int(ratio[1])
    if frames < 1 or not math.isfinite(fps) or fps <= 0:
        raise ValueError('Invalid decoded video timebase')
    return {'frames': frames, 'fps': fps, 'width': int(stream['width']), 'height': int(stream['height']),
            'duration_seconds': float(info['format']['duration'])}


def contact_sheet(clip, output, frames, fps):
    cap = cv2.VideoCapture(str(clip))
    selected = sorted({min(frames - 1, round((frames - 1) * fraction)) for fraction in (0.2, 0.5, 0.8)})
    cells = []
    try:
        for number in selected:
            cap.set(cv2.CAP_PROP_POS_FRAMES, number)
            ok, frame = cap.read()
            if not ok or frame is None or not frame.size:
                raise ValueError('Contact sheet frame decode failed')
            scale = min(320 / frame.shape[1], 280 / frame.shape[0])
            image = cv2.resize(frame, (max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale))))
            cell = np.full((312, 320, 3), 245, np.uint8)
            y, x = (280 - image.shape[0]) // 2, (320 - image.shape[1]) // 2
            cell[y:y + image.shape[0], x:x + image.shape[1]] = image
            cv2.putText(cell, f'{number + 1}/{frames} | {number / fps:.2f}s', (10, 300),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (30, 30, 30), 1)
            cells.append(cell)
    finally:
        cap.release()
    if not cells or not cv2.imwrite(str(output), np.hstack(cells)):
        raise ValueError('Contact sheet write failed')
    return [number + 1 for number in selected]


def materialize(row, output):
    folder = output / 'assets' / row['id']
    folder.mkdir(parents=True)
    clip = folder / 'clip.mp4'
    reused = row.get('_reuse_clip')
    if reused:
        source = Path(reused['path'])
        if source.resolve(strict=True) != contained_file(Path(reused['allowed_root']),
                source.relative_to(reused['allowed_root']).as_posix()).resolve(strict=True):
            raise ValueError('Prior reference escaped tutorial artifact root')
        if sha(source) != reused['sha256']:
            raise ValueError('Prior reference clip SHA-256 mismatch')
        shutil.copyfile(source, clip)
        row['reused_clip_provenance'] = dict(reused)
    else:
        start, end = row['source_window_seconds']
        command = ['ffmpeg', '-v', 'error', '-nostdin', '-n', '-ss', str(start),
                   '-i', row['source_absolute_path'], '-t', str(end - start), '-an',
                   '-vf', 'fps=25,scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2',
                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-threads', '1',
                   '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(clip)]
        subprocess.run(command, capture_output=True, check=True, timeout=180)
        row['extraction_command'] = command
        row['extraction_exit_code'] = 0
    decoded = probe(clip)
    if decoded['frames'] < 2:
        raise ValueError('Candidate too short for continuous video')
    decoded_duration = decoded['frames'] / decoded['fps']
    expected_duration = row['source_window_seconds'][1] - row['source_window_seconds'][0]
    if abs(decoded_duration - expected_duration) > max(0.12, 2 / decoded['fps']):
        raise ValueError('Extracted clip duration differs from nominal candidate window')
    frames = contact_sheet(clip, folder / 'keyframes.jpg', decoded['frames'], decoded['fps'])
    row.update(reference_clip=str(clip.relative_to(output)), keyframes=str((folder / 'keyframes.jpg').relative_to(output)),
               materialization_status='extracted_candidate', decoded_video=decoded,
               selected_keyframes_1based=frames, clip_sha256=sha(clip), keyframes_sha256=sha(folder / 'keyframes.jpg'))
    (folder / 'frames.jsonl').write_text(''.join(json.dumps({
        'frame_1based': index + 1, 'reference_seconds': index / decoded['fps'],
        'source_seconds_nominal': row['source_window_seconds'][0] + index / decoded['fps'],
        'source_pts_measured': False, 'word_alignment_verified': False}) + '\n' for index in range(decoded['frames'])))
    write_json(folder / 'candidate.json', {key: value for key, value in row.items() if not key.startswith('_')})
    return row


def attach_verified_reuse(row, prior_by_id, prior_root):
    prior = prior_by_id.get(row['id'])
    if not prior or prior.get('materialization_status') != 'extracted_candidate':
        return False
    if any(row.get(key) != prior.get(key) for key in ('source_sha256', 'source_window_seconds', 'proposed_text')):
        raise ValueError('Reuse candidate source/window/label identity differs')
    clip = contained_file(prior_root, prior['reference_clip'])
    if sha(clip) != prior['clip_sha256']:
        raise ValueError('Reuse candidate video hash differs')
    row['_reuse_clip'] = {'path': str(clip), 'sha256': prior['clip_sha256'],
                         'allowed_root': str(prior_root), 'prior_candidate_id': row['id']}
    return True


def attach_native_pose_crop(row, native_by_sha, cache, output, input_hashes):
    if not row.get('materialize_requested'):
        return False
    choices = native_by_sha.get(row['source_sha256'], [])
    for sequence in choices:
        sequence_window = valid_window(sequence['source_window_seconds'], sequence['source_duration_seconds'])
        candidate_window = valid_window(row['source_window_seconds'], sequence['source_duration_seconds'])
        tolerance = 1e-8
        if (candidate_window[0] < sequence_window[0] - tolerance or
                candidate_window[1] > sequence_window[1] + tolerance):
            continue
        if candidate_window[1] > sequence_window[0] + sequence['total_frames'] / sequence['fps'] + tolerance:
            continue
        if '_current_native_verification' not in sequence:
            sequence['_current_native_verification'] = verify_native_sequence(sequence['_native_evidence'], input_hashes)
        cropped = crop_native_pose_candidate(
            row, sequence, _load_effective_pose(sequence, cache, input_hashes)
        )
        if cropped is None:
            continue
        relative = Path('native-candidates') / (row['id'] + '.json')
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, cropped)
        row['native_3d_available'] = True
        row['native_asset'] = relative.as_posix()
        row['native_source_sequence_uid'] = sequence['sequence_uid']
        row['native_mapping_status'] = 'same-video-sha-and-contained-nominal-window; original-pts-not-verified'
        row['review_flags'].append('native_3d_is_caption_time_crop_not_verified_word_motion')
        row['native_asset_sha256'] = sha(target)
        return True
    return False


def _load_effective_pose(sequence, cache, input_hashes):
    digest = sequence['effective_pose_sha256']
    if digest not in cache:
        source = Path(sequence['effective_pose_path'])
        local_data = Path(__file__).resolve().parents[3] / 'local-data'
        try:
            source.resolve(strict=True).relative_to(local_data.resolve(strict=True))
        except (ValueError, OSError) as error:
            raise ValueError('Effective-pose file escaped the project local-data directory') from error
        if not source.is_file() or source.is_symlink() or sha(source) != digest:
            raise ValueError('Existing effective-pose JSON path/hash validation failed')
        value = json.loads(source.read_text())
        if (value.get('id') != sequence['sequence_uid'] or
                value.get('frames') != sequence['total_frames'] or
                value.get('fps') != sequence['fps'] or
                value.get('experimental') is not True or
                len(value.get('poses', [])) != sequence['total_frames']):
            raise ValueError('Existing effective-pose sequence identity/frame metadata differs')
        poses = np.asarray(value['poses'], dtype=np.float32)
        if poses.shape != (sequence['total_frames'], 55, 3) or not np.isfinite(poses).all():
            raise ValueError('Existing effective-pose data is malformed or nonfinite')
        cache[digest] = poses
        input_hashes[str(source)] = digest
    return cache[digest]


def find_source(row, sources_by_sha):
    digest = row.get('source_sha256', row.get('sha256'))
    if digest not in sources_by_sha:
        raise ValueError('No matching current original-video SHA-256')
    return sources_by_sha[digest]


def snapshot_inputs(inputs, output, original_paths):
    snapshots = {}
    folder = output / 'provenance-inputs'
    folder.mkdir()
    for name, digest in sorted(inputs.items()):
        if name in original_paths:
            continue
        source = Path(name)
        if not source.is_file() or source.is_symlink() or sha(source) != digest:
            raise ValueError('Snapshot input changed or became a symlink: ' + name)
        target = folder / (digest + source.suffix)
        if not target.exists():
            shutil.copyfile(source, target)
        snapshots[name] = target.relative_to(output).as_posix()
    return snapshots


def contained_file(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or '\n' in relative:
        raise ValueError('Invalid artifact relative path')
    name = Path(relative)
    if name.is_absolute() or any(part in ('.', '..') for part in name.parts):
        raise ValueError('Artifact path escaped output directory')
    target = root / name
    try:
        target.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (ValueError, OSError) as error:
        raise ValueError('Artifact path escaped output directory or is missing') from error
    if target.is_symlink() or not target.is_file():
        raise ValueError('Artifact is not a regular file')
    return target


def verified_local_input(path, digest, inputs):
    path = Path(path)
    local_data = Path(__file__).resolve().parents[3] / 'local-data'
    try:
        path.resolve(strict=True).relative_to(local_data.resolve(strict=True))
    except (ValueError, OSError) as error:
        raise ValueError('Native provenance path escaped local-data or is missing') from error
    if path.is_symlink() or not path.is_file() or sha(path) != digest:
        raise ValueError('Native provenance file hash differs or is missing: ' + str(path))
    inputs[str(path)] = digest
    return path


def verify_legacy_timing(evidence, inputs):
    name = evidence.get('metadata_source_path')
    if not name or not Path(name).is_file():
        raise ValueError('Legacy native sequence has no existing source-bound timing descriptor')
    if not evidence.get('metadata_source_sha256'):
        raise ValueError('Legacy timing descriptor has no pre-existing pinned hash')
    path = verified_local_input(name, evidence['metadata_source_sha256'], inputs)
    matches = [row for row in read_rows(path) if row.get('annotation_id') == evidence['annotation_id']]
    if len(matches) != 1:
        raise ValueError('Legacy native timing descriptor identity is not unique')
    row = matches[0]
    if (row.get('source_sha256') != evidence['source_sha256'] or
            [row.get('start_seconds'), row.get('end_seconds')] != evidence['source_window_seconds'] or
            row.get('frames') != evidence['total_frames'] or row.get('fps') != evidence['fps']):
        raise ValueError('Legacy native timing descriptor source/window/frame mapping differs')
    clip = contained_file(path.parent, row['clip'])
    if row['clip_sha256'] != (evidence.get('clip_timebase_verification') or {}).get('sha256'):
        raise ValueError('Legacy reference clip differs from previously audited clip hash')
    verified_local_input(clip, row['clip_sha256'], inputs)
    decoded = probe(clip)
    if decoded['frames'] != evidence['total_frames'] or abs(decoded['fps'] - evidence['fps']) > 1e-6:
        raise ValueError('Legacy reference clip decoded frame count or fps differs')
    return {'kind': 'existing_legacy_source_bound_sequence_descriptor',
            'descriptor_path': str(path), 'descriptor_sha256': sha(path),
            'reference_clip_sha256': row['clip_sha256'], 'reference_clip_frames_decoded': decoded['frames'],
            'original_input_jpeg_hashes_verified': False, 'original_pts_measured': False,
            'limitation': 'Existing sequence descriptor and reference clip bind nominal timing; no original per-frame JPEG/PTS equivalence claimed.'}


def verify_native_sequence(evidence, inputs):
    n = evidence['total_frames']
    if (not isinstance(n, int) or n < 2 or evidence.get('native_frame_count') != n or
            evidence.get('missing_native_frames_1based') or evidence.get('metadata_mapping_errors')):
        raise ValueError('Native sequence count, gaps or metadata mapping invalid')
    manifest = verified_local_input(evidence['frozen_manifest_path'], evidence['frozen_manifest_sha256'], inputs)
    entries = json.loads(manifest.read_text())
    hashes = {entry['path']: entry['sha256'] for entry in entries}
    fit = Path(evidence['fit_path'])
    params = {str(fit / 'smplx' / f'{frame:05d}_0.npz') for frame in range(1, n + 1)}
    metas = {str(fit / 'meta' / f'{frame:05d}_0.json') for frame in range(1, n + 1)}
    if len(hashes) != len(entries) or set(hashes) != params | metas:
        raise ValueError('Frozen native manifest exact frame/person set differs')
    if ({str(path) for path in (fit / 'smplx').glob('*.npz')} != params or
            {str(path) for path in (fit / 'meta').glob('*.json')} != metas):
        raise ValueError('Native frame/person files differ from exact contiguous sets')
    reference = evidence.get('reference_frames_manifest')
    frames, timing_evidence = None, None
    if reference:
        frames_path = verified_local_input(reference['path'], reference['sha256'], inputs)
        frames = read_rows(frames_path)
        if len(frames) != n or [row.get('frame_id', row.get('frame_1based')) for row in frames] != list(range(1, n + 1)):
            raise ValueError('Native reference frame index differs')
        timing_evidence = {'kind': 'existing_reference_frame_manifest', 'sha256': reference['sha256']}
    else:
        timing_evidence = verify_legacy_timing(evidence, inputs)
    for frame in range(1, n + 1):
        param = fit / 'smplx' / f'{frame:05d}_0.npz'
        meta = fit / 'meta' / f'{frame:05d}_0.json'
        verified_local_input(param, hashes[str(param)], inputs)
        verified_local_input(meta, hashes[str(meta)], inputs)
        with np.load(param, allow_pickle=False) as arrays:
            for key, shape in NATIVE_SHAPES.items():
                value = arrays[key]
                if value.shape != shape or value.dtype.kind != 'f' or not np.isfinite(value).all():
                    raise ValueError('Native numeric shape/dtype/finiteness differs')
        metadata = json.loads(meta.read_text())
        image = Path(metadata.get('img_path', ''))
        if (metadata.get('bbox_id') != 0 or image.name not in (f'{frame:06d}.jpg', f'{frame:05d}.jpg') or
                evidence['annotation_id'] not in image.parts):
            raise ValueError('Native metadata frame/image/person mapping differs')
        expected_time = evidence['source_window_seconds'][0] + (frame - 1) / evidence['fps']
        if frames is not None and abs(frames[frame - 1]['source_seconds_nominal'] - expected_time) > 1e-6:
            raise ValueError('Native reference nominal time mapping differs')
    return {'sequence_uid': evidence['sequence_uid'], 'frames_verified': n,
            'native_and_meta_files_rehashed': 2 * n, 'manifest_sha256': evidence['frozen_manifest_sha256'],
            'exact_native_frame_person_sets': True, 'native_parameters_finite_correct_shape': True,
            'nominal_timing_evidence': timing_evidence,
            'original_input_jpeg_hash_equivalence_not_reconstructed': True,
            'original_pts_measured': False}


def require_complete_materialization(candidates):
    failed = [row['id'] for row in candidates if row.get('materialize_requested') and
              (row.get('materialization_status') != 'extracted_candidate' or
               not row.get('reference_clip') or not row.get('keyframes'))]
    if failed:
        raise ValueError('Incomplete requested materialization: ' + ','.join(failed[:20]))


def verify_manifest(root):
    root = Path(root)
    paths = set()
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, relative = line.split('  ', 1)
        if not re.fullmatch('[0-9a-f]{64}', digest) or relative in paths:
            raise ValueError('Malformed or duplicated checksum record')
        path = contained_file(root, relative)
        if sha(path) != digest:
            raise ValueError('Artifact SHA-256 differs: ' + relative)
        paths.add(relative)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    if paths != actual:
        raise ValueError('Checksum manifest does not cover exactly the artifact file set')
    return {'files_verified': len(paths), 'manifest_sha256': sha(root / 'SHA256SUMS')}


def pose_quality(poses):
    values = np.asarray(poses, dtype=np.float64)
    if values.ndim != 3 or values.shape[1:] != (55, 3) or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError('Cannot measure malformed or incomplete pose candidates')
    angles = np.linalg.norm(values, axis=-1, keepdims=True)
    scale = np.divide(np.sin(angles / 2), angles, out=np.full_like(angles, .5), where=angles > 1e-12)
    q = np.concatenate([np.cos(angles / 2), values * scale], axis=-1)
    steps = np.rad2deg(2 * np.arccos(np.clip(np.abs(np.sum(q[1:] * q[:-1], axis=-1)), 0., 1.)))
    result = {'frames': len(values), 'adjacent_rotation_degrees_max': float(steps.max()),
              'hand_adjacent_degrees_p95': float(np.percentile(steps[:, 25:55], 95)),
              'adjacent_joint_steps_over_90_degrees': int((steps > 90).sum()),
              'semantics_or_collision_assessed': False,
              'quality_approved': False, 'source_parameters_modified': False}
    if len(q) >= 3:
        left, right = q[:-2], q[2:]
        right = np.where(np.sum(left * right, axis=-1, keepdims=True) < 0, -right, right)
        midpoint = left + right
        midpoint /= np.linalg.norm(midpoint, axis=-1, keepdims=True)
        residual = np.rad2deg(2 * np.arccos(np.clip(np.abs(np.sum(midpoint * q[1:-1], axis=-1)), 0., 1.)))
        result['hand_midpoint_residual_degrees_p95'] = float(np.percentile(residual[:, 25:55], 95))
    return result


def audit(args):
    root = args.audit.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError('Audit requires a NEW output directory')
    manifest = verify_manifest(root)
    report = json.loads((root / 'report.json').read_text())
    candidates = read_rows(root / 'candidates.jsonl')
    require_complete_materialization(candidates)
    if report['candidates'] != candidates or len({r['id'] for r in candidates}) != len(candidates):
        raise ValueError('Candidate report/JSONL identities differ or repeat')
    inputs = json.loads((root / 'inputs.json').read_text())
    for path, digest in inputs.items():
        if not Path(path).is_file() or sha(path) != digest:
            raise ValueError('Input provenance differs: ' + path)
    sources = json.loads((root / 'source-snapshot.json').read_text())
    by_sha = {source['sha256']: source for source in sources}
    recipe = json.loads((root / 'recipe.json').read_text())
    native, _, _ = index_native_sequences(recipe['native_motion_map'], sources)
    native_by_uid = {sequence['sequence_uid']: sequence for sequences in native.values() for sequence in sequences}
    cache, pose_inputs, checked = {}, {}, []

    def check_video(row):
        video = contained_file(root, row['reference_clip'])
        capture = cv2.VideoCapture(str(video))
        frames = 0
        try:
            if not capture.isOpened():
                raise ValueError('Candidate video cannot be opened')
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame is None or not frame.size:
                    raise ValueError('Empty decoded frame')
                frames += 1
        finally:
            capture.release()
        if frames != row['decoded_video']['frames'] or frames < 2:
            raise ValueError('Full decode differs from declared exact frame count')
        sheet = cv2.imread(str(contained_file(root, row['keyframes'])))
        if sheet is None or not sheet.size:
            raise ValueError('Contact sheet cannot be decoded')
        mapping = read_rows(contained_file(root, f"assets/{row['id']}/frames.jsonl"))
        if len(mapping) != frames or [r['frame_1based'] for r in mapping] != list(range(1, frames + 1)):
            raise ValueError('Candidate frame mapping is not exact and contiguous')
        for index, record in enumerate(mapping):
            expected = row['source_window_seconds'][0] + index / row['decoded_video']['fps']
            if record['source_pts_measured'] is not False or abs(record['source_seconds_nominal'] - expected) > 1e-7:
                raise ValueError('Candidate nominal time mapping differs')
        return {'id': row['id'], 'decoded_frames': frames, 'video_sha256': sha(video)}

    for row in candidates:
        if (row.get('text_verified') != '' or row.get('human_approved') is not False or
                row.get('training_ready') is not False or row.get('model_training_ready') is not False or
                row.get('word_boundaries_verified') is not False):
            raise ValueError('Candidate approval/readiness boundary violated')
        valid_window(row['source_window_seconds'], by_sha[row['source_sha256']]['duration_seconds'])
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(check_video, [r for r in candidates if r.get('reference_clip')]):
            checked.append(result)
    quality = []
    native_verified = {}
    for row in candidates:
        if row.get('native_3d_available') is not True:
            continue
        asset = json.loads(contained_file(root, row['native_asset']).read_text())
        sequence = native_by_uid[row['native_source_sequence_uid']]
        if sequence['sequence_uid'] not in native_verified:
            native_verified[sequence['sequence_uid']] = verify_native_sequence(sequence['_native_evidence'], pose_inputs)
        expected = crop_native_pose_candidate(row, sequence, _load_effective_pose(sequence, cache, pose_inputs))
        if asset != expected:
            raise ValueError('Native crop differs from exact source pose subset: ' + row['id'])
        quality.append({'id': row['id'], 'label_candidate': row['proposed_text'], **pose_quality(asset['poses'])})
    summary = report['summary']
    if (len(checked) != summary['materialized'] or len(candidates) != summary['candidates'] or
            len(quality) != summary['native_3d'] or len(sources) != summary['video_paths'] or
            len(report['video_path_coverage']) != summary['video_paths']):
        raise ValueError('Output coverage/completeness totals differ')
    result = {'schema': SCHEMA + '-audit', 'created_at': datetime.now(timezone.utc).isoformat(),
              'results': str(root), 'manifest': manifest, 'input_hashes_verified': len(inputs),
              'video_paths_accounted': len(sources), 'candidates_checked': len(candidates),
              'videos_fully_decoded': len(checked), 'video_frames_fully_decoded': sum(r['decoded_frames'] for r in checked),
              'native_exact_subsets_verified': len(quality), 'per_clip': checked, 'native_quality': quality,
              'current_native_sequence_verifications': list(native_verified.values()),
              'human_approved': False, 'training_ready': False, 'model_training_ready': False,
              'word_semantics_verified': False, 'no_missing_frames_filled': True}
    output.mkdir(parents=True)
    write_json(output / 'audit.json', result)
    print(json.dumps({key: value for key, value in result.items() if key not in ('per_clip', 'native_quality')}, ensure_ascii=False), flush=True)
    return result


def build(args):
    recipe_path = args.recipe.resolve()
    recipe = json.loads(recipe_path.read_text())
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError('Choose a NEW output directory; previous evidence is immutable')
    inventory_path = Path(recipe['video_inventory']).resolve()
    inventory = json.loads(inventory_path.read_text())
    videos = inventory['videos']
    sources, by_sha = [], {}
    inputs = {str(recipe_path): sha(recipe_path), str(inventory_path): sha(inventory_path), str(Path(__file__).resolve()): sha(__file__)}
    for name in recipe.get('additional_input_files', []):
        path = Path(name)
        path.resolve(strict=True).relative_to((Path(__file__).resolve().parents[3] / 'local-data').resolve(strict=True))
        if path.is_symlink() or not path.is_file():
            raise ValueError('Additional evidence must be a regular local-data file')
        inputs[str(path.resolve())] = sha(path)
    failures, exclusions = [], []
    for video in videos:
        source = {**video, 'path': video.get('path', video.get('absolute_path')),
                  'sha256': video.get('sha256', video.get('source_sha256')),
                  'duration_seconds': video.get('duration_seconds')}
        path = Path(source['path'])
        allowed_root = Path('/Users/mac/Desktop/手语') / str(source['batch'])
        try:
            if path.is_symlink():
                raise ValueError('Original symlink')
            resolved = path.resolve(strict=True)
            resolved.relative_to(allowed_root.resolve(strict=True))
        except (FileNotFoundError, ValueError, OSError):
            failures.append({'source_path': str(path), 'stage': 'source_preflight', 'reason': 'Original missing or escaped the authorized batch directory'})
            continue
        if not resolved.is_file() or resolved.is_symlink():
            failures.append({'source_path': str(path), 'stage': 'source_preflight', 'reason': 'Original missing or symlink'})
            continue
        path = resolved
        current_sha = sha(path)
        if source.get('sha256') and current_sha != source['sha256']:
            failures.append({'source_path': str(path), 'stage': 'source_preflight', 'reason': 'Original SHA-256 changed'})
            continue
        source['sha256'] = current_sha
        if not isinstance(source['duration_seconds'], (int, float)) or source['duration_seconds'] <= 0:
            process = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                                     capture_output=True, check=True, text=True, timeout=30)
            source['duration_seconds'] = float(json.loads(process.stdout)['format']['duration'])
        source['source_id'] = source.get('source_id') or 'source-' + current_sha[:16]
        inputs[str(path)] = current_sha
        sources.append(source)
        by_sha.setdefault(current_sha, source)
    rows, context, covered_sha = [], [], set()
    for name in recipe.get('tutorial_indexes', []):
        path = Path(name).resolve()
        inputs[str(path)] = sha(path)
        for row in read_rows(path):
            try:
                source = find_source(row, by_sha)
                if source_scope(source) == 'excluded_non_CSL_or_performative' and row.get('category') != 'finger_spelling':
                    exclusions.append({'stage': 'tutorial_index', 'source_sha256': source['sha256'],
                                       'path': str(path), 'reason': 'excluded_source_scope'})
                    continue
                result = tutorial_candidate(row, source, path)
                rows.append(result)
                rows.extend(instruction_candidates({**row, 'source_window_seconds': result['source_window_seconds']}, source, path))
                covered_sha.add(source['sha256'])
            except (ValueError, KeyError) as error:
                failures.append({'stage': 'tutorial_index', 'path': str(path), 'annotation_id': row.get('annotation_id'), 'reason': str(error)})
    for name in recipe.get('caption_indexes', []):
        path = index_path(name)
        inputs[str(path)] = sha(path)
        for row in bound_index_rows(name):
            try:
                source = find_source(row, by_sha)
                if source_scope(source) == 'excluded_non_CSL_or_performative':
                    exclusions.append({'source_sha256': source['sha256'], 'path': str(path),
                                       'reason': 'other_sign_language_song_or_non_CSL_filename_hint', 'segment_id': row.get('segment_id')})
                    continue
                result = caption_candidate(row, source, path)
                covered_sha.add(source['sha256'])
                (rows if result['materialize_requested'] else context).append(result)
            except (ValueError, KeyError) as error:
                failures.append({'stage': 'caption_index', 'path': str(path), 'segment_id': row.get('segment_id'), 'reason': str(error)})
    for name in recipe.get('title_span_indexes', []):
        path = index_path(name)
        inputs[str(path)] = sha(path)
        for row in bound_index_rows(name):
            try:
                source = find_source(row, by_sha)
                if source_scope(source) == 'excluded_non_CSL_or_performative':
                    exclusions.append({'stage': 'title_span_index', 'path': str(path),
                                       'source_sha256': source['sha256'], 'reason': 'excluded_source_scope'})
                    continue
                candidate = title_span_candidate(row, source, path)
                (rows if candidate['materialize_requested'] else context).append(candidate)
                covered_sha.add(source['sha256'])
            except (ValueError, KeyError) as error:
                failures.append({'stage': 'title_span_index', 'path': str(path), 'reason': str(error)})
    for name in recipe.get('spatial_caption_indexes', []):
        path = index_path(name)
        inputs[str(path)] = sha(path)
        for row in bound_index_rows(name):
            try:
                source = find_source(row, by_sha)
                if source_scope(source) == 'excluded_non_CSL_or_performative':
                    exclusions.append({'stage': 'spatial_caption_index', 'path': str(path),
                                       'source_sha256': source['sha256'], 'reason': 'excluded_source_scope'})
                    continue
                candidate = spatial_caption_candidate(row, source, path)
                (rows if candidate['materialize_requested'] else context).append(candidate)
                covered_sha.add(source['sha256'])
            except (ValueError, KeyError) as error:
                failures.append({'stage': 'spatial_caption_index', 'path': str(path),
                                 'annotation_id': row.get('annotation_id'), 'reason': str(error)})
    for name in recipe.get('subtitle_indexes', []):
        path = index_path(name)
        inputs[str(path)] = sha(path)
        for row in bound_index_rows(name):
            try:
                source = find_source(row, by_sha)
            except ValueError as error:
                failures.append({'stage': 'subtitle_index', 'path': str(path), 'reason': str(error)})
                continue
            if source_scope(source) == 'excluded_non_CSL_or_performative':
                exclusions.append({'stage': 'subtitle_index', 'path': str(path),
                                   'source_sha256': source['sha256'], 'reason': 'excluded_source_scope'})
                continue
            text = str(row.get('text', '')).strip()
            if not text:
                continue
            second = row.get('seconds')
            if not isinstance(second, (int, float)) or not math.isfinite(second):
                continue
            short = bool(SHORT_TEXT.fullmatch(normalize_text(text))) and not NOISE.search(text)
            if short:
                start, end = max(0., second - .5), min(source['duration_seconds'], second + .5)
                caption = {'source_sha256': source['sha256'], 'text_candidate': text,
                           'start_seconds': start, 'end_seconds': end, 'observed_times': [second],
                           'sampling_interval_seconds': 1., 'segment_id': None}
                result = caption_candidate(caption, source, path)
                result['evidence_kind'] = 'subtitle_short_unconfirmed'
                result['materialize_requested'] = False
                result['review_flags'].append('subtitle_visibility_does_not_prove_signing')
                context.append(result)
            else:
                context.append(candidate_record(text, source, [max(0., second - .5),
                    min(source['duration_seconds'], second + .5)], 'subtitle_sentence_context',
                    {'path': str(path), 'seconds': second, 'image': row.get('image'),
                     'image_sha256': row.get('image_sha256')}))
            covered_sha.add(source['sha256'])
    rows = suppress_persistent_overlays(deduplicate_candidates(rows), by_sha)
    lexicon = json.loads(Path(recipe['dictionary_lexicon']).read_text())
    inputs[str(Path(recipe['dictionary_lexicon']).resolve())] = sha(recipe['dictionary_lexicon'])
    rows = attach_dictionary_coverage(rows, lexicon)
    context = attach_dictionary_coverage(context, lexicon)
    if recipe.get('reuse_results') and not getattr(args, 'dry_run', False):
        reuse = recipe['reuse_results']
        prior_root = Path(reuse['path']).resolve(strict=True)
        prior_root.relative_to((Path(__file__).resolve().parents[3] / 'local-data').resolve(strict=True))
        verified = verify_manifest(prior_root)
        if verified['manifest_sha256'] != reuse['manifest_sha256']:
            raise ValueError('Prior results manifest differs from frozen reuse provenance')
        prior_rows = read_rows(prior_root / 'candidates.jsonl')
        prior_by_id = {row['id']: row for row in prior_rows}
        for row in rows:
            if row.get('materialize_requested'):
                attach_verified_reuse(row, prior_by_id, prior_root)
        for name in ('SHA256SUMS', 'report.json', 'candidates.jsonl'):
            inputs[str(prior_root / name)] = sha(prior_root / name)
    if getattr(args, 'dry_run', False):
        planned = [row for row in rows if row['materialize_requested']]
        seconds = sum(row['source_window_seconds'][1] - row['source_window_seconds'][0] for row in planned)
        plan = {'dry_run': True, 'video_paths': len(sources), 'unique_sources': len(by_sha),
                'candidate_windows': len(rows), 'clips_planned': len(planned),
                'unique_raw_labels': len({row['proposed_text'] for row in rows}),
                'clip_seconds_nominal': seconds, 'context_windows': len(context),
                'excluded_index_rows': len(exclusions), 'preflight_failures': failures,
                'candidate_kinds': dict(Counter(row['evidence_kind'] for row in rows)),
                'pronoun_candidates': {word: sum(row['proposed_text'] == word for row in rows)
                                       for word in ('我', '你', '他', '我们', '你们', '他们', '自己')}}
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        return plan
    output.mkdir(parents=True)
    native_by_sha = {}
    native_cache, native_pose_inputs = {}, {}
    native_summary = {'verified_complete_sequences': 0, 'rejected_sequences': {},
                      'keyframe_only_references_not_used_as_continuous_motion': 0}
    if recipe.get('native_motion_map'):
        native_path = Path(recipe['native_motion_map']).resolve()
        local_data_root = Path(__file__).resolve().parents[3] / 'local-data'
        try:
            native_path.relative_to(local_data_root.resolve(strict=True))
        except ValueError as error:
            raise ValueError('Native motion map must remain under local-data') from error
        if not native_path.is_file() or native_path.is_symlink():
            raise ValueError('Native motion map is missing or a symlink')
        inputs[str(native_path)] = sha(native_path)
        native_by_sha, native_metadata, _ = index_native_sequences(native_path, sources)
        for digest, sequences in native_by_sha.items():
            for sequence in sequences:
                sequence['source_duration_seconds'] = by_sha[digest]['duration_seconds']
        native_summary = {
            'verified_complete_sequences': sum(map(len, native_by_sha.values())),
            'sequence_map_sha256': inputs[str(native_path)],
            'rejected_sequences': native_metadata['excluded_counts'],
            'keyframe_only_references_not_used_as_continuous_motion': int(
                (native_metadata.get('summary') or {}).get('tutorial_independent_keyframe_npz', 0)
            ),
        }
        for row in rows:
            try:
                attach_native_pose_crop(row, native_by_sha, native_cache, output, native_pose_inputs)
            except (ValueError, OSError, KeyError, TypeError) as error:
                row['review_flags'].append('native_pose_crop_rejected')
                row['native_crop_failure_reason'] = str(error)[:300]
                failures.append({'stage': 'native_pose_crop', 'candidate_id': row['id'],
                                 'reason': str(error)[:600]})
        inputs.update(native_pose_inputs)
        native_summary['current_sequence_verifications'] = [sequence['_current_native_verification']
            for sequences in native_by_sha.values() for sequence in sequences if '_current_native_verification' in sequence]
    write_json(output / 'recipe.json', recipe)
    write_json(output / 'source-snapshot.json', sources)
    finished = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(materialize, row, output): row for row in rows if row['materialize_requested']}
        for future in as_completed(futures):
            row = futures[future]
            try:
                finished.append(future.result())
            except Exception as error:
                row['materialization_status'] = 'failed_preserved'
                row['review_flags'].append('video_extraction_failed')
                failures.append({'stage': 'materialization', 'id': row['id'], 'reason': str(error)[:600]})
                if isinstance(error, subprocess.CalledProcessError):
                    failures[-1].update(command=error.cmd, exit_code=error.returncode,
                                        stderr=(error.stderr or b'').decode('utf-8', errors='replace')[:4000])
            if len(finished) % 25 == 0:
                print(json.dumps({'completed': len(finished), 'planned': len(futures), 'failures': len(failures)}), flush=True)
    for row in rows:
        row.pop('_reuse_clip', None)
        row.setdefault('materialization_status', 'metadata_only')
    rows.sort(key=lambda r: (r['source_batch'], r['source_sha256'], r['source_window_seconds'], r['proposed_text']))
    counts = Counter(row['source_sha256'] for row in rows)
    coverage = [{'source_id': source['source_id'], 'source_sha256': source['sha256'], 'path': source['path'],
                 'batch': source['batch'], 'candidate_count': counts[source['sha256']],
                 'content_classes': source.get('content_classes', []),
                 'status': 'excluded_other_language_or_performative_hint' if source_scope(source) == 'excluded_non_CSL_or_performative' else
                 'regional_variant_review_separate' if source_scope(source) == 'regional_variant_candidate_separate' else
                 'candidate_evidence_indexed' if counts[source['sha256']] else
                 'caption_context_only' if source['sha256'] in covered_sha else 'no_caption_or_lexical_evidence_available'}
                for source in sources]
    current_paths = {source['path'] for source in sources}
    video_path_coverage = [
        {'path': source['path'], 'source_sha256': source['sha256'],
         'batch': source['batch'], 'canonical': source.get('is_canonical_video_path', True)}
        for source in sources
    ]
    for group in inventory.get('duplicate_groups', []):
        for alias in group.get('paths', []):
            if alias not in current_paths:
                parts = Path(alias).parts
                video_path_coverage.append({
                    'path': alias, 'source_sha256': group['sha256'],
                    'batch': parts[5] if len(parts) > 5 else 'unknown',
                    'canonical': False, 'same_sha256_duplicate': True,
                })
    source_preflight_failures = sum(row.get('stage') == 'source_preflight' for row in failures)
    summary = {'video_paths': inventory['summary']['original_video_paths'],
               'videos': len(sources), 'unique_sources': len(by_sha),
               'duplicate_excess_paths': inventory['summary']['duplicate_excess_paths'],
               'historically_registered_missing_paths': inventory['summary']['missing_original_paths_referenced_by_inventory'],
               'current_missing_original_paths': source_preflight_failures,
               'candidates': len(rows),
               'materialized': len(finished), 'unique_labels': len({r['proposed_text'] for r in rows}),
               'native_3d': sum(row.get('native_3d_available') is True for row in rows),
               'verified_native_sequences_available_for_candidate_crops': native_summary['verified_complete_sequences'],
               'context_windows': len(context), 'failures': len(failures),
               'training_ready': False, 'model_training_ready': False, 'source_files_modified': False,
               'verified_word_units': 0, 'all_video_words_extracted': False}
    report = {'schema': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(),
              'summary': summary, 'candidates': rows, 'coverage': coverage,
              'video_path_coverage': video_path_coverage,
              'duplicate_source_groups': inventory.get('duplicate_groups', []),
              'unresolved_legacy_source_paths': inventory.get('missing_original_paths', []),
              'native_sequence_evidence': native_summary,
              'limitations': ['Captions and instructional windows do not establish true CSL word boundaries.',
                             'Every output is a candidate; no source or motion-quality approval is promoted to semantic approval.',
                             'Videos without lexical evidence remain explicit gaps; no arbitrary sentence subdivision.',
                             'Nominal source timing is retained; original per-frame PTS are not claimed.',
                             'CE-CSL held-out data and future motion assets are not published.']}
    write_json(output / 'report.json', report)
    write_json(output / 'failures.json', failures)
    write_json(output / 'exclusions.json', exclusions)
    (output / 'candidates.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows))
    (output / 'caption-context.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in context))
    write_json(output / 'coverage.json', coverage)
    write_json(output / 'lexical-coverage.json', lexical_coverage(rows, context, lexicon))
    (output / 'reconstruction-queue.jsonl').write_text(''.join(json.dumps({
        'candidate_id': row['id'], 'label_candidate': row['proposed_text'],
        'source_sha256': row['source_sha256'], 'source_window_seconds': row['source_window_seconds'],
        'reference_clip': row['reference_clip'], 'clip_sha256': row['clip_sha256'],
        'decoded_frames': row['decoded_video']['frames'], 'fps': row['decoded_video']['fps'],
        'language_scope_status': row['language_scope_status'], 'review_flags': row['review_flags'],
        'purpose': 'independent_continuous_3d_reconstruction_after_candidate_window_review',
        'automatic_launch_allowed': False, 'text_verified': '', 'human_approved': False,
        'training_ready': False, 'model_training_ready': False,
    }, ensure_ascii=False) + '\n' for row in rows if row.get('reference_clip') and not row['native_3d_available']))
    snapshots = snapshot_inputs(inputs, output, {source['path'] for source in sources})
    write_json(output / 'input-snapshots.json', snapshots)
    write_json(output / 'inputs.json', inputs)
    write_json(output / 'runtime.json', {
        'python': sys.version, 'python_executable': sys.executable,
        'numpy': np.__version__, 'opencv': cv2.__version__, 'argv': sys.argv,
        'ffmpeg': subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, text=True).stdout.splitlines()[0],
        'ffprobe': subprocess.run(['ffprobe', '-version'], capture_output=True, check=True, text=True).stdout.splitlines()[0],
        'no_training_started': True, 'no_source_parameters_smoothed_or_filled': True,
    })
    review_report = {key: value for key, value in report.items() if key not in ('limitations', 'duplicate_source_groups', 'video_path_coverage', 'unresolved_legacy_source_paths', 'native_sequence_evidence')}
    review_report['summary'] = {**report['summary'], 'context_windows': 0}
    (output / 'review-data.js').write_text('globalThis.SIGNBRIDGE_WORD_MOTIONS = ' + json.dumps(review_report, ensure_ascii=True, allow_nan=False) + ';\n')
    (output / 'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.relative_to(output)}\n' for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--make-recipe', action='store_true')
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--dictionary', type=Path)
    parser.add_argument('--native-map', type=Path)
    parser.add_argument('--tutorial', type=Path, action='append', default=[])
    parser.add_argument('--recipe', type=Path)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 9))
    args = parser.parse_args()
    if args.audit and args.output:
        audit(args)
    elif args.make_recipe:
        if not all((args.inventory, args.dictionary, args.native_map, args.recipe)):
            parser.error('--make-recipe requires --inventory, --dictionary and --native-map')
        if args.recipe.exists():
            raise FileExistsError('Recipe already exists; select a new recipe path')
        write_json(args.recipe, recipe_from_inventory(json.loads(args.inventory.read_text()),
                   args.inventory.resolve(), args.dictionary.resolve(), args.native_map.resolve(),
                   [path.resolve() for path in args.tutorial]))
    elif args.output and args.recipe:
        build(args)
    else:
        parser.error('--output is required when building')


if __name__ == '__main__':
    main()
