"""Freeze Chinese development contrasts and prepare new research supervision.

No optimizer runs here. Never reads official test or produces playable motions.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


unified = load('sign-csl-unified.py')
contrast = load('sign-semantic-contrast.py')
GATES = dict(training_started=False, human_approved=False, semantics_approved=False,
             boundaries_approved=False, training_ready=False, model_training_ready=False,
             can_play=False, csl_supervision=False, test_read=False, text_verified='')


def sha(path):
    return unified.base.sha(path)


def seal(root):
    paths = sorted(p for p in root.rglob('*') if p.is_file() and p != root / 'SHA256SUMS')
    (root / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(root).as_posix()}\n' for p in paths))


def read_frozen(root):
    root = unified.safe_path(root)
    manifest, consumed = unified.read_manifest(root)
    report = json.loads(unified.checked(root, 'preparation.json', manifest, consumed))
    content = unified.checked(root, 'contrasts.json', manifest, consumed)
    fixture = json.loads(content)
    if (hashlib.sha256(content).hexdigest() != report.get('frozen_contrast_sha256')
            or fixture.get('schema') != 'signbridge-next-round-contrast-v1'
            or any(fixture.get(k) != value for k, value in GATES.items())):
        raise ValueError('Invalid frozen contrast digest or research gates')
    rows = fixture['rows']
    if (not rows or len({r['id'] for r in rows}) != len(rows) or len({r['text'] for r in rows}) != len(rows)
            or any(r.get('human_approved') is not False or r.get('csl_supervision') is not False
                   or r.get('label_source') != 'assistant_synthetic_chinese' for r in rows)):
        raise ValueError('Invalid frozen contrast identity or provenance')
    return fixture


def tagged(parts):
    text, tags, spans = '', [], []
    for role, value in parts:
        if not value:
            continue
        start = len(text); text += value
        tags.extend([unified.ROLE_LABELS.index('B-' + role)] +
                    [unified.ROLE_LABELS.index('I-' + role)] * (len(value) - 1))
        spans.append({'role': role, 'start': start, 'end': len(text), 'text': value})
    return text, tags, spans


def contrasts():
    rows = []
    def add(parts, family, pair=None, relation='different', partition='development', text=None):
        if parts is None:
            roles, ops = None, []
        else:
            text, _, spans = tagged(parts)
            roles = {s['role']: s['text'] for s in spans}
            ops = [s['role'] + ':' + s['text'] for s in spans if s['role'] in ('negation', 'modal')]
        rows.append({'id': f'next-{len(rows) + 1:03}', 'text': text, 'expected_roles': roles,
                     'expected_operators': ops, 'template_group': family, 'partition': partition,
                     'pair_id': pair, 'pair_relation': relation,
                     'label_source': 'assistant_synthetic_chinese', 'human_approved': False, 'csl_supervision': False})
    for i, predicate in enumerate(['帮', '帮助', '等', '告诉']):
        for actor, patient in [('我', '你'), ('你', '我')]:
            add([('actor', actor), ('predicate', predicate), ('patient', patient)], 'role_swap', f'roles-{i}')
    for actor in ['我', '你', '他', '我们']:
        for predicate in ['跑步', '洗澡', '开车', '回家']:
            add([('actor', actor), ('predicate', predicate)], 'lexical_transfer')
        for i, predicate in enumerate(['工作', '跑步']):
            for order in [0, 1]:
                parts = [('actor', actor), ('time', '今天')] if order else [('time', '今天'), ('actor', actor)]
                add(parts + [('predicate', predicate)], 'time_paraphrase', f'time-{actor}-{i}', 'same')
        for predicate in ['跑步', '去']:
            for operators in [[('negation', '不'), ('modal', '想')], [('modal', '想'), ('negation', '不')]]:
                add([('actor', actor)] + operators + [('predicate', predicate)], 'operator_scope', f'scope-{actor}-{predicate}')
        for predicate in ['跑步', '工作']:
            add([('actor', actor), ('negation', '不'), ('modal', '能'), ('predicate', predicate)],
                'ability_scope_holdout', partition='structural_holdout')
        for value in ['了', '过']:
            add([('actor', actor), ('predicate', '去'), ('aspect', value)], 'event_status')
    for actor in ['你', '我们']:
        add([('politeness', '请'), ('actor', actor), ('predicate', '开车')],
            'politeness_holdout', partition='structural_holdout')
    for text in ['我不想不能去', '我去学校你回家', '我去。你回家', '我没有你', '我没有工作',
                 '我没有跑步', '我没有年龄', '我帮你还是你帮我', '我们今天明天去', '你把我帮',
                 '我想不想去', '我没不去', '他工作你洗澡', '今天今天我跑步', '😀', '我如果去就回来']:
        add(None, 'unsupported_or_ambiguous', text=text)
    return rows


def augment(reserved, inherited_groups=None):
    """Hold out actor/predicate/argument groups, never form fake CSL Gloss targets."""
    result = {'train': [], 'dev': []}; seen = set(reserved)
    inherited_groups = inherited_groups or {}
    actors = ['我', '你', '他', '她', '我们', '你们', '他们']
    events = ['工作', '休息', '学习', '跑步', '洗澡', '开车', '回家']
    events += ['去', '来', '回', '帮', '帮助', '等', '买', '喝']
    for actor in actors:
        for predicate in events:
            arguments = ([('goal', g) for g in ['家', '学校', '医院']] if predicate in ['去', '来', '回'] else
                         [('patient', p) for p in ['我', '你', '他', '我们'] if p != actor] if predicate in ['帮', '帮助', '等'] else
                         [('patient', p) for p in ['帽子', '袜子', '大米', '醋', '衣服']] if predicate == '买' else
                         [('patient', '水'), ('patient', '茶')] if predicate == '喝' else [None])
            for argument in arguments:
                canonical_predicate, canonical_argument = ('回', ('goal', '家')) if predicate == '回家' else (predicate, argument)
                group = '|'.join([actor, canonical_predicate, canonical_argument[1] if canonical_argument else ''])
                split = inherited_groups.get(group) or ('dev' if int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 5 == 0 else 'train')
                for prefix in [[], [('time', '今天')], [('time', '明天')]]:
                    for operator in [[], [('negation', '不')], [('modal', '想')], [('modal', '能')], [('modal', '可以')]]:
                        parts = prefix + [('actor', actor)] + operator + [('predicate', canonical_predicate)] + ([canonical_argument] if canonical_argument else [])
                        text, tags, _ = tagged(parts)
                        if text in seen:
                            continue
                        seen.add(text)
                        result[split].append({'id': 'next-roles-' + hashlib.sha256(text.encode()).hexdigest()[:20],
                            'text': text, 'tags': tags, 'task': 'roles', 'split_group': group,
                            'label_source': 'assistant_synthetic_chinese', 'human_approved': False, 'csl_supervision': False,
                            'supervision_scope': 'Chinese BIO only; not CSL alignment'})
    return result['train'], result['dev']


def canonical_roles(roles):
    roles = dict(roles)
    if roles.get('predicate') == '回家' and 'goal' not in roles:
        roles.update(predicate='回', goal='家')
    return roles


class Adapter:
    def __init__(self, predictor):
        self.predictor = predictor

    def predict(self, text):
        out = self.predictor.predict(text)
        return dict(out, strict_roles=out.get('roles', {}), roles=canonical_roles(out.get('roles', {})),
                    status='parsed' if out.get('status') in ['parsed', 'research_candidate_only'] else 'abstained')


def evaluate(predictor, rows):
    canonical = [dict(r, expected_roles=canonical_roles(r['expected_roles']) if r['expected_roles'] is not None else None) for r in rows]
    report = contrast.evaluate(Adapter(predictor), canonical)
    report['wrong_accepts'] = sum(r['parsed'] and not r['correct_parse'] for r in report['records'])
    report['strict_role_exact'] = sum(r['parsed'] and r['prediction'].get('strict_roles') == source['expected_roles']
                                    for source, r in zip(rows, report['records']))
    reasons = Counter()
    raw_correct = raw_available = 0
    for row, record in zip(rows, report['records']):
        out = record['prediction']
        reasons.update(out.get('uncertainty') or out.get('reasons') or [])
        if row['expected_roles'] is not None and out.get('raw_tags'):
            raw_available += 1
            tags = [unified.ROLE_LABELS.index(t) for t in out['raw_tags']]
            raw = unified.parse_roles(unified.base.normalize(row['text']), tags, unified.ROLE_LABELS)
            raw_roles = {s['role']: s['text'] for s in raw['spans']}
            raw_ops = [s['role'] + ':' + s['text'] for s in raw['spans'] if s['role'] in ('negation', 'modal')]
            raw_correct += canonical_roles(raw_roles) == canonical_roles(row['expected_roles']) and raw_ops == row['expected_operators'] and 'invalid_BIO' not in raw['uncertainty'] and 'unresolved_O' not in raw['uncertainty']
    report.update(rejection_reasons=dict(reasons), raw_role_cases=raw_available,
                  raw_role_and_operator_exact=raw_correct if raw_available else None,
                  semantic_equivalence_policy='Only 回家 <=> predicate 回 + goal 家; strict role match separately reported')
    return report


def prepare(source, output):
    source = unified.safe_path(source); output = unified.safe_path(output)
    if output.exists():
        raise FileExistsError('Choose a NEW output directory')
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Output overlaps source')
    data, labels, provenance = unified.read_package(source)
    rows = contrasts()
    prior = {unified.base.normalize(r['text']) for task in data.values() for split in task.values() for r in split}
    primary = [r for r in rows if unified.base.normalize(r['text']) not in prior]
    overlaps = [r['id'] for r in rows if unified.base.normalize(r['text']) in prior]
    inherited_groups = {}
    for split in ['train', 'dev']:
        for row in data['roles'][split]:
            group = row.get('split_group')
            if group:
                if group in inherited_groups and inherited_groups[group] != split:
                    raise ValueError('Historical role group crosses splits')
                inherited_groups[group] = split
    train, dev = augment(prior | {unified.base.normalize(r['text']) for r in rows}, inherited_groups)
    output.mkdir(parents=True); package = output / 'package'; package.mkdir()
    for split in ['train', 'dev']:
        shutil.copyfile(source / f'gloss-{split}.jsonl', package / f'gloss-{split}.jsonl')
        additions = train if split == 'train' else dev
        original = (source / f'roles-{split}.jsonl').read_bytes()
        (package / f'roles-{split}.jsonl').write_bytes(original + (b'' if original.endswith(b'\n') else b'\n') +
            ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in additions).encode())
    shutil.copyfile(source / 'role-labels.json', package / 'role-labels.json')
    counts = {f'{task}-{split}': len(data[task][split]) + (len(train if split == 'train' else dev) if task == 'roles' else 0)
              for task in data for split in data[task]}
    fixture = {'schema': 'signbridge-next-round-contrast-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
               **GATES, 'frozen_before_model_evaluation': True, 'rows': rows,
               'original_text_overlap_ids': overlaps, 'primary_nonoverlap_ids': [r['id'] for r in primary],
               'limitations': ['Developer-authored synthetic Chinese engineering benchmark, not CSL language evidence.',
                              'Not an independent final test; old initialization provenance gaps remain.',
                              'Unseen structure refers only to named structural_holdout families.']}
    unified.base.write_json(output / 'contrasts.json', fixture)
    report = {'schema': 'signbridge-csl-unified-data-v1', **GATES, 'counts': counts,
              'source_files_sha256': provenance['sha256'], 'source_root': str(source),
              'addition_counts': {'train': len(train), 'dev': len(dev)}, 'frozen_contrast_sha256': sha(output / 'contrasts.json'),
              'quarantine_reasons': provenance['report'].get('quarantine_reasons', {}),
              'gloss_bytes_unchanged': True, 'original_role_rows_unchanged': True,
              'validation_added_to_training': False, 'csl_labels_invented': False,
              'synthetic_chinese_labels_added': True,
              'historical_role_groups_respected': True,
              'semantic_equivalence_policy': '回家 canonicalizes to predicate 回 + goal 家 before synthetic BIO construction',
              'limits': ['No event-scope head: compound scope evaluated separately and not silently accepted.',
                         'Cannot represent implicit have-predicate in possession negation using existing one-role-per-character BIO.']}
    unified.base.write_json(package / 'report.json', report); seal(package)
    unified.read_package(package)
    new_train = {r['text'] for r in data['roles']['train']} | {r['text'] for r in train}
    new_dev = {r['text'] for r in data['roles']['dev']} | {r['text'] for r in dev}
    assert not new_train & new_dev
    groups = {s: {r.get('split_group') for r in data['roles'][s] + (train if s == 'train' else dev)} - {None}
              for s in ['train', 'dev']}
    assert not groups['train'] & groups['dev']
    assert not {r['text'] for r in primary} & (new_train | new_dev)
    unified.base.write_json(output / 'preparation.json', {**report, 'primary_cases': len(primary),
        'contrast_cases': len(rows), 'original_overlap_cases': len(overlaps),
        'next_command': 'GPU-only sign-csl-unified.py train with package; never use test or motion candidates'})
    seal(output)
    return json.loads((output / 'preparation.json').read_text())


def benchmark(preparation, model, old_roles, output):
    preparation, model, old_roles, output = [unified.safe_path(p) for p in [preparation, model, old_roles, output]]
    if output.exists():
        raise FileExistsError('Choose a NEW benchmark output')
    if any(output == p or output in p.parents or p in output.parents for p in [preparation, model, old_roles]):
        raise ValueError('Benchmark output overlaps an input')
    fixture = read_frozen(preparation)
    rows = fixture['rows']; ids = set(fixture['primary_nonoverlap_ids'])
    manifest, _ = unified.read_manifest(model)
    paths = [model / n for n in ['model.json', 'vocab.json', 'role-labels.json']]
    meta = json.loads((model / 'model.json').read_text()); paths.append(model / meta['checkpoint'])
    paths += [old_roles / n for n in ['model.json', 'weights.npz', 'train.jsonl']]
    paths += [preparation / 'contrasts.json', Path(__file__), Path(unified.__file__), Path(unified.base.__file__),
              Path(contrast.__file__), Path(contrast.scope.__file__), Path(contrast.scope.base.__file__)]
    hashes = {str(p): sha(p) for p in paths}
    if any(manifest.get(str(p.relative_to(model))) != hashes[str(p)] for p in paths[:4]):
        raise ValueError('Model artifact digest differs')
    learned = contrast.scope.base.load_model(old_roles)
    predictors = {'unified_transformer': unified.ResearchPredictor(model), 'perceptron': learned,
                  'perceptron_scope_constraints': contrast.scope.ScopeParser(learned)}
    results = {}
    for name, predictor in predictors.items():
        all_result = evaluate(predictor, rows)
        primary_records = [r for r in all_result['records'] if r['id'] in ids]
        results[name] = {'all': all_result, 'primary_nonoverlap_metrics': contrast.summarize(primary_records),
                        'primary_wrong_accepts': sum(r['parsed'] and not r['correct_parse'] for r in primary_records)}
    if any(sha(Path(p)) != h for p, h in hashes.items()):
        raise ValueError('Input bytes changed during benchmark')
    report = {'schema': 'signbridge-next-round-benchmark-v1', **GATES, 'device': 'cpu_forward_only',
              'results': results, 'input_sha256': hashes, 'fixture_sha256': sha(preparation / 'contrasts.json'),
              'primary_cases': len(ids), 'contrast_cases': len(rows), 'independent_final_test': False}
    output.mkdir(parents=True); unified.base.write_json(output / 'report.json', report)
    import csv
    with (output / 'cases.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream); writer.writerow(['model', 'id', 'text', 'group', 'partition', 'nonoverlap', 'accepted', 'correct', 'false_accept', 'reasons'])
        for name, result in results.items():
            for r in result['all']['records']:
                prediction = r['prediction']
                writer.writerow([name, r['id'], r['text'], next(x['template_group'] for x in rows if x['id'] == r['id']),
                    r['partition'], r['id'] in ids, r['parsed'], r['correct_parse'], r['false_accept'],
                    '|'.join(prediction.get('uncertainty') or prediction.get('reasons') or [])])
    seal(output)
    return {name: result['primary_nonoverlap_metrics'] for name, result in results.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--source', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('benchmark')
    for field in ['preparation', 'model', 'old-roles', 'output']:
        p.add_argument('--' + field, type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source, args.output) if args.command == 'prepare' else benchmark(args.preparation, args.model, args.old_roles, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
