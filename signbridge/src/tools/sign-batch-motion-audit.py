"""Read-only motion and checkpoint triage from an explicit frozen cross-batch plan."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import cv2
import numpy as np


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


audit = load_tool('sign-candidate-fit-review.py', 'batch_native_audit')


def source_batches(row):
    aliases = row.get('aliases', []) + [row.get('relative_path', '')]
    return sorted({int(path.split('/')[0]) for path in aliases if path.split('/')[0] in list('123456')})


def risk_level(errors, flags):
    return 'technical_error' if errors else 'high_priority_review' if flags else 'no_automatic_red_flag'


def temporal_metrics(poses, numbers):
    poses = np.asarray(poses, np.float64)
    if not len(poses):
        return {'adjacent_p95_deg': None, 'midpoint_residual_p95_deg': None, 'max_adjacent_deg': None,
                'large_jump_frames': [], 'isolated_spike_frames': [], 'worst_frames': []}
    rotations = np.array([cv2.Rodrigues(v)[0] for v in poses.reshape(-1, 3)]).reshape(len(poses), -1, 3, 3)
    numbers = np.asarray(numbers)
    if len(numbers) != len(poses) or np.any(np.diff(numbers) <= 0):
        raise ValueError('Increasing original frame numbers required')
    adjacent = []; residuals = []; large = []; spikes = []; scored = []
    def angle(matrix):
        return np.degrees(np.arccos(np.clip((np.trace(matrix, axis1=-2, axis2=-1) - 1) / 2, -1, 1)))
    for i in range(1, len(poses)):
        if numbers[i] != numbers[i - 1] + 1:
            continue
        values = angle(rotations[i - 1].swapaxes(-1, -2) @ rotations[i])
        adjacent.extend(values.tolist())
        if np.any(values > 90): large.append(int(numbers[i]))
    for i in range(1, len(poses) - 1):
        if numbers[i] != numbers[i - 1] + 1 or numbers[i + 1] != numbers[i] + 1:
            continue
        relative = rotations[i - 1].swapaxes(-1, -2) @ rotations[i + 1]
        halves = np.array([cv2.Rodrigues(cv2.Rodrigues(r)[0] * .5)[0] for r in relative])
        midpoint = rotations[i - 1] @ halves
        values = angle(midpoint.swapaxes(-1, -2) @ rotations[i])
        residuals.extend(values.tolist()); maximum = float(values.max())
        scored.append({'frame_1based': int(numbers[i]), 'residual_max_deg': maximum})
        if maximum > 30: spikes.append(int(numbers[i]))
    return {'adjacent_p95_deg': float(np.percentile(adjacent, 95)) if adjacent else None,
            'midpoint_residual_p95_deg': float(np.percentile(residuals, 95)) if residuals else None,
            'max_adjacent_deg': float(max(adjacent)) if adjacent else None,
            'large_jump_frames': large, 'isolated_spike_frames': spikes,
            'worst_frames': sorted(scored, key=lambda r: -r['residual_max_deg'])[:5]}


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                             '-show_entries', 'stream=avg_frame_rate,nb_read_frames', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=90)
    if result.returncode: raise ValueError('video_decode_failed: ' + result.stderr[-300:])
    stream = json.loads(result.stdout)['streams'][0]
    a, b = map(int, stream['avg_frame_rate'].split('/'))
    return {'frames': int(stream['nb_read_frames']), 'fps': a / b}


def native_case(case, mean, output):
    fit = Path(case['fit']); n = case['frames']; errors = []; flags = []; notes = []
    params = {}; tracks = {}; invalid = []; hashes = []
    for path in sorted((fit / 'smplx').glob('*.npz')):
        digest = audit.sha(path); hashes.append({'path': str(path), 'sha256': digest})
        match = re.fullmatch(r'(\d{5})_(\d+)\.npz', path.name)
        if not match or not 1 <= int(match[1]) <= n:
            invalid.append(path.name); continue
        frame, person = map(int, match.groups()); tracks.setdefault(frame, []).append(person)
        try:
            with np.load(path, allow_pickle=False) as a:
                values = {key: a[key].copy() for key in audit.NATIVE_SHAPES}
            for key, shape in audit.NATIVE_SHAPES.items():
                if values[key].shape != shape or values[key].dtype.kind != 'f' or not np.isfinite(values[key]).all():
                    raise ValueError(key)
            if person == 0: params[frame] = values
        except Exception as exc:
            invalid.append(path.name + ': ' + str(exc)); continue
        meta = fit / 'meta' / (path.stem + '.json')
        if not meta.is_file(): errors.append('missing_metadata:' + path.stem); continue
        info = json.loads(meta.read_text()); img = Path(info.get('img_path', ''))
        hashes.append({'path': str(meta), 'sha256': audit.sha(meta)})
        if (img.name not in (f'{frame:06d}.jpg', f'{frame:05d}.jpg')
                or case['id'] not in img.parts or info.get('bbox_id', person) != person):
            errors.append('metadata_mapping:' + path.stem)
    missing = sorted(set(range(1, n + 1)) - set(tracks)); multi = sorted(i for i, p in tracks.items() if p != [0])
    if missing: errors.append('missing_native_frames')
    if multi: errors.append('ambiguous_person_tracks')
    if invalid: errors.append('invalid_native_parameters')
    expected_meta = {p.stem + '.json' for p in (fit / 'smplx').glob('*.npz')}
    if {p.name for p in (fit / 'meta').glob('*.json')} != expected_meta: errors.append('metadata_set_differs')
    numbers = sorted(params)
    metrics = {}
    for key in ['global_orient', 'body_pose', 'left_hand_pose', 'right_hand_pose']:
        values = np.stack([params[i][key] for i in numbers]) if numbers else np.empty((0, 3))
        metrics[key] = temporal_metrics(values, numbers)
    for side in ['body_pose', 'left_hand_pose', 'right_hand_pose']:
        metric = metrics[side]
        if metric['large_jump_frames']: flags.append(side + ':rotation_jumps_over_90deg')
        if metric['isolated_spike_frames']: flags.append(side + ':midpoint_spikes_over_30deg')
        if (metric['midpoint_residual_p95_deg'] or 0) > 10: flags.append(side + ':residual_p95_over_10deg')
    renders = fit / 'img'; decoded = 0; broken = []; actual_renders = {p.name for p in renders.glob('*.jpg')}
    expected = {f'{i:06d}.jpg' for i in range(1, n + 1)}
    if actual_renders != expected: errors.append('render_frame_set_differs')
    for path in sorted(renders.glob('*.jpg')):
        image = cv2.imread(str(path))
        if image is None: broken.append(path.name)
        else: decoded += 1
    if broken: errors.append('render_decode_failed')
    clip_info = None
    if case.get('clip'):
        clip = Path(case['clip'])
        if clip.is_file():
            if case.get('clip_sha256') and audit.sha(clip) != case['clip_sha256']: errors.append('input_clip_hash_mismatch')
            try:
                clip_info = probe(clip)
                if clip_info['frames'] != n or abs(clip_info['fps'] - case['fps']) > .01: errors.append('clip_frame_fps_mismatch')
            except Exception as exc: errors.append(str(exc))
        else: notes.append('source_clip_unavailable')
    complete = not missing and not multi and not invalid and len(params) == n
    pose_asset = None
    if complete:
        pose = np.zeros((n, 55, 3), np.float32)
        for j, i in enumerate(numbers):
            pose[j, 12:22] = params[i]['body_pose'][11:21]
            pose[j, 22] = params[i]['jaw_pose'][0]
            pose[j, 25:40] = params[i]['left_hand_pose']; pose[j, 40:55] = params[i]['right_hand_pose']
        pose += mean
        pose_asset = 'poses/' + case['uid'] + '.json'
        audit.sequence.write_json(output / pose_asset, {'id': case['uid'], 'text': case['text'], 'frames': n,
            'fps': case['fps'], 'poses': np.round(pose, 6).tolist(), 'experimental': True})
    checksum_path = output / 'native-checksums' / (case['uid'] + '.json')
    audit.sequence.write_json(checksum_path, hashes)
    return {**case, 'kind': 'native', 'errors': sorted(set(errors)), 'risk_flags': sorted(set(flags)),
            'notes': notes + case.get('limitations', []), 'missing_frames': missing, 'multiple_person_frames': multi,
            'invalid_parameters': invalid, 'native_parameter_files': len(list((fit / 'smplx').glob('*.npz'))),
            'fitted_frames': len(tracks), 'render_frames_decoded': decoded, 'broken_render_frames': broken,
            'input_clip_probe': clip_info, 'metrics': metrics, 'display_pose_asset': pose_asset,
            'status': risk_level(errors, flags), 'native_files_manifest': str(checksum_path.relative_to(output))}


def reference_case(case):
    path = Path(case['landmarks']); flags = []; errors = []; coverage = {}; jumps = {}
    with np.load(path, allow_pickle=False) as a:
        for side in ['left', 'right']:
            key = side + '_hand_image'; mask_key = side + '_hand_detected'
            if key not in a: key = side + '_hand'
            if mask_key not in a: mask_key = side + '_hand_image_detected'
            values = a[key]; mask = a[mask_key]
            if values.shape != (case['frames'], 21, 3) or mask.shape != (case['frames'],): errors.append(side + ':shape_mismatch'); continue
            valid = np.isfinite(values).all(axis=(1, 2))
            if not np.array_equal(mask, valid) or not np.isnan(values[~mask]).all(): errors.append(side + ':missing_mask_nan_mismatch')
            coverage[side] = int(mask.sum()) / len(mask)
            if coverage[side] < .2: flags.append(side + ':low_2d_hand_coverage')
            pairs = mask[:-1] & mask[1:]
            distances = np.linalg.norm(np.diff(values[:, :, :2], axis=0), axis=-1)
            d = distances[pairs]
            jumps[side] = float(np.percentile(d, 95)) if d.size else None
    return {**case, 'kind': 'reference2d', 'errors': errors, 'risk_flags': flags,
            'status': 'not_3d_reconstructed' if not errors else 'technical_error', 'hand_coverage': coverage,
            'observed_2d_step_p95_normalized_image': jumps, 'artifact_sha256': audit.sha(path),
            'limitations': ['2D motion is not a 3D target; missing slots are not evidence of incorrect sign language.']}


def run(args):
    plan_path = Path(args.plan).resolve(); plan = json.loads(plan_path.read_text()); output = Path(args.output).resolve()
    if output.exists(): raise ValueError('Use a new output; never overwrite evidence')
    model = Path(plan['smplx_model'])
    if audit.sha(model) != '376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992': raise ValueError('Pinned body model hash differs')
    with np.load(model, allow_pickle=False) as a:
        mean = np.zeros((55, 3), np.float32); mean[25:40] = a['hands_meanl'].reshape(15, 3); mean[40:55] = a['hands_meanr'].reshape(15, 3)
        rest = np.asarray(a['J_regressor'] @ a['v_template'], np.float32); parents = a['kintree_table'][0].astype(np.int32); parents[0] = -1
    output.mkdir(parents=True); (output / 'poses').mkdir(); (output / 'native-checksums').mkdir()
    results = []
    for i, case in enumerate(plan['cases']):
        try: result = native_case(case, mean, output) if case['kind'] == 'native' else reference_case(case)
        except Exception as exc: result = {**case, 'status': 'technical_error', 'errors': [str(exc)], 'risk_flags': []}
        results.append(result)
        with (output / 'progress.jsonl').open('a') as stream: stream.write(json.dumps({'case': i + 1, 'uid': case['uid'], 'status': result['status']}) + '\n')
        if (i + 1) % 10 == 0: print(json.dumps({'done': i + 1, 'total': len(plan['cases'])}), flush=True)
    audit.sequence.write_json(output / 'native-review.json', {'schema': 'signbridge-cross-batch-native-audit-v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'plan_sha256': audit.sha(plan_path), 'tool_sha256': audit.sha(__file__),
        'model_sha256': audit.sha(model), 'restJoints': rest.tolist(), 'parents': parents.tolist(), 'records': results,
        'thresholds_are_triage_not_sign_accuracy': True, 'thresholds': {'jump_deg': 90, 'isolated_residual_deg': 30, 'p95_residual_deg': 10},
        'human_approved': False, 'training_ready': False, 'model_training_ready': False, 'sources_modified': False})
    print(json.dumps({'output': str(output), 'cases': len(results), 'technical_errors': sum(r['status'] == 'technical_error' for r in results)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
