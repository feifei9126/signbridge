"""Audit revised unapproved video windows and prepare candidate-only reconstruction inputs."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import traceback

import numpy as np


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reference = load_tool('sign-tutorial-reference.py', 'refinement_reference')
data = reference.data
sequence = load_tool('sign-source-catchup-smplx.py', 'refinement_sequences')


def validate_revision(row, previous, duration):
    identity = row.get('annotation_id')
    if not isinstance(identity, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', identity) is None:
        raise ValueError('Unsafe annotation ID')
    if any(row.get(k) != previous.get(k) for k in ('annotation_id', 'source_id', 'source_sha256')):
        raise ValueError('Revision source differs')
    if (row.get('revision_of_annotation_id') != identity or
            row.get('previous_label_candidate') != previous.get('label') or
            row.get('previous_window_seconds') != [previous.get('start_seconds'), previous.get('end_seconds')]):
        raise ValueError('Revision is not bound to the prior candidate')
    for flag in ('human_approved', 'semantics_approved', 'boundaries_approved', 'training_ready',
                 'model_training_ready', 'smplx_parameters_created'):
        if row.get(flag) is not False:
            raise ValueError('Do not promote unreviewed labels or training: ' + flag)
    if (row.get('text_verified') != '' or row.get('mirror_status') != 'unknown' or
            row.get('language') != 'unconfirmed' or row.get('split') != 'unassigned' or
            row.get('boundary_review') != 'assistant_visual_coarse' or not row.get('boundary_note') or
            not isinstance(row.get('label'), str) or not row['label'].strip()):
        raise ValueError('Explicit coarse proposal and unreviewed metadata are required')
    start, end = row.get('start_seconds'), row.get('end_seconds')
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end, duration)) or not 0 <= start < end <= duration:
        raise ValueError('Invalid proposed source boundaries')
    if type(row.get('frames')) is not int or row['frames'] < 4 or row.get('fps') != 25.:
        raise ValueError('Actual decoded frame count and 25 FPS are required')
    return row


def observation_coverage(left, right, left_mask, right_mask, width, height):
    arrays, masks = (np.asarray(left), np.asarray(right)), (np.asarray(left_mask), np.asarray(right_mask))
    n = len(arrays[0])
    for values, mask in zip(arrays, masks):
        if (values.shape != (n, 21, 3) or mask.shape != (n,) or mask.dtype != np.bool_ or
                not np.array_equal(np.isfinite(values).all(axis=(1, 2)), mask) or
                not np.isnan(values[~mask]).all()):
            raise ValueError('Missing observations must keep their original NaN/mask contract')
    flags = [reference.reference_hand_flags(arrays[0][i], arrays[1][i], masks[0][i], masks[1][i], width, height) for i in range(n)]
    return {'frames': n, 'detected_frames': {side: int(mask.sum()) for side, mask in zip(('left', 'right'), masks)},
            'eligible_frames': {side: sum(row[side]['eligible_for_2d_fit'] for row in flags) for side in ('left', 'right')},
            'any_hand_detected_frames': int((masks[0] | masks[1]).sum()),
            'both_hands_detected_frames': int((masks[0] & masks[1]).sum()),
            'anatomical_handedness_verified': False, 'hand_absence_is_not_an_error_label': True}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def seal_candidate_package(root):
    (root / 'SHA256SUMS').write_text(''.join(data.sha256_file(p) + '  ' + str(p.relative_to(root)) + '\n'
        for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    return sequence.validate_package(root)


def prepare(args):
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    batch, pack, output = (p.resolve() for p in (args.batch, args.references, args.output))
    if output.exists() or output == batch or output in pack.parents or pack in output.parents:
        raise ValueError('New output separate from the reference attempt required')
    watched = {}

    def watch(path, expected=None):
        path = Path(path).resolve()
        value = data.sha256_file(path)
        if expected and value != expected:
            raise ValueError('Changed input artifact: ' + str(path))
        watched[str(path)] = value
        return path

    def artifact(root, relative, expected=None):
        path = (root / relative).resolve()
        if Path(relative).is_absolute() or root not in path.parents:
            raise ValueError('Unsafe input artifact path')
        return watch(path, expected)

    baseline = json.loads(watch(batch / 'validation.json').read_text())
    intake = json.loads(watch(batch / 'intake-v1/sources.json').read_text())
    attempt = json.loads(watch(pack / 'report.json').read_text())
    rows = sequence.read_jsonl(watch(pack / 'references.jsonl'))
    sources = {row['source_id']: row for row in intake['sources']}
    previous = {row['annotation_id']: row for row in baseline['references']}
    if (baseline.get('status') != 'passed' or attempt.get('status') != 'completed_pending_quality_review' or
            attempt.get('samples') != len(rows) or attempt.get('frames') != sum(r['frames'] for r in rows) or
            attempt.get('human_approved') is not False or attempt.get('training_ready') is not False or
            set(previous) != {row['annotation_id'] for row in rows} or len(rows) != len(previous)):
        raise ValueError('All revised reference sequences must have completed without approval')
    checksums = watch(pack / 'SHA256SUMS')
    for line in checksums.read_text().splitlines():
        digest, relative = line.split('  ', 1)
        artifact(pack, relative, digest)
    output.mkdir(parents=True)
    package = output / 'package'
    package.mkdir()
    records, cases = [], []
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 17)
    for row in rows:
        old = previous[row['annotation_id']]
        source = sources[row['source_id']]
        validate_revision(row, old, source['duration_seconds'])
        if source.get('authorization_status') != 'user_reported' or source['sha256'] != row['source_sha256']:
            raise ValueError('Source authorization/provenance differs')
        artifact(Path(intake['source_root']).resolve(), source['relative_path'], source['sha256'])
        if row.get('previous_clip_sha256') != old['artifacts']['clip.mp4']['sha256']:
            raise ValueError('Old clip digest differs')
        for item in old['artifacts'].values():
            artifact(batch, item['path'], item['sha256'])
        visual = row['visual_evidence']
        artifact(batch, visual['path'], visual['sha256'])
        all_assets = {name: {'path': str(artifact(pack, path).relative_to(batch)),
                             'sha256': data.sha256_file(pack / path)} for name, path in row['artifacts'].items()}
        landmarks = batch / all_assets['landmarks.npz']['path']
        with np.load(landmarks, allow_pickle=False) as arrays:
            data.validate_landmark_arrays(arrays, row['frames'])
            if (not np.allclose(arrays['timestamps_seconds'], np.arange(row['frames']) / 25.) or
                    not np.allclose(arrays['source_timestamps_seconds'], arrays['timestamps_seconds'] + row['start_seconds'])):
                raise ValueError('Reference nominal time map differs')
            coverage = observation_coverage(arrays['left_hand_image'], arrays['right_hand_image'],
                arrays['left_hand_image_detected'], arrays['right_hand_image_detected'], row['width'], row['height'])
        with np.load(batch / old['artifacts']['landmarks.npz']['path'], allow_pickle=False) as arrays:
            data.validate_landmark_arrays(arrays, old['frames'])
            old_coverage = observation_coverage(arrays['left_hand_image'], arrays['right_hand_image'],
                arrays['left_hand_image_detected'], arrays['right_hand_image_detected'], old['width'], old['height'])
        if coverage['eligible_frames'] != row['usable_hand_observation_frames']:
            raise ValueError('Hand coverage summary differs from actual frames')
        for name in ('clip.mp4', 'overlay.mp4'):
            capture = cv2.VideoCapture(str(batch / all_assets[name]['path']))
            if not capture.isOpened() or abs(capture.get(cv2.CAP_PROP_FPS) - 25.) > 1e-6:
                raise ValueError('Reference video does not decode at 25 FPS')
            count = 0
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                if image.shape[:2] != (row['height'], row['width']):
                    raise ValueError('Reference frame dimensions differ')
                count += 1
            capture.release()
            if count != row['frames']:
                raise ValueError('Actual decoded video frames differ')
        # Kept frames are real video frames; sheets are review evidence, not 3D labels.
        sheet = Image.new('RGB', (1080, 65 + 3 * 510), 'white')
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 5), row['label'], font=font, fill='black')
        draw.text((8, 33), 'Assistant visual proposal / NOT human-approved', font=font, fill='black')
        capture = cv2.VideoCapture(str(batch / all_assets['clip.mp4']['path']))
        for index in range(9):
            frame = round(index * (row['frames'] - 1) / 8)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, image = capture.read()
            if not ok:
                raise ValueError('Review frame decode failed')
            preview = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            preview.thumbnail((350, 475))
            x, y = index % 3 * 360, 65 + index // 3 * 510
            sheet.paste(preview, (x, y))
            draw.text((x + 4, y + 477), f'{frame + 1} / nominal source {row["start_seconds"] + frame / 25.:.2f}s', font=font, fill='black')
        capture.release()
        sheet_path = output / 'sheets' / (row['annotation_id'] + '.jpg')
        sheet_path.parent.mkdir(exist_ok=True)
        sheet.save(sheet_path, quality=90)
        review_flags = [side + '_low_2d_observation_coverage' for side in ('left', 'right')
                        if coverage['eligible_frames'][side] / row['frames'] < .2]
        if source['duration_seconds'] - row['end_seconds'] < .5:
            review_flags.append('source_end_near_boundary_check_motion_completion')
        actual_duration = row['frames'] / 25.
        nominal_duration = row['end_seconds'] - row['start_seconds']
        if abs(actual_duration - nominal_duration) > .041:
            review_flags.append('actual_video_duration_differs_from_nominal_cut_window')
        record = {**row, 'artifacts': all_assets, 'previous_reference': old,
                  'coverage_before': old_coverage, 'coverage_after': coverage,
                  'actual_duration_seconds': actual_duration, 'nominal_window_duration_seconds': nominal_duration,
                  'review_flags': review_flags, 'keyframe_sheet': {'path': str(sheet_path.relative_to(batch)),
                  'sha256': data.sha256_file(sheet_path)}, 'model_training_ready': False}
        records.append(record)
        clip_target = package / 'clips' / row['annotation_id'] / 'clip.mp4'
        clip_target.parent.mkdir(parents=True)
        shutil.copy2(batch / all_assets['clip.mp4']['path'], clip_target)
        observation_target = clip_target.with_name('observations.npz')
        shutil.copy2(landmarks, observation_target)
        frame_map = clip_target.with_name('frames.jsonl')
        sequence.write_jsonl(frame_map, [{'frame_1based': i + 1, 'clip_seconds': i / 25.,
            'source_seconds_nominal': row['start_seconds'] + i / 25., 'interpolated': False,
            'observation_representation': 'mediapipe-2d-reference-only'} for i in range(row['frames'])])
        case = sequence.build_case_records([{**row, 'clip': str(clip_target.relative_to(package)),
            'clip_sha256': data.sha256_file(clip_target)}], [])[0]
        cases.append(case)
        print(json.dumps({'id': row['annotation_id'], 'frames': row['frames'],
            'before_any_fraction': old_coverage['any_hand_detected_frames'] / old['frames'],
            'after_any_fraction': coverage['any_hand_detected_frames'] / row['frames'],
            'review_flags': review_flags}, ensure_ascii=False), flush=True)
    sequence.write_jsonl(package / 'sequences.jsonl', cases)
    sequence.write_jsonl(package / 'keyframes.jsonl', [])
    write_json(package / 'manifest.json', {'schema': 'signbridge-smplerx-candidate-sequences-v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'source_reference_index_sha256': data.sha256_file(pack / 'references.jsonl'),
        'sequence_count': len(cases), 'frames': sum(row['frames'] for row in cases), 'fps': 25., 'keyframe_count': 0,
        'frames_are_temporally_contiguous_within_sequence': True, 'text_verified_count': 0,
        'human_approved': False, 'training_ready': False, 'training_started': False, 'source_files_modified': False,
        'observation_representation': 'mediapipe-2d-reference-only',
        'nominal_source_times_not_exact_original_pts': True, 'purpose': 'experimental reconstruction candidates; no training promotion'})
    seal_candidate_package(package)
    for path, expected in watched.items():
        if data.sha256_file(path) != expected:
            raise ValueError('Input changed during refinement audit')
    low = sum(any(flag.endswith('_low_2d_observation_coverage') for flag in row['review_flags']) for row in records)
    old_any = sum(r['coverage_before']['any_hand_detected_frames'] for r in records)
    new_any = sum(r['coverage_after']['any_hand_detected_frames'] for r in records)
    before_frames = sum(r['previous_reference']['frames'] for r in records)
    new_frames = sum(r['frames'] for r in records)
    report = {'schema': 'signbridge-reference-refinement-report-v1', 'status': 'audited_pending_human_review',
        'samples': len(records), 'frames': new_frames, 'previous_frames': before_frames, 'low_hand_observation_samples': low,
        'previous_low_hand_observation_samples': baseline['low_hand_observation_samples'],
        'before_any_hand_detected_frames': old_any, 'after_any_hand_detected_frames': new_any,
        'before_any_hand_fraction': old_any / before_frames, 'after_any_hand_fraction': new_any / new_frames,
        'same_frames_compared': False, 'comparison_meaning': 'Different proposed windows, same detector configuration; measures selected movement content, not detector accuracy.',
        'input_validation_sha256': data.sha256_file(batch / 'validation.json'), 'references': records,
        'input_reference_attempt_sha256': data.sha256_file(pack / 'report.json'),
        'package': str(package.relative_to(batch)), 'package_manifest_sha256': data.sha256_file(package / 'manifest.json'),
        'tool_sha256': data.sha256_file(__file__), 'inputs': [{'path': path, 'sha256': digest} for path, digest in watched.items()],
        'training_ready': False, 'model_training_ready': False, 'human_approved': False,
        'training_started': False, 'smplx_parameters_created': False, 'source_files_modified': False,
        'limitations': ['Assistant visual coarse boundaries and caption proposals require review; not certified signing.',
                       'Some source videos end during or close to motion; inspect completion before fitting or training.',
                       'Missing hand observations stay NaN with original masks. One-handed signing is not automatically erroneous.',
                       'Cropped source times are nominal 25 FPS mappings, not exact original video presentation timestamps.']}
    write_json(output / 'report.json', report)
    for root in (package, output):
        (root / 'SHA256SUMS').write_text(''.join(data.sha256_file(p) + '  ' + str(p.relative_to(root)) + '\n'
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('batch', 'references', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    fresh_output = not args.output.exists()
    try:
        report = prepare(args)
    except Exception as error:
        if fresh_output and args.output.is_dir():
            write_json(args.output / 'failure.json', {'status': 'failed_preserved_not_ready', 'error_type': type(error).__name__,
                'error': str(error), 'traceback': traceback.format_exc(), 'training_ready': False,
                'training_started': False, 'retry_requires_new_output': True})
        raise
    print(json.dumps({k: report[k] for k in ('samples', 'frames', 'low_hand_observation_samples', 'before_any_hand_fraction', 'after_any_hand_fraction', 'package')}, ensure_ascii=False))
