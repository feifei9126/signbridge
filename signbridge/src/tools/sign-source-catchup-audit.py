"""Audit completed continuous candidate fits without promoting data or training."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def probe_clip(path, ffprobe):
    result = subprocess.run([
        str(ffprobe), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=avg_frame_rate,nb_read_frames', '-of', 'json', str(path)
    ], check=True, capture_output=True, text=True)
    row = json.loads(result.stdout)['streams'][0]
    numerator, denominator = map(int, row['avg_frame_rate'].split('/'))
    fps = numerator / denominator
    frames = int(row['nb_read_frames'])
    if abs(fps - 25.) > .01:
        raise ValueError(f'Unexpected source fps {fps}: {path}')
    return frames, fps


def audit(job, ffprobe):
    job = Path(job).resolve()
    package = job / 'continuous-smplx-input-v3'
    run_root = job / 'results-v2'
    manifest_path = package / 'manifest.json'
    run_report_path = run_root / 'report.json'
    manifest = json.loads(manifest_path.read_text())
    run = json.loads(run_report_path.read_text())
    if (manifest.get('schema') != 'signbridge-smplerx-candidate-sequences-v1' or
            manifest.get('training_ready') is not False or manifest.get('source_files_modified') is not False):
        raise ValueError('Input package contract differs')
    if (run.get('status') != 'smplerx_sequences_completed_pending_quality_review' or
            run.get('completed_sequences') != manifest.get('sequence_count') or
            run.get('completed_frames') != manifest.get('frames') or
            run.get('training_started') is not False or run.get('training_ready') is not False):
        raise ValueError('Remote inference is incomplete or promoted')
    if run.get('input_manifest_sha256') != sha(manifest_path):
        raise ValueError('Run report input manifest digest mismatch')
    for line in (package / 'SHA256SUMS').read_text().splitlines():
        checksum, relative = line.split('  ', 1)
        file = (package / relative).resolve()
        if package not in file.parents or sha(file) != checksum:
            raise ValueError('Input package checksum mismatch: ' + relative)
    cases = read_jsonl(package / 'sequences.jsonl')
    keyframes = read_jsonl(package / 'keyframes.jsonl')
    records = run.get('candidate_records', [])
    if (len(cases) != 76 or len(records) != 76 or len(keyframes) != 380 or
            sum(row['frames'] for row in cases) != 17300 or manifest.get('keyframe_count') != 380):
        raise ValueError('Input sequence/frame/MANO mapping totals differ')
    if len({row['annotation_id'] for row in records}) != 76:
        raise ValueError('Output sequence IDs are missing or duplicated')
    by_id = {row['annotation_id']: row for row in records}
    keyframe_map = {row['annotation_id']: [] for row in cases}
    for keyframe in keyframes:
        sequence = next((row for row in cases if row['annotation_id'] == keyframe['annotation_id']), None)
        if not sequence or not 1 <= keyframe['frame_1based'] <= sequence['frames']:
            raise ValueError('Mapped MANO keyframe is outside its continuous candidate')
        keyframe_map[sequence['annotation_id']].append(keyframe['frame_1based'])
    sequences = []
    for case in cases:
        sequence_id = case['annotation_id']
        record = by_id.get(sequence_id)
        if not record or record.get('frames_expected') != case['frames'] or record.get('training_ready') is not False:
            raise ValueError('Sequence output contract differs: ' + sequence_id)
        clip = (package / case['clip']).resolve()
        if package not in clip.parents or not clip.is_file() or sha(clip) != case['clip_sha256']:
            raise ValueError('Source candidate clip hash mismatch: ' + sequence_id)
        clip_frames, fps = probe_clip(clip, ffprobe)
        if clip_frames != case['frames']:
            raise ValueError(f'Source clip frame count differs ({clip_frames}/{case["frames"]}): {sequence_id}')
        image_dir = run_root / 'input-frames' / sequence_id
        input_images = sorted(image_dir.glob('*.jpg'))
        if len(input_images) != case['frames'] or any(p.name != f'{i:06d}.jpg' for i, p in enumerate(input_images, 1)):
            raise ValueError('Input image sequence missing/noncontiguous: ' + sequence_id)
        for file in input_images:
            if cv2.imread(str(file)) is None:
                raise ValueError('Input frame cannot decode: ' + str(file))
        fit = run_root / 'fits' / sequence_id
        smplx_dir, meta_dir, render_dir = fit / 'smplx', fit / 'meta', fit / 'img'
        renders = sorted(render_dir.glob('*.jpg')) if render_dir.is_dir() else []
        expected_names = [f'{i:06d}.jpg' for i in range(1, case['frames'] + 1)]
        if len(renders) != case['frames'] or [p.name for p in renders] != expected_names:
            raise ValueError('Rendered sequence incomplete: ' + sequence_id)
        for file in renders:
            if cv2.imread(str(file)) is None:
                raise ValueError('Rendered frame cannot decode: ' + str(file))
        params = sorted(smplx_dir.glob('*.npz')) if smplx_dir.is_dir() else []
        fitted_frames = set()
        shapes = {'global_orient': (1, 3), 'body_pose': (21, 3), 'left_hand_pose': (15, 3),
                  'right_hand_pose': (15, 3), 'jaw_pose': (1, 3), 'leye_pose': (1, 3),
                  'reye_pose': (1, 3), 'betas': (1, 10), 'expression': (1, 10), 'transl': (1, 3)}
        for parameter in params:
            frame = int(parameter.stem.split('_', 1)[0])
            if not 1 <= frame <= case['frames'] or frame in fitted_frames:
                raise ValueError('Duplicate/out-of-range SMPL-X frame: ' + str(parameter))
            fitted_frames.add(frame)
            metadata_path = meta_dir / (parameter.stem + '.json')
            if not metadata_path.is_file():
                raise ValueError('SMPL-X metadata missing: ' + str(parameter))
            metadata = json.loads(metadata_path.read_text())
            expected_input = (image_dir / f'{frame:06d}.jpg').resolve()
            if Path(metadata.get('img_path', '')).resolve() != expected_input:
                raise ValueError('SMPL-X metadata points at the wrong sequence frame')
            for name in ('focal', 'princpt', 'bbox', 'bbox_mmdet'):
                values = np.asarray(metadata.get(name, []), dtype=np.float64)
                if values.shape != ({'focal': (2,), 'princpt': (2,), 'bbox': (4,), 'bbox_mmdet': (4,)}[name]) or not np.isfinite(values).all():
                    raise ValueError('Invalid camera metadata: ' + str(metadata_path))
            with np.load(parameter, allow_pickle=False) as values:
                for name, shape in shapes.items():
                    if name not in values.files or values[name].shape != shape or not np.isfinite(values[name]).all():
                        raise ValueError('Invalid full axis-angle parameter ' + name + ': ' + str(parameter))
        missing = sorted(set(range(1, case['frames'] + 1)) - fitted_frames)
        mapped_keyframes = sorted(keyframe_map[sequence_id])
        if record.get('smplx_missing_detection_frames') != missing:
            raise ValueError('Missing fit frames differ from the incremental run report')
        log = run_root / 'logs' / (sequence_id + '.log')
        if not log.is_file():
            raise ValueError('Sequence inference log missing: ' + sequence_id)
        sequences.append({
            'annotation_id': sequence_id, 'source_id': case['source_id'], 'source_sha256': case['source_sha256'],
            'label_candidate': case['label_candidate'], 'text_verified': '', 'start_seconds': case['start_seconds'],
            'end_seconds': case['end_seconds'], 'frames': case['frames'], 'fps': fps,
            'input_frames': len(input_images), 'render_frames': len(renders), 'smplx_parameter_frames': len(params),
            'smplx_missing_detection_frames': missing, 'mapped_mano_keyframe_frames': mapped_keyframes,
            'mapped_mano_frames_missing_body_fit': sorted(set(mapped_keyframes) & set(missing)),
            'run_log_sha256': sha(log), 'language': case['language'], 'mirror_status': case['mirror_status'],
            'signer_identity': case['signer_identity'], 'human_approved': False, 'training_ready': False,
        })
    audit = {
        'schema': 'signbridge-continuous-smplerx-audit-v1', 'status': 'passed',
        'audited_at': datetime.now(timezone.utc).isoformat(),
        'input_manifest_sha256': sha(manifest_path), 'run_report_sha256': sha(run_report_path),
        'smplerx_commit': run.get('smplerx_commit') or run.get('preflight', {}).get('actual_commit'),
        'sequences': len(sequences), 'input_frames': 17300,
        'render_frames': sum(row['render_frames'] for row in sequences),
        'parameter_frames': sum(row['smplx_parameter_frames'] for row in sequences),
        'missing_parameter_frames': sum(len(row['smplx_missing_detection_frames']) for row in sequences),
        'mano_keyframe_mappings': len(keyframes),
        'mano_keyframes_missing_body_fit': sum(len(row['mapped_mano_frames_missing_body_fit']) for row in sequences),
        'temporal_interpolation_performed': False, 'training_started': False,
        'human_approved': False, 'training_ready': False, 'semantic_accuracy': 'not_assessed',
        'sequences_audit': sequences,
    }
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--ffprobe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.job, args.ffprobe)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'sequences_audit'}))


if __name__ == '__main__':
    main()
