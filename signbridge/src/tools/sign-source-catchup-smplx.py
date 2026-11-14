"""Run unapproved full-window SMPLer-X inference without starting training."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import traceback


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


data = load_tool('sign-data.py', 'catchup_smplx_data')
motion = load_tool('sign-motion.py', 'catchup_smplx_motion')


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def write_jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows))


def safe_id(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}', value) is None:
        raise ValueError('Unsafe sequence or keyframe ID')
    return value


def build_case_records(references, keyframes):
    if not references or len({r.get('annotation_id') for r in references}) != len(references):
        raise ValueError('Nonempty unique reference sequences required')
    cases = []
    for row in references:
        safe_id(row.get('annotation_id'))
        fps = row.get('fps', row.get('reference_fps'))
        label = row.get('label', row.get('label_candidate'))
        if (not row.get('source_id') or not re.fullmatch(r'[a-f0-9]{64}', row.get('source_sha256', '')) or
                not isinstance(label, str) or not label.strip() or
                type(row.get('frames')) is not int or row['frames'] < 4 or fps != 25.0 or
                row.get('human_approved') is not False or row.get('training_ready') is not False):
            raise ValueError('Sequence source, timing or unapproved status differs')
        window = row.get('source_window_seconds')
        start = row.get('start_seconds', window[0] if isinstance(window, list) and len(window) == 2 else None)
        end = row.get('end_seconds', window[1] if isinstance(window, list) and len(window) == 2 else None)
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not 0 <= start < end:
            raise ValueError('Invalid candidate reference window')
        clip = row.get('clip')
        clip_sha = row.get('clip_sha256')
        if not clip and isinstance(row.get('artifacts'), dict):
            asset = row['artifacts'].get('clip.mp4', {})
            clip, clip_sha = asset.get('relative_path'), asset.get('sha256')
        if not isinstance(clip, str) or not re.fullmatch(r'[a-f0-9]{64}', clip_sha or ''):
            raise ValueError('Reference clip path and digest are required')
        cases.append({
            'annotation_id': row['annotation_id'],
            'source_id': row['source_id'],
            'source_sha256': row['source_sha256'],
            'label_candidate': label,
            'text_verified': '',
            'start_seconds': float(start),
            'end_seconds': float(end),
            'frames': row['frames'],
            'fps': fps,
            'clip': clip,
            'clip_sha256': clip_sha,
            'language': 'unconfirmed',
            'mirror_status': 'unknown',
            'signer_identity': 'unconfirmed',
            'sample_type': 'sentence_candidate',
            'human_approved': False,
            'training_ready': False,
            'mano_keyframes': [],
        })
    by_id = {row['annotation_id']: row for row in cases}
    used_frames = set()
    for keyframe in keyframes:
        annotation_id = keyframe.get('annotation_id')
        if annotation_id not in by_id:
            raise ValueError('MANO keyframe references an unknown continuous sequence')
        row = by_id[annotation_id]
        frame = keyframe.get('frame_1based')
        keyframe_id = safe_id(keyframe.get('case_id'))
        if type(frame) is not int or not 1 <= frame <= row['frames']:
            raise ValueError('MANO keyframe is outside its source clip')
        if keyframe.get('training_ready') is not False or keyframe.get('human_approved') is not False:
            raise ValueError('Keyframe package cannot promote prior approval')
        unique = (annotation_id, frame)
        if unique in used_frames:
            raise ValueError('Duplicate keyframe-to-sequence mapping')
        used_frames.add(unique)
        row['mano_keyframes'].append({
            'case_id': keyframe_id,
            'frame_1based': frame,
            'source_seconds_nominal': keyframe.get('source_seconds_nominal'),
            'training_ready': False,
            'human_approved': False,
        })
    return cases


def build_frame_map(references, keyframes):
    by_id = {row['annotation_id']: row for row in build_case_records(references, [])}
    used_cases, used_frames, output = set(), set(), []
    for keyframe in keyframes:
        annotation_id = keyframe.get('annotation_id')
        case_id = safe_id(keyframe.get('case_id'))
        frame = keyframe.get('frame_1based')
        if annotation_id not in by_id:
            raise ValueError('MANO keyframe references an unknown continuous sequence')
        if case_id in used_cases or type(frame) is not int or not 1 <= frame <= by_id[annotation_id]['frames']:
            raise ValueError('Duplicate keyframe ID or frame outside continuous sequence')
        marker = (annotation_id, frame)
        if marker in used_frames:
            raise ValueError('Multiple MANO cases map to the same clip frame')
        used_cases.add(case_id)
        used_frames.add(marker)
        output.append({'keyframe_case_id': case_id, 'annotation_id': annotation_id,
                       'clip_frame_1based': frame, 'source_seconds_nominal': keyframe.get('source_seconds_nominal'),
                       'training_ready': False})
    return output


def validate_package(root):
    root = Path(root).resolve()
    manifest_path = root / 'manifest.json'
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        checksum, relative = line.split('  ', 1)
        file = (root / relative).resolve()
        if root not in file.parents or not file.is_file() or data.sha256_file(file) != checksum:
            raise ValueError('Sequence package checksum mismatch: ' + relative)
    manifest = json.loads(manifest_path.read_text())
    cases = read_jsonl(root / 'sequences.jsonl')
    keyframes = read_jsonl(root / 'keyframes.jsonl')
    if (manifest.get('schema') != 'signbridge-smplerx-candidate-sequences-v1' or
            manifest.get('training_ready') is not False or manifest.get('training_started') is not False or
            manifest.get('sequence_count') != len(cases) or manifest.get('keyframe_count') != len(keyframes)):
        raise ValueError('Sequence package contract differs')
    expected = build_case_records(cases, keyframes)
    if expected != cases:
        raise ValueError('Sequence/keyframe mapping differs from manifest')
    for case in cases:
        clip = (root / case['clip']).resolve()
        if root not in clip.parents or not clip.is_file() or data.sha256_file(clip) != case['clip_sha256']:
            raise ValueError('Sequence clip escaped package or digest changed')
    return manifest, cases, keyframes, data.sha256_file(manifest_path)


def make_package(args):
    index = args.reference_index.resolve()
    keyframe_plan = args.keyframe_plan.resolve()
    output = args.output.resolve()
    if output.exists() or output in index.parents or index in output.parents:
        raise ValueError('New sequence package required outside the reference delivery')
    refs = read_jsonl(index)
    plan = json.loads(keyframe_plan.read_text())
    if plan.get('training_ready') is not False or len(plan.get('cases', [])) != 380:
        raise ValueError('Expected the verified 380-case unapproved MANO keyframe plan')
    cases = build_case_records(refs, [])
    mapping = build_frame_map(refs, plan['cases'])
    by_id = {row['case_id']: row for row in plan['cases']}
    grouped_mapping = {case['annotation_id']: [] for case in cases}
    for item in mapping:
        source_keyframe = by_id[item['keyframe_case_id']]
        grouped_mapping[item['annotation_id']].append({
            'case_id': item['keyframe_case_id'],
            'frame_1based': item['clip_frame_1based'],
            'source_seconds_nominal': item['source_seconds_nominal'],
            'training_ready': source_keyframe['training_ready'],
            'human_approved': source_keyframe['human_approved'],
        })
    for case in cases:
        case['mano_keyframes'] = grouped_mapping[case['annotation_id']]
    root = index.parent
    output.mkdir(parents=True)
    sequences = []
    for row in cases:
        source_record = next(r for r in refs if r['annotation_id'] == row['annotation_id'])
        asset = source_record['artifacts']['clip.mp4']
        source = (root / asset['relative_path']).resolve()
        if root not in source.parents or not source.is_file() or data.sha256_file(source) != asset['sha256']:
            raise ValueError('Candidate reference clip changed: ' + row['annotation_id'])
        target = output / 'clips' / row['annotation_id'] / 'clip.mp4'
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            import shutil
            shutil.copy2(source, target)
        copied = dict(row)
        copied['clip'] = str(target.relative_to(output))
        sequences.append(copied)
    keyframes = [{'annotation_id': row['annotation_id'], **keyframe}
                 for row in sequences for keyframe in row['mano_keyframes']]
    write_jsonl(output / 'sequences.jsonl', sequences)
    write_jsonl(output / 'keyframes.jsonl', keyframes)
    manifest = {
        'schema': 'signbridge-smplerx-candidate-sequences-v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_reference_index_sha256': data.sha256_file(index),
        'keyframe_plan_sha256': data.sha256_file(keyframe_plan),
        'sequence_count': len(sequences),
        'frames': sum(row['frames'] for row in sequences),
        'fps': 25.0,
        'keyframe_count': len(keyframes),
        'frames_are_temporally_contiguous_within_sequence': True,
        'text_verified_count': 0,
        'human_approved': False,
        'training_ready': False,
        'training_started': False,
        'source_files_modified': False,
    }
    write_json(output / 'manifest.json', manifest)
    (output / 'SHA256SUMS').write_text(''.join(
        data.sha256_file(file) + '  ' + str(file.relative_to(output)) + '\n'
        for file in sorted(output.rglob('*')) if file.is_file() and file.name != 'SHA256SUMS'))
    validate_package(output)
    print(json.dumps({'package': str(output), **manifest}, ensure_ascii=False))


def probe_clip(path):
    ffprobe = shutil.which('ffprobe') or str(Path(sys.executable).with_name('ffprobe'))
    if not Path(ffprobe).is_file():
        raise ValueError('ffprobe is unavailable in the SMPLer-X runtime')
    result = subprocess.run([
        ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=avg_frame_rate,nb_read_frames,width,height', '-of', 'json', str(path)
    ], check=True, capture_output=True, text=True)
    stream = json.loads(result.stdout)['streams'][0]
    numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
    fps = numerator / denominator
    count = int(stream['nb_read_frames'])
    if abs(fps - 25.) > .01:
        raise ValueError(f'Clip FPS differs from the reference contract: {path} {fps}')
    return {'frames': count, 'fps': fps, 'width': int(stream['width']), 'height': int(stream['height'])}


def audit_case(case, root, output, image_root):
    np = __import__('numpy')
    cv2 = __import__('cv2')
    fit = output / 'fits' / case['annotation_id']
    params_dir, meta_dir, render_dir = fit / 'smplx', fit / 'meta', fit / 'img'
    render_count = 0
    for number in range(1, case['frames'] + 1):
        image_path = image_root / case['annotation_id'] / f'{number:06d}.jpg'
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError('Extracted sequence image failed decoding: ' + str(image_path))
        # SMPLer-X renders one output image per input frame, including frames with no person fit.
        render = render_dir / f'{number:06d}.jpg'
        if render.is_file() and cv2.imread(str(render)) is not None:
            render_count += 1
        for parameter in sorted(params_dir.glob(f'{number:05d}_*.npz')):
            stem = parameter.stem
            metadata = meta_dir / f'{stem}.json'
            if not metadata.is_file():
                raise ValueError('SMPL-X parameter has no metadata: ' + str(parameter))
            with np.load(parameter, allow_pickle=False) as values:
                required = {
                    'global_orient': (1, 3), 'body_pose': (21, 3),
                    'left_hand_pose': (15, 3), 'right_hand_pose': (15, 3),
                    'jaw_pose': (1, 3), 'leye_pose': (1, 3), 'reye_pose': (1, 3),
                    'betas': (1, 10), 'expression': (1, 10), 'transl': (1, 3),
                }
                for key, shape in required.items():
                    if key not in values.files or values[key].shape != shape or not np.isfinite(values[key]).all():
                        raise ValueError('Invalid SMPL-X parameter ' + key + ': ' + str(parameter))
            info = json.loads(metadata.read_text())
            if Path(info.get('img_path', '')).resolve() != image_path.resolve():
                raise ValueError('SMPL-X metadata input frame mismatch: ' + str(metadata))
    if render_count != case['frames']:
        raise ValueError(f'SMPLer-X renders {render_count}/{case["frames"]} frames for {case["annotation_id"]}')
    parameter_files = sorted(params_dir.glob('*.npz')) if params_dir.exists() else []
    fitted_frames = {int(file.name.split('_', 1)[0]) for file in parameter_files}
    missing = [number for number in range(1, case['frames'] + 1) if number not in fitted_frames]
    expected_ids = [link['frame_1based'] for link in case['mano_keyframes']]
    keyframe_missing = [number for number in expected_ids if number in missing]
    return {
        'annotation_id': case['annotation_id'], 'source_id': case['source_id'],
        'source_sha256': case['source_sha256'], 'label_candidate': case['label_candidate'],
        'frames_expected': case['frames'], 'render_frames': render_count,
        'smplx_parameter_files': len(parameter_files), 'smplx_missing_detection_frames': missing,
        'mano_keyframe_frames': expected_ids, 'mano_keyframes_missing_smplx_fit': keyframe_missing,
        'smplx_directory': str(params_dir.relative_to(output)),
        'metadata_directory': str(meta_dir.relative_to(output)),
        'render_directory': str(render_dir.relative_to(output)),
        'text_verified': '', 'human_approved': False, 'training_ready': False,
    }


def run(args):
    root = args.smplerx_root.resolve()
    package = args.package.resolve()
    output = args.output.resolve()
    manifest, cases, _, manifest_sha = validate_package(package)
    if output.exists() or output in package.parents or package in output.parents or output in root.parents or root in output.parents:
        raise ValueError('Use a new output directory separate from inputs and SMPLer-X')
    python = args.python.resolve()
    check = motion.preflight(root, python, args.model)
    if not check['ready']:
        raise ValueError('SMPLer-X preflight blocked: ' + json.dumps(check, ensure_ascii=False))
    output.mkdir(parents=True)
    image_root = output / 'input-frames'
    image_root.mkdir()
    logs = output / 'logs'; logs.mkdir()
    report = {
        'schema': 'signbridge-smplerx-candidate-sequences-run-v1',
        'status': 'running', 'created_at': datetime.now(timezone.utc).isoformat(),
        'input_manifest_sha256': manifest_sha, 'smplerx_commit': check['actual_commit'],
        'preflight': check, 'sequence_count': len(cases), 'frames_expected': manifest['frames'],
        'completed_sequences': 0, 'completed_frames': 0,
        'frames_are_temporally_contiguous_within_sequence': True,
        'independent_keyframe_count': manifest['keyframe_count'],
        'candidate_records': [], 'training_started': False,
        'human_approved': False, 'training_ready': False,
        'text_verified_count': 0, 'source_files_modified': False,
    }
    report_path = output / 'report.json'
    write_json(report_path, report)
    failed = None
    try:
        ffmpeg = shutil.which('ffmpeg') or str(python.with_name('ffmpeg'))
        if not Path(ffmpeg).is_file():
            raise ValueError('ffmpeg is unavailable in the SMPLer-X runtime')
        for sequence_index, case in enumerate(cases, 1):
            case_dir = image_root / case['annotation_id']; case_dir.mkdir()
            clip = (package / case['clip']).resolve()
            probe = probe_clip(clip)
            if probe['frames'] != case['frames']:
                raise ValueError(f'Input clip frame count {probe["frames"]} differs from manifest {case["frames"]}: {case["annotation_id"]}')
            subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(clip),
                '-vsync', '0', '-q:v', '2', '-threads', '2', str(case_dir / '%06d.jpg')
            ], check=True, timeout=300)
            images = sorted(case_dir.glob('*.jpg'))
            if len(images) != case['frames'] or any(file.name != f'{index:06d}.jpg' for index, file in enumerate(images, 1)):
                raise ValueError('Extracted frame sequence is not contiguous: ' + case['annotation_id'])
            (output / 'fits').mkdir(exist_ok=True)
            argv = motion.fitting_command({
                'segment_id': case['annotation_id'], 'frames': case['frames'], 'images': str(case_dir),
            }, package, root, python, output / 'fits', args.model)
            # The fitting helper points at package-relative images; make the validated extracted folder explicit.
            argv[argv.index('--img_path') + 1] = str(case_dir)
            log_path = logs / (case['annotation_id'] + '.log')
            with log_path.open('w') as log:
                env = os.environ.copy(); env.setdefault('PYOPENGL_PLATFORM', 'egl'); env.setdefault('MPLBACKEND', 'Agg')
                result = subprocess.run(argv, cwd=root / 'main', env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                failed = {'annotation_id': case['annotation_id'], 'exit_code': result.returncode, 'log': str(log_path.relative_to(output))}
                raise RuntimeError('SMPLer-X failed on candidate sequence ' + case['annotation_id'])
            audited = audit_case(case, root, output, image_root)
            audited['sequence_index'] = sequence_index
            audited['log_sha256'] = data.sha256_file(log_path)
            report['candidate_records'].append(audited)
            report['completed_sequences'] = sequence_index
            report['completed_frames'] = sum(row['frames_expected'] for row in report['candidate_records'])
            write_json(report_path, report)
            print(json.dumps({'sequence': sequence_index, 'total_sequences': len(cases),
                              'annotation_id': case['annotation_id'], 'fitted_parameters': audited['smplx_parameter_files'],
                              'expected_frames': audited['frames_expected'], 'completed_frames': report['completed_frames']}, ensure_ascii=False), flush=True)
        if data.sha256_file(package / 'manifest.json') != manifest_sha:
            raise ValueError('Sequence input manifest changed during inference')
        report.update(status='smplerx_sequences_completed_pending_quality_review', finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        report.update(status='failed', failed_sequence=failed, error=str(error), traceback=traceback.format_exc())
        write_json(report_path, report)
        raise
    write_json(report_path, report)
    (output / 'SHA256SUMS').write_text(''.join(
        data.sha256_file(file) + '  ' + str(file.relative_to(output)) + '\n'
        for file in sorted(output.rglob('*')) if file.is_file() and file.name != 'SHA256SUMS'))
    print(json.dumps({'status': report['status'], 'sequences': report['completed_sequences'],
                      'frames': report['completed_frames'], 'training_ready': False}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--reference-index', type=Path, required=True)
    prepare.add_argument('--keyframe-plan', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.set_defaults(func=make_package)
    run_parser = commands.add_parser('run')
    run_parser.add_argument('--package', type=Path, required=True)
    run_parser.add_argument('--smplerx-root', type=Path, required=True)
    run_parser.add_argument('--python', type=Path, required=True)
    run_parser.add_argument('--model', default='smpler_x_h32', choices=['smpler_x_s32','smpler_x_b32','smpler_x_l32','smpler_x_h32'])
    run_parser.add_argument('--output', type=Path, required=True)
    run_parser.set_defaults(func=run)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
