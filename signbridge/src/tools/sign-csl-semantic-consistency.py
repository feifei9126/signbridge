"""Explicit consistency decoding of learned kind/BIO; no text lookup or retraining.

Raw learned outputs and raw scores remain available. A learned rejection is
never overridden. Only a unique valid alternative kind may resolve an isolated
kind/role mismatch; BIO labels, words, roles and operator order never change.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


c = load('sign-csl-typed-coverage.py')
SCHEMA = 'signbridge-semantic-consistency-v1'


def resolve(raw):
    if 'explicit_contract_rejection' in raw:
        p = raw.get('prediction', {})
        allowed = {'outside_single_clause_Chinese_character_contract', 'invalid_or_overlong_input',
                   'outside_training_character_support', 'unaligned_or_unknown_BERT_tokens', 'unknown_encoder_character'}
        if (raw['explicit_contract_rejection'] is not True or 'raw_kind' in raw or 'raw_BIO' in raw
                or p.get('status') != 'abstained' or p.get('kind') != 'reject'
                or p.get('roles') != {} or p.get('spans') != [] or p.get('operators') != []
                or any(p.get(k) != v for k, v in c.b.GATES.items())
                or not isinstance(p.get('reasons'), list) or not p['reasons'] or not set(p['reasons']) <= allowed
                or p.get('event_graph') is not None or p.get('event_key') is not None):
            raise ValueError('Forged or malformed explicit input rejection')
        return {**copy.deepcopy(raw), 'kind_resolved_by_explicit_structure': False}
    expected = c.interpret(raw['text'], raw['raw_BIO'], raw['raw_kind'])
    if raw.get('prediction') != expected: raise ValueError('Consistency input differs from original raw evidence')
    output = copy.deepcopy(raw); output['original_prediction'] = copy.deepcopy(expected)
    output['kind_resolved_by_explicit_structure'] = False
    if raw['raw_kind'] == 'reject' or expected['status'] == 'parsed': return output
    if expected['reasons'] not in (['entity_kind_role_mismatch'], ['event_kind_role_mismatch']): return output
    candidates = [c.interpret(raw['text'], raw['raw_BIO'], kind) for kind in ['entity', 'event'] if kind != raw['raw_kind']]
    candidates = [p for p in candidates if p['status'] == 'parsed']
    if len(candidates) != 1: return output
    output.update(prediction=candidates[0], kind_resolved_by_explicit_structure=True,
                  resolution='unique_structurally_valid_kind_for_unchanged_learned_BIO',
                  resolution_is_learned_model_improvement=False)
    return output


def predict_texts(runtime, texts):
    started = time.perf_counter()
    raw = c.predict_texts(runtime, texts)
    elapsed = time.perf_counter() - started
    return [{**envelope, 'result': resolve(envelope['result']), 'consistency_schema': SCHEMA,
             'timing': {'batch_end_to_end_seconds': elapsed, 'batch_size': len(texts),
                        'scope': 'full BERT+heads+input guards; one shared batch time, not per-row latency'}}
            for envelope in raw]


def measure(rows, predictions):
    return c.b.s.evaluate(c.Adapter(predictions), rows)


def audit(prepared, results, encoder_root, output):
    u = c.u; output = u.new_output(output, [prepared, results, encoder_root])
    started = time.perf_counter(); runtime = c.load_runtime(prepared, results, encoder_root)
    load_seconds = time.perf_counter() - started
    rows = [r for r in runtime['diagnostic'] if r['partition'] in ('dev', 'challenge', 'legacy_diagnostic')]
    envelopes = predict_texts(runtime, [r['text'] for r in rows])
    resolved = [dict(p['result'], id=r['id'], text=r['text']) for r, p in zip(rows, envelopes)]
    raw = []
    for p in resolved:
        original = copy.deepcopy(p)
        if 'original_prediction' in p: original['prediction'] = p['original_prediction']
        raw.append(original)
    train_texts = {r['text'] for r in runtime['data']['train']}; dev_texts = {r['text'] for r in runtime['data']['dev']}
    nonoverlap = [(r, p) for r, p in zip(rows, resolved) if r['text'] not in train_texts | dev_texts]
    # Verify every raw dev output against the selected GPU checkpoint first.
    cached = c.b.features(runtime['encoder'], runtime['tokenizer'], runtime['data']['dev'], 'cpu')
    dev_raw = c.predict_cached(runtime['model'], runtime['data']['dev'], cached, 'cpu')
    if dev_raw != json.loads((Path(results) / 'dev-predictions.json').read_text()): raise ValueError('Consistency CPU raw dev replay differs')
    dev_resolved = [resolve(p) for p in dev_raw]
    report = {**c.b.GATES, 'schema': SCHEMA, 'status': 'completed_audit',
              'checkpoint_sha256': runtime['checkpoint_sha256'], 'CPU_raw_dev_replay_exact': True,
              'raw_diagnostic': measure(rows, raw), 'consistent_diagnostic': measure(rows, resolved),
              'consistent_diagnostic_excluding_train_dev_overlap': measure([r for r, _ in nonoverlap], [p for _, p in nonoverlap]),
              'raw_dev_metrics': c.metrics(runtime['data']['dev'], dev_raw),
              'consistent_dev': measure(runtime['data']['dev'], dev_resolved),
              'resolved_ids': [r['id'] for r, p in zip(rows, resolved) if p['kind_resolved_by_explicit_structure']],
              'dev_resolved_ids': [p['id'] for p in dev_resolved if p['kind_resolved_by_explicit_structure']],
              'diagnostic_overlap': {'train': [r['id'] for r in rows if r['text'] in train_texts], 'dev': [r['id'] for r in rows if r['text'] in dev_texts]},
              'real_timing': {'cold_model_load_seconds': load_seconds, **envelopes[0]['timing']},
              'source_sha256': {Path(__file__).name: u.base.sha(Path(__file__)), **c.source_hashes()},
              'original_gold_and_BIO_unchanged': True, 'CSL_quality_improvement_verified': False,
              'known_contract_conflict_kept_in_all_raw_metrics': 'legacy fixture rejects 我可以不去; current finite Chinese contract supports it',
              'limits': ['Explicit consistency decoding, not additional model training or calibrated confidence.',
                         'All diagnostic data previously used for development; no independent accuracy/generalization result.',
                         'Replay-adapter elapsed_ms is metric bookkeeping time, not inference latency; use real_timing.',
                         'Model outputs, finite lexicon guards, rule composition and motion approvals remain separate.']}
    output.mkdir(parents=True)
    u.base.write_json(output / 'report.json', report)
    u.base.write_json(output / 'raw-diagnostic-predictions.json', raw)
    u.base.write_json(output / 'consistent-diagnostic-predictions.json', resolved)
    u.base.write_json(output / 'consistent-dev-predictions.json', dev_resolved)
    u.seal(output); return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    for command in ['audit', 'interactive']:
        p = sub.add_parser(command)
        for name in ['prepared', 'results', 'encoder-root']: p.add_argument('--' + name, type=Path, required=True)
        if command == 'audit': p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'audit':
        print(json.dumps(audit(args.prepared, args.results, args.encoder_root, args.output), ensure_ascii=False, indent=2)); return
    runtime = c.load_runtime(args.prepared, args.results, args.encoder_root)
    print('有限中文语义研究终端。学习角色＋显式一致性；非手语翻译。/quit退出。', flush=True)
    for line in sys.stdin:
        text = line.rstrip('\r\n')
        if text == '/quit': break
        print(json.dumps(predict_texts(runtime, [text])[0], ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
