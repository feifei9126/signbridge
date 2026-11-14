#!/usr/bin/env python3
"""Export complete native candidates to display poses without training features."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


MODEL_SHA = '376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992'
SHAPES = {'global_orient': (1, 3), 'body_pose': (21, 3), 'left_hand_pose': (15, 3),
          'right_hand_pose': (15, 3), 'jaw_pose': (1, 3), 'leye_pose': (1, 3),
          'reye_pose': (1, 3), 'betas': (1, 10), 'expression': (1, 10), 'transl': (1, 3)}
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
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')


def display_pose(values, mean):
    n = len(values['frame_ids_1based'])
    if not 4 <= n <= 2000 or not np.array_equal(values['frame_ids_1based'], np.arange(1, n + 1)):
        raise ValueError('Complete consecutive frame IDs required')
    for key, shape in SHAPES.items():
        v = values[key]
        if v.shape != (n, *shape) or v.dtype.kind != 'f' or not np.isfinite(v).all():
            raise ValueError('Invalid native parameter: ' + key)
    if mean.shape != (55, 3) or not np.isfinite(mean).all():
        raise ValueError('Invalid hand mean')
    pose = np.zeros((n, 55, 3), dtype=np.float64)
    pose[:, 12:22] = values['body_pose'][:, 11:21]
    pose[:, 25:40] = values['left_hand_pose'] + mean[None, 25:40]
    pose[:, 40:55] = values['right_hand_pose'] + mean[None, 40:55]
    return pose


def clip_metadata(row):
    for key in ('human_approved', 'training_ready', 'model_training_ready'):
        if row.get(key) is not False:
            raise ValueError('Unapproved native candidate contract differs')
    if row.get('text_verified') != '':
        raise ValueError('Unexpected verified label')
    aliases = list(dict.fromkeys([row['label_candidate'], *[a['label_candidate'] for a in row['aliases']]]))
    return {'id': 'native_' + row['annotation_id'], 'text': row['label_candidate'], 'aliases': aliases,
            'source': 'native', 'fps': row['fps'], 'frames': row['frames_expected'],
            'source_uid': row['uid'], 'source_sha256': row['source_sha256'],
            'native_sha256': row['native_asset_sha256'], 'mirror_status': 'unknown',
            'signer_id': 'unconfirmed', 'model_output': 'native_smplx_display_candidate', **FLAGS}


def export(source, model, output):
    source, model, output = Path(source).resolve(), Path(model).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source):
        raise ValueError('Choose a new output outside source evidence')
    if sha(model) != MODEL_SHA:
        raise ValueError('Frozen SMPL-X model digest differs')
    inventory = dict((name, digest) for digest, name in
                     (line.split('  ', 1) for line in (source / 'SHA256SUMS').read_text().splitlines()))
    if inventory.get('index.json') != sha(source / 'index.json'):
        raise ValueError('Candidate library index digest differs')
    library = json.loads((source / 'index.json').read_text())
    if library.get('schema') != 'signbridge-native-candidate-library-v1':
        raise ValueError('Unknown library schema')
    with np.load(model, allow_pickle=False) as assets:
        mean = np.zeros((55, 3))
        mean[25:40] = assets['hands_meanl'].reshape(15, 3)
        mean[40:55] = assets['hands_meanr'].reshape(15, 3)
        rest = np.asarray(assets['J_regressor'] @ assets['v_template'], dtype=np.float64)
        parents = assets['kintree_table'][0].astype(int)
        parents[0] = -1
    output.mkdir(parents=True)
    (output / 'poses').mkdir()
    clips = []
    for row in library['records']:
        clip = clip_metadata(row)
        name = row['native_asset']
        asset = (source / name).resolve()
        if not asset.is_relative_to(source) or source.joinpath(name).is_symlink() or sha(asset) != row['native_asset_sha256'] or inventory.get(name) != row['native_asset_sha256']:
            raise ValueError('Native container digest/path differs')
        with np.load(asset, allow_pickle=False) as native:
            pose = display_pose(native, mean)
        if len(pose) != clip['frames']:
            raise ValueError('Native frame count differs')
        relative = 'poses/' + clip['id'] + '.json'
        write_json(output / relative, {**clip, 'poses': pose.tolist()})
        clips.append({**clip, 'asset': relative, 'sha256': sha(output / relative)})
    result = {'schema': 'signbridge-native-display-inputs-v1', 'restJoints': rest.tolist(),
              'parents': parents.tolist(), 'clips': clips, 'smplx_model_sha256': MODEL_SHA,
              'source_index_sha256': sha(source / 'index.json'), 'tool_sha256': sha(__file__),
              'display_policy': 'static root/lower body/spine/camera; 40 signing bones; jaw/eyes/face held at REST; hand means added once; no missing-frame filling',
              **FLAGS}
    write_json(output / 'index.json', result)
    print(json.dumps({'clips': len(clips), 'frames': sum(c['frames'] for c in clips), 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--smplx-model', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    export(args.source, args.smplx_model, args.output)
