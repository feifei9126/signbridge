"""Read-only hand-observation screening and masked research dataset snapshots."""
import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np


def tool(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = tool('sign-contact-audit')
motion = tool('sign-motion')
MEAN_ERROR_OVER_PALM_MAX = .75
WRIST_ERROR_PIXELS_MAX = 35.
PALM_PIXELS_MIN = 15.
DUPLICATE_MEAN_OVER_PALM_MAX = .25
DUPLICATE_WRIST_OVER_PALM_MAX = .35


def hand_screen(points, detected, projection, width, height):
    points, projection = np.asarray(points), np.asarray(projection)
    if type(detected) not in (bool, np.bool_) or points.shape != (21, 3) or \
            projection.shape != (21, 2) or width <= 0 or height <= 0 or not np.isfinite(projection).all():
        raise ValueError('Invalid hand observation/projection contract')
    result = {'observed': bool(detected), 'eligible_for_research_loss': False,
              'hand_shape_approved': False, 'mean_error_pixels': None, 'wrist_error_pixels': None,
              'palm_pixels': None, 'error_over_palm': None, 'reason': 'missing_observation'}
    if not detected:
        return result
    if not np.isfinite(points).all() or np.any(points[:, :2] < 0) or np.any(points[:, :2] > 1):
        result['reason'] = 'nonfinite_or_outside_observation'
        return result
    target = points[:, :2] * [width, height]
    palm = float(np.median(np.linalg.norm(target[[5, 9, 13, 17]] - target[0], axis=1)))
    errors = np.linalg.norm(target - projection, axis=1)
    result.update(mean_error_pixels=float(errors.mean()), wrist_error_pixels=float(errors[0]),
                  palm_pixels=palm, error_over_palm=float(errors.mean() / palm) if palm > 0 else None)
    if palm < PALM_PIXELS_MIN:
        result['reason'] = 'small_or_degenerate_hand'
    elif result['error_over_palm'] > MEAN_ERROR_OVER_PALM_MAX or errors[0] > WRIST_ERROR_PIXELS_MAX:
        result['reason'] = 'projection_disagreement'
    else:
        result.update(reason='automatic_projection_screen_passed', eligible_for_research_loss=True)
    return result


def stable_hand_mask(records):
    good = np.array([r['eligible_for_research_loss'] for r in records], dtype=bool)
    result = np.zeros(len(good), dtype=bool)
    if len(good) >= 3:
        result[1:-1] = good[:-2] & good[1:-1] & good[2:]
    return result


def exclude_duplicate_hands(left, right, left_record, right_record, width, height):
    records = [dict(left_record), dict(right_record)]
    if not all(r['observed'] and r['palm_pixels'] is not None and
               r['palm_pixels'] >= PALM_PIXELS_MIN for r in records):
        return tuple(records)
    a, b = np.asarray(left)[:, :2] * [width, height], np.asarray(right)[:, :2] * [width, height]
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        return tuple(records)
    palm = min(r['palm_pixels'] for r in records)
    separation = np.linalg.norm(a - b, axis=1)
    if separation.mean() <= DUPLICATE_MEAN_OVER_PALM_MAX * palm and \
            separation[0] <= DUPLICATE_WRIST_OVER_PALM_MAX * palm:
        for record in records:
            record.update(eligible_for_research_loss=False, reason='ambiguous_overlapping_observations',
                          side_assignment_unchanged=True)
    return tuple(records)


def feature_mask(left, right):
    if left.ndim != 1 or right.shape != left.shape or left.dtype.kind != 'b' or right.dtype.kind != 'b':
        raise ValueError('Invalid hand masks')
    mask = np.ones((len(left), 133), dtype=bool)
    mask[:, 30:75] = left[:, None]
    mask[:, 75:120] = right[:, None]
    return mask


def audit(args):
    delivery, batch, out = args.training_delivery.resolve(), args.batch.resolve(), args.output.resolve()
    if out.exists() or any(out == p or p in out.parents or out in p.parents for p in (delivery, batch)):
        raise ValueError('New output must be separate from inputs')
    checks = evidence.verify_manifest(delivery, delivery / 'SHA256SUMS')
    tasks = {r['segment_id']: r for r in motion.verify_pack(batch)}
    source = delivery / 'verified/motions'
    rows = motion.read_jsonl(source / 'motions.jsonl')
    train_report = evidence.load_json(delivery / 'verified/training/report.json')
    if [r['segment_id'] for r in rows] != [r['segment_id'] for r in train_report['sequences']]:
        raise ValueError('Motion scope differs from the retained training run')
    if any(r['segment_id'].startswith('new-') for r in rows):
        raise ValueError('Deferred new clips are outside this audit')
    out.mkdir(parents=True)
    screened, details = {}, []
    for row in rows:
        segment, count = row['segment_id'], row['frames']
        task = tasks[segment]
        if any(row[k] != task[k] for k in ('frames', 'source_id', 'source_sha256', 'fps')):
            raise ValueError('Source scope or timeline differs')
        image = evidence.contained_file(batch, task['images'] + '/000001.jpg')
        from PIL import Image
        with Image.open(image) as picture:
            width, height = picture.size
        path = delivery / 'review-media-v2' / (segment + '-joints.npz')
        if checks.get(str(path.relative_to(delivery))) != evidence.digest(path):
            raise ValueError('Reference projection was changed')
        with np.load(path, allow_pickle=False) as a:
            if not np.array_equal(a['frame_ids'], np.arange(1, count + 1)):
                raise ValueError('Reference projection frame identity differs')
            projections = {side: a[side + '_hand_projection'][:, 0].copy() for side in ('left', 'right')}
        observations = batch / 'samples' / segment / 'observations.npz'
        with np.load(observations, allow_pickle=False) as a:
            motion.data.validate_landmark_arrays(a, count)
            if not np.allclose(a['timestamps_seconds'], np.arange(count) / task['fps'], atol=1e-6, rtol=0):
                raise ValueError('Observation timeline differs')
            records = {side: [hand_screen(a[side + '_hand_image'][i], a[side + '_hand_image_detected'][i],
                         projections[side][i], width, height) for i in range(count)] for side in ('left', 'right')}
            for i in range(count):
                records['left'][i], records['right'][i] = exclude_duplicate_hands(
                    a['left_hand_image'][i], a['right_hand_image'][i], records['left'][i], records['right'][i],
                    width, height)
        masks = {side: stable_hand_mask(records[side]) for side in records}
        summaries = {}
        for side, entries in records.items():
            for i, entry in enumerate(entries):
                details.append({'segment_id': segment, 'frame_1based': i + 1, 'side': side,
                                **entry, 'three_adjacent_frames_passed': bool(masks[side][i])})
            errors = [x['mean_error_pixels'] for x in entries if x['mean_error_pixels'] is not None]
            summaries[side] = {'observed_frames': sum(x['observed'] for x in entries),
                'loss_frames': int(masks[side].sum()), 'excluded_frames': int(count - masks[side].sum()),
                'mean_projection_error_pixels': float(np.mean(errors)) if errors else None,
                'ambiguous_overlapping_frames': sum(x['reason'] == 'ambiguous_overlapping_observations' for x in entries),
                'projection_disagreement_frames': sum(x['reason'] == 'projection_disagreement' for x in entries)}
        screened[segment] = (masks, summaries)
        print(json.dumps({'segment_id': segment, 'frames': count, 'hands': summaries}), flush=True)
    snapshot = out / 'masked-motions'
    shutil.copytree(source, snapshot)
    for row in rows:
        masks, summaries = screened[row['segment_id']]
        folder = snapshot / 'samples' / row['segment_id']
        np.save(folder / 'feature-valid-mask.npy', feature_mask(masks['left'], masks['right']), allow_pickle=False)
        quality = evidence.load_json(folder / 'quality.json')
        quality.update(automatic_observation_screen=summaries, hand_shape_approved=False)
        motion.data.write_json(folder / 'quality.json', quality)
    verification = evidence.load_json(snapshot / 'verification.json')
    verification.update(schema='signbridge-hand-observation-screen-v1', quality_masks_required=True,
        training_ready=False, input_quality='Raw SMPLer-X fitted motion; hand targets excluded unless observed, bounded and projection-consistent for three adjacent frames; NOT human-approved hand truth.',
        parent_motion_manifest_sha256=evidence.digest(source / 'motions.jsonl'))
    motion.data.write_json(snapshot / 'verification.json', verification)
    report = {'schema': 'signbridge-hand-quality-audit-v1', 'status': 'automatic_screen_complete',
        'frames': sum(r['frames'] for r in rows), 'samples': len(rows), 'training_ready': False,
        'hand_shape_approved': False, 'parameters_modified': False, 'weights_modified': False,
        'thresholds': {'mean_error_over_palm_max': MEAN_ERROR_OVER_PALM_MAX,
            'wrist_error_pixels_max': WRIST_ERROR_PIXELS_MAX, 'palm_pixels_min': PALM_PIXELS_MIN,
            'ambiguous_mean_separation_over_palm_max': DUPLICATE_MEAN_OVER_PALM_MAX,
            'ambiguous_wrist_separation_over_palm_max': DUPLICATE_WRIST_OVER_PALM_MAX,
            'three_adjacent_observations_required': True},
        'hands': {segment: values[1] for segment, values in screened.items()},
        'source_delivery_sha256': evidence.digest(delivery / 'SHA256SUMS'),
        'source_batch_tasks_sha256': evidence.digest(batch / 'tasks.jsonl'),
        'audit_tool_sha256': evidence.digest(__file__),
        'limitations': ['Heuristic automatic screen, not a calibrated hand-accuracy threshold.',
                       'MediaPipe points and SMPL-X estimates are not independent ground truth.',
                       'Body/face dimensions remain model-estimated supervision.',
                       'Missing/rejected hand values remain unchanged; only model loss/input masks are changed.']}
    motion.data.write_json(out / 'report.json', report)
    motion.write_jsonl(out / 'frame-quality.jsonl', details)
    for root in (snapshot, out):
        (root / 'SHA256SUMS').write_text(''.join(evidence.digest(p) + '  ' + str(p.relative_to(root)) + '\n'
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    evidence.verify_manifest(delivery, delivery / 'SHA256SUMS')
    motion.verify_pack(batch)
    return out / 'report.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('training-delivery', 'batch', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    print(audit(parser.parse_args()))


if __name__ == '__main__':
    main()
