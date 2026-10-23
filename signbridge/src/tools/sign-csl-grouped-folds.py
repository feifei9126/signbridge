"""Build train-only leave-one-source-code-out folds for CSL video recognition research."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_manifest(root):
    path = root / 'SHA256SUMS'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or unsafe package manifest')
    entries = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        if not re.fullmatch('[0-9a-f]{64}', digest) or name in entries:
            raise ValueError('Invalid/duplicate package manifest entry')
        entries[name] = digest
    return entries, sha(path)


def read_train(root, manifest):
    relative = 'splits/train/samples.jsonl'
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or unsafe train samples')
    digest = sha(path)
    if digest != manifest.get(relative):
        raise ValueError('Train sample digest differs')
    rows, identities, videos = [], set(), set()
    for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        identity, code = row.get('id'), row.get('source_translator')
        relative_video, target = row.get('video_relative_path'), row.get('gloss_sequence')
        if (row.get('schema') != 'signbridge-ce-csl-sample-v1' or row.get('source_split') != 'train'
                or not isinstance(identity, str) or not identity or identity in identities
                or not isinstance(code, str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', code)
                or row.get('source_translator_scope') != 'dataset_code_only_not_cross_dataset_identity'
                or not isinstance(target, list) or not target
                or any(not isinstance(token, str) or not token for token in target)
                or not isinstance(relative_video, str) or Path(relative_video).is_absolute()
                or '..' in Path(relative_video).parts or '\\' in relative_video
                or relative_video != f'video/train/{code}/{row.get("source_id")}.mp4'):
            raise ValueError(f'Malformed/ambiguous train sample: {relative}:{line_number}')
        if relative_video in videos:
            raise ValueError('Duplicate train video path: ' + relative_video)
        identities.add(identity); videos.add(relative_video)
        rows.append({'id': identity, 'source_code': code, 'video_relative_path': relative_video,
                     'gloss_sequence': target})
    if len({row['source_code'] for row in rows}) < 2:
        raise ValueError('At least two source codes are required for grouped folds')
    return rows, digest


def build_folds(library, output):
    library_arg, output_arg = Path(library).absolute(), Path(output).absolute()
    if library_arg.is_symlink():
        raise ValueError('Library root cannot be a symlink')
    library = library_arg.resolve()
    if not library.is_dir():
        raise ValueError('Expected an existing library directory')
    if output_arg.exists():
        raise FileExistsError('Choose a new fold output directory')
    output_resolved = output_arg.resolve()
    if output_resolved == library or output_resolved.is_relative_to(library) or library.is_relative_to(output_resolved):
        raise ValueError('Output must be separate from source data')
    manifest, manifest_sha = read_manifest(library)
    rows, train_sha = read_train(library, manifest)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['source_code']].append(row)
    codes = sorted(grouped)
    folds = []
    for heldout in codes:
        dev_rows = grouped[heldout]
        train_rows = [row for row in rows if row['source_code'] != heldout]
        folds.append({
            'id': 'leave-source-code-' + heldout + '-out',
            'heldout_source_code': heldout,
            'train_count': len(train_rows), 'dev_count': len(dev_rows),
            'train_source_codes': [code for code in codes if code != heldout],
            'train_samples': train_rows, 'dev_samples': dev_rows,
        })
    report = {
        'schema': 'signbridge-csl-source-code-folds-v1',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_manifest_sha256': manifest_sha,
        'train_samples_sha256': train_sha,
        'sample_count': len(rows), 'fold_count': len(folds),
        'group_field': 'source_translator',
        'group_counts': dict(sorted(Counter(row['source_code'] for row in rows).items())),
        'fold_policy': 'leave-one-dataset-source-code-out; train split only',
        'group_identity_verified': False,
        'signer_identity_verified': False,
        'signer_independent_claim': False,
        'official_dev_read': False, 'test_read': False,
        'human_approved': False, 'training_ready': False, 'model_training_ready': False,
        'deployment_ready': False,
        'limitations': [
            'Codes are source-local dataset labels; they are not verified person identities.',
            'This creates a stronger proxy split only if source codes map consistently to individual signers.',
            'Folds contain sequence-level Gloss labels, not frame-level word boundaries.',
            'The fold manifest is not a video model, training result or recognition accuracy claim.',
        ],
    }
    output = output_arg.resolve(); output.mkdir(parents=True)
    fold_path, report_path = output / 'folds.json', output / 'report.json'
    fold_path.write_text(json.dumps({'schema': report['schema'], 'folds': folds},
                                    ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    reproduce = ('# CE-CSL source-code folds\n\n'
        'Generated from the train split only. The official dev and test files were not opened.\n\n'
        'Each fold holds out one dataset-local source code. This is a proxy grouping, not a verified signer-independent split.\n\n'
        'No videos were copied. Resolve `video_relative_path` against the original local CE-CSL root after verifying the video readiness audit.\n')
    reproduce_path = output / 'README.md'; reproduce_path.write_text(reproduce, encoding='utf-8')
    files = [fold_path, report_path, reproduce_path]
    (output / 'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.name}\n' for path in files), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_folds(args.library, args.output), ensure_ascii=False, indent=2))
