"""New immutable typed-semantic coverage control; preserves the original trainer.

Same model/initial seed/settings, new synthetic multi-character entity examples
and four existing-role-model goals. No prior developer text moves into train.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import random
import sys


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


b = load('sign-csl-typed-semantics.py')
u, t = b.u, b.t
SCHEMA = 'signbridge-typed-coverage-v1'
NAMES = ['小王', '小李', '小张', '小刘', '小陈', '小赵', '大家']
GOALS = ['公司', '公园', '北京', '图书馆']
LIMITS = ['This is a bundled coverage experiment, not a one-variable causal ablation.',
          'Added names are synthetic Chinese entity supervision, not sign-language evidence.',
          'Old raw diagnostic references remain unchanged, including legacy rejection of 我可以不去, which differs from the current supported contract.',
          'No H/test/motions, no independent generalization or semantic approval.']


def source_hashes():
    return {**b.source_hashes(), Path(__file__).name: u.base.sha(Path(__file__))}


def expand(reserved, train_reserved):
    data = b.corpus(reserved, train_reserved)
    additions = {key: 0 for key in data}
    seen = {r['text'] for rows in data.values() for r in rows}
    def add(row):
        text = b.s.normalize(row['text']); split = row['partition']
        if text in seen or text in reserved or split == 'train' and text in train_reserved: return
        data[split].append(row); additions[split] += 1; seen.add(text)
    for name in NAMES:
        add(b.sample([('actor', name)], 'entity|' + name, 'train', 'multicharacter_entity'))
    for actor in b.s.PEOPLE:
        for predicate in ['去', '来', '回']:
            for goal in GOALS:
                group = '|'.join([actor, predicate, goal])
                split = 'dev' if int(b.hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 5 == 0 else 'train'
                for time_parts, front in [([], False), ([('time', '今天')], True), ([('time', '明天')], False)]:
                    prefix = time_parts + [('actor', actor)] if front else [('actor', actor)] + time_parts
                    for operators in b.OPERATORS:
                        add(b.sample(prefix + operators + [('predicate', predicate), ('goal', goal)], group, split, 'goal_coverage'))
                    for aspect in ['了', '过']:
                        add(b.sample(prefix + [('predicate', predicate), ('aspect', aspect), ('goal', goal)], group, split, 'goal_aspect'))
                for operator in ['不不', '想想', '不想不能']:
                    add(b.sample(None, group, split, 'duplicate_operator', text=actor + operator + predicate + goal))
                add(b.sample(None, group, split, 'multi_clause', text=actor + predicate + goal + '然后你学习'))
                add(b.sample(None, group, split, 'double_time', text=actor + '今天明天' + predicate + goal))
    b.validate_data(data, reserved, train_reserved)
    return data, additions


def interpret(text, tags, kind):
    # The old BIO/kind validation remains authoritative. Expansion merely adds
    # finite allowed entity/goal values; it never corrects or supplies a role.
    result = b.interpret(text, tags, kind)
    if result['status'] == 'parsed' or result['reasons'] != ['explicit_role_value_argument_order_contract']:
        return result
    spans = []
    for i, index in enumerate(tags):
        tag = b.s.base.LABELS[index]
        if tag.startswith('B-'): spans.append({'role': tag[2:], 'text': text[i], 'start': i, 'end': i + 1})
        else: spans[-1]['text'] += text[i]; spans[-1]['end'] = i + 1
    roles = {s['role']: s['text'] for s in spans}
    supported = kind == 'entity' and list(roles) == ['actor'] and roles['actor'] in NAMES
    if kind == 'event' and roles.get('goal') in GOALS:
        validation_spans = [dict(s, text='家') if s['role'] == 'goal' else s for s in spans]
        supported = b.supported_graph(validation_spans, kind)
    if not supported: return result
    graph = {'type': 'entity', 'roles': roles} if kind == 'entity' else b.s.contrast.scope.event_graph(roles, spans)
    result.update(status='parsed', reasons=[], roles=roles, spans=spans, event_graph=graph,
                  event_key=b.s.contrast.scope.graph_key(graph), operators=[s['role'] + ':' + s['text'] for s in spans if s['role'] in ('modal', 'negation')])
    return result


def predict_cached(model, rows, cached, device):
    predictions = b.predict_cached(model, rows, cached, device)
    for p in predictions: p['prediction'] = interpret(p['text'], p['raw_BIO'], p['raw_kind'])
    return predictions


def validate_predictions(rows, predictions):
    if (len(rows) != len(predictions) or len({p.get('id') for p in predictions}) != len(rows)
            or any(r['id'] != p.get('id') or r['text'] != p.get('text') for r, p in zip(rows, predictions))):
        raise ValueError('Coverage prediction identity differs')
    for p in predictions:
        if p['prediction'] != interpret(p['text'], p['raw_BIO'], p['raw_kind']): raise ValueError('Coverage raw evidence differs')


def metrics(rows, predictions):
    validate_predictions(rows, predictions)
    # The shared mature metric validates its own original contract. Recompute
    # expanded outputs through a reference-free replay adapter using full rows.
    measured = b.s.evaluate(Adapter(predictions), rows)
    m = measured['metrics']; by_id = {r['id']: r for r in measured['records']}
    entities = [r for r in rows if r['expected_kind'] == 'entity']
    scope = [r for r in rows if r['expected_operators'] and len(r['expected_operators']) > 1]
    pairs = measured['pairs']
    return {'samples': len(rows), 'supported': m['supported'], 'supported_correct': m['correct_parses'],
            'supported_correct_rate': m['correct_supported_parse_rate'], 'wrong_accepts': m['accepted'] - m['correct_parses'],
            'unsupported_false_accepts': m['false_accepts'], 'correct_rejections': m['correct_rejections'],
            'entity_cases': len(entities), 'entity_correct': sum(by_id[r['id']]['correct_parse'] for r in entities),
            'entity_correct_rate': sum(by_id[r['id']]['correct_parse'] for r in entities) / len(entities) if entities else None,
            'scope_correct_rate': sum(by_id[r['id']]['correct_parse'] for r in scope) / len(scope) if scope else None,
            'complete_pairs_pass_rate': sum(p['passed'] for p in pairs) / len(pairs) if pairs else None}


class Adapter:
    def __init__(self, predictions): self.items = iter(predictions)
    def predict(self, text):
        row = next(self.items)
        if row['text'] != text: raise ValueError('Coverage replay text differs')
        return row['prediction']


def prepare(original, output):
    original, output = map(u.safe_path, [original, output]); u.new_output(output, [original])
    old, diagnostic, prior, used = b.read_prepared(original)
    manifest, consumed = u.read_manifest(original)
    reserved = set(json.loads(u.checked(original, 'reserved-texts.json', manifest, consumed)))
    train_reserved = set(json.loads(u.checked(original, 'train-reserved-texts.json', manifest, consumed)))
    data, additions = expand(reserved, train_reserved)
    output.mkdir(parents=True)
    # Full old input is allowlisted and kept for provenance/reproduction.
    origin = output / 'original'; origin.mkdir()
    for name in ['plan.json', 'reserved-texts.json', 'train-reserved-texts.json', 'diagnostic.json', 'legacy-diagnostic.json', 'train.jsonl', 'dev.jsonl']:
        (origin / name).write_bytes(u.checked(original, name, manifest, consumed))
    u.seal(origin)
    for split, rows in data.items():
        (output / (split + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    plan = {**b.GATES, 'schema': SCHEMA, 'settings': b.SETTINGS, 'source_hashes': source_hashes(),
            'counts': {k: len(v) for k, v in data.items()}, 'additions': additions,
            'original_inputs': used, 'original_plan': prior, 'limits': LIMITS,
            'hypothesis': 'Multi-character entity supervision reduces the length-one shortcut; existing-role goals close character coverage without moving diagnostic texts into train.',
            'comparison': 'same architecture,seed,optimizer,epoch count; dataset cardinality/coverage/optimizer-update count differ'}
    u.base.write_json(output / 'plan.json', plan); u.seal(output); return plan


def read_prepared(root):
    root = u.safe_path(root); manifest, used = u.read_manifest(root)
    plan = json.loads(u.checked(root, 'plan.json', manifest, used))
    old, diagnostic, prior, original_inputs = b.read_prepared(root / 'original')
    original_manifest, consumed = u.read_manifest(root / 'original')
    reserved = set(json.loads(u.checked(root / 'original', 'reserved-texts.json', original_manifest, consumed)))
    train_reserved = set(json.loads(u.checked(root / 'original', 'train-reserved-texts.json', original_manifest, consumed)))
    expected, additions = expand(reserved, train_reserved)
    data = {split: [json.loads(line) for line in u.checked(root, split + '.jsonl', manifest, used).decode().splitlines()] for split in ['train', 'dev']}
    if (plan.get('schema') != SCHEMA or plan.get('settings') != b.SETTINGS or plan.get('source_hashes') != source_hashes()
            or plan.get('original_inputs') != original_inputs or plan.get('original_plan') != prior or data != expected
            or plan.get('counts') != {k: len(v) for k, v in data.items()} or plan.get('additions') != additions
            or any(plan.get(k) != v for k, v in b.GATES.items())):
        raise ValueError('Coverage preparation contract differs')
    return data, diagnostic, plan, used


def train(prepared, encoder_root, output):
    import torch
    device = u.cuda_device('cuda'); prepared, encoder_root, output = map(u.safe_path, [prepared, encoder_root, output])
    u.new_output(output, [prepared, encoder_root]); data, _, plan, inputs = read_prepared(prepared)
    settings = b.SETTINGS
    torch.set_num_threads(4); random.seed(settings['seed']); torch.manual_seed(settings['seed']); torch.cuda.manual_seed_all(settings['seed'])
    encoder, tokenizer, hashes, _ = t.load_encoder(encoder_root)
    if hashes != plan['original_plan']['encoder_inputs']: raise ValueError('Coverage encoder differs')
    frozen = u.base.weights_hash(encoder); output.mkdir(parents=True); (output / 'checkpoints').mkdir()
    report = {**b.GATES, 'schema': SCHEMA, 'status': 'running', 'training_started': True, 'weights_updated': True,
              'plan': plan, 'inputs': inputs, 'history': [], 'frozen_encoder_hash': frozen, 'source_hashes': source_hashes(),
              'runtime': {'python': sys.version, 'torch': str(torch.__version__), 'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(device)},
              'diagnostic_evaluated_during_selection': False}
    try:
        cached = {split: b.features(encoder, tokenizer, rows, device) for split, rows in data.items()}
        if u.base.weights_hash(encoder) != frozen: raise ValueError('Coverage frozen encoder changed')
        del encoder; torch.cuda.empty_cache()
        model = b.make_model().to(device); initial = t.state_hash(model.state_dict())
        optimizer = torch.optim.AdamW(model.parameters(), lr=settings['learning_rate'], weight_decay=settings['weight_decay'])
        best, steps = None, 0
        for epoch in range(1, settings['epochs'] + 1):
            model.train(); counts = Counter(r['expected_kind'] for r in data['train'])
            order = random.choices(list(range(len(data['train']))), weights=[1. / counts[r['expected_kind']] for r in data['train']], k=len(data['train'])); losses = []
            for start in range(0, len(order), settings['batch_size']):
                x, lengths, kind, target = b.batch(data['train'], cached['train'], order[start:start + settings['batch_size']], device)
                optimizer.zero_grad(set_to_none=True); kl, tl = model(x, lengths)
                loss = torch.nn.functional.cross_entropy(kl, kind)
                if bool(target.ne(-100).any()): loss = loss + torch.nn.functional.cross_entropy(tl.flatten(0, 1), target.reshape(-1), ignore_index=-100)
                if not torch.isfinite(loss): raise ValueError('Nonfinite coverage loss')
                loss.backward()
                if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()): raise ValueError('Nonfinite coverage gradient')
                torch.nn.utils.clip_grad_norm_(model.parameters(), settings['clip_grad']); optimizer.step(); steps += 1; losses.append(float(loss.detach()))
            predictions = predict_cached(model, data['dev'], cached['dev'], device); measured = metrics(data['dev'], predictions)
            key = (measured['wrong_accepts'], -measured['supported_correct'], -measured['correct_rejections'])
            if best is None or key < best:
                best = key; report['selected_epoch'] = epoch; report['selected_dev_metrics'] = measured
                torch.save({k: v.detach().cpu() for k, v in model.state_dict().items()}, output / 'checkpoints/best.pt')
                u.base.write_json(output / 'dev-predictions.json', predictions)
            torch.save({'model': {k: v.detach().cpu() for k, v in model.state_dict().items()}, 'optimizer': optimizer.state_dict(),
                        'epoch': epoch, 'steps': steps, 'python_rng': random.getstate(), 'torch_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state_all()}, output / 'checkpoints/recovery-last.pt')
            item = {'epoch': epoch, 'steps': steps, 'train_loss': sum(losses) / len(losses), 'dev': measured}
            report['history'].append(item); report.update(epochs_completed=epoch, optimizer_steps=steps)
            u.base.write_json(output / 'report.json', report); print(json.dumps(item), flush=True)
        b.restore(model, torch.load(output / 'checkpoints/best.pt', map_location='cpu', weights_only=True))
        if predict_cached(model, data['dev'], cached['dev'], device) != json.loads((output / 'dev-predictions.json').read_text()): raise ValueError('Coverage GPU checkpoint replay differs')
        report.update(status='completed', finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      checkpoint='checkpoints/best.pt', checkpoint_sha256=u.base.sha(output / 'checkpoints/best.pt'),
                      selected_parameter_hash=t.state_hash(model.state_dict()), initial_parameter_hash=initial,
                      encoder_assets_unchanged=t.check_encoder(encoder_root) == hashes, frozen_encoder_unchanged=True)
        u.base.write_json(output / 'report.json', report); u.seal(output)
    except Exception as error:
        report.update(status='failed', error=repr(error)); u.base.write_json(output / 'report.json', report); u.seal(output); raise
    return report


def load_runtime(prepared, results, encoder_root):
    import torch
    data, diagnostic, plan, inputs = read_prepared(prepared)
    manifest, used = u.read_manifest(u.safe_path(results))
    report = json.loads(u.checked(u.safe_path(results), 'report.json', manifest, used))
    saved = json.loads(u.checked(u.safe_path(results), 'dev-predictions.json', manifest, used))
    measured = metrics(data['dev'], saved)
    expected_steps = ((len(data['train']) + 127) // 128) * 18
    if (report.get('schema') != SCHEMA or report.get('status') != 'completed' or report.get('plan') != plan
            or report.get('inputs') != inputs or report.get('source_hashes') != source_hashes()
            or report.get('epochs_completed') != 18 or report.get('optimizer_steps') != expected_steps
            or len(report.get('history', [])) != 18 or report.get('selected_dev_metrics') != measured
            or report.get('encoder_assets_unchanged') is not True or report.get('frozen_encoder_unchanged') is not True
            or report.get('diagnostic_evaluated_during_selection') is not False
            or any(report.get(k) != v for k, v in b.GATES.items() if k not in ('training_started', 'weights_updated', 'optimizer_steps'))
            or report.get('training_started') is not True or report.get('weights_updated') is not True):
        raise ValueError('Completed coverage run differs')
    selected = min(report['history'], key=lambda h: (h['dev']['wrong_accepts'], -h['dev']['supported_correct'], -h['dev']['correct_rejections']))
    if selected['epoch'] != report['selected_epoch'] or selected['dev'] != measured: raise ValueError('Coverage epoch selection differs')
    content = u.checked(u.safe_path(results), 'checkpoints/best.pt', manifest, used)
    if report.get('checkpoint') != 'checkpoints/best.pt' or report.get('checkpoint_sha256') != used['checkpoints/best.pt']: raise ValueError('Coverage checkpoint digest differs')
    torch.set_num_threads(4); encoder, tokenizer, hashes, _ = t.load_encoder(encoder_root)
    if hashes != plan['original_plan']['encoder_inputs'] or u.base.weights_hash(encoder) != report['frozen_encoder_hash']: raise ValueError('Coverage encoder state differs')
    model = b.make_model(); b.restore(model, torch.load(io.BytesIO(content), map_location='cpu', weights_only=True)); model.eval()
    if t.state_hash(model.state_dict()) != report['selected_parameter_hash']: raise ValueError('Coverage restored parameters differ')
    return {'model': model, 'encoder': encoder, 'tokenizer': tokenizer, 'characters': {c for r in data['train'] for c in r['text']},
            'data': data, 'diagnostic': diagnostic, 'plan': plan, 'report': report, 'inputs': used, 'checkpoint_sha256': report['checkpoint_sha256']}


def predict_texts(runtime, texts):
    rows, outputs = [], {}
    for i, text in enumerate(texts):
        try:
            value = b.input_text(text)
            if any(c not in runtime['characters'] for c in value): raise ValueError('outside_training_character_support')
            b.char_ids(value, runtime['tokenizer']); rows.append({'id': str(i), 'text': value, 'expected_kind': 'reject', 'tags': None})
        except ValueError as error:
            outputs[str(i)] = {'text': text, 'explicit_contract_rejection': True,
                'prediction': {**b.GATES, 'status': 'abstained', 'kind': 'reject', 'roles': {}, 'spans': [], 'reasons': [str(error)], 'operators': []}}
    if rows:
        cached = b.features(runtime['encoder'], runtime['tokenizer'], rows, 'cpu')
        outputs.update({p['id']: p for p in predict_cached(runtime['model'], rows, cached, 'cpu')})
    return [{**b.GATES, 'input': text, 'checkpoint_sha256': runtime['checkpoint_sha256'], 'result': outputs[str(i)],
             'notice': '受限中文语义研究输出；显式合同验证，非中国手语翻译，不驱动动作。'} for i, text in enumerate(texts)]


def audit(prepared, results, encoder_root, output):
    output = u.new_output(output, [prepared, results, encoder_root]); state = load_runtime(prepared, results, encoder_root)
    rows = [r for r in state['diagnostic'] if r['partition'] in ('dev', 'challenge', 'legacy_diagnostic')]
    envelopes = predict_texts(state, [r['text'] for r in rows])
    predictions = [dict(p['result'], id=r['id'], text=r['text']) for r, p in zip(rows, envelopes)]
    measured = b.s.evaluate(Adapter(predictions), rows)
    train_texts = {r['text'] for r in state['data']['train']}; dev_texts = {r['text'] for r in state['data']['dev']}
    selected = [(r, p) for r, p in zip(rows, predictions) if r['text'] not in train_texts | dev_texts]
    nonoverlap = b.s.evaluate(Adapter([p for _, p in selected]), [r for r, _ in selected])
    cached = b.features(state['encoder'], state['tokenizer'], state['data']['dev'], 'cpu')
    replay = predict_cached(state['model'], state['data']['dev'], cached, 'cpu')
    if replay != json.loads((Path(results) / 'dev-predictions.json').read_text()): raise ValueError('Coverage CPU replay differs')
    output.mkdir(parents=True)
    report = {**b.GATES, 'schema': SCHEMA, 'status': 'completed_audit', 'CPU_dev_replay_exact': True,
              'diagnostic': measured, 'diagnostic_excluding_train_dev_overlap': nonoverlap,
              'overlap': {'train': [r['id'] for r in rows if r['text'] in train_texts], 'dev': [r['id'] for r in rows if r['text'] in dev_texts]},
              'dev_metrics': metrics(state['data']['dev'], replay), 'checkpoint_sha256': state['checkpoint_sha256'],
              'legacy_reference_labels_unchanged': True, 'contract_conflict_kept_in_raw_metrics': '我可以不去', 'limits': LIMITS,
              'CSL_quality_improvement_verified': False}
    u.base.write_json(output / 'report.json', report); u.base.write_json(output / 'diagnostic-predictions.json', predictions)
    u.base.write_json(output / 'dev-predictions.json', replay); u.seal(output); return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for name in ['original', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('train')
    for name in ['prepared', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('audit')
    for name in ['prepared', 'results', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('interactive')
    for name in ['prepared', 'results', 'encoder-root']: p.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare(args.original, args.output)
    elif args.command == 'train': result = train(args.prepared, args.encoder_root, args.output)
    elif args.command == 'audit': result = audit(args.prepared, args.results, args.encoder_root, args.output)
    else:
        state = load_runtime(args.prepared, args.results, args.encoder_root)
        print('有限中文语义研究终端；/quit退出。非中国手语翻译。', flush=True)
        for line in sys.stdin:
            text = line.rstrip('\r\n')
            if text == '/quit': break
            print(json.dumps(predict_texts(state, [text])[0], ensure_ascii=False), flush=True)
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
