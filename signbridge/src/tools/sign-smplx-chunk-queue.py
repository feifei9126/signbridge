"""Run SMPLer-X input chunks serially and pause before the reserved disk margin."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


GIB = 1024 ** 3
BYTES_PER_FRAME_ESTIMATE = 100_000


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def verified_manifest(root):
    root = Path(root).resolve(strict=True)
    entries = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, relative = line.split('  ', 1)
        name = Path(relative)
        if not re.fullmatch('[0-9a-f]{64}', digest) or relative in entries:
            raise ValueError('Malformed or duplicate SHA256 entry')
        if name.is_absolute() or '..' in name.parts or '\\' in relative:
            raise ValueError('SHA256 path escaped package root')
        target = root / name
        try:
            target.resolve(strict=True).relative_to(root)
        except (ValueError, OSError) as error:
            raise ValueError('SHA256 item missing or escaped package root') from error
        if target.is_symlink() or not target.is_file() or sha(target) != digest:
            raise ValueError('SHA256 mismatch: ' + relative)
        entries[relative] = digest
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
    actual.discard('SHA256SUMS')
    if actual != set(entries):
        raise ValueError('Manifest does not cover exact package file set')
    return {'files': len(entries), 'bytes': sum((root / name).stat().st_size for name in entries),
            'manifest_sha256': sha(root / 'SHA256SUMS')}


def validate_chunk_index(index_path, chunk_root):
    index_path = Path(index_path).resolve(strict=True)
    chunk_root = Path(chunk_root).resolve(strict=True)
    index = read_json(index_path)
    if (index.get('schema') != 'signbridge-smplerx-candidate-chunk-index-v1' or
            index.get('partition_exactly_once') is not True or
            index.get('training_ready') is not False or index.get('training_started') is not False):
        raise ValueError('Chunk index contract differs')
    chunks = index.get('chunks')
    if not isinstance(chunks, list) or not chunks:
        raise ValueError('Chunk index has no chunks')
    expected = [f'chunk-{number:03d}' for number in range(1, len(chunks) + 1)]
    if [item.get('path') for item in chunks] != expected:
        raise ValueError('Chunk paths are not a contiguous ordered partition')
    if (sum(item['sequence_count'] for item in chunks) != index['sequence_count'] or
            sum(item['candidate_alias_count'] for item in chunks) != index['candidate_alias_count'] or
            sum(item['frames'] for item in chunks) != index['frame_count']):
        raise ValueError('Chunk totals do not agree with the index')
    for item in chunks:
        package = (chunk_root / item['path']).resolve(strict=True)
        package.relative_to(chunk_root)
        summary = verified_manifest(package)
        if summary['manifest_sha256'] != item['package_manifest_sha256']:
            raise ValueError('Chunk manifest digest differs: ' + item['path'])
        manifest = read_json(package / 'manifest.json')
        if (manifest.get('sequence_count') != item['sequence_count'] or
                manifest.get('frames') != item['frames'] or
                manifest.get('candidate_alias_count') != item['candidate_alias_count'] or
                manifest.get('training_started') is not False):
            raise ValueError('Chunk manifest values differ: ' + item['path'])
    return index, chunks


def validate_completed_attempt(chunk, package, attempt, quarantine_missing_detections=False):
    package = Path(package).resolve(strict=True)
    attempt = Path(attempt).resolve(strict=True)
    report_path = attempt / 'report.json'
    report = read_json(report_path)
    manifest = read_json(package / 'manifest.json')
    cases = [json.loads(line) for line in (package / 'sequences.jsonl').read_text().splitlines() if line.strip()]
    records = report.get('candidate_records', [])
    if (report.get('schema') != 'signbridge-smplerx-candidate-sequences-run-v1' or
            report.get('status') != 'smplerx_sequences_completed_pending_quality_review' or
            report.get('training_started') is not False or report.get('training_ready') is not False or
            report.get('human_approved') is not False or
            report.get('model_training_ready', False) is not False or
            report.get('input_manifest_sha256') != sha(package / 'manifest.json') or
            report.get('sequence_count') != len(cases) or report.get('completed_sequences') != len(cases) or
            report.get('frames_expected') != manifest['frames'] or report.get('completed_frames') != manifest['frames'] or
            sum(row['frames'] for row in cases) != manifest['frames'] or
            not cases or len({row['annotation_id'] for row in cases}) != len(cases) or
            [row.get('annotation_id') for row in records] != [row['annotation_id'] for row in cases]):
        raise ValueError('Fit report or completed sequence set differs: ' + chunk['path'])
    attempt_manifest = verified_manifest(attempt)
    identifiers = {case['annotation_id'] for case in cases}
    if {path.name for path in (attempt / 'fits').iterdir() if path.is_dir()} != identifiers:
        raise ValueError('Fit candidate directory set differs from input package')
    input_root = attempt / 'input-frames'
    if ((quarantine_missing_detections or input_root.exists()) and
            {path.name for path in input_root.glob('*') if path.is_dir()} != identifiers):
        raise ValueError('Input candidate directory set differs from input package')
    frame_total = parameter_total = render_total = complete_count = 0
    quarantined = []
    for case, record in zip(cases, records):
        count = case['frames']
        identifier = case['annotation_id']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', identifier):
            raise ValueError('Invalid candidate identifier')
        parameter_count = record.get('parameters', record.get('smplx_parameter_files'))
        render_count = record.get('renders', record.get('render_frames'))
        missing = record.get('smplx_missing_detection_frames', [])
        if (not isinstance(missing, list) or any(type(n) is not int or not 1 <= n <= count for n in missing) or
                missing != sorted(set(missing)) or type(parameter_count) is not int or
                record.get('frames_expected') != count or parameter_count != count - len(missing) or
                render_count != count or record.get('text_verified', '') != '' or
                record.get('human_approved', False) is not False or
                record.get('training_ready', False) is not False or
                record.get('model_training_ready', False) is not False or
                any(key in record and record[key] != parameter_count for key in ('parameters', 'smplx_parameter_files')) or
                any(key in record and record[key] != render_count for key in ('renders', 'render_frames'))):
            raise ValueError('Fit counts, missing frames or candidate flags differ: ' + identifier)
        expected_mano_missing = sorted(link['frame_1based'] for link in case.get('mano_keyframes', [])
                                       if link['frame_1based'] in missing)
        if record.get('mano_keyframes_missing_smplx_fit', []) != expected_mano_missing:
            raise ValueError('MANO missing-frame report differs: ' + identifier)
        for key in ('source_id', 'source_sha256', 'label_candidate'):
            if key in case and record.get(key) != case[key]:
                raise ValueError('Candidate source mapping differs: ' + identifier)
        log = attempt / 'logs' / (case['annotation_id'] + '.log')
        if not log.is_file() or sha(log) != record.get('log_sha256'):
            raise ValueError('Per-sequence log hash differs: ' + case['annotation_id'])
        fit = attempt / 'fits' / case['annotation_id']
        present = set(range(1, count + 1)) - set(missing)
        if ({path.name for path in (fit / 'smplx').glob('*.npz')} != {f'{i:05d}_0.npz' for i in present} or
                {path.name for path in (fit / 'meta').glob('*.json')} != {f'{i:05d}_0.json' for i in present} or
                {path.name for path in (fit / 'img').glob('*.jpg')} != {f'{i:06d}.jpg' for i in range(1, count + 1)}):
            raise ValueError('Native/meta/render exact frame sets differ: ' + case['annotation_id'])
        inputs = attempt / 'input-frames' / identifier
        if ((quarantine_missing_detections or inputs.exists()) and
                {path.name for path in inputs.glob('*.jpg')} != {f'{i:06d}.jpg' for i in range(1, count + 1)}):
            raise ValueError('Input exact frame set differs: ' + identifier)
        if missing:
            if not quarantine_missing_detections:
                raise ValueError('Incomplete fit or missing detection frames: ' + identifier)
            quarantined.append({'annotation_id': identifier, 'source_id': case.get('source_id'),
                'source_sha256': case.get('source_sha256'), 'label_candidate': case.get('label_candidate'),
                'reason': 'missing_person_detections', 'missing_frames_1based': missing,
                'frames_expected': count, 'native_frames_present': parameter_count,
                'feature_extraction_allowed': False, 'missing_frames_filled': False,
                'text_verified': '', 'human_approved': False, 'training_ready': False,
                'model_training_ready': False, 'log_sha256': record['log_sha256']})
        else:
            complete_count += 1
            frame_total += count
        parameter_total += parameter_count; render_total += count
    report_sha = sha(report_path)
    for item in quarantined:
        item.update(chunk=chunk['path'], attempt=attempt.name, report_sha256=report_sha,
                    attempt_manifest_sha256=attempt_manifest['manifest_sha256'])
    return {'status': ('smplerx_sequences_accounted_with_quarantined_candidates' if quarantined else report['status']),
            'runner_report_status': report['status'], 'report_sha256': report_sha,
            'attempt_manifest_sha256': attempt_manifest['manifest_sha256'],
            'attempt_bytes': attempt_manifest['bytes'], 'sequences': complete_count,
            'sequences_accounted': len(cases), 'frames_expected': manifest['frames'],
            'quarantined_candidates': quarantined,
            'frames': frame_total, 'parameter_files': parameter_total,
            'render_frames': render_total, 'training_started': False,
            'training_ready': False, 'model_training_ready': False, 'human_approved': False}


def required_free_bytes(frames, reserve_gib=6):
    if type(frames) is not int or frames <= 0 or type(reserve_gib) is not int or reserve_gib < 1:
        raise ValueError('Invalid disk reserve')
    return reserve_gib * GIB + frames * BYTES_PER_FRAME_ESTIMATE


def active_inference_processes():
    result = subprocess.run(['ps', '-eo', 'pid=,args='], capture_output=True, text=True, check=True)
    active = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or int(fields[0]) == os.getpid():
            continue
        if any(name in fields[1] for name in ('inference.py --num_gpus',
                'sign-source-catchup-smplx.py run', 'sign-smplx-chunk-queue.py')):
            active.append(line.strip())
    return active


def save_progress(queue_root, state, completed):
    state['completed'] = [completed[k] for k in sorted(completed)]
    candidates = [row for item in state['completed'] for row in item['quarantined_candidates']]
    state.update(chunks_accounted=len(completed),
                 complete_sequences=sum(row['sequences'] for row in completed.values()),
                 accounted_sequences=sum(row['sequences_accounted'] for row in completed.values()),
                 quarantined_sequences=len(candidates),
                 complete_frames=sum(row['frames'] for row in completed.values()),
                 native_parameter_frames=sum(row['parameter_files'] for row in completed.values()))
    write_json(queue_root / 'quarantined-candidates.json', {
        'schema': 'signbridge-smplx-quarantined-candidates-v1', 'updated_at': now(),
        'chunk_index_sha256': state['chunk_index_sha256'], 'queue_provenance': state['queue_provenance'],
        'candidates': candidates, 'training_ready': False, 'model_training_ready': False,
        'human_approved': False})
    write_json(queue_root / 'queue-state.json', state)


def run_queue(args):
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / '.queue.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another queue owns the output-root lock') from error
        return run_locked_queue(args)


def run_locked_queue(args):
    chunk_root = args.chunk_root.resolve(strict=True)
    index_path = args.chunk_index.resolve(strict=True)
    index, chunks = validate_chunk_index(index_path, chunk_root)
    smplerx = args.smplerx_root.resolve(strict=True)
    python = args.python.resolve(strict=True)
    runner = args.runner.resolve(strict=True)
    output_root = args.output_root.resolve(); queue_root = args.queue_root.resolve()
    queue_root.mkdir(parents=True, exist_ok=True); output_root.mkdir(parents=True, exist_ok=True)
    state_path = queue_root / 'queue-state.json'
    allow_missing = getattr(args, 'quarantine_missing_detections', False)
    provenance = {'quarantine_missing_detections': allow_missing,
                  'queue_tool_sha256': sha(Path(__file__)), 'runner_sha256': sha(runner),
                  'smplerx_root': str(smplerx), 'python': str(python),
                  'expected_commit': args.expected_commit, 'reserve_gib': args.reserve_gib}
    if state_path.exists():
        state = read_json(state_path)
        if (state.get('schema') != 'signbridge-smplx-candidate-queue-v2' or
                state.get('chunk_index_sha256') != sha(index_path) or state.get('model') != args.model or
                state.get('queue_provenance') != provenance):
            raise ValueError('Queue state is pinned to different chunk/model/policy provenance; use a new queue directory')
    else:
        state = {'schema': 'signbridge-smplx-candidate-queue-v2', 'created_at': now(),
                 'chunk_index_sha256': sha(index_path), 'parent_package_sha256': index['parent_package_manifest_sha256'],
                 'chunks_total': len(chunks), 'sequences_total': index['sequence_count'],
                 'frames_total': index['frame_count'], 'model': args.model,
                 'smplerx_commit_expected': args.expected_commit, 'status': 'queued', 'completed': [],
                 'blocked': None, 'training_started': False, 'training_ready': False,
                 'model_training_ready': False, 'human_approved': False, 'queue_provenance': provenance}
        write_json(state_path, state)
    if active_inference_processes():
        raise ValueError('Another SMPLer-X inference process is active; queue refuses duplicate launch')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=smplerx,
                              capture_output=True, text=True, check=True).stdout.strip()
    if revision != args.expected_commit:
        raise ValueError('SMPLer-X commit differs from frozen checkpoint/runtime provenance')
    if not (smplerx / 'main/inference.py').is_file():
        raise ValueError('Pinned SMPLer-X inference entry point missing')
    completed = {item['chunk_index_1based']: item for item in state['completed']}
    if len(completed) != len(state['completed']):
        raise ValueError('Queue state contains duplicate completed chunks')
    queue_log = queue_root / 'queue-driver.log'

    def audit_attempt(chunk, package, attempt):
        try:
            return validate_completed_attempt(chunk, package, attempt, allow_missing)
        except Exception as error:
            state.update(status='paused_audit_failure', failed_at=now(), current_chunk=None,
                         blocked={'chunk': chunk['path'], 'attempt': str(attempt),
                                  'error': str(error), 'attempt_preserved': True})
            save_progress(queue_root, state, completed)
            raise

    for chunk in chunks:
        number = chunk['chunk_index_1based']; package = chunk_root / chunk['path']
        attempt = output_root / f"{chunk['path']}-attempt-1"
        if attempt.exists():
            result = audit_attempt(chunk, package, attempt)
            old = completed.get(number)
            if old and (old.get('report_sha256') != result['report_sha256'] or
                        old.get('attempt_manifest_sha256') != result['attempt_manifest_sha256']):
                raise ValueError('Previously recorded chunk output changed: ' + chunk['path'])
            if not old:
                completed[number] = {'chunk_index_1based': number, 'chunk': chunk['path'],
                                     'attempt': attempt.name, **result, 'adopted_existing_verified_output': True}
                state.update(status='running', current_chunk=None, blocked=None)
                save_progress(queue_root, state, completed)
            continue
        if number in completed:
            raise ValueError('Queue state says completed but attempt directory is missing: ' + chunk['path'])
        active = active_inference_processes()
        if active:
            raise ValueError('Another inference process appeared; pausing queue')
        free = shutil.disk_usage(output_root).free
        reserve = required_free_bytes(chunk['frames'], args.reserve_gib)
        if free < reserve:
            state.update(status='paused_low_disk', paused_at=now(), current_chunk=None,
                         blocked={'chunk': chunk['path'], 'free_bytes': free,
                                  'required_free_bytes': reserve, 'attempt_started': False})
            save_progress(queue_root, state, completed)
            print(json.dumps({'status': state['status'], 'completed_chunks': len(completed),
                              'blocked': state['blocked']}, ensure_ascii=False), flush=True)
            return 75
        state.update(status='running', current_chunk=chunk['path'],
                     current_chunk_started_at=now(), free_bytes_before_chunk=free, blocked=None)
        save_progress(queue_root, state, completed)
        command = [str(python), str(runner), 'run', '--package', str(package),
                   '--smplerx-root', str(smplerx), '--python', str(python),
                   '--model', args.model, '--output', str(attempt)]
        env = os.environ.copy(); env['PYOPENGL_PLATFORM'] = 'egl'; env['MPLBACKEND'] = 'Agg'
        env['PATH'] = str(python.parent) + os.pathsep + env.get('PATH', '')
        with queue_log.open('ab') as log:
            log.write((json.dumps({'event': 'start_chunk', 'chunk': chunk['path'], 'time': now(),
                                   'free_bytes': free, 'argv': command}, ensure_ascii=False) + '\n').encode())
            result_code = subprocess.run(command, cwd=smplerx / 'main', env=env,
                                         stdout=log, stderr=subprocess.STDOUT).returncode
        state['last_exit_code'] = result_code; state['last_driver_log_sha256'] = sha(queue_log)
        if result_code:
            state.update(status='paused_fit_failure', failed_at=now(), current_chunk=None,
                         blocked={'chunk': chunk['path'], 'attempt': str(attempt),
                                  'exit_code': result_code, 'attempt_preserved': attempt.exists()})
            save_progress(queue_root, state, completed)
            print(json.dumps({'status': state['status'], 'blocked': state['blocked']}, ensure_ascii=False), flush=True)
            return result_code
        result = audit_attempt(chunk, package, attempt)
        completed[number] = {'chunk_index_1based': number, 'chunk': chunk['path'],
                             'attempt': attempt.name, **result, 'adopted_existing_verified_output': False}
        state.update(status='running', current_chunk=None, last_chunk_completed_at=now())
        save_progress(queue_root, state, completed)
        print(json.dumps({'event': 'chunk_verified', 'chunk': chunk['path'],
                          'chunks_completed': len(completed), **result}, ensure_ascii=False), flush=True)
    state.update(status=('completed_with_quarantined_candidates'
                         if any(row['quarantined_candidates'] for row in completed.values()) else 'completed'),
                 finished_at=now(), current_chunk=None, blocked=None)
    save_progress(queue_root, state, completed)
    print(json.dumps({'status': state['status'], 'chunks': len(completed),
                      'sequences': sum(r['sequences'] for r in completed.values()),
                      'accounted_sequences': state['accounted_sequences'],
                      'quarantined_sequences': state['quarantined_sequences'],
                      'frames': sum(r['frames'] for r in completed.values()),
                      'training_started': False, 'training_ready': False}, ensure_ascii=False), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('chunk-root', 'chunk-index', 'runner', 'smplerx-root', 'python', 'output-root', 'queue-root'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--model', choices=['smpler_x_s32', 'smpler_x_b32', 'smpler_x_l32', 'smpler_x_h32'], default='smpler_x_h32')
    parser.add_argument('--expected-commit', default='064baef0e4ab5277a3297691bc1d46ea5412586f')
    parser.add_argument('--reserve-gib', type=int, default=6)
    parser.add_argument('--quarantine-missing-detections', action='store_true',
                        help='Account for verified missing detections separately; never fill or use incomplete motion')
    args = parser.parse_args()
    return run_queue(args)


if __name__ == '__main__':
    sys.exit(main())
