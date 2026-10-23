"""Audit local CE-CSL train/dev video-to-Gloss pairs without opening test data."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def checked_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts or '\\' in str(relative):
        raise ValueError('Unsafe relative path: ' + str(relative))
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink rejected: ' + str(relative))
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('Missing or escaping file: ' + str(relative))
    return path


def read_manifest(library):
    path = checked_path(library, 'SHA256SUMS')
    entries = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        if not re.fullmatch('[0-9a-f]{64}', digest) or name in entries:
            raise ValueError('Invalid/duplicate package manifest entry')
        entries[name] = digest
    return entries, sha(path)


def read_train_dev(library, manifest):
    samples, hashes = {}, {}
    identities, video_paths = set(), set()
    for split in ['train', 'dev']:
        relative = f'splits/{split}/samples.jsonl'
        path = checked_path(library, relative)
        digest = sha(path)
        if digest != manifest.get(relative):
            raise ValueError('Sample split digest differs: ' + relative)
        hashes[relative] = digest
        rows = []
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            sample_id, source_id = row.get('id'), row.get('source_id')
            translator, gloss, text = row.get('source_translator'), row.get('gloss_sequence'), row.get('proposed_text')
            relative_video = row.get('video_relative_path')
            video = row.get('video')
            if (not isinstance(relative_video, str) or Path(relative_video).is_absolute()
                    or '..' in Path(relative_video).parts or '\\' in relative_video):
                raise ValueError(f'Unsafe train/dev video path: {relative}:{line_number}')
            expected_relative = f'video/{split}/{translator}/{source_id}.mp4'
            if (row.get('schema') != 'signbridge-ce-csl-sample-v1' or row.get('source_split') != split
                    or not isinstance(sample_id, str) or not sample_id or sample_id in identities
                    or not isinstance(source_id, str) or not re.fullmatch(split + r'-[0-9]+', source_id)
                    or not isinstance(translator, str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', translator)
                    or not isinstance(text, str) or not text.strip() or not isinstance(gloss, list) or not gloss
                    or any(not isinstance(token, str) or not token for token in gloss)
                    or relative_video != expected_relative or not isinstance(video, dict)
                    or video.get('relative_path') != expected_relative
                    or not re.fullmatch('[a-f0-9]{64}', str(video.get('sha256', '')))
                    or type(video.get('bytes')) is not int or video['bytes'] < 1):
                raise ValueError(f'Malformed train/dev video-label row: {relative}:{line_number}')
            if relative_video in video_paths:
                raise ValueError('Duplicate video path in train/dev: ' + relative_video)
            if row.get('word_spans') not in ([], None):
                raise ValueError('Unexpected word-level spans; preserve sequence-level target contract')
            identities.add(sample_id); video_paths.add(relative_video); rows.append(row)
        if not rows:
            raise ValueError('Empty train/dev split: ' + relative)
        samples[split] = rows
    return samples, hashes


def probe_video(path, executable):
    result = subprocess.run(
        [str(executable), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=codec_name,width,height,avg_frame_rate,nb_frames,duration:format=duration',
         '-of', 'json', str(path)], capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace')[:500])
    raw = json.loads(result.stdout)
    streams = raw.get('streams') or []
    if not streams:
        raise ValueError('No video stream')
    stream = streams[0]
    from fractions import Fraction
    fps = float(Fraction(stream.get('avg_frame_rate', '0/1')))
    duration = float(stream.get('duration', raw.get('format', {}).get('duration', 'nan')))
    count = stream.get('nb_frames')
    metadata = {'codec': stream.get('codec_name'), 'width': int(stream.get('width', 0)),
                'height': int(stream.get('height', 0)), 'fps': fps, 'duration_seconds': duration,
                'container_reported_frames': int(count) if count and count.isdecimal() else None}
    if (metadata['width'] <= 0 or metadata['height'] <= 0 or not math.isfinite(fps) or fps <= 0
            or not math.isfinite(duration) or duration <= 0):
        raise ValueError('Invalid video header metadata')
    return metadata


def decode_video(path, executable):
    result = subprocess.run(
        [str(executable), '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
         '-map', '0:v:0', '-f', 'null', '-'], capture_output=True, timeout=1200, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace')[-1000:])
    return {'decoded': True}


def metadata_matches(expected, actual):
    if not isinstance(expected, dict):
        return False
    for key in ['width', 'height', 'container_reported_frames']:
        if expected.get(key) is not None and actual.get(key) != expected.get(key):
            return False
    for key in ['fps', 'duration_seconds']:
        value = expected.get(key)
        if value is not None and (not isinstance(value, (int, float)) or
                                  not math.isclose(float(value), float(actual.get(key, float('nan'))),
                                                   rel_tol=1e-5, abs_tol=0.01)):
            return False
    return True


def inspect_clip(row, video_root, full_decode, probe, decode):
    relative = row['video_relative_path']
    record = {'id': row['id'], 'split': row['source_split'], 'translator_code': row['source_translator'],
              'video_relative_path': relative, 'text': row['proposed_text'], 'gloss_sequence': row['gloss_sequence'],
              'annotation_scope': row.get('annotation_scope'), 'word_spans_present': bool(row.get('word_spans')),
              'expected_sha256': row['video']['sha256'], 'expected_bytes': row['video']['bytes'],
              'status': 'failed', 'hash_matches': False, 'metadata_matches': False,
              'full_decode_requested': full_decode, 'full_decode_passed': None, 'errors': []}
    path = checked_path(video_root, relative)
    before = path.stat()
    actual_hash = sha(path)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Video changed during audit: ' + relative)
    record.update(actual_sha256=actual_hash, actual_bytes=after.st_size,
                  hash_matches=actual_hash == row['video']['sha256'] and after.st_size == row['video']['bytes'])
    if not record['hash_matches']:
        record['errors'].append('video_hash_or_size_mismatch')
        return record
    try:
        actual_metadata = probe(path)
        record['actual_metadata'] = actual_metadata
        record['metadata_matches'] = metadata_matches(row['video'].get('probe', {}).get('metadata'), actual_metadata)
        if not record['metadata_matches']:
            record['errors'].append('video_metadata_differs_from_intake')
    except Exception as error:
        record['probe_error'] = str(error)[:500]
        record['errors'].append('video_probe_failed')
    if full_decode:
        try:
            record['decode'] = decode(path)
            record['full_decode_passed'] = True
        except Exception as error:
            record['decode_error'] = str(error)[:1000]
            record['full_decode_passed'] = False
            record['errors'].append('full_decode_failed')
    record['status'] = 'passed' if record['metadata_matches'] and (not full_decode or record['full_decode_passed']) else 'failed'
    return record


def run_audit(library, video_root, output, full_decode=False, workers=4, ffprobe=None, ffmpeg=None,
              probe=None, decode=None, progress=None):
    library_arg, video_arg, output_arg = Path(library).absolute(), Path(video_root).absolute(), Path(output).absolute()
    if library_arg.is_symlink() or video_arg.is_symlink():
        raise ValueError('Input roots cannot be symlinks')
    library, video_root = library_arg.resolve(), video_arg.resolve()
    if not library.is_dir() or not video_root.is_dir():
        raise ValueError('Expected existing library and video roots')
    if output_arg.exists():
        raise FileExistsError('Choose a new audit directory')
    if output_arg.is_symlink() or any(output_arg.resolve() == root or output_arg.resolve().is_relative_to(root)
                                      or root.is_relative_to(output_arg.resolve()) for root in [library, video_root]):
        raise ValueError('Output must be new and separate from both inputs')
    if not 1 <= workers <= 16:
        raise ValueError('Workers must be in [1, 16]')
    manifest, manifest_sha = read_manifest(library)
    samples, sample_hashes = read_train_dev(library, manifest)
    runtime = {'python': sys.version, 'workers': workers}
    probe_executable = None
    decode_executable = None
    if probe is None:
        import shutil
        probe_executable = Path(ffprobe or shutil.which('ffprobe') or '')
        if not probe_executable.is_file():
            raise ValueError('ffprobe is required')
        probe_executable = probe_executable.resolve()
        runtime.update(ffprobe=str(probe_executable), ffprobe_sha256=sha(probe_executable))
        probe = lambda path: probe_video(path, probe_executable)
    if full_decode and decode is None:
        import shutil
        decode_executable = Path(ffmpeg or shutil.which('ffmpeg') or '')
        if not decode_executable.is_file():
            raise ValueError('ffmpeg is required for full decode')
        decode_executable = decode_executable.resolve()
        runtime.update(ffmpeg=str(decode_executable), ffmpeg_sha256=sha(decode_executable))
        decode = lambda path: decode_video(path, decode_executable)
    if not full_decode and decode is not None:
        raise ValueError('Decode callback supplied when full decode is disabled')
    flat = [row for split in ['train', 'dev'] for row in samples[split]]
    records = [None] * len(flat)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(inspect_clip, row, video_root, full_decode, probe, decode): index
                   for index, row in enumerate(flat)}
        for completed, future in enumerate(as_completed(futures), 1):
            records[futures[future]] = future.result()
            if progress and (completed % 100 == 0 or completed == len(flat)):
                progress({'audited': completed, 'total': len(flat)})
    for relative, digest in sample_hashes.items():
        if sha(checked_path(library, relative)) != digest:
            raise ValueError('Sample split changed during audit: ' + relative)
    if sha(checked_path(library, 'SHA256SUMS')) != manifest_sha:
        raise ValueError('Package manifest changed during audit')
    by_split = {split: [r for r in records if r['split'] == split] for split in ['train', 'dev']}
    translator_codes = {split: sorted({r['translator_code'] for r in rows}) for split, rows in by_split.items()}
    source_cross_split = sorted(set(translator_codes['train']) & set(translator_codes['dev']))
    video_hash_groups = {}
    for record in records:
        if record.get('actual_sha256'):
            video_hash_groups.setdefault(record['actual_sha256'], []).append(record['id'])
    duplicate_video_groups = [ids for ids in video_hash_groups.values() if len(ids) > 1]
    status_counts = {name: sum(r['status'] == name for r in records) for name in ['passed', 'failed']}
    full_decode_failures = sum(r['full_decode_passed'] is False for r in records)
    all_hashes = all(r['hash_matches'] for r in records)
    all_metadata = all(r['metadata_matches'] for r in records)
    all_decodes = full_decode if full_decode_failures == 0 and all(r['full_decode_passed'] is True for r in records) else False
    report = {
        'schema': 'signbridge-ce-csl-video-readiness-v1', 'status': 'completed',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'library': str(library), 'video_root': str(video_root),
        'source_manifest_sha256': manifest_sha,
        'source_sample_sha256': sample_hashes,
        'counts': {split: len(samples[split]) for split in ['train', 'dev']},
        'audited_pairs': len(records), 'status_counts': status_counts,
        'all_video_hashes_match': all_hashes, 'all_video_metadata_match': all_metadata,
        'full_decode_requested': bool(full_decode), 'all_full_decodes_passed': all_decodes,
        'full_decode_failures': full_decode_failures,
        'translator_codes_by_split': translator_codes,
        'shared_translator_codes': source_cross_split,
        'signer_independent_split': False,
        'duplicate_video_hash_groups': duplicate_video_groups,
        'sequence_level_gloss_available': True,
        'word_boundaries_verified': False,
        'signer_identity_verified': False,
        'upstream_license_verified': False,
        'test_read': False, 'test_enumerated': False,
        'training_started': False, 'training_ready': False, 'model_training_ready': False,
        'deployment_ready': False,
        'runtime': runtime,
        'limitations': [
            'Only train/dev sample files were opened. Test labels and test videos were not read, counted, hashed or decoded.',
            'Source translator codes are dataset-local identifiers; signer identity/equivalence is not verified.',
            'Labels provide sequence-level Gloss only; no word-level frame boundaries were used or inferred.',
            'This audit verifies pair integrity and decoding, not label correctness, signer generalization or CSL recognition accuracy.',
            'No source video was copied or uploaded; license/redistribution rights remain unverified.',
        ],
    }
    output = output_arg.resolve(); output.mkdir(parents=True)
    clips_path = output / 'clips.jsonl'
    with clips_path.open('x', encoding='utf-8') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    tool_path = Path(__file__).resolve()
    files = [clips_path, output / 'report.json']
    sums = ''.join(f'{sha(path)}  {path.name}\n' for path in files)
    (output / 'SHA256SUMS').write_text(sums, encoding='utf-8')
    report['tool_sha256'] = sha(tool_path)
    temp = output / 'report.json.tmp'
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(output / 'report.json')
    (output / 'SHA256SUMS').write_text(
        ''.join(f'{sha(path)}  {path.name}\n' for path in [clips_path, output / 'report.json']), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--video-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--full-decode', action='store_true')
    parser.add_argument('--ffprobe', type=Path)
    parser.add_argument('--ffmpeg', type=Path)
    args = parser.parse_args()
    report = run_audit(args.library, args.video_root, args.output, full_decode=args.full_decode,
                       workers=args.workers, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
                       progress=lambda value: print(json.dumps(value), flush=True))
    print(json.dumps({k: report[k] for k in ['status', 'counts', 'status_counts', 'all_video_hashes_match',
        'all_video_metadata_match', 'full_decode_requested', 'all_full_decodes_passed',
        'full_decode_failures', 'shared_translator_codes', 'training_ready']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
