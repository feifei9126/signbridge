"""Build an immutable SMPLer-X input package with exact clip duplicates fit once.

Usage:
  python sign-word-motion-dedupe.py build-package --report REPORT.json --source-sums SHA256SUMS --candidate-root CANDIDATE_ROOT --output NEW_PACKAGE
  python sign-word-motion-dedupe.py split-package --package NEW_PACKAGE --output NEW_CHUNKS --chunk-size 24
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil

import numpy as np


HERE = Path(__file__).resolve().parent


def load_tool(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


data = load_tool('sign-data.py', 'word_motion_dedupe_data')
runner = load_tool('sign-source-catchup-smplx.py', 'word_motion_dedupe_runner')


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def write_jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows))


def write_checksums(root):
    root = Path(root)
    (root / 'SHA256SUMS').write_text(''.join(
        data.sha256_file(path) + '  ' + path.relative_to(root).as_posix() + '\n'
        for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))


def split_package(master_path, output, chunk_size=24):
    master_path = Path(master_path).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists() or output in master_path.parents or master_path in output.parents:
        raise FileExistsError('Chunk output must be a new directory outside the parent package')
    if type(chunk_size) is not int or not 1 <= chunk_size <= 64:
        raise ValueError('Chunk size must be an integer between 1 and 64 sequences')
    _, sequences, keyframes, parent_sha = runner.validate_package(master_path)
    aliases = read_rows(master_path / 'aliases.jsonl')
    sequence_ids = {sequence['annotation_id'] for sequence in sequences}
    aliases_by_sequence = defaultdict(list)
    for row in aliases:
        if row.get('fit_sequence_id') not in sequence_ids:
            raise ValueError('Alias references an unknown fit sequence')
        if row.get('text_verified') != '' or row.get('human_approved') is not False or row.get('training_ready') is not False:
            raise ValueError('Alias carries a promoted approval/readiness status')
        aliases_by_sequence[row['fit_sequence_id']].append(row)
    if sum(map(len, aliases_by_sequence.values())) != len(aliases):
        raise ValueError('Some aliases were not associated with exactly one fit sequence')
    output.mkdir(parents=True)
    chunks = []
    for offset in range(0, len(sequences), chunk_size):
        group = sequences[offset:offset + chunk_size]
        number = len(chunks) + 1
        name = f'chunk-{number:03d}'
        target = output / name
        target.mkdir()
        selected_aliases = []
        for sequence in group:
            source_clip = (master_path / sequence['clip']).resolve(strict=True)
            if master_path not in source_clip.parents or data.sha256_file(source_clip) != sequence['clip_sha256']:
                raise ValueError('Parent package clip changed: ' + sequence['annotation_id'])
            destination = target / sequence['clip']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_clip, destination)
            selected_aliases.extend(aliases_by_sequence[sequence['annotation_id']])
        write_jsonl(target / 'sequences.jsonl', group)
        write_jsonl(target / 'keyframes.jsonl', [row for row in keyframes
            if row.get('annotation_id') in {sequence['annotation_id'] for sequence in group}])
        write_jsonl(target / 'aliases.jsonl', selected_aliases)
        write_json(target / 'dedup-report.json', {'schema': 'signbridge-word-motion-exact-content-dedup-chunk-v1',
            'parent_package_manifest_sha256': parent_sha, 'chunk_index_1based': number,
            'chunk_size': len(group), 'candidate_alias_count': len(selected_aliases),
            'training_ready': False, 'model_training_ready': False})
        write_json(target / 'manifest.json', {
            'schema': 'signbridge-smplerx-candidate-sequences-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
            'parent_package_manifest_sha256': parent_sha, 'chunk_index_1based': number,
            'sequence_count': len(group), 'frames': sum(row['frames'] for row in group),
            'fps': 25.0, 'keyframe_count': sum(len(row['mano_keyframes']) for row in group),
            'candidate_alias_count': len(selected_aliases), 'frames_are_temporally_contiguous_within_sequence': True,
            'text_verified_count': 0, 'human_approved': False, 'training_ready': False,
            'training_started': False, 'source_files_modified': False})
        write_checksums(target)
        runner.validate_package(target)
        chunks.append({'path': name, 'chunk_index_1based': number, 'sequence_count': len(group),
                       'frames': sum(row['frames'] for row in group),
                       'candidate_alias_count': len(selected_aliases),
                       'package_manifest_sha256': data.sha256_file(target / 'SHA256SUMS'),
                       'clip_bytes': sum((target / row['clip']).stat().st_size for row in group)})
    if sum(row['sequence_count'] for row in chunks) != len(sequences) or sum(row['candidate_alias_count'] for row in chunks) != len(aliases):
        raise ValueError('Chunk partition does not cover every sequence and alias exactly once')
    result = {'schema': 'signbridge-smplerx-candidate-chunk-index-v1',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'parent_package_manifest_sha256': parent_sha, 'chunk_size': chunk_size,
              'sequence_count': len(sequences), 'candidate_alias_count': len(aliases),
              'frame_count': sum(row['frames'] for row in sequences), 'chunks': chunks,
              'partition_exactly_once': True, 'training_ready': False, 'training_started': False}
    write_json(output / 'chunk-index.json', result)
    write_checksums(output)
    return result


def verify_sum_manifest(root, manifest_path):
    root = Path(root).resolve(strict=True)
    entries = {}
    for line in Path(manifest_path).read_text().splitlines():
        digest, relative = line.split('  ', 1)
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or relative in entries:
            raise ValueError('Malformed or repeated input checksum record')
        name = Path(relative)
        if name.is_absolute() or '..' in name.parts:
            raise ValueError('Input checksum path escaped its package')
        target = root / name
        try:
            target.resolve(strict=True).relative_to(root)
        except (ValueError, OSError) as error:
            raise ValueError('Input checksum path escaped its package') from error
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != root.parent) or not target.is_file() or data.sha256_file(target) != digest:
            raise ValueError('Input package checksum mismatch: ' + relative)
        entries[relative] = digest
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    actual.discard(Path(manifest_path).resolve().relative_to(root).as_posix())
    if set(entries) != actual:
        raise ValueError('Input manifest does not cover the exact package file set')
    return entries


def deduplicate_candidates(rows, candidate_root):
    root = Path(candidate_root).resolve(strict=True)
    groups = defaultdict(list)
    seen_ids = set()
    for row in rows:
        identifier = row.get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}', identifier):
            raise ValueError('Candidate ID is not safe for a fit package')
        if identifier in seen_ids:
            raise ValueError('Duplicate candidate ID')
        seen_ids.add(identifier)
        if (row.get('human_approved') is not False or row.get('training_ready') is not False or
                row.get('model_training_ready') is not False or row.get('text_verified') != ''):
            raise ValueError('Candidate package must not promote any approval or readiness flag')
        clip_hash = row.get('clip_sha256')
        if not isinstance(clip_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', clip_hash):
            raise ValueError('Candidate clip SHA-256 is missing')
        relative = row.get('reference_clip')
        if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('Candidate clip path is unsafe')
        clip = root / relative
        try:
            clip.resolve(strict=True).relative_to(root)
        except (ValueError, OSError) as error:
            raise ValueError('Candidate clip escaped its package') from error
        if clip.is_symlink() or any(parent.is_symlink() for parent in clip.parents if parent != root.parent) or not clip.is_file() or data.sha256_file(clip) != clip_hash:
            raise ValueError('Candidate clip hash differs: ' + identifier)
        meta = row.get('decoded_video') or {}
        if (type(meta.get('frames')) is not int or meta['frames'] < 4 or
                not isinstance(meta.get('fps'), (int, float)) or float(meta['fps']) != 25.0):
            raise ValueError('Candidate does not meet the continuous 25fps fitting contract: ' + identifier)
        if not re.fullmatch(r'[a-f0-9]{64}', row.get('source_sha256', '')) or not row.get('source_id'):
            raise ValueError('Candidate is missing exact source identity: ' + identifier)
        groups[clip_hash].append(row)
    result = []
    for digest in sorted(groups):
        aliases = sorted(groups[digest], key=lambda row: row['id'])
        clip_meta = {(r['decoded_video']['frames'], float(r['decoded_video']['fps'])) for r in aliases}
        if len(clip_meta) != 1:
            raise ValueError('Byte-identical clips have conflicting decoded timing metadata')
        result.append({'clip_sha256': digest, 'canonical': aliases[0], 'aliases': aliases})
    return result


def native_pose_exact_duplicates(rows, candidate_root):
    root = Path(candidate_root).resolve()
    groups = defaultdict(list)
    for row in rows:
        relative = row.get('native_asset')
        if not relative:
            continue
        path = root / relative
        try:
            path.resolve(strict=True).relative_to(root)
        except (ValueError, OSError) as error:
            raise ValueError('Native projection escaped the candidate package') from error
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent) or not path.is_file() or data.sha256_file(path) != row.get('native_asset_sha256'):
            raise ValueError('Native projection asset hash differs: ' + row['id'])
        value = json.loads(path.read_text())
        poses = np.asarray(value.get('poses'), dtype=np.float32)
        if poses.ndim != 3 or poses.shape[1:] != (55, 3) or not np.isfinite(poses).all():
            raise ValueError('Native projection is malformed: ' + row['id'])
        digest = hashlib.sha256(str(poses.shape).encode() + poses.tobytes()).hexdigest()
        groups[digest].append({'candidate_id': row['id'], 'label_candidate': row['proposed_text'],
                               'native_asset_sha256': row['native_asset_sha256'], 'frames': len(poses)})
    return [{'pose_sha256': digest, 'members': members} for digest, members in sorted(groups.items()) if len(members) > 1]


def build_package(report_path, source_sums, candidate_root, output):
    report_path = Path(report_path).resolve(strict=True)
    source_sums = Path(source_sums).resolve(strict=True)
    root = Path(candidate_root).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists() or output in root.parents or root in output.parents:
        raise FileExistsError('Choose a new output directory outside the source package')
    input_manifest = verify_sum_manifest(root, source_sums)
    if report_path != root / 'report.json' or data.sha256_file(report_path) != input_manifest.get('report.json'):
        raise ValueError('Source report is not covered by the frozen package manifest')
    report = json.loads(report_path.read_text())
    rows = read_rows(root / 'candidates.jsonl')
    if report.get('candidates') != rows or report.get('summary', {}).get('candidates') != len(rows):
        raise ValueError('Report and candidate JSONL differ')
    groups = deduplicate_candidates(rows, root)
    output.mkdir(parents=True)
    (output / 'clips').mkdir()
    sequences, aliases = [], []
    for group in groups:
        canonical = group['canonical']
        sequence_id = 'fit_' + group['clip_sha256'][:32]
        relative_clip = f'clips/{sequence_id}/clip.mp4'
        target = output / relative_clip
        target.parent.mkdir(parents=True)
        source = root / canonical['reference_clip']
        shutil.copyfile(source, target)
        if data.sha256_file(target) != group['clip_sha256']:
            raise ValueError('Copied unique clip hash differs: ' + sequence_id)
        sequence = {
            'annotation_id': sequence_id,
            'source_id': canonical['source_id'], 'source_sha256': canonical['source_sha256'],
            'label_candidate': canonical['proposed_text'], 'text_verified': '',
            'start_seconds': canonical['source_window_seconds'][0],
            'end_seconds': canonical['source_window_seconds'][1],
            'frames': canonical['decoded_video']['frames'], 'fps': float(canonical['decoded_video']['fps']),
            'clip': relative_clip, 'clip_sha256': group['clip_sha256'],
            'language': 'unconfirmed', 'mirror_status': 'unknown', 'signer_identity': 'unconfirmed',
            'sample_type': 'sentence_candidate', 'human_approved': False,
            'training_ready': False, 'mano_keyframes': [],
        }
        sequences.append(sequence)
        for candidate in group['aliases']:
            aliases.append({
                'fit_sequence_id': sequence_id, 'candidate_id': candidate['id'],
                'label_candidate': candidate['proposed_text'],
                'source_id': candidate['source_id'], 'source_sha256': candidate['source_sha256'],
                'source_absolute_path': candidate['source_absolute_path'],
                'source_window_seconds_nominal': candidate['source_window_seconds'],
                'evidence_kind': candidate['evidence_kind'],
                'language_scope_status': candidate['language_scope_status'],
                'candidate_clip_sha256': candidate['clip_sha256'],
                'existing_display_projection_candidate': candidate.get('native_asset'),
                'existing_projection_is_full_smplx': False,
                'text_verified': '', 'human_approved': False,
                'training_ready': False, 'model_training_ready': False,
                'word_boundaries_verified': False,
            })
    write_jsonl(output / 'sequences.jsonl', sequences)
    write_jsonl(output / 'keyframes.jsonl', [])
    write_jsonl(output / 'aliases.jsonl', aliases)
    native_duplicates = native_pose_exact_duplicates(rows, root)
    dedup = {
        'schema': 'signbridge-word-motion-exact-content-dedup-v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_candidate_report_sha256': data.sha256_file(report_path),
        'source_candidate_manifest_sha256': data.sha256_file(source_sums),
        'candidate_rows': len(rows), 'unique_exact_clip_contents': len(groups),
        'duplicate_clip_groups': sum(len(group['aliases']) > 1 for group in groups),
        'duplicate_rows_not_refit': sum(len(group['aliases']) - 1 for group in groups),
        'native_exact_pose_duplicate_groups': len(native_duplicates),
        'native_exact_pose_duplicate_details': native_duplicates,
        'near_duplicate_actions_removed': 0,
        'policy': 'Only byte-identical candidate clips are fitted once. Every label/source/window remains in aliases.jsonl. No candidate label is merged or approved. Similar but nonidentical motion is not deleted automatically.',
        'source_candidates_modified': False,
    }
    write_json(output / 'dedup-report.json', dedup)
    manifest = {
        'schema': 'signbridge-smplerx-candidate-sequences-v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_candidate_report_sha256': data.sha256_file(report_path),
        'source_candidate_manifest_sha256': data.sha256_file(source_sums),
        'sequence_count': len(sequences), 'frames': sum(row['frames'] for row in sequences),
        'fps': 25.0, 'keyframe_count': 0,
        'candidate_alias_count': len(aliases), 'duplicate_content_fit_jobs_removed': len(rows) - len(sequences),
        'frames_are_temporally_contiguous_within_sequence': True,
        'text_verified_count': 0, 'human_approved': False, 'training_ready': False,
        'training_started': False, 'source_files_modified': False,
    }
    write_json(output / 'manifest.json', manifest)
    (output / 'SHA256SUMS').write_text(''.join(
        data.sha256_file(path) + '  ' + path.relative_to(output).as_posix() + '\n'
        for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))
    validated, tasks, keyframes, _ = runner.validate_package(output)
    if len(tasks) != len(groups) or keyframes:
        raise ValueError('SMPLer-X package failed sequence/empty-keyframe validation')
    return {'package': str(output), **manifest, 'dedup': dedup,
            'manifest_sha256': data.sha256_file(output / 'SHA256SUMS')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build-package')
    build.add_argument('--report', type=Path, required=True)
    build.add_argument('--source-sums', type=Path, required=True)
    build.add_argument('--candidate-root', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    split = commands.add_parser('split-package')
    split.add_argument('--package', type=Path, required=True)
    split.add_argument('--output', type=Path, required=True)
    split.add_argument('--chunk-size', type=int, default=24)
    args = parser.parse_args()
    result = build_package(args.report, args.source_sums, args.candidate_root, args.output) if args.command == 'build-package' else split_package(args.package, args.output, args.chunk_size)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
