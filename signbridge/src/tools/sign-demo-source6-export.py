"""Export complete source-6 native fits for a separate unapproved avatar preview."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_tool('sign-candidate-fit-review.py', 'source6_preview_audit')
experimental = load_tool('sign-demo-experimental-export.py', 'source6_preview_export')


def display_pose(native, mean):
    for name, shape in audit.NATIVE_SHAPES.items():
        value = native.get(name)
        if (value is None or value.shape != shape or value.dtype.kind != 'f'
                or not np.isfinite(value).all()):
            raise ValueError('Invalid complete native parameter: ' + name)
    if mean.shape != (55, 3) or not np.isfinite(mean).all() or np.any(mean[:25]):
        raise ValueError('Only the pinned hand mean can be added to displayed poses')
    pose = np.zeros((55, 3), np.float32)
    pose[12:22] = native['body_pose'][11:21]
    pose[22] = native['jaw_pose'][0]
    pose[25:40] = native['left_hand_pose']
    pose[40:55] = native['right_hand_pose']
    return pose + mean


def read_sequence(folder, frames, mean):
    inventory = audit.native_inventory(folder, frames)
    if not inventory['complete_single_person']:
        raise ValueError('Preview requires a complete single-person native sequence')
    rows = []
    checksums = []
    for number in range(1, frames + 1):
        path = Path(folder) / f'{number:05d}_0.npz'
        with np.load(path, allow_pickle=False) as native:
            rows.append(display_pose(dict(native), mean))
        checksums.append({'file': path.name, 'sha256': audit.sha(path)})
    return np.stack(rows), checksums


def validate_candidate(row):
    if (row.get('text_verified') != '' or not row.get('label_candidate', '').strip()
            or any(row.get(k) is not False for k in ('human_approved', 'training_ready', 'model_training_ready'))
            or row.get('native_parameter_inventory', {}).get('complete_single_person') is not True
            or not isinstance(row.get('frames_expected'), int) or not 4 <= row['frames_expected'] <= 2000):
        raise ValueError('Expected an unapproved, complete native candidate')


def export(args):
    package, review, pilot, remaining, model, output = [
        Path(getattr(args, key)).resolve() for key in
        ('package', 'review', 'pilot_results', 'remaining_results', 'smplx_model', 'output')]
    inputs = (package, review, pilot, remaining, model.parent)
    if output.exists() or any(output == p or output in p.parents or p in output.parents for p in inputs):
        raise ValueError('Use a new preview output separate from existing evidence')
    if audit.sha(model) != experimental.MODEL_SHA:
        raise ValueError('Pinned SMPL-X model hash differs')
    manifest, cases, _, manifest_sha = audit.sequence.validate_package(package)
    audit.verify_checksums(review)
    report_path = review / 'report.json'
    report = json.loads(report_path.read_text())
    if (report.get('status') != 'structural_audit_passed_motion_quality_unreviewed'
            or report.get('input_manifest_sha256') != manifest_sha
            or report.get('training_started') is not False
            or any(report.get(k) is not False for k in ('human_approved', 'training_ready', 'model_training_ready'))
            or report.get('sequences') != len(cases) or report.get('frames') != manifest['frames']):
        raise ValueError('Source-6 structural review/input contract differs')
    records = {r['annotation_id']: r for r in report['records']}
    if len(records) != len(cases) or set(records) != {r['annotation_id'] for r in cases}:
        raise ValueError('Exact candidate sequence IDs required')
    roots = {}
    result_hashes = {}
    for root in (pilot, remaining):
        audit.verify_checksums(root)
        result_hashes[str(root)] = audit.sha(root / 'SHA256SUMS')
        run = json.loads((root / 'report.json').read_text())
        subset, subset_cases, _, subset_sha = audit.sequence.validate_package(
            root.parent / ('pilot-package' if root == pilot else 'remaining-package'))
        if (run.get('input_manifest_sha256') != subset_sha or subset.get('parent_manifest_sha256') != manifest_sha
                or run.get('status') != 'smplerx_sequences_completed_pending_quality_review'
                or run.get('training_started') is not False):
            raise ValueError('Inference attempt/package provenance differs')
        for case in subset_cases:
            sid = case['annotation_id']
            if case not in cases or sid in roots:
                raise ValueError('Overlapping or changed candidate sequence')
            roots[sid] = root
    if set(roots) != set(records):
        raise ValueError('Native attempts do not exactly cover candidate review')
    with np.load(model, allow_pickle=False) as assets:
        mean = np.zeros((55, 3), np.float32)
        mean[25:40] = assets['hands_meanl'].reshape(15, 3)
        mean[40:55] = assets['hands_meanr'].reshape(15, 3)
        rest = np.asarray(assets['J_regressor'] @ assets['v_template'], np.float32)
        parents = assets['kintree_table'][0].astype(np.int32)
        parents[0] = -1
    output.mkdir(parents=True)
    (output / 'experimental').mkdir()
    (output / 'provenance').mkdir()
    clips = []
    for case in cases:
        sid = case['annotation_id']
        record = records[sid]
        validate_candidate(record)
        if record['frames_expected'] != case['frames'] or record['source_sha256'] != case['source_sha256']:
            raise ValueError('Review source/frame count differs: ' + sid)
        root = roots[sid]
        poses, checksums = read_sequence(root / 'fits' / sid / 'smplx', case['frames'], mean)
        metadata = sorted((root / 'fits' / sid / 'meta').glob('*.json'))
        if {p.name for p in metadata} != {f'{n:05d}_0.json' for n in range(1, case['frames'] + 1)}:
            raise ValueError('Exact native metadata frame/person set differs: ' + sid)
        launch = json.loads((root.parent / ('launch.json' if root == pilot else 'remaining-launch.json')).read_text())
        for n in range(1, case['frames'] + 1):
            audit.validate_metadata(json.loads((root / 'fits' / sid / 'meta' / f'{n:05d}_0.json').read_text()),
                                    launch['output'], sid, n, 0)
        frame_map = package / 'clips' / sid / 'frames.jsonl'
        audit.validate_frame_map(audit.sequence.read_jsonl(frame_map), case)
        fit_digest = hashlib.sha256(json.dumps(checksums, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        effective_digest = hashlib.sha256(poses.astype('<f4').tobytes()).hexdigest()
        identity = 'source6-' + sid
        flags = record['review_flags']
        maximum = max(record['raw_quality_metrics'][name]['adjacent_degrees']['maximum']
                      for name in ('smplx_body_pose', 'smplx_lhand_pose', 'smplx_rhand_pose'))
        clip = {
            'id': identity, 'text': case['label_candidate'], 'aliases': [case['label_candidate']],
            'fps': case['fps'], 'frames': case['frames'], 'experimental': True,
            'model_output': 'smplx_fit_demo', 'source_id': case['source_id'],
            'source_sha256': case['source_sha256'], 'feature_sha256': effective_digest,
            'feature_digest_representation': 'effective-display-pose-float32-le; not tokenizer features',
            'fitted_sha256': fit_digest, 'training_data_member': False, 'human_approved': False,
            'training_ready': False, 'model_training_ready': False, 'motion_review_status': 'needs_review',
            'mirror_status': 'unknown', 'signer_id': 'unconfirmed', 'language': 'unconfirmed',
            'split': 'unassigned', 'quality_warning': maximum > 90,
            'max_adjacent_rotation_degrees': maximum, 'source_batch': 'source-6', 'preview_only': True,
            'text_verified': '', 'semantics_approved': False, 'boundaries_approved': False,
            'temporal_interpolation': False, 'source_annotation_id': sid,
            'source_clip_sha256': case['clip_sha256'], 'source_frames_sha256': audit.sha(frame_map),
            'source_fit_manifest_sha256': fit_digest, 'boundary_review_flags': flags,
            'source_window_seconds_nominal': [case['start_seconds'], case['end_seconds']],
            'source_times_not_original_pts_exact': True,
            'quality_warning_reason': 'Unreviewed hands and coarse boundaries; adjacent-angle threshold is not a quality approval.',
        }
        relative = 'experimental/' + identity + '.json'
        experimental.write_json(output / relative, {'schema': 'signbridge-experimental-clip-v1',
                                                    **clip, 'poses': np.round(poses, 6).tolist()})
        experimental.write_json(output / 'provenance' / (identity + '.json'), {
            'native_files': checksums, 'native_manifest_sha256': fit_digest,
            'pose_float32_sha256': effective_digest, 'result_checksum_manifest_sha256': result_hashes[str(root)],
            'review_report_sha256': audit.sha(report_path), 'source_clip_sha256': case['clip_sha256'],
            'training_ready': False, 'model_training_ready': False, 'human_approved': False})
        clips.append({**clip, 'asset': relative, 'sha256': audit.sha(output / relative)})
    index = {
        'schema': 'signbridge-experimental-motion-index-v1', 'representation': 'effective-smplx-55-axis-angle',
        'smplx_rest_model_sha256': experimental.MODEL_SHA, 'training_weights_updated': False,
        'text_to_sign_trained': False, 'training_ready': False, 'model_training_ready': False,
        'research_only': True, 'parents': parents.tolist(), 'restJoints': np.round(rest, 7).tolist(),
        'clips': clips, 'input_sequences': len(cases), 'frames': sum(c['frames'] for c in clips),
        'source_manifest_sha256': manifest_sha, 'source_audit_sha256': audit.sha(report_path),
        'export_tool_sha256': audit.sha(Path(__file__)), 'duplicates': [], 'incomplete_excluded': [],
        'source_batch': 'source-6', 'preview_only': True, 'created_at': datetime.now(timezone.utc).isoformat(),
        'provenance_limitations': report['limitations'],
        'presentation': 'Existing demo mapping: root/lower body/spine fixed; native upper-body and hand axes, hand mean added once. Camera/face coefficients not mapped. Candidate text and boundaries unapproved.',
    }
    experimental.write_json(output / 'experimental-index.json', index)
    (output / 'SHA256SUMS').write_text(''.join(audit.sha(p) + '  ' + str(p.relative_to(output)) + '\n'
                                             for p in sorted(output.rglob('*')) if p.is_file()))
    audit.verify_checksums(output)
    return index


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('package', 'review', 'pilot-results', 'remaining-results', 'smplx-model', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    index = export(parser.parse_args())
    print(json.dumps({'clips': len(index['clips']), 'frames': index['frames'], 'training_ready': False}))
