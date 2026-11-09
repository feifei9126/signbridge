"""Attach twice-repeatable Demo references without promoting CSL training approval."""

import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import sqlite3


CHECKS = ('source_label_bound', 'source_frames_accounted', 'finite_bound_target_frames',
          'existing_numeric_repair_gate', 'intermediate_geometry_no_risks')
BINDINGS = ('source_sha256', 'clip_sha256', 'annotation_sha256', 'action_version_sha256',
            'target_model_sha256', 'source_frame_range_1based')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def reference_id(value):
    if not isinstance(value, str) or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,120}', value) is None:
        raise ValueError('Unsafe reference identity')
    return value


def demo_gate(first, second):
    """Reproducibility alone never converts repeated failures into successes."""
    reasons = []
    if first != second:
        reasons.append('round_results_differ')
    for row in (first, second):
        if row.get('status') != 'passed' or any(row.get('checks', {}).get(k) is not True for k in CHECKS):
            reasons.append('round_failed_or_required_check_missing')
        binding = row.get('binding', {})
        if any(key not in binding for key in BINDINGS):
            reasons.append('missing_version_binding')
        if any(not isinstance(binding.get(k), str) or re.fullmatch('[0-9a-f]{64}', binding[k]) is None for k in BINDINGS[:-1]):
            reasons.append('invalid_version_digest')
        interval = binding.get('source_frame_range_1based')
        if not isinstance(interval, list) or len(interval) != 2 or any(type(x) is not int for x in interval) or not 1 <= interval[0] <= interval[1]:
            reasons.append('invalid_source_range')
        if any(row.get(key) is not False for key in ('human_approved', 'training_ready', 'model_training_ready', 'semantic_certified')):
            reasons.append('approval_scope_changed')
        if row.get('acceptance_scope') != 'automated_demo_stability_and_same_version_reproducibility_not_standard_CSL_certification':
            reasons.append('acceptance_scope_changed')
    return {'demo_reference_accepted': not reasons, 'reasons': sorted(set(reasons)),
            'complete_CSL_certification': False, 'training_allowed': False}


def build(base, audit, output):
    base, audit, output = [Path(p).resolve() for p in (base, audit, output)]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in (base, audit)):
        raise ValueError('New output separate from frozen sources required')
    manifest = {}
    for line in (base / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name in manifest:
            raise ValueError('Duplicate base manifest path')
        manifest[name] = digest
    file = base / 'foundation-units.jsonl'
    if manifest.get('foundation-units.jsonl') != sha(file):
        raise ValueError('Frozen foundation units changed')
    units = lines(file)
    first = read(audit / 'consistency-round-1/results.json')
    second = read(audit / 'consistency-round-2/results.json')
    runs = [read(audit / f'consistency-round-{n}/run.json') for n in (1, 2)]
    for number, run in enumerate(runs, 1):
        if run.get('round') != number or run.get('payload_sha256') != sha(audit / f'consistency-round-{number}/results.json'):
            raise ValueError('Round run/payload binding differs')
    if runs[0].get('process') == runs[1].get('process'):
        raise ValueError('Two separate validation executions required')
    if len({r['id'] for r in first['records']}) != len(first['records']) or len({r['id'] for r in second['records']}) != len(second['records']):
        raise ValueError('Duplicate round identities')
    a, b = [{r['id']: r for r in d['records']} for d in (first, second)]
    plan = read(audit / 'plan.json')
    ids = [reference_id(r['id']) for r in plan['records']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate reference plan identities')
    fixes = {r['id']: r for r in read(audit / 'repair-v3/report.json')['records']}
    expected = {r['id'] for r in plan['records']}
    if set(a) != expected or set(b) != expected or set(fixes) != expected:
        raise ValueError('Round/plan/repair identities differ')
    output.mkdir()
    (output / 'reference-actions').mkdir()
    (output / 'validation').mkdir()
    accepted, pending = [], []
    for item in plan['records']:
        sid = item['id']
        gate = demo_gate(a[sid], b[sid])
        if not gate['demo_reference_accepted']:
            pending.append({'id': sid, 'text': item['text'], 'gate': gate})
            continue
        fix = fixes[sid]
        if fix['chosen'] is None:
            raise ValueError('Passed reference lacks a selected repair')
        selected = fix['profiles'][fix['chosen']]
        source = Path(selected['asset']).resolve()
        if not source.is_relative_to(audit) or sha(source) != a[sid]['binding']['action_version_sha256']:
            raise ValueError('Selected reference action changed')
        clip = read(source)
        binding = a[sid]['binding']
        if clip['boundary_annotation_sha256'] != binding['annotation_sha256'] or clip['source_frame_range_1based'] != binding['source_frame_range_1based']:
            raise ValueError('Reference annotation or range changed')
        if sha(item['source_clip']) != binding['clip_sha256'] or item['task']['source_sha256'] != binding['source_sha256']:
            raise ValueError('Reference source identity changed')
        if item['text'] != a[sid]['text'] or item['text'] != clip['text'] or item['unit_type'] not in ('word', 'sentence', 'phrase'):
            raise ValueError('Reference label or type differs')
        name = 'reference-actions/' + sid + '.json'
        shutil.copy2(source, output / name)
        record = {'id': sid, 'text': item['text'], 'unit_type': item['unit_type'], 'asset': name,
                  'sha256': sha(output / name), 'binding': binding, 'frames': clip['frames'], 'fps': clip['fps'],
                  'display_profile': fix['chosen'], 'demo_reference_accepted': True,
                  'acceptance_scope': a[sid]['acceptance_scope'], 'same_version_two_rounds': True,
                  'historical_approval_scope': 'motion_quality_only', 'human_approved': False,
                  'semantic_certified': False, 'word_boundary_verified': False,
                  'training_ready': False, 'model_training_ready': False, 'standard_motion_training_member': False}
        matches = [u for u in units if u['text'] == item['text'] and u['unit_type'] == item['unit_type']]
        if len(matches) > 1:
            raise ValueError('Ambiguous typed foundation label')
        if matches:
            unit = matches[0]
        else:
            unit = {'id': 'reference-unit-' + hashlib.sha256((item['unit_type'] + ':' + item['text']).encode()).hexdigest()[:20],
                    'text': item['text'], 'unit_type': item['unit_type'], 'target_structure_type': item['unit_type'],
                    'category': '历史模型参考补充', 'meaning': None, 'source_lexical_ids': [], 'source_caption_ids': [],
                    'action_ids': [], 'source_forms': [], 'training_ready': False, 'model_training_ready': False,
                    'word_boundary_verified': False, 'full_action_consistency_verified': False}
            units.append(unit)
        unit.setdefault('demo_reference_ids', []).append(sid)
        unit['demo_reference_scope'] = 'automated_reproducible_preview_not_CSL_training_label'
        record['foundation_unit_id'] = unit['id']
        accepted.append(record)
    for number in (1, 2):
        for name in ('results.json', 'run.json'):
            shutil.copy2(audit / f'consistency-round-{number}' / name, output / 'validation' / f'round-{number}-{name}')
    for name, rows in [('foundation-units', units), ('demo-reference-actions', accepted), ('reference-not-accepted', pending)]:
        (output / (name + '.jsonl')).write_text(''.join(json.dumps(x, ensure_ascii=False, allow_nan=False) + '\n' for x in rows))
    with sqlite3.connect(output / 'database.sqlite') as db:
        for table, rows in [('foundation_units', units), ('demo_references', accepted), ('reference_pending', pending)]:
            db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.executemany(f'INSERT INTO {table} VALUES (?,?)', [(x['id'], json.dumps(x, ensure_ascii=False, allow_nan=False)) for x in rows])
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity failure')
    report = {'schema': 'signbridge-foundation-demo-reference-layer-v1', 'base': str(base),
              'base_manifest_sha256': sha(base / 'SHA256SUMS'), 'base_units_retained': len(lines(file)),
              'foundation_units': len(units), 'new_typed_entries': len(units) - len(lines(file)),
              'demo_reference_actions_accepted': len(accepted), 'references_not_accepted': len(pending),
              'counts_by_type': {kind: sum(u['unit_type'] == kind for u in units) for kind in ('word', 'phrase', 'sentence')},
              'complete_CSL_two_round_passes': 0, 'training_ready': False, 'model_training_ready': False,
              'network_training_started': False, 'original_sources_unchanged': True, 'source_legacy_input_hash_gaps_retained': True}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'audit', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.audit, args.output), ensure_ascii=False))
