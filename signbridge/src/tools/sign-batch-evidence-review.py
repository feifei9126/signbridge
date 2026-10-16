"""Supplement a frozen six-batch native audit without changing any source artifact."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

import cv2
import numpy as np


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


native = load('sign-batch-motion-audit.py')
sha = native.audit.sha
write = native.audit.sequence.write_json


def check_npz(path):
    errors = []; arrays = {}; missing_observations = []
    try:
        with np.load(path, allow_pickle=False) as values:
            for key in values.files:
                value = values[key]
                arrays[key] = {'shape': list(value.shape), 'dtype': str(value.dtype)}
                if key == 'mediapipe_slot_xy' and value.shape == (21, 2) and np.isnan(value).all():
                    missing_observations.append(key)
                elif value.dtype.kind in 'fc' and not np.isfinite(value).all(): errors.append('nonfinite:' + key)
                if key in ('hand_pose', 'global_orient') and value.shape[-2:] == (3, 3):
                    if (not np.allclose(value.swapaxes(-1, -2) @ value, np.eye(3), atol=1e-3)
                            or not np.allclose(np.linalg.det(value), 1, atol=1e-3)):
                        errors.append('invalid_SO3:' + key)
    except Exception as exc: errors.append(str(exc))
    return {'path': str(path), 'sha256': sha(path), 'arrays': arrays, 'errors': errors, 'missing_observations': missing_observations}


def token_errors(tokens, frames, code_num):
    errors = []
    if tokens.shape != (1, (frames + 3) // 4) or tokens.dtype.kind not in 'iu': errors.append('token_shape')
    if tokens.size and (tokens.min() < 0 or tokens.max() >= code_num): errors.append('token_range')
    return errors


def check_manifest(path, cache):
    root = path.parent.resolve(); mismatches = []; missing = []; unsafe = []; seen = set(); duplicates = []; checked = 0
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})\s+\*?(.+)', line)
        if not match: unsafe.append(line); continue
        expected, relative = match.groups(); file = (root / relative).resolve()
        if root not in file.parents: unsafe.append(relative); continue
        if relative in seen: duplicates.append(relative); continue
        seen.add(relative)
        if not file.is_file(): missing.append(relative); continue
        actual = cache.get(str(file)) or sha(file)
        checked += 1
        if actual != expected: mismatches.append(relative)
    return {'path': str(path), 'sha256': sha(path), 'checked': checked, 'missing': missing,
            'mismatches': mismatches, 'unsafe_paths': unsafe, 'duplicate_paths': duplicates}


def sparse_review(data, source_map, output):
    groups = [
        ('tutorial400', data / 'tutorial-native-hands-20261010-v1/full-gpu-inputs',
         data / 'tutorial-native-hands-20261010-v1/full-alignment-download-20261012/tutorial-native-full-alignment-20261012-v5'),
        ('shouyu285', data / 'tutorial-shouyu-expansion-20261012/gpu-inputs',
         data / 'tutorial-shouyu-expansion-20261012/complete-evidence-download/tutorial-shouyu-alignment-20261012-v1')]
    records = []; parameter_files = []; manifests = []
    for group, package, root in groups:
        manifest = json.loads((package / 'manifest.json').read_text()); report = json.loads((root / 'report.json').read_text())
        result_map = {c['case_id']: c for c in report['cases']}
        for case in manifest['cases']:
            cid = case['case_id']; result = result_map.get(cid, {}); errors = []; flags = []
            files = []
            for name in ('baseline.npz', 'candidate.npz'):
                p = root / cid / name
                if not p.exists(): errors.append('missing:' + name); continue
                info = check_npz(p)
                for key, shape in native.audit.NATIVE_SHAPES.items():
                    item = info['arrays'].get(key)
                    if not item or item['shape'] != list(shape) or not item['dtype'].startswith('float'):
                        info['errors'].append('native_shape_dtype:' + key)
                files.append(info); errors.extend(info['errors'])
            image = package / case['image']
            if sha(image) != case['image_sha256']: errors.append('input_image_hash_mismatch')
            if cv2.imread(str(image)) is None: errors.append('input_image_decode_failed')
            for p in sorted((root / cid).glob('*.jpg')):
                if cv2.imread(str(p)) is None: errors.append('render_decode:' + p.name)
            if not result.get('selected'): flags.append('no_selected_hand_candidate')
            if any(not c.get('candidate_gate_passed') for c in result.get('selected', {}).values()): flags.append('selected_hand_gate_failed')
            if result.get('status') in ('no_smplx_detection', 'missing_smplx'): flags.append(result['status'])
            parameter_files.extend(files)
            records.append({'uid': group + '--' + cid, 'id': cid, 'group': group, 'kind': 'independent_keyframe',
                'annotation_id': case['annotation_id'], 'text': case['label'], 'source_sha256': case['source_sha256'],
                'batches': source_map.get(case['source_sha256'], []), 'source_frame': case.get('frame_1based', case.get('source_reference_frame_1based')),
                'gpu_input_frame_1based': case['gpu_input_frame_1based'], 'errors': errors, 'risk_flags': flags,
                'status': 'technical_error' if errors else 'sparse_not_temporal', 'temporal_jitter_assessable': False,
                'input_image': str(image), 'comparison_image': str(root / cid / 'frame-compare.jpg'),
                'candidate_npz': str(root / cid / 'candidate.npz'), 'parameter_files_checked': len(files),
                'historical_selected_hands': result.get('selected', {}), 'human_approved': False})
        manifests.extend(root.glob('SHA256SUMS'))
        print(json.dumps({'sparse_group': group, 'cases': len(manifest['cases'])}), flush=True)
    # MANO detections remain independent candidates, including failed/absent detections.
    for group, root in [
        ('shouyu-mano', data / 'tutorial-shouyu-expansion-20261012/complete-evidence-download/tutorial-shouyu-mano-20261012-v1'),
        ('catchup-mano', data / 'data-expansion-20261013/mano-batch-download-v2/verified/results')]:
        report = json.loads((root / 'report.json').read_text())
        for case in report['cases']:
            errors = []; flags = []; files = []
            for hand in case.get('hands', []):
                p = root / hand['parameters']
                if not p.is_file(): errors.append('missing_hand:' + hand['parameters']); continue
                info = check_npz(p); files.append(info); errors.extend(info['errors'])
                if info['missing_observations']: flags.append('missing_optional_2d_observation')
                if info['sha256'] != hand['parameters_sha256']: errors.append('hand_parameter_hash_mismatch')
                expected_shapes = {'hand_pose': [15, 3, 3], 'global_orient': [1, 3, 3], 'vertices': [778, 3], 'joints': [21, 3]}
                for key, shape in expected_shapes.items():
                    if info['arrays'].get(key, {}).get('shape') != shape: errors.append('MANO_shape:' + key)
            if not files: flags.append('no_mano_detection')
            parameter_files.extend(files)
            records.append({'uid': group + '--' + case['case_id'], 'id': case['case_id'], 'group': group,
                'kind': 'independent_mano', 'annotation_id': case['annotation_id'], 'text': case['label'],
                'batches': source_map.get(case.get('source_sha256'), []), 'source_sha256': case.get('source_sha256'),
                'parameter_files_checked': len(files), 'errors': errors, 'risk_flags': flags,
                'status': 'technical_error' if errors else 'sparse_not_temporal', 'temporal_jitter_assessable': False})
        manifests.extend(root.glob('SHA256SUMS'))
        print(json.dumps({'mano_group': group, 'cases': len(report['cases'])}), flush=True)
    write(output / 'sparse-parameter-checks.json', parameter_files)
    return records, manifests


def training_review(data, base, mean, output):
    registry = json.loads((data / 'training-master-report-20261010-v1/training-registry.json').read_text())
    rounds = json.loads((data / 'training-dedup-20261015/deduplicated-bundle-v3/rounds.json').read_text())['rounds']
    lookup = {r['id']: r for r in base['records'] if r['kind'] == 'native'}
    models = []; records = []; poses = []
    for model in registry['models']:
        mid = model['id']; p = Path(model['checkpoint']); expected = model.get('checkpoint_sha256')
        if mid == 'T10': p = Path(rounds[mid]['run_root']) / 'tokenizer-smoke.pt'; expected = rounds[mid]['checkpoint_sha256']
        digest = sha(p); models.append({'id': mid, 'path': str(p), 'sha256': digest, 'expected_sha256': expected,
            'hash_verified': digest == expected, 'fresh_inference_executed': False,
            'scope': 'checkpoint bytes and stored decoded outputs; no unsafe checkpoint unpickling or retraining'})
        paths = [(f, 'training_diagnostic') for f in sorted(p.parent.rglob('reconstructed-133.npy'))]
        if mid in ('T08', 'T09', 'T10'):
            v = 'v2' if mid == 'T10' else 'v1'
            common = data / f'training-dedup-20261015/{mid}-frozen-common-reference-{v}/inference'
            paths += [(f, 'frozen_common_reference') for f in sorted(common.rglob('reconstructed-133.npy'))]
        for f, scope in paths:
            values = np.load(f, allow_pickle=False); errors = []; hashes = [{'path': str(f), 'sha256': sha(f)}]
            cid = f.parent.name; uid = f'{mid}--{scope}--{cid}'; original = lookup.get(cid, {})
            if values.ndim != 2 or values.shape[1] != 133 or values.dtype != np.float32 or not np.isfinite(values).all(): errors.append('decoded_shape_dtype_or_nonfinite')
            token_inventory = {}
            for name, code_num in [('body', 16), ('left', 32), ('right', 32)]:
                file = f.parent / (name + '-tokens.npy')
                if not file.exists(): errors.append('missing_tokens:' + name); continue
                tokens = np.load(file, allow_pickle=False); errors += [name + ':' + e for e in token_errors(tokens, len(values), code_num)]
                token_inventory[name] = {'shape': list(tokens.shape), 'code_num': code_num, 'unique_codes': int(len(np.unique(tokens)))}
                hashes.append({'path': str(file), 'sha256': sha(file)})
            if not models[-1]['hash_verified']: errors.append('checkpoint_hash_mismatch')
            metric = {}; asset = None
            if not errors:
                for key, start, end in [('body_pose', 0, 30), ('left_hand_pose', 30, 75), ('right_hand_pose', 75, 120)]:
                    metric[key] = native.temporal_metrics(values[:, start:end].reshape(len(values), -1, 3), np.arange(1, len(values) + 1))
                export = load('sign-demo-experimental-export.py'); pose = export.effective_pose(values, mean)
                asset = output / 'poses' / (uid + '.json')
                write(asset, {'id': uid, 'text': original.get('text', cid), 'poses': pose.tolist(), 'frames': len(values), 'fps': 25., 'experimental': False})
                poses.append({'uid': uid, 'asset': str(asset), 'kind': 'decoded', 'current_runtime': mid == 'T08' and scope == 'training_diagnostic', 'default_smoothing': False})
            flags = [k + ':temporal_risk' for k, m in metric.items() if m['large_jump_frames'] or m['isolated_spike_frames'] or (m['midpoint_residual_p95_deg'] or 0) > 10]
            records.append({'uid': uid, 'id': cid, 'group': mid, 'kind': 'decoded', 'scope': scope,
                'text': original.get('text', cid), 'batches': original.get('batches', []), 'frames': len(values), 'fps': 25.,
                'errors': errors, 'risk_flags': flags, 'status': native.risk_level(errors, flags), 'metrics': metric,
                'token_inventory': token_inventory, 'checkpoint_sha256': digest, 'input_hashes': hashes,
                'display_pose_asset': str(asset) if asset else None})
        print(json.dumps({'checkpoint': mid, 'stored_decodes': len(paths), 'hash_verified': digest == expected}), flush=True)
    return models, records, poses


def run(args):
    root = args.root.resolve(); output = args.output.resolve(); data = root.parent
    if output.exists(): raise ValueError('New output directory required')
    output.mkdir(parents=True); (output / 'poses').mkdir()
    base = json.loads((root / 'native-audit-v1/native-review.json').read_text()); plan = json.loads((root / 'plan.json').read_text())
    sources = json.loads((root / 'current-source-files.json').read_text())['sources']; source_map = {}
    for row in sources: source_map.setdefault(row['sha256'], set()).add(row['batch'])
    source_map = {k: sorted(v) for k, v in source_map.items()}
    for row in base['records']:
        row['batches'] = source_map.get(row.get('source_sha256'), row.get('batches', []))
        if row.get('native_files_manifest'):
            # Explicit inventory count, independent of metadata presence.
            hashes = json.loads((root / 'native-audit-v1' / row['native_files_manifest']).read_text())
            row['native_parameter_files'] = sum(p['path'].endswith('.npz') for p in hashes)
    records, manifests = sparse_review(data, source_map, output)
    with np.load(plan['smplx_model'], allow_pickle=False) as a:
        mean = np.zeros((55, 3), np.float32); mean[25:40] = a['hands_meanl'].reshape(15, 3); mean[40:55] = a['hands_meanr'].reshape(15, 3)
    models, decodes, poses = training_review(data, base, mean, output)
    for row in base['records']:
        if row.get('display_pose_asset'): poses.append({'uid': row['uid'], 'asset': str(root / 'native-audit-v1' / row['display_pose_asset']), 'kind': 'native', 'current_runtime': False, 'default_smoothing': False})
    # Runtime bundles, including three T08 candidate decodes and source-6's separate preview.
    runtime = []
    for group, folder, index_name in [
        ('runtime-t08', data / 'demo-20261012', 't08-motion.json'),
        ('runtime-t08-candidates', data / 'demo-20261012', 't08-candidates.json'),
        ('runtime-source4', data / 'demo-experimental-20261015', 'experimental-index.json'),
        ('runtime-source6', data / 'data-expansion-20261015/source-6/avatar-preview-20261016-hjzppz64/motions-v1', 'experimental-index.json')]:
        bundle = json.loads((folder / index_name).read_text())
        for entry in bundle['clips']:
            file = folder / entry['asset'] if entry.get('asset') else folder / index_name
            clip = json.loads(file.read_text()) if entry.get('asset') else entry
            uid = group + '--' + clip['id']; errors = []
            if entry.get('sha256') and sha(file) != entry['sha256']: errors.append('runtime_asset_hash_mismatch')
            pose = np.asarray(clip['poses'])
            if pose.shape != (clip['frames'], 55, 3) or not np.isfinite(pose).all(): errors.append('runtime_pose_invalid')
            if clip['id'] in {x['id'] for x in base['records']}: original = next(x for x in base['records'] if x['id'] == clip['id'])
            else: original = next((x for x in base['records'] if clip.get('source_annotation_id') == x['id']), {})
            runtime.append({'uid': uid, 'id': clip['id'], 'text': clip['text'], 'kind': 'runtime', 'group': group,
                'batches': original.get('batches', source_map.get(clip.get('source_sha256'), [])), 'frames': clip['frames'], 'fps': clip['fps'],
                'asset': str(file), 'asset_sha256': sha(file), 'errors': errors, 'risk_flags': [], 'status': native.risk_level(errors, []),
                'default_smoothing': clip.get('experimental') is True, 'boundary_review_flags': clip.get('boundary_review_flags', [])})
            if entry.get('asset'):
                asset = file
            else:
                asset = output / 'poses' / (uid + '.json'); write(asset, clip)
            poses.append({'uid': uid, 'asset': str(asset), 'kind': 'runtime', 'current_runtime': True, 'default_smoothing': clip.get('experimental') is True})
    # Carry forward reviewed boundary cautions without upgrading assistant proposals into approvals.
    source6 = data / 'data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/candidate-review-v5/report.json'
    prior = {r['annotation_id']: r for r in json.loads(source6.read_text())['records']}
    for row in base['records']:
        if row['group'] == 'source6': row['boundary_review_flags'] = prior[row['id']]['review_flags']
    cache = {}
    for row in base['records']:
        if row.get('native_files_manifest'):
            for f in json.loads((root / 'native-audit-v1' / row['native_files_manifest']).read_text()): cache[f['path']] = f['sha256']
    roots = [data / 'data-expansion-20261014/sequence-review-20261014-nPfhgF/results-v2',
        data / 'data-expansion-20261014/source-4/reconstruction-delivery-20261015-69rzrm_g/evidence']
    source6root = source6.parent.parent
    roots += [source6root / 'pilot-verified-results-83ud9eeq/evidence', source6root / 'remaining-verified-results-nvbpi1k2/evidence']
    manifests += [p / 'SHA256SUMS' for p in roots if (p / 'SHA256SUMS').exists()]
    for p in roots[-2:]:
        manifests += sorted(p.glob('*evidence*.SHA256SUMS'))
    # Save intermediate results before the large preserved-evidence checksum pass.
    report = {'schema': 'signbridge-six-batch-evidence-review-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'native_report_sha256': sha(root / 'native-audit-v1/native-review.json'), 'tool_sha256': sha(__file__),
        'sources': sources, 'records': base['records'] + records + decodes + runtime, 'checkpoints': models,
        'restJoints': base['restJoints'], 'parents': base['parents'], 'pose_jobs': poses,
        'human_approved': False, 'training_ready': False, 'model_training_ready': False,
        'scope': 'Latest preserved evidence per stage; old failed/superseded attempts retained, not mistaken for current outputs.',
        'limitations': ['No semantic sign-language approval.', 'No fresh checkpoint inference; stored decodes only.',
            'Sparse frames cannot establish continuous stability.', 'Source4 legacy original JPEG hashes remain unavailable.',
            'Native full body metrics include joints held at rest in Demo; avatar metrics are reported separately.']}
    write(output / 'evidence-review.json', report)
    checks = []
    for p in manifests:
        print(json.dumps({'checking_manifest': str(p)}), flush=True); checks.append(check_manifest(p, cache))
    report['preserved_manifests'] = checks
    report['manifest_gaps'] = ['initial16/candidate3 legacy provenance retained; no new claim of complete original archive coverage']
    report['counts'] = dict(Counter(r['kind'] for r in report['records']))
    write(output / 'evidence-review.json', report)
    print(json.dumps({'counts': report['counts'], 'manifest_errors': sum(bool(x['missing'] or x['mismatches'] or x['unsafe_paths'] or x['duplicate_paths']) for x in checks)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
