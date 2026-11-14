"""Re-encode and decode hash-verified T08 reference motions for an offline avatar demo."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

T08_SHA = '438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b'
SOKE_COMMIT = '5cbc55d84b5a7cbf05a9cf020c468052e8d94d00'
MODEL_SHA = '376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def assemble_pose(features, hand_mean):
    features = np.asarray(features)
    if features.ndim != 2 or features.shape[1] != 133 or not np.isfinite(features).all():
        raise ValueError('Expected finite T08 133D motion')
    if hand_mean.shape != (55, 3) or not np.isfinite(hand_mean).all():
        raise ValueError('Invalid SMPL-X hand mean')
    poses = np.zeros((len(features), 55, 3), dtype=np.float32)
    poses[:, 12:22] = features[:, :30].reshape(-1, 10, 3)
    poses[:, 25:40] = features[:, 30:75].reshape(-1, 15, 3)
    poses[:, 40:55] = features[:, 75:120].reshape(-1, 15, 3)
    poses[:, 22] = features[:, 120:123]
    poses += hand_mean[None]
    return poses


def main(args):
    import torch
    checkpoint, motions, soke, model = (x.resolve() for x in (args.checkpoint, args.motions, args.soke_root, args.smplx_model))
    if sha(checkpoint) != T08_SHA or sha(model) != MODEL_SHA:
        raise ValueError('Frozen T08 or SMPL-X asset digest differs')
    if subprocess.check_output(['git', '-C', str(soke), 'rev-parse', 'HEAD'], text=True).strip() != SOKE_COMMIT:
        raise ValueError('SOKE revision differs')
    spec = importlib.util.spec_from_file_location('demo_smoke', Path(__file__).with_name('sign-tokenizer-smoke.py'))
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    saved = torch.load(checkpoint, map_location='cpu', weights_only=False)
    if saved['research_only'] is not True or saved['training_ready'] is not False or saved['soke_commit'] != SOKE_COMMIT:
        raise ValueError('Unexpected model artifact contract')
    rows = [json.loads(line) for line in (motions / 'motions.jsonl').read_text().splitlines() if line.strip()]
    if len(rows) != 14 or [r['segment_id'] for r in rows] != saved['train_segments']:
        raise ValueError('Demo must use exactly T08 fourteen reference sequences in trained order')
    sys.path.insert(0, str(soke))
    module = importlib.import_module('mGPT.archs.mgpt_vq')
    models = torch.nn.ModuleList([module.VQVae(**cfg) for cfg in saved['model_configs']])
    models.load_state_dict(saved['state_dict'], strict=True)
    models.eval()
    torch.set_num_threads(2)
    with np.load(model, allow_pickle=False) as a:
        mean = np.zeros((55, 3), dtype=np.float32)
        mean[25:40] = a['hands_meanl'].reshape(15, 3)
        mean[40:55] = a['hands_meanr'].reshape(15, 3)
        rest = np.asarray(a['J_regressor'] @ a['v_template'], dtype=np.float32)
        parents = a['kintree_table'][0].astype(np.int32)
        parents[0] = -1
    clips = []
    for row in rows:
        feature_path = (motions / row['features']).resolve()
        if motions not in feature_path.parents:
            raise ValueError('Source motion escaped data root')
        values = np.load(feature_path, allow_pickle=False)
        if values.shape != (row['frames'], 133) or values.dtype != np.float32 or not np.isfinite(values).all():
            raise ValueError('Invalid source features')
        padded = np.pad(values, ((0, (-len(values)) % 4), (0, 0)), mode='edge')
        normalized = smoke.normalized_model_input(padded, saved['mean'], saved['std'], np.ones_like(padded, dtype=bool))
        decoded, tokens, parity = [], [], []
        with torch.inference_mode():
            for vq, part in zip(models, smoke.split_parts(normalized)):
                x = torch.from_numpy(part).unsqueeze(0)
                ids, _ = vq.encode(x)
                prediction = vq.decode(ids)
                reference, _, _ = vq(x)
                error = float((prediction - reference).abs().max())
                if error > 1e-4:
                    raise ValueError('Token decode differs from forward reconstruction')
                decoded.append(prediction[0].numpy())
                tokens.append(ids[0].tolist())
                parity.append(error)
        reconstructed = (smoke.combine_parts(decoded) * saved['std'] + saved['mean'])[:len(values)].astype(np.float32)
        pose = assemble_pose(reconstructed, mean)
        clips.append({'id': row['segment_id'], 'text': row['text_verified'], 'aliases': [row['text_verified']],
                      'fps': row['fps'], 'frames': row['frames'], 'duration': round(row['frames'] / row['fps'], 3),
                      'tokens': dict(zip(['body', 'left', 'right'], tokens)),
                      'poses': np.round(pose, 6).tolist(), 'feature_sha256': sha(feature_path),
                      'token_decode_parity_max': max(parity), 'source_id': row['source_id'],
                      'source_sha256': row['source_sha256'], 'model_output': 'token_decode',
                      'text_to_sign_generated': False, 'human_motion_quality_approved': False})
        print(row['segment_id'], row['frames'], 'CPU encode/decode parity', max(parity), flush=True)
    bundle = {'schema': 'signbridge-t08-demo-v1', 'checkpoint_sha256': T08_SHA, 'checkpoint_step': saved['step'],
              'soke_commit': SOKE_COMMIT, 'smplx_rest_model_sha256': MODEL_SHA,
              'representation': 'effective-smplx-55-axis-angle', 'restJoints': rest.tolist(), 'parents': parents.tolist(),
              'clips': clips, 'research_only': True, 'text_to_sign_trained': False, 'runtime': 'precomputed_cpu_token_decode',
              'heldout_accuracy_available': False, 'unmodeled_joints': 'Root, lower body and torso outside 133D held at zero; eyes at rest. Facial coefficients not retargeted.',
              'export_tool_sha256': sha(__file__)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, separators=(',', ':')) + '\n')
    print('EXPORT', args.output, sha(args.output), args.output.stat().st_size)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('checkpoint', 'motions', 'soke-root', 'smplx-model', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    main(p.parse_args())
