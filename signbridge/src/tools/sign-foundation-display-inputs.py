#!/usr/bin/env python3
# Convert full-foundation canonical pose candidates into signbridge-native-display-inputs-v1.
# Display-only candidates: no approval, no training flags, no frame filling, no source mutation.
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

MODEL_SHA = '376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992'
SCHEMA_IN = 'signbridge-full-foundation-pose-candidates-v1'
FLAGS = {'human_approved': False, 'training_ready': False, 'model_training_ready': False,
         'text_verified': '', 'semantics_approved': False, 'boundaries_approved': False,
         'training_started': False, 'feature_extraction_allowed': False}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + chr(10))


def convert(source, model, output):
    source, model, output = Path(source).resolve(), Path(model).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source):
        raise ValueError('Choose a new output outside source evidence')
    if sha(model) != MODEL_SHA:
        raise ValueError('Frozen SMPL-X model digest differs')
    index = json.loads((source / 'index.json').read_text())
    if index.get('schema') != SCHEMA_IN:
        raise ValueError('Unknown source schema')
    if MODEL_SHA not in index['input_hashes'].values():
        raise ValueError('Source index does not record the frozen SMPL-X digest')
    with np.load(model, allow_pickle=False) as assets:
        rest = np.asarray(assets['J_regressor'] @ assets['v_template'], dtype=np.float64)
        parents = assets['kintree_table'][0].astype(int)
        parents[0] = -1
    if rest.shape != (55, 3) or not np.allclose(rest, np.asarray(index['restJoints']), atol=1e-6):
        raise ValueError('Source restJoints differ from the SMPL-X model')
    if parents.tolist() != index['parents']:
        raise ValueError('Source parents differ from the SMPL-X model')
    output.mkdir(parents=True)
    (output / 'poses').mkdir()
    clips, stats, joints, types = [], [], set(), {}
    for row in index['clips']:
        cid = row['id']
        path = (source / row['asset']).resolve()
        if not path.is_relative_to(source) or sha(path) != row['sha256']:
            raise ValueError('Pose digest differs: ' + cid)
        raw = (source / row['raw_native']).resolve()
        if not raw.is_relative_to(source) or sha(raw) != row['raw_native_sha256']:
            raise ValueError('Raw native digest differs: ' + cid)
        clip = json.loads(path.read_text())
        poses = np.asarray(clip['poses'], dtype=np.float64)
        n = row['frames']
        if not 4 <= n <= 2000 or poses.shape != (n, 55, 3) or not np.isfinite(poses).all():
            raise ValueError('Invalid pose array: ' + cid)
        for key in ('text', 'source_uid', 'source_sha256', 'fps', 'frames', 'raw_native_sha256'):
            if clip[key] != row[key]:
                raise ValueError('Pose identity differs (' + key + '): ' + cid)
        for key in ('human_approved', 'training_ready', 'model_training_ready'):
            if clip[key] is not False or row[key] is not False:
                raise ValueError('Unapproved candidate contract differs: ' + cid)
        active = sorted(np.nonzero(np.abs(poses).max(axis=(0, 2)) > 0)[0].tolist())
        joints.update(active)
        types[row['unit_type']] = types.get(row['unit_type'], 0) + 1
        meta = {'id': 'native_' + cid, 'text': row['text'], 'aliases': [row['text']], 'source': 'native',
                'fps': row['fps'], 'frames': n, 'source_uid': row['source_uid'],
                'source_sha256': row['source_sha256'], 'native_sha256': row['raw_native_sha256'],
                'mirror_status': 'unknown', 'signer_id': 'unconfirmed',
                'model_output': 'native_smplx_display_candidate', 'unit_type': row['unit_type'],
                'foundation_unit_id': row['foundation_unit_id'], 'source_word_boundary_verified': False,
                **FLAGS}
        rel = 'poses/' + meta['id'] + '.json'
        write_json(output / rel, {**meta, 'poses': clip['poses']})
        clips.append({**meta, 'asset': rel, 'sha256': sha(output / rel)})
        stats.append({'id': meta['id'], 'text': row['text'], 'unit_type': row['unit_type'], 'frames': n,
                      'active_joints': active, 'max_abs_axis_angle': float(np.abs(poses).max())})
    result = {'schema': 'signbridge-native-display-inputs-v1', 'restJoints': rest.tolist(),
              'parents': parents.tolist(), 'clips': clips, 'smplx_model_sha256': MODEL_SHA,
              'source_index_sha256': sha(source / 'index.json'), 'tool_sha256': sha(__file__),
              'display_policy': 'converted from full-foundation canonical poses; no missing-frame filling; all flags false',
              **FLAGS}
    write_json(output / 'index.json', result)
    summary = {'clips': len(clips), 'frames': sum(c['frames'] for c in clips), 'unit_types': types,
               'active_joint_union': sorted(joints), 'output': str(output)}
    write_json(output / 'report.json', {'schema': 'signbridge-foundation-display-conversion-report-v1',
                                        'summary': summary, 'clips': stats, **FLAGS})
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert foundation pose candidates to native display inputs')
    parser.add_argument('--source', required=True)
    parser.add_argument('--smplx-model', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    convert(args.source, args.smplx_model, args.output)
