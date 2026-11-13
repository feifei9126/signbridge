#!/usr/bin/env python3
# Assemble the demo vocabulary from audited sources. Display-only: no approval or training flags change.
import argparse
import hashlib
import json
import re
from pathlib import Path

FLAGS = {'human_approved': False, 'training_ready': False, 'model_training_ready': False,
         'text_verified': '', 'semantics_approved': False, 'boundaries_approved': False,
         'training_started': False}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def norm(text):
    return re.sub('[（(].*?[）)]', '', text).strip()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(work, builtin_src, output, native_src=None):
    work, output = Path(work), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Choose a new output directory')
    paths = {'db_all_units': work / 'db-all-units-20261111.json',
             'validated_labels': work / 'validated-units-labels-20261111.json',
             'class_mapping': work / 'class-mapping-107units-20261111.json',
             'native_index': Path(native_src) / 'native-index.json' if native_src else work / 'native-library-20261112-v1' / 'native-index.json',
             'canonical_index': work / 'canonical-native-v1' / 'index.json',
             'builtin_dictionary': Path(builtin_src)}
    db = {u['id']: u['text'] for u in load(paths['db_all_units'])['units']}
    val = {u['id']: u['label'] for u in load(paths['validated_labels'])['units']}
    conflicts = [i for i in val if i in db and db[i] != val[i]]
    mapping = load(paths['class_mapping'])
    unresolved = [i for i in mapping if i not in db and i not in val]
    entries = {}

    def add(text, source):
        key = norm(text)
        e = entries.setdefault(key, {'text': key, 'forms': [], 'sources': [], 'display_motion_id': None, 'isolated_motion_id': None})
        if text not in e['forms']:
            e['forms'].append(text)
        if source not in e['sources']:
            e['sources'].append(source)
        return e

    for i in mapping:
        text = db.get(i) or val.get(i)
        if text:
            add(text, 'model_107')
    for c in load(paths['native_index'])['clips']:
        e = add(c['text'], 'native_display_candidate')
        e['display_motion_id'] = c['id']
        if c.get('wrist_amplitude_reduced'):
            e['wrist_amplitude_reduced'] = True
    for c in load(paths['canonical_index'])['clips']:
        e = add(c['text'], 'canonical_motion_candidate')
        if e['display_motion_id'] is None:
            e['isolated_motion_id'] = 'native_' + c['id']
    q = chr(34)
    glosses = re.findall('gloss: ' + q + '([^' + q + ']+)' + q, paths['builtin_dictionary'].read_text(encoding='utf-8'))
    for g in glosses:
        add(g, 'builtin_dictionary')
    counts = {}
    rows = []
    for key in sorted(entries):
        e = entries[key]
        if e['display_motion_id']:
            status = ('wrist_amplitude_reduced_candidate' if e.get('wrist_amplitude_reduced')
                      else 'native_display_candidate')
        elif 'builtin_dictionary' in e['sources']:
            status = 'builtin_handmade_pose'
        elif e['isolated_motion_id']:
            status = 'isolated_by_technical_gate'
        else:
            status = 'list_only'
        e['motion_status'] = status
        counts[status] = counts.get(status, 0) + 1
        rows.append({**e, **FLAGS})
    output.mkdir(parents=True)
    summary = {'total_entries': len(rows), 'motion_status': counts, 'builtin_glosses_found': len(glosses),
               'model_107_unresolved': unresolved, 'db_vs_validated_conflicts': conflicts}
    ui_rows = [{'text': r['text'], 'forms': r['forms'], 'status': r['motion_status'],
                'nativeId': r.get('display_motion_id')} for r in rows]
    result = {'schema': 'signbridge-demo-vocabulary-ui-v1', **FLAGS, 'humanApproved': False,
              'summary': summary, 'entries': ui_rows,
              'input_sha256': {k: sha(v) for k, v in paths.items()}, 'tool_sha256': sha(__file__),
              'policy': 'list_only entries have no motion and must not borrow another motion; all flags false', **FLAGS}
    (output / 'vocabulary.json').write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + chr(10), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Assemble demo vocabulary')
    parser.add_argument('--work', required=True)
    parser.add_argument('--builtin', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--native', help='Native library directory to index (native-index.json inside)')
    args = parser.parse_args()
    main(args.work, args.builtin, args.output, args.native)
