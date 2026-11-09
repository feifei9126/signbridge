"""Audit frozen CSL media on CPU, preserving every failure and source alias.

CLI: python3 -B src/tools/sign-csl-expanded-media.py --database /frozen/database
     --output /task/media-audit-v1 --manifest-sha256 <externally frozen SHA256SUMS hash>

Only validation/ may preexist in a new output. The exclusive audit.lock prevents
reruns from overwriting evidence. progress.json is the latest snapshot; its history
is append-only. This technical audit cannot approve semantics or training data.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


sys.dont_write_bytecode = True
HELPER = Path(__file__).with_name('sign-ce-csl-import.py')
SPEC = importlib.util.spec_from_file_location('expanded_media_ce_import', HELPER)
ce = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ce)
# Reuse the original intake's streaming hash, path containment and stat checks.
sha, contained, signature = ce.sha, ce.contained, ce.signature
GATES = {'training_ready': False, 'model_training_ready': False,
         'human_approved': False, 'semantic_acceptance': False,
         'training_started': False, 'gpu_used': False}
HEX = re.compile(r'[0-9a-f]{64}')


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def save_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(dumps(value) + '\n')


def error(category, message):
    return {'category': category, 'message': str(message)}


def positive_int(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a frame count')
    result = int(value)
    if result <= 0 or str(result) != str(value):
        raise ValueError('Expected a positive integer')
    return result


def probe(path, ffprobe, timeout):
    command = [str(ffprobe), '-v', 'error', '-threads', '1', '-count_frames',
               '-select_streams', 'v:0', '-show_entries',
               'stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,nb_read_frames,duration:format=duration',
               '-of', 'json', str(path)]
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    return {'command': command, 'exitcode': process.returncode,
            'stdout': stdout.decode('utf-8', errors='backslashreplace'),
            'stderr': stderr.decode('utf-8', errors='backslashreplace'),
            'timed_out': timed_out, 'elapsed_seconds': time.monotonic() - started}


def audit_media(database, row, manifest, samples, ffprobe, timeout):
    """One unique SHA, always returning a record even after a per-file exception."""
    started = time.monotonic()
    record = {**GATES, 'inventory_index': row.get('inventory_index'),
              'relative_path': row.get('relative_path'), 'expected_sha256': row.get('sha256'),
              'expected_bytes': row.get('bytes'), 'sha256': None, 'bytes': None,
              'codec': None, 'dimensions': None, 'fps': None, 'framecount': None,
              'full_decode': False, 'decode_attempted': False, 'exitcode': None,
              'stderr': '', 'stdout': '', 'command': None, 'timed_out': False,
              'samples': samples, 'container_reported': [], 'expected_frames': None,
              'errors': list(row.get('inventory_errors', [])), 'started_at_utc': now()}
    problems = record['errors']
    try:
        path = contained(database, row['relative_path'])
    except (ValueError, OSError, TypeError) as exc:
        problems.append(error('unsafe_path', exc))
        path = None
    try:
        if path is not None:
            if not path.is_file():
                raise FileNotFoundError(str(path))
            before = signature(path)
            record.update(stat_before=list(before), bytes=before[2], sha256=sha(path))
            if not HEX.fullmatch(str(row.get('sha256', ''))) or record['sha256'] != row['sha256']:
                problems.append(error('sha256_mismatch', 'Actual media differs from frozen inventory'))
            record['manifest_sha256'] = manifest.get(row['relative_path'])
            if record['sha256'] != record['manifest_sha256']:
                problems.append(error('manifest_media_sha256_mismatch', 'Actual media differs from SHA256SUMS'))
            if type(row.get('bytes')) is not int or record['bytes'] != row['bytes']:
                problems.append(error('byte_size_mismatch', 'Actual media bytes differ from inventory'))
            expected_frames = sorted({positive_int(s['frames']) for s in samples if s.get('frames') is not None})
            record['expected_frames'] = expected_frames or None
            record['expected_frames_basis'] = 'samples.frames' if expected_frames else 'not_provided'
            record['decode_attempted'] = True
            decoded = probe(path, ffprobe, timeout)
            record.update(decoded)
            decode_ok = True
            if decoded['timed_out']:
                problems.append(error('decode_timeout', f'Exceeded {timeout} seconds; process killed and reaped'))
                decode_ok = False
            if decoded['exitcode'] != 0:
                problems.append(error('decode_exit_nonzero', f"ffprobe exitcode={decoded['exitcode']}"))
                decode_ok = False
            if decoded['stderr'].strip():
                problems.append(error('decode_stderr', 'ffprobe -v error emitted stderr; raw stderr retained'))
                decode_ok = False
            try:
                raw = json.loads(decoded['stdout'])
                stream = raw['streams'][0]
                frames = positive_int(stream['nb_read_frames'])
                width, height = positive_int(stream['width']), positive_int(stream['height'])
                fps = float(Fraction(stream['avg_frame_rate']))
                if not math.isfinite(fps) or fps <= 0 or not stream.get('codec_name'):
                    raise ValueError('Invalid codec or FPS')
                record.update(codec=stream['codec_name'], dimensions=[width, height],
                              fps=fps, avg_frame_rate=stream['avg_frame_rate'], framecount=frames,
                              current_container_reported_frames=stream.get('nb_frames'),
                              probe_result=raw)
            except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as exc:
                problems.append(error('invalid_probe_output', exc))
                decode_ok = False
            record['full_decode'] = decode_ok
            if record['framecount'] is not None and expected_frames and any(
                    count != record['framecount'] for count in expected_frames):
                problems.append(error('expected_framecount_mismatch',
                                      f"decoded={record['framecount']}; samples.frames={expected_frames}"))
            for sample in samples:
                count = sample.get('container_reported_frames')
                if count is not None:
                    record['container_reported'].append({
                        'sample_id': sample['id'], 'basis': 'container_reported',
                        'frames': count, 'matches_decoded': count == record['framecount'],
                        'authoritative_expected_count': False})
            if signature(path) != before or contained(database, row['relative_path']) != path:
                problems.append(error('media_changed_during_audit', 'Source stat/path changed'))
    except FileNotFoundError as exc:
        problems.append(error('missing_media', exc))
    except Exception as exc:
        problems.append(error('media_exception', f'{type(exc).__name__}: {exc}'))
    record.update(passed=not problems and record['full_decode'],
                  completed_at_utc=now(), elapsed_seconds=time.monotonic() - started)
    return record


def read_manifest(raw):
    entries = {}
    for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        parts = line.split('  ', 1)
        if len(parts) != 2 or not HEX.fullmatch(parts[0]) or parts[1] in entries:
            raise ValueError(f'Malformed/duplicate SHA256SUMS line {number}')
        digest, name = parts
        relative = Path(name)
        if not name or relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError(f'Unsafe SHA256SUMS line {number}: {name}')
        entries[name] = digest
    if not entries:
        raise ValueError('Empty SHA256SUMS')
    return entries


def sample_index(samples, inventory, manifest, fail):
    indexed = defaultdict(list)
    inventory_hashes = {r.get('sha256') for r in inventory}
    identities = set()
    for sample in samples:
        sid, digest, path = sample.get('id'), sample.get('media_sha256'), sample.get('local_video')
        if not sid or sid in identities or digest not in inventory_hashes or manifest.get(path) != digest:
            fail('sample_media_binding', {'sample_id': sid, 'local_video': path, 'sha256': digest})
        identities.add(sid)
        metadata = sample.get('video', {}).get('probe', {}).get('metadata', {})
        container_frames = metadata.get('container_reported_frames')
        if container_frames is None:
            streams = sample.get('video_metadata', {}).get('streams', [])
            videos = [s for s in streams if s.get('codec_type') == 'video']
            if videos and str(videos[0].get('nb_frames', '')).isdigit():
                container_frames = int(videos[0]['nb_frames'])
        indexed[digest].append({'id': sid, 'dataset_id': sample.get('dataset_id'),
                                'status': sample.get('status'), 'local_video': path,
                                'frames': sample.get('frames'),
                                'container_reported_frames': container_frames})
    return indexed


def run_audit(database, output, manifest_sha256, ffprobe=Path('/opt/homebrew/bin/ffprobe'),
              workers=4, timeout=1800):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('Use 1..4 workers')
    if not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError('Timeout must be finite, positive and at most 3600 seconds')
    source, out_arg = Path(database).absolute(), Path(output).absolute()
    for path in (source, out_arg):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlink in input/output root rejected')
    database, output = source.resolve(), out_arg.resolve()
    if output == database or output.is_relative_to(database) or database.is_relative_to(output):
        raise ValueError('Output must be separate from frozen database')
    if output.exists() and any(p.name != 'validation' for p in output.iterdir()):
        raise FileExistsError('Audit output already exists; preserve it and choose a NEW output')
    output.mkdir(parents=True, exist_ok=True)
    save_new(output / 'audit.lock', {'pid': os.getpid(), 'started_at_utc': now()})
    started = time.monotonic()
    failure_counts, counts = Counter(), Counter()
    failures = (output / 'failures.jsonl').open('x', encoding='utf-8', buffering=1)
    records = (output / 'records.jsonl').open('x', encoding='utf-8', buffering=1)
    manifest_records = (output / 'manifest-records.jsonl').open('x', encoding='utf-8', buffering=1)
    history = (output / 'progress.jsonl').open('x', encoding='utf-8', buffering=1)
    state = {**GATES, 'schema': 'signbridge-csl-expanded-media-progress-v1',
             'status': 'preflight', 'total': 0, 'completed': 0, 'passed': 0, 'failed': 0,
             'started_at_utc': now(), 'workers': workers, 'decoder_threads': 1,
             'timeout_seconds_per_media': timeout, 'database': str(database), 'output': str(output)}
    provenance_hash = None
    signatures, manifest, inventory, finished = {}, {}, [], []
    last_progress = 0

    def fail(category, detail):
        failure_counts[category] += 1
        failures.write(dumps({'at_utc': now(), 'category': category, 'detail': detail}) + '\n')

    def progress(force=False, in_flight=None):
        nonlocal last_progress
        if not force and time.monotonic() - last_progress < 5:
            return
        state.update(updated_at_utc=now(), elapsed_seconds=time.monotonic() - started,
                     failure_categories=dict(failure_counts), manifest_entries_checked=counts['manifest_checked'])
        if in_flight is not None:
            state['in_flight'] = in_flight
        snapshot = dumps(state) + '\n'
        temp = output / 'progress.next.json'
        with temp.open('x', encoding='utf-8') as stream:
            stream.write(snapshot)
        os.replace(temp, output / 'progress.json')
        history.write(snapshot)
        print(snapshot, end='', flush=True)
        last_progress = time.monotonic()

    def checked_manifest_record(name, expected, actual, problems, stat=None):
        counts['manifest_checked'] += 1
        if problems:
            counts['manifest_failed'] += 1
        manifest_records.write(dumps({'relative_path': name, 'expected_sha256': expected,
                                      'sha256': actual, 'passed': not problems, 'errors': problems}) + '\n')
        if stat is not None:
            signatures[name] = stat

    progress(force=True)
    try:
        (output / 'inputs').mkdir()
        (output / 'tool').mkdir()
        input_hashes, tool_hashes = {}, {}
        for path in [Path(__file__).resolve(), HELPER.resolve()]:
            raw = path.read_bytes()
            (output / 'tool' / path.name).write_bytes(raw)
            tool_hashes[str(path)] = hashlib.sha256(raw).hexdigest()
        for name in ['SHA256SUMS', 'media-inventory.jsonl', 'samples.jsonl']:
            path = contained(database, name)
            raw = path.read_bytes()
            (output / 'inputs' / name).write_bytes(raw)
            input_hashes[name] = hashlib.sha256(raw).hexdigest()
        executable = Path(ffprobe).resolve(strict=True)
        version = subprocess.run([str(executable), '-version'], capture_output=True, timeout=10, check=False)
        provenance = {**GATES, 'schema': 'signbridge-csl-expanded-media-provenance-v1',
                      'created_at_utc': now(), 'tool': tool_hashes, 'inputs': input_hashes,
                      'database': str(database), 'expected_manifest_sha256': manifest_sha256,
                      'ffprobe': {'path': str(executable), 'sha256': sha(executable),
                                  'version_exitcode': version.returncode,
                                  'version_stdout': version.stdout.decode('utf-8', errors='backslashreplace'),
                                  'version_stderr': version.stderr.decode('utf-8', errors='backslashreplace')},
                      'python': {'executable': sys.executable, 'version': sys.version},
                      'invocation': sys.argv, 'arguments': {'workers': workers, 'timeout': timeout},
                      'source_reuse': ['sign-ce-csl-import.py:sha,contained,signature',
                                       'sign-csl-reference-database.py:manifest (failure-preserving adaptation)'],
                      'scope': 'all unique frozen media; technical CPU video decode only; aliases retained',
                      'semantic_gate': 'every action requires two complete nine-dimensional acceptances of the same version'}
        save_new(output / 'provenance.json', provenance)
        provenance_hash = sha(output / 'provenance.json')
        (output / 'provenance.sha256').write_text(provenance_hash + '  provenance.json\n')
        save_new(output / 'tool.json', tool_hashes)
        save_new(output / 'inputs.json', input_hashes)
        state['provenance_sha256'] = provenance_hash
        if not HEX.fullmatch(str(manifest_sha256)) or input_hashes['SHA256SUMS'] != manifest_sha256:
            fail('manifest_sha256_mismatch', {'expected': manifest_sha256, 'actual': input_hashes['SHA256SUMS']})
            raise ValueError('Pinned frozen SHA256SUMS differs')
        if version.returncode != 0:
            fail('ffprobe_version_failed', version.returncode)
            raise ValueError('ffprobe preflight failed')
        manifest = read_manifest((output / 'inputs/SHA256SUMS').read_bytes())
        for name in ['media-inventory.jsonl', 'samples.jsonl']:
            if manifest.get(name) != input_hashes[name]:
                fail('input_sha256_mismatch', name)
                raise ValueError('Frozen input differs: ' + name)
        inventory = [json.loads(line) for line in (output / 'inputs/media-inventory.jsonl').read_text().splitlines() if line.strip()]
        samples = [json.loads(line) for line in (output / 'inputs/samples.jsonl').read_text().splitlines() if line.strip()]
        if not inventory or any(not isinstance(row, dict) for row in inventory + samples):
            raise ValueError('Expected nonempty inventory and object JSONL rows')
        state.update(total=len(inventory), sample_count=len(samples), status='verifying_manifest')
        sample_map = sample_index(samples, inventory, manifest, fail)
        aliases = defaultdict(list)
        for name, digest in manifest.items():
            if Path(name).suffix.lower() == '.mp4':
                aliases[digest].append(name)
        paths, hashes = Counter(), Counter()
        for i, row in enumerate(inventory):
            row['inventory_index'] = i
            row['inventory_errors'] = []
            paths[row.get('relative_path')] += 1
            hashes[row.get('sha256')] += 1
        for row in inventory:
            if paths[row.get('relative_path')] != 1 or hashes[row.get('sha256')] != 1:
                row['inventory_errors'].append(error('duplicate_inventory_identity', 'Inventory must contain unique paths and SHAs'))
        media_paths = {row.get('relative_path') for row in inventory}
        for name, expected in manifest.items():
            if name in media_paths:
                continue
            actual, stat, problems = None, None, []
            try:
                path = contained(database, name)
                stat = signature(path)
                actual = sha(path)
                if actual != expected:
                    problems.append(error('manifest_sha256_mismatch', name))
                if signature(path) != stat:
                    problems.append(error('manifest_file_changed', name))
            except Exception as exc:
                problems.append(error('unsafe_path' if isinstance(exc, ValueError) else 'manifest_file_exception', exc))
            checked_manifest_record(name, expected, actual, problems, stat)
            for problem in problems:
                fail(problem['category'], {'relative_path': name, 'message': problem['message']})
            progress()
        state['status'] = 'decoding'
        progress(force=True)
        # Largest files first avoid a long serial tail; no more than four queued jobs.
        pending = iter(sorted(inventory, key=lambda r: r.get('bytes', 0) if type(r.get('bytes')) is int else 0, reverse=True))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            active = {}

            def enqueue():
                row = next(pending, None)
                if row is None:
                    return
                future = pool.submit(audit_media, database, row, manifest,
                                     sample_map.get(row.get('sha256'), []), executable, timeout)
                active[future] = row

            for _ in range(workers):
                enqueue()
            while active:
                done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    row = active.pop(future)
                    try:
                        record = future.result()
                    except Exception as exc:
                        record = {**GATES, 'relative_path': row.get('relative_path'),
                                  'inventory_index': row['inventory_index'], 'expected_sha256': row.get('sha256'),
                                  'passed': False, 'full_decode': False, 'sha256': None,
                                  'errors': [error('worker_exception', f'{type(exc).__name__}: {exc}')]}
                    record['aliases'] = aliases.get(row.get('sha256'), [])
                    records.write(dumps(record) + '\n')
                    finished.append(record)
                    counts['decoded'] += bool(record['full_decode'])
                    counts['decoded_frames'] += record.get('framecount') or 0
                    state['completed'] += 1
                    state['passed' if record['passed'] else 'failed'] += 1
                    for problem in record['errors']:
                        fail(problem['category'], {'inventory_index': row['inventory_index'],
                                                   'relative_path': row.get('relative_path'), 'message': problem['message']})
                    if row.get('relative_path') in manifest:
                        manifest_errors = []
                        if record.get('sha256') != manifest[row['relative_path']]:
                            manifest_errors.append(error('manifest_media_sha256_mismatch', 'See media record'))
                        checked_manifest_record(row['relative_path'], manifest[row['relative_path']],
                                                record.get('sha256'), manifest_errors, record.get('stat_before'))
                    enqueue()
                progress(in_flight=[r['relative_path'] for r in active.values()])
        state['status'] = 'verifying_unchanged_sources'
        progress(force=True, in_flight=[])
        for name, before in signatures.items():
            try:
                if list(signature(contained(database, name))) != list(before):
                    fail('source_changed_after_verification', name)
            except Exception as exc:
                fail('source_changed_after_verification', {'relative_path': name, 'error': str(exc)})
        actual_files = {p.relative_to(database).as_posix() for p in database.rglob('*') if p.is_file() or p.is_symlink()}
        if actual_files - {'SHA256SUMS'} != set(manifest):
            fail('manifest_tree_coverage', {'unlisted': sorted(actual_files - {'SHA256SUMS'} - set(manifest)),
                                            'missing': sorted(set(manifest) - actual_files)})
        for name, expected in input_hashes.items():
            if sha(contained(database, name)) != expected:
                fail('input_changed_during_audit', name)
        for path, expected in tool_hashes.items():
            if sha(path) != expected:
                fail('tool_changed_during_audit', path)
        if sha(executable) != provenance['ffprobe']['sha256']:
            fail('ffprobe_changed_during_audit', str(executable))
        state['status'] = 'completed_with_failures' if failure_counts else 'completed'
    except Exception as exc:
        fail('audit_exception', f'{type(exc).__name__}: {exc}')
        state['status'] = 'failed_preflight' if not finished else 'incomplete_with_failures'
    finally:
        progress(force=True, in_flight=[])
        report = {**state, 'schema': 'signbridge-csl-expanded-media-audit-v1',
                  'completed_at_utc': now(), 'total_inventory_media': len(inventory),
                  'full_decodes': counts['decoded'], 'decoded_framecount': counts['decoded_frames'],
                  'failure_categories': dict(failure_counts), 'failure_events': sum(failure_counts.values()),
                  'manifest_verification': {'entries': len(manifest), 'checked': counts['manifest_checked'],
                                             'failed': counts['manifest_failed']},
                  'all_media_accounted': bool(inventory) and state['completed'] == len(inventory),
                  'source_files_unchanged': state['status'] == 'completed',
                  'provenance_sha256': provenance_hash,
                  'container_count_policy': 'container_reported only; never invented as expected source frames',
                  'semantic_gate': 'two complete nine-dimensional acceptances per same action version remain required',
                  'records_sha256': sha(output / 'records.jsonl'),
                  'manifest_records_sha256': sha(output / 'manifest-records.jsonl'),
                  'failures_sha256': sha(output / 'failures.jsonl')}
        save_new(output / 'report.json', report)
        for stream in (records, failures, manifest_records, history):
            stream.close()
        print(dumps({'status': report['status'], 'completed': report['completed'],
                     'failed': report['failed'], 'failure_categories': dict(failure_counts),
                     'report': str(output / 'report.json')}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--ffprobe', type=Path, default=Path('/opt/homebrew/bin/ffprobe'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=1800)
    args = parser.parse_args()
    report = run_audit(args.database, args.output, args.manifest_sha256,
                       args.ffprobe, args.workers, args.timeout)
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
