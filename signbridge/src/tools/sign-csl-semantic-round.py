"""Prepare a frozen Chinese semantic contract and diagnose unchanged CSL outputs.

No optimizer, GPU job, video inference, CSL relabeling or Demo promotion.
Synthetic BIO/entity/operator targets are explicitly Chinese-only supervision.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


upper = load('sign-csl-upper-transfer.py')
u, g = upper.u, upper.g
contrast = load('sign-semantic-contrast.py')
base = contrast.scope.base
SCHEMA = 'signbridge-basic-semantic-preparation-v1'
GATES = {**g.GATES, 'csl_supervision': False, 'weights_updated': False, 'optimizer_steps': 0}
PEOPLE = ['我', '你', '他', '她', '我们', '你们', '他们']
NEGATION = {'不', '没', '没有', '不是', '不能', '不要', '不想', '不用'}
normalize = u.base.normalize


def cases():
    rows = []
    def add(parts, group, partition, pair=None, relation='different', text=None):
        spans, tags = [], []
        if parts is not None:
            text = ''
            for role, value in parts:
                start = len(text); text += value
                spans.append({'role': role, 'text': value, 'start': start, 'end': len(text)})
                tags.extend([base.LABELS.index('B-' + role)] + [base.LABELS.index('I-' + role)] * (len(value) - 1))
            roles = {role: value for role, value in parts}
            operators = [role + ':' + value for role, value in parts if role in ('negation', 'modal')]
            kind = 'event' if 'predicate' in roles else 'entity'
        else:
            roles, operators, tags, kind = None, None, None, 'reject'
        rows.append({'id': 'semantic-' + hashlib.sha256(text.encode()).hexdigest()[:20],
                     'text': text, 'partition': partition, 'template_group': group,
                     'expected_kind': kind, 'expected_roles': roles, 'expected_operators': operators,
                     'tags': tags, 'spans': spans, 'pair_id': pair, 'pair_relation': relation,
                     'label_source': 'assistant_synthetic_chinese', 'human_approved': False, 'csl_supervision': False})
    for person in PEOPLE:
        add([('actor', person)], 'bare_singular' if len(person) == 1 else 'bare_plural', 'train' if len(person) == 1 else 'dev')
        for predicate in ['工作', '学习', '休息']:
            parts = [('actor', person), ('predicate', predicate)]
            add(parts, 'plain_event', 'train')
            for role, operator in [('negation', '不'), ('modal', '想'), ('modal', '能')]:
                add([parts[0], (role, operator), parts[1]], 'single_operator', 'train')
            add([parts[0], ('negation', '不'), ('modal', '能'), parts[1]], 'negated_ability', 'dev')
        for predicate in ['去', '来']:
            for goal in ['学校', '家', '医院']:
                add([('actor', person), ('predicate', predicate), ('goal', goal)], 'plain_goal', 'train')
        for predicate, patient in [('买', '书'), ('喝', '水'), ('看', '电影')]:
            add([('actor', person), ('predicate', predicate), ('patient', patient)], 'plain_object', 'train')
        for predicate in ['来', '看']:
            for aspect in ['了', '过']:
                add([('actor', person), ('predicate', predicate), ('aspect', aspect)], 'event_aspect', 'dev')
        for predicate in ['去', '来', '工作']:
            for order in [0, 1]:
                parts = [('negation', '不'), ('modal', '想')] if order == 0 else [('modal', '想'), ('negation', '不')]
                add([('actor', person), *parts, ('predicate', predicate)], 'desire_scope', 'challenge', 'scope-' + person + '-' + predicate)
            pair = 'time-' + person + '-' + predicate
            add([('time', '今天'), ('actor', person), ('predicate', predicate)], 'time_order', 'challenge', pair, 'same')
            add([('actor', person), ('time', '今天'), ('predicate', predicate)], 'time_order', 'challenge', pair, 'same')
        pair = 'occurrence-' + person
        add([('actor', person), ('predicate', '去'), ('aspect', '了')], 'occurrence_contrast', 'challenge', pair)
        add([('actor', person), ('negation', '没'), ('predicate', '去')], 'occurrence_contrast', 'challenge', pair)
    for i, (a, b) in enumerate([('我', '你'), ('我', '他'), ('他', '我们'), ('你们', '他们')]):
        for predicate in ['帮', '帮助', '等']:
            for actor, patient in [(a, b), (b, a)]:
                add([('actor', actor), ('predicate', predicate), ('patient', patient)], 'person_exchange', 'challenge', f'exchange-{i}-{predicate}')
    for text in ['我去学校然后回家', '我不想想工作', '我去学校你来医院', '他休息她学习']:
        add(None, 'training_contract_rejection', 'train', text=text)
    for text in ['我不想不能去', '我去。你来', '我帮你还是你帮我', '我想不想去', '我没不去',
                 '我们今天明天去', '你把我帮', '我没有你', '我没有工作', '我没有年龄',
                 '我不想今天去学校', '如果你来我就去', '我去火星', '我喝书', '😀', '今天今天我去']:
        add(None, 'outside_chinese_contract', 'challenge', text=text)
    validate_cases(rows)
    return rows


def validate_cases(rows):
    if not rows or len({r['id'] for r in rows}) != len(rows) or len({normalize(r['text']) for r in rows}) != len(rows):
        raise ValueError('Duplicate/empty semantic identities/text')
    groups, pairs = defaultdict(set), defaultdict(list)
    for row in rows:
        if (row.get('partition') not in ('train', 'dev', 'challenge') or row.get('label_source') != 'assistant_synthetic_chinese'
                or row.get('human_approved') is not False or row.get('csl_supervision') is not False
                or row['text'] != normalize(row['text']) and row['expected_roles'] is not None):
            raise ValueError('Invalid semantic label provenance or partition')
        groups[row['template_group']].add(row['partition'])
        if row.get('pair_id'): pairs[row['pair_id']].append(row)
        roles = row['expected_roles']
        if roles is None:
            if row['tags'] is not None or row['expected_kind'] != 'reject' or row['expected_operators'] is not None:
                raise ValueError('Unsupported text cannot acquire BIO labels')
            continue
        tags, index, observed = [], 0, {}
        for span in row['spans']:
            role, value = span['role'], span['text']
            if role in observed or not value or span['start'] != index or span['end'] != index + len(value) or row['text'][index:span['end']] != value:
                raise ValueError('Semantic span alignment/role uniqueness differs')
            tags.extend([base.LABELS.index('B-' + role)] + [base.LABELS.index('I-' + role)] * (len(value) - 1))
            observed[role] = value; index = span['end']
        operators = [s['role'] + ':' + s['text'] for s in row['spans'] if s['role'] in ('negation', 'modal')]
        if (tags != row['tags'] or index != len(row['text']) or observed != roles or operators != row['expected_operators']
                or row['expected_kind'] != ('event' if 'predicate' in roles else 'entity')):
            raise ValueError('Semantic BIO/operator target differs')
    if any(len(parts) != 1 for parts in groups.values()): raise ValueError('Template family crosses partitions')
    for pair in pairs.values():
        if (len(pair) != 2 or len({r['partition'] for r in pair}) != 1 or len({r['pair_relation'] for r in pair}) != 1
                or pair[0]['pair_relation'] not in ('same', 'different')):
            raise ValueError('Malformed contrast pair')
        same = (pair[0]['expected_roles'], pair[0]['expected_operators']) == (pair[1]['expected_roles'], pair[1]['expected_operators'])
        if same != (pair[0]['pair_relation'] == 'same'): raise ValueError('Contrast relation contradicts targets')


def partition(rows, reserved):
    validate_cases(rows)
    train, dev, removed = [], [], []
    for row in rows:
        if row['partition'] == 'challenge': continue
        if normalize(row['text']) in reserved:
            removed.append(row['id']); continue
        (train if row['partition'] == 'train' else dev).append(row)
    if not train or not dev: raise ValueError('Empty training/development partition after reservation')
    return train, dev, removed


def write_package(root, train, dev, provenance, frozen_content):
    u.new_output(root, []); root.mkdir(parents=True)
    (root / 'frozen-cases.json').write_bytes(frozen_content)
    for split, rows in [('train', train), ('dev', dev)]:
        (root / (split + '.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    report = {**GATES, 'schema': SCHEMA, 'task': 'Chinese BIO + entity/event/reject + ordered operators',
              'counts': {'train': len(train), 'dev': len(dev)}, 'labels': base.LABELS, 'provenance': provenance,
              'trainer_compatibility': 'Requires a typed semantic trainer. Not a Gloss/motion dataset; do not pass to old multitask trainer unchanged.',
              'coverage': training_coverage({'train': train, 'dev': dev}),
              'label_source': 'assistant_synthetic_chinese', 'independent_test': False}
    u.base.write_json(root / 'contract.json', report); u.seal(root)
    read_package(root)


def read_package(root):
    root = u.safe_path(root)
    manifest, used = u.read_manifest(root)
    report = json.loads(u.checked(root, 'contract.json', manifest, used))
    if (report.get('schema') != SCHEMA or report.get('labels') != base.LABELS
            or report.get('label_source') != 'assistant_synthetic_chinese'
            or any(report.get(k) != value for k, value in GATES.items())):
        raise ValueError('Semantic package contract differs')
    frozen_content = u.checked(root, 'frozen-cases.json', manifest, used)
    frozen = json.loads(frozen_content)
    if (used['frozen-cases.json'] != report.get('provenance', {}).get('fixture_sha256')
            or frozen.get('schema') != SCHEMA or frozen.get('frozen_before_current_round_evaluation') is not True
            or any(frozen.get(k) != value for k, value in GATES.items())):
        raise ValueError('Original frozen fixture binding differs')
    validate_cases(frozen['rows'])
    targets = {row['id']: row for row in frozen['rows']}
    data = {}
    for split in ['train', 'dev']:
        rows = [json.loads(line) for line in u.checked(root, split + '.jsonl', manifest, used).decode().splitlines()]
        if len(rows) != report['counts'][split] or not rows or any(r.get('partition') != split for r in rows):
            raise ValueError('Semantic split counts/partition differ')
        if any(row != targets.get(row.get('id')) for row in rows):
            raise ValueError('Packaged row differs from original frozen target')
        data[split] = rows
    validate_cases(data['train'] + data['dev'])
    if report.get('coverage') != training_coverage(data): raise ValueError('Training coverage contract differs')
    return data, report, used


def training_coverage(data):
    counts = {s: dict(Counter(r['expected_kind'] for r in rows)) for s, rows in data.items()}
    operators = {s: sorted({tuple(r['expected_operators']) for r in rows if r['expected_operators'] is not None})
                 for s, rows in data.items()}
    blockers = ['typed_semantic_trainer_not_implemented']
    if not any(len(x) >= 2 for x in operators['train']): blockers.append('compound_scope_absent_from_train')
    if not counts['dev'].get('reject'): blockers.append('no_dev_rejection_cases')
    return {'counts': counts, 'operator_orders': {s: [list(x) for x in values] for s, values in operators.items()},
            'blockers': blockers, 'ready_for_GPU_training': False,
            'interpretation': 'Seed data contract; requires broader grouped supervision and a typed trainer before a GPU experiment.'}


def evaluate(parser, rows):
    # The existing evaluator keeps abstentions, coverage, selective accuracy and
    # false accepts separate; a valid-looking wrong parse is not a success.
    measured = contrast.evaluate(parser, rows)
    pairs = defaultdict(list)
    for row in rows:
        if row.get('pair_id'): pairs[row['pair_id']].append(row)
    incomplete = sorted(key for key, group in pairs.items() if len(group) != 2)
    measured['pairs'] = [pair for pair in measured['pairs'] if pair['id'] not in incomplete]
    measured['incomplete_pair_ids'] = incomplete
    measured['pair_policy'] = 'Only complete two-member pairs enter paired metrics; all rows remain in per-sample metrics.'
    return measured


def diagnose(reference, prediction, frequencies):
    result = g.t.c.study.err.diagnose(reference, prediction, Counter(frequencies))
    person = lambda sequence: Counter(x for x in sequence if x in PEOPLE)
    negation = lambda sequence: Counter(g.t.c.study.err.variant_surface(x) for x in sequence
                                        if g.t.c.study.err.variant_surface(x) in NEGATION)
    return {**result, 'person_surface_mismatch': person(reference) != person(prediction),
            'negation_surface_mismatch': negation(reference) != negation(prediction),
            'annotation_changed': False, 'human_approved': False,
            'inference_limit': 'Alignment/surface clues do not establish semantic roles or erroneous source labels.'}


def gloss_audit(delivery):
    state, report, inputs = upper.read_result(delivery / 'verified-v1/evidence/results-v1', delivery / 'prepared-v1')
    data, _, prior, _, saved, _, _ = state
    frequencies = Counter(w for row in data['train'] for w in row['gloss_sequence'])
    raw = [{**p, 'quality': g.assess(p, prior['repeat_limit_from_train'])} for p in saved]
    runs = {'baseline': raw}
    manifest, used = u.read_manifest(delivery / 'verified-v1/evidence/results-v1')
    for arm in upper.ARMS:
        name = arm + '/selection-predictions.json'
        runs[arm] = json.loads(u.checked(delivery / 'verified-v1/evidence/results-v1', name, manifest, used))
    cases, aggregate = [], {}
    for name, predictions in runs.items():
        entries = []
        for row, prediction in zip(data['selection'], predictions):
            info = diagnose(row['gloss_sequence'], prediction['predicted'], frequencies)
            entries.append(info)
            cases.append({'id': row['id'], 'text': row['text'], 'model': name, 'reference': row['gloss_sequence'],
                          'predicted': prediction['predicted'], 'quality': prediction['quality'], **info})
        aggregate[name] = {key: sum(r[key] for r in entries) for key in
            ['substitutions', 'deletions', 'insertions', 'person_surface_mismatch', 'negation_surface_mismatch',
             'rare_reference_error_occurrences', 'unseen_reference_error_occurrences', 'variant_surface_confusions']}
        aggregate[name]['samples'] = len(entries)
    by_text = defaultdict(set)
    for row in data['train']: by_text[normalize(row['text'])].add(tuple(row['gloss_sequence']))
    conflicts = [{'text': text, 'references': [list(v) for v in sorted(values)]} for text, values in by_text.items() if len(values) > 1]
    audit = {**GATES, 'schema': SCHEMA, 'train_samples': len(data['train']), 'G_samples': len(data['selection']),
             'train_gloss_types': len(frequencies), 'models': aggregate, 'train_normalized_text_label_conflicts': conflicts,
             'raw_labels_unchanged': True, 'source_inputs': inputs,
             'limits': ['G was repeatedly used for development.', 'Minimum edit alignments and surface tokens are error clues, not semantic adjudication.',
                        'No word boundary, mirror, signer, motion or source label approvals are created.']}
    return audit, cases, data


def prepare(delivery, role_model, legacy_fixture, output):
    delivery, role_model, legacy_fixture, output = map(u.safe_path, [delivery, role_model, legacy_fixture, output])
    u.new_output(output, [delivery, role_model, legacy_fixture])
    # Freeze target cases before any current-round model predictions are read.
    rows = cases(); output.mkdir(parents=True)
    fixture = {**GATES, 'schema': SCHEMA, 'frozen_before_current_round_evaluation': True, 'rows': rows,
               'independent_final_test': False, 'label_source': 'assistant_synthetic_chinese'}
    u.base.write_json(output / 'frozen-cases.json', fixture)
    fixture_sha = u.base.sha(output / 'frozen-cases.json')
    provenance = {'frozen-cases.json': fixture_sha}
    role_manifest, used = u.read_manifest(role_model)
    for name in ['model.json', 'weights.npz', 'train.jsonl', 'provenance.json']:
        u.checked(role_model, name, role_manifest, used)
    role_train = [json.loads(line) for line in u.checked(role_model, 'train.jsonl', role_manifest, used).decode().splitlines()]
    old_contrasts = json.loads(legacy_fixture.read_text())
    audit, errors, grouped = gloss_audit(delivery)
    old_training = {normalize(r['text']) for r in role_train}
    historical_contrasts = {normalize(r['text']) for r in old_contrasts['rows']}
    challenge_texts = {normalize(r['text']) for r in rows if r['partition'] == 'challenge'}
    # Existing train/G texts are excluded from this new synthetic training pool.
    old_gloss_texts = {normalize(r['text']) for part in grouped.values() for r in part}
    train, dev, removed = partition(rows, historical_contrasts | challenge_texts | old_gloss_texts)
    write_package(output / 'package', train, dev, {'fixture_sha256': fixture_sha, 'role_inputs': used,
                  'legacy_fixture_sha256': u.base.sha(legacy_fixture), 'excluded_ids': removed},
                  (output / 'frozen-cases.json').read_bytes())
    u.base.write_json(output / 'gloss-error-audit.json', audit)
    u.base.write_json(output / 'gloss-error-cases.json', errors)
    baseline = base.load_model(role_model)
    overlap = [r['id'] for r in rows if normalize(r['text']) in old_training]
    predictors = {'learned_roles': baseline, 'learned_roles_plus_explicit_scope': contrast.scope.ScopeParser(baseline)}
    scores = {}
    for name, parser in predictors.items():
        scores[name] = {}
        for split in ['dev', 'challenge']:
            part = [r for r in rows if r['partition'] == split]
            scores[name][split] = evaluate(parser, part)
            scores[name][split + '_no_exact_old_role_train_overlap'] = evaluate(parser, [r for r in part if r['id'] not in overlap])
    u.base.write_json(output / 'semantic-baseline.json', {**GATES, 'models': scores,
        'prior_model_text_overlap_ids': overlap, 'independent_test': False,
        'scope_contract_is_explicit_rule': True, 'source_model_id': baseline.metadata['model_id']})
    # Verify the package and read-only inputs again before sealing the evidence.
    package_data, package_report, _ = read_package(output / 'package')
    if u.base.sha(output / 'frozen-cases.json') != fixture_sha: raise ValueError('Frozen cases changed during evaluation')
    for name, digest in used.items():
        if u.base.sha(role_model / name) != digest: raise ValueError('Source role artifact changed: ' + name)
    signatures = defaultdict(set)
    for row in train + dev:
        signature = '|'.join(s['role'] for s in row['spans']) if row['expected_roles'] else 'reject'
        signatures[signature].add(row['partition'])
    result = {**GATES, 'schema': SCHEMA, 'status': 'prepared_and_baselines_evaluated',
              'created_at_utc': datetime.now(timezone.utc).isoformat(), 'fixture_sha256': fixture_sha,
              'counts': {'frozen_all': len(rows), 'train': len(train), 'dev': len(dev),
                         'challenge': sum(r['partition'] == 'challenge' for r in rows), 'excluded_from_new_package': len(removed)},
              'template_families_partition_disjoint': True, 'exact_text_partition_disjoint': True,
              'shared_BIO_orders_train_dev': [s for s, parts in signatures.items() if len(parts) > 1],
              'old_role_train_exact_overlap_ids': overlap, 'existing_role_inputs': used,
              'source_files': {Path(p).name: u.base.sha(Path(p)) for p in [__file__, contrast.__file__, contrast.scope.__file__, base.__file__, upper.__file__]},
              'next_training_target': 'Chinese entity/event/reject classification, role BIO and ordered negation/modal operators; not Gloss generation.',
              'trainer_status': 'data_contract_prepared; typed trainer required before GPU launch',
              'training_package_coverage': package_report['coverage'],
              'preserved': ['all old weights', 'original Gloss labels', 'H and official test unopened', 'motion approval boundaries', 'Demo'],
              'limitations': ['Developer-authored engineering contrast set is not independent natural-language evaluation.',
                             'Template families are disjoint; some BIO role orders are shared and listed explicitly.',
                             'Only a controlled finite Chinese subset is represented; outside-contract rejection does not mean ungrammatical Chinese.',
                             'Synthetic Chinese targets are not new CSL supervision or human approval.']}
    u.base.write_json(output / 'report.json', result); u.seal(output)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['delivery', 'role-model', 'legacy-fixture', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.delivery, args.role_model, args.legacy_fixture, args.output), ensure_ascii=False, indent=2))
