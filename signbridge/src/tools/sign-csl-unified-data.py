"""Build a NEW source-bound multi-task research package, never merge model weights."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location('unified_gloss_contract', Path(__file__).with_name('sign-ce-csl-gloss.py'))
gloss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gloss)


def regular_file(root, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe relative input path')
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Input symlink rejected')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('Missing or unsafe input file')
    return path


def curate(rows, target, heldout_texts, heldout_targets=(), heldout_videos=()):
    alternatives = defaultdict(set)
    for row in rows:
        alternatives[gloss.normalize(row['text'])].add(tuple(row[target]))
    conflicts = {text for text, values in alternatives.items() if len(values) > 1}
    kept, rejected, seen = [], [], set()
    for row in rows:
        text, value = gloss.normalize(row['text']), tuple(row[target])
        key = (text, value)
        reason = None
        if text in conflicts:
            reason = 'same_text_conflicting_targets'
        elif text in heldout_texts:
            reason = 'heldout_text_overlap'
        elif value in heldout_targets:
            reason = 'heldout_target_sequence_overlap'
        elif row.get('video_sha256') in heldout_videos:
            reason = 'heldout_video_overlap'
        elif key in seen:
            reason = 'exact_duplicate'
        if reason:
            rejected.append({'id': row['id'], 'task': row['task'], 'reason': reason, 'text': row['text']})
        else:
            kept.append(row)
            seen.add(key)
    return kept, rejected


def build(ce_library, role_model, output):
    roots = [Path(p).absolute() for p in [ce_library, role_model]]
    if any(p.is_symlink() for p in roots):
        raise ValueError('Input roots cannot be symlinks')
    ce, roles = [p.resolve() for p in roots]
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError('Choose a NEW package directory')
    if any(output.resolve() == p or p in output.resolve().parents or output.resolve() in p.parents for p in [ce, roles]):
        raise ValueError('Output overlaps source evidence')
    consumed = {}
    def load_manifest(root):
        path = regular_file(root, 'SHA256SUMS')
        consumed[str(path)] = gloss.sha(path)
        result = {}
        for line in path.read_text().splitlines():
            checksum, name = line.split('  ', 1)
            if name in result:
                raise ValueError('Duplicate manifest entry')
            result[name] = checksum
        return result
    ce_manifest, role_manifest = load_manifest(ce), load_manifest(roles)
    def read(root, manifest, name):
        path = regular_file(root, name)
        digest = gloss.sha(path)
        if digest != manifest.get(name):
            raise ValueError('Source digest differs: ' + name)
        consumed[str(path)] = digest
        return path.read_text(encoding='utf-8')
    metadata = json.loads(read(roles, role_manifest, 'model.json'))
    labels = metadata['labels']
    expected_labels = ['O'] + [prefix + role for role in ['actor', 'predicate', 'patient', 'goal', 'time',
        'negation', 'modal', 'question', 'aspect', 'politeness', 'degree'] for prefix in ['B-', 'I-']]
    if metadata.get('schema') != 'signbridge-learned-chinese-roles-v1' or labels != expected_labels:
        raise ValueError('Incompatible prior role label contract')
    raw, data, quarantined = {}, {}, []
    for split in ['train', 'dev']:
        ce_rows = [json.loads(line) for line in read(ce, ce_manifest, f'splits/{split}/samples.jsonl').splitlines() if line.strip()]
        samples = []
        for row in ce_rows:
            gloss.validate_sample(row, split)
            samples.append({'id': row['id'], 'text': gloss.normalize(row['proposed_text']),
                            'gloss_sequence': row['gloss_sequence'], 'task': 'gloss',
                            'video_sha256': row.get('video', {}).get('sha256'),
                            'label_source': 'ce_csl_dataset', 'human_approved': False})
        raw['gloss-' + split] = samples
        source_split = 'train' if split == 'train' else 'validation'
        role_rows = [json.loads(line) for line in read(roles, role_manifest, source_split + '.jsonl').splitlines() if line.strip()]
        samples = []
        for i, row in enumerate(role_rows):
            text, tags = row.get('text'), row.get('tags')
            if (row.get('split') != source_split or row.get('label_source') != 'assistant_synthetic_chinese'
                    or row.get('human_approved') is not False or row.get('csl_supervision') is not False
                    or not isinstance(text, str) or not 1 <= len(text) <= 126 or gloss.normalize(text) != text
                    or not isinstance(tags, list) or len(tags) != len(text)
                    or any(type(t) is not int or not 0 <= t < len(labels) for t in tags)):
                raise ValueError('Malformed or relabeled role supervision')
            for position, tag in enumerate(tags):
                name = labels[tag]
                if name.startswith('I-') and (position == 0 or labels[tags[position - 1]] not in ['B-' + name[2:], name]):
                    raise ValueError('Invalid source BIO transition')
            samples.append({'id': f'roles-{split}-{i:05d}', 'text': text, 'tags': tags, 'task': 'roles',
                            'split_group': row['split_group'], 'label_source': 'assistant_synthetic_chinese',
                            'human_approved': False})
        raw['roles-' + split] = samples
    heldout = {gloss.normalize(r['text']) for key in ['gloss-dev', 'roles-dev'] for r in raw[key]}
    dev_groups = {r['split_group'] for r in raw['roles-dev']}
    for key, target in [('gloss-train', 'gloss_sequence'), ('roles-train', 'tags')]:
        candidates = raw[key]
        if key == 'roles-train':
            candidates = []
            for row in raw[key]:
                if row['split_group'] in dev_groups:
                    quarantined.append({'id': row['id'], 'task': row['task'], 'reason': 'role_dev_group_overlap', 'text': row['text']})
                else:
                    candidates.append(row)
        targets = {tuple(r['gloss_sequence']) for r in raw['gloss-dev']} if key == 'gloss-train' else set()
        videos = {r['video_sha256'] for r in raw['gloss-dev'] if r.get('video_sha256')} if key == 'gloss-train' else set()
        data[key], rejected = curate(candidates, target, heldout, targets, videos)
        quarantined.extend(rejected)
    data['gloss-dev'], data['roles-dev'] = raw['gloss-dev'], raw['roles-dev']
    if any(not rows for rows in data.values()):
        raise ValueError('Empty task split after curation')
    if len({r['id'] for rows in data.values() for r in rows}) != sum(map(len, data.values())):
        raise ValueError('Duplicate identity across task splits')
    report = {'schema': 'signbridge-csl-unified-data-v1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'raw_counts': {k: len(v) for k, v in raw.items()}, 'counts': {k: len(v) for k, v in data.items()},
        'quarantine_reasons': dict(Counter(r['reason'] for r in quarantined)),
        'source_files_sha256': consumed, 'tool_sha256': gloss.sha(Path(__file__)),
        'test_read': False, 'validation_added_to_training': False, 'labels_invented': False,
        'training_ready': False, 'model_training_ready': False, 'human_approved': False,
        'limitations': ['Role labels remain synthetic Chinese supervision, not CSL supervision.',
            'Prior initialization may have seen historical train/dev overlaps; development validation is not an independent final test.',
            'Historical motion checkpoints are not compatible with text labels; do not merge weights.',
            'No new video/motion word alignment or semantic approval is invented.']}
    for path, checksum in consumed.items():
        root = ce if Path(path).is_relative_to(ce) else roles
        regular_file(root, Path(path).relative_to(root).as_posix())
        if gloss.sha(path) != checksum:
            raise ValueError('Source changed during preparation')
    output.mkdir(parents=True)
    for key, rows in data.items():
        with (output / (key + '.jsonl')).open('x', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    gloss.write_json(output / 'role-labels.json', labels)
    gloss.write_json(output / 'report.json', report)
    gloss.write_json(output / 'quarantine.json', quarantined)
    (output / 'SHA256SUMS').write_text(''.join(f'{gloss.sha(p)}  {p.name}\n' for p in sorted(output.iterdir()) if p.is_file()))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ce-library', type=Path, required=True)
    parser.add_argument('--role-model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.ce_library, args.role_model, args.output), ensure_ascii=False, indent=2))
