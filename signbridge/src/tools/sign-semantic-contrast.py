"""Frozen synthetic contrast evaluation with separate coverage and false acceptance."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope = load('sign-csl-scope.py')


def operators(prediction):
    return [s['role'] + ':' + s['text'] for s in prediction.get('spans', []) if s['role'] in ('negation', 'modal')]


def evaluate(parser, rows):
    records = []
    for row in rows:
        started = time.perf_counter()
        out = parser.predict(row['text'])
        elapsed = (time.perf_counter() - started) * 1000
        parsed = out['status'] == 'parsed'
        supported = row['expected_roles'] is not None
        correct = parsed and supported and out['roles'] == row['expected_roles'] and operators(out) == row['expected_operators']
        graph = out.get('event_graph') or (scope.event_graph(out['roles'], out['spans']) if parsed else None)
        records.append({'id': row['id'], 'text': row['text'], 'partition': row['partition'], 'template_group': row['template_group'],
                        'supported': supported, 'parsed': parsed, 'correct_parse': correct, 'correct_rejection': not parsed and not supported,
                        'false_accept': parsed and not supported, 'event_key': scope.graph_key(graph) if graph else None,
                        'prediction': out, 'expected_roles': row['expected_roles'], 'expected_operators': row['expected_operators'], 'elapsed_ms': elapsed})
    pairs = defaultdict(list)
    by_id = {r['id']: r for r in records}
    for row in rows:
        if row.get('pair_id'):
            pairs[row['pair_id']].append(row)
    pair_results = []
    for pair_id, group in pairs.items():
        values = [by_id[r['id']] for r in group]
        resolved = all(v['correct_parse'] for v in values)
        equal = len({v['event_key'] for v in values}) == 1
        expected = group[0]['pair_relation']
        pair_results.append({'id': pair_id, 'relation': expected, 'resolved': resolved,
                             'passed': resolved and (equal if expected == 'same' else not equal)})
    return {'metrics': summarize(records), 'by_partition': {p: summarize([r for r in records if r['partition'] == p]) for p in sorted({r['partition'] for r in records})},
            'by_structure': {p: summarize([r for r in records if r['template_group'] == p]) for p in sorted({r['template_group'] for r in records})},
            'pairs': pair_results, 'records': records}


def summarize(records):
    total = len(records)
    accepted = sum(r['parsed'] for r in records)
    supported = sum(r['supported'] for r in records)
    unsupported = total - supported
    accepted_supported = sum(r['parsed'] and r['supported'] for r in records)
    correct = sum(r['correct_parse'] for r in records)
    false_accept = sum(r['false_accept'] for r in records)
    rejected = sum(r['correct_rejection'] for r in records)
    ratio = lambda value, denominator: value / denominator if denominator else None
    return {'cases': total, 'supported': supported, 'unsupported': unsupported, 'accepted': accepted,
            'correct_parses': correct, 'false_accepts': false_accept, 'correct_rejections': rejected,
            'coverage': ratio(accepted, total), 'supported_coverage': ratio(accepted_supported, supported),
            'correct_supported_parse_rate': ratio(correct, supported),
            'selective_accuracy': ratio(correct, accepted), 'false_accept_rate': ratio(false_accept, unsupported),
            'correct_rejection_rate': ratio(rejected, unsupported), 'overall_contract_accuracy': ratio(correct + rejected, total)}


def run(model, fixture, output):
    if output.exists():
        raise FileExistsError('Choose a new output; preserve prior evidence')
    original = scope.base.load_model(model)
    data = json.loads(fixture.read_text())
    rows = data['rows']
    groups = defaultdict(set)
    for row in rows:
        groups[row['template_group']].add(row['partition'])
    if any(len(parts) != 1 for parts in groups.values()):
        raise ValueError('Structure group crosses partitions')
    training = {json.loads(line)['text'] for line in (model / 'train.jsonl').read_text().splitlines() if line.strip()}
    overlap_ids = [r['id'] for r in rows if scope.base.clean(r['text']) in training]
    leakage_excluded_rows = [r for r in rows if r['id'] not in overlap_ids]
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    inputs = {str(p): sha(p) for p in [model / 'model.json', model / 'weights.npz', model / 'train.jsonl', fixture, Path(__file__), Path(scope.__file__), Path(scope.base.__file__)]}
    result = {'schema': 'signbridge-semantic-contrast-report-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'baseline': evaluate(original, rows), 'scope_experiment': evaluate(scope.ScopeParser(original), rows),
              'leakage_excluded_baseline': evaluate(original, leakage_excluded_rows),
              'leakage_excluded_scope_experiment': evaluate(scope.ScopeParser(original), leakage_excluded_rows),
              'old_training_text_overlap': overlap_ids,
              'group_partition_disjoint': True, 'fixture_sha256': sha(fixture), 'inputs': inputs,
              'weights_updated': False, 'csl_translation_trained': False, 'model_training_ready': False,
              'limitations': data['limitations'] + ['Coverage/correctness refer to this bounded Chinese contract only, not real-world Chinese or CSL accuracy.']}
    if any(sha(Path(path)) != digest for path, digest in inputs.items()):
        raise ValueError('Input bytes changed during evaluation')
    output.mkdir()
    (output / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (output / 'cases.json').write_bytes(fixture.read_bytes())
    (output / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(output.iterdir()) if p.is_file()))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = run(args.model, args.fixture, args.output)
    print(json.dumps({k: out[k]['metrics'] for k in ['baseline', 'scope_experiment']}, ensure_ascii=False))
