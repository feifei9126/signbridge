"""Controlled CUDA role-head ablation and saved-prediction error analysis."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import random


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


u = load('sign-csl-unified.py')
errors = load('sign-ce-csl-gloss-errors.py')


def filter_known(rows, vocab):
    known, good, blocked = set(vocab['source']), [], []
    for row in rows:
        missing = sorted(set(u.base.normalize(row['text'])) - known)
        if missing:
            blocked.append({'id': row['id'], 'unknown_characters': missing})
        else:
            good.append(row)
    return good, blocked


def freeze(model):
    for name, param in model.named_parameters():
        param.requires_grad_(name.startswith('role_head.'))
    model.eval()


def step(model, optimizer, rows, vocab, device):
    import torch
    model.eval(); model.role_head.train()
    source, target = u.task_batch(rows, 'roles', vocab, device)
    with torch.no_grad():
        memory = model.encode(source)
    loss = torch.nn.functional.cross_entropy(model.role_head(memory).flatten(0, 1), target.flatten(), ignore_index=-100)
    if not torch.isfinite(loss):
        raise ValueError('Nonfinite role loss')
    optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step()
    return float(loss.detach())


def analyze(package, model, output):
    package, model, output = map(u.safe_path, [package, model, output])
    if output.exists():
        raise FileExistsError('Choose a NEW output')
    data, _, provenance = u.read_package(package)
    manifest, used = u.read_manifest(model)
    report = json.loads(u.checked(model, 'report.json', manifest, used))
    assert report['status'] == 'completed' and report['test_read'] is False
    predictions = [json.loads(u.checked(model, n, manifest, used)) for n in
                   ['initial-dev-predictions.json', 'selected-dev-predictions.json']]
    freq = Counter(t for row in data['gloss']['train'] for t in row['gloss_sequence'])
    truth = {row['id']: row for row in data['gloss']['dev']}
    before, after = [{r['id']: r for r in p['gloss']} for p in predictions]
    if set(before) != set(truth) or set(after) != set(truth):
        raise ValueError('Prediction identities differ from dev')
    cases, confusion = [], {'before': Counter(), 'after': Counter()}
    for id, row in truth.items():
        a, b = before[id], after[id]
        if any(p['text'] != row['text'] or p['reference'] != row['gloss_sequence'] for p in [a, b]):
            raise ValueError('Prediction targets differ from dev')
        ca, cb = (errors.diagnose(row['gloss_sequence'], p['predicted'], freq) for p in [a, b])
        for name, diagnosis in [('before', ca), ('after', cb)]:
            for op in diagnosis['operations']:
                if op['operation'] != 'match':
                    confusion[name][(op['operation'], str(op['reference']), str(op['predicted']))] += 1
        cases.append({'id': id, 'text': row['text'], 'reference': row['gloss_sequence'],
                      'before_prediction': a['predicted'], 'after_prediction': b['predicted'],
                      'before': ca, 'after': cb, 'edit_delta': cb['edit_errors'] - ca['edit_errors']})
    output.mkdir(parents=True)
    result = {'schema': 'signbridge-head-only-dev-diagnosis-v1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'cases': len(cases), 'improved': sum(r['edit_delta'] < 0 for r in cases),
              'regressed': sum(r['edit_delta'] > 0 for r in cases), 'tied': sum(r['edit_delta'] == 0 for r in cases),
              'before_metrics': u.base.metrics([r['reference'] for r in cases], [r['before_prediction'] for r in cases]),
              'after_metrics': u.base.metrics([r['reference'] for r in cases], [r['after_prediction'] for r in cases]),
              'confusions': {k: [{'operation': op, 'reference': a, 'predicted': b, 'count': n}
                                  for (op, a, b), n in v.most_common(30)] for k, v in confusion.items()},
              'source_input_sha256': provenance['sha256'], 'model_input_sha256': used,
              'train_test_read': False, 'limitations': ['Dev-based diagnostic, not independent evaluation.',
                 'Fixed edit alignment has ties and is not a causal explanation.', 'Raw numbered Gloss variants remain distinct.']}
    u.base.write_json(output/'report.json', result)
    (output/'cases.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in cases))
    u.seal(output)
    return result


def train(package, initial, output, epochs=25, patience=6, batch=64, lr=.001, seed=20261105):
    import torch
    package, initial, output = map(u.safe_path, [package, initial, output])
    u.new_output(output, [package, initial]); device = u.cuda_device('cuda')
    data, labels, provenance = u.read_package(package); original = u.read_initial(initial)
    vocab = original['vocab']; torch.manual_seed(seed); torch.cuda.manual_seed_all(seed); random.seed(seed); torch.set_num_threads(4)
    model, initialization = u.initialize_model(vocab, labels, original); model.to(device); freeze(model)
    reference = {k: v.detach().cpu().clone() for k, v in model.state_dict().items() if not k.startswith('role_head.')}
    train_rows, train_blocked = filter_known(data['roles']['train'], vocab)
    dev_rows, dev_blocked = filter_known(data['roles']['dev'], vocab)
    if not train_rows or not dev_rows:
        raise ValueError('No known-character role data')
    subset = {'gloss': data['gloss'], 'roles': {'train': train_rows, 'dev': dev_rows}}
    optimizer = torch.optim.AdamW(model.role_head.parameters(), lr=lr)
    output.mkdir(parents=True); (output/'checkpoints').mkdir()
    u.base.write_json(output/'vocab.json', vocab); u.base.write_json(output/'role-labels.json', labels)
    before, before_predictions = u.evaluate(model, subset, vocab, device, batch, 62)
    u.base.write_json(output/'initial-dev-predictions.json', before_predictions)
    best, best_epoch, stale, history = -1, 0, 0, []
    for epoch in range(1, epochs + 1):
        random.shuffle(train_rows); losses = []
        for i in range(0, len(train_rows), batch):
            losses.append(step(model, optimizer, train_rows[i:i+batch], vocab, device))
        metrics, predictions = u.evaluate(model, subset, vocab, device, batch, 62)
        if metrics['gloss'] != before['gloss'] or predictions['gloss'] != before_predictions['gloss']:
            raise ValueError('Frozen Gloss predictions changed')
        score = metrics['roles']['exact_matches']
        if score > best:
            best, best_epoch, stale = score, epoch, 0
            u.save_weights(output/'checkpoints/best.pt', model)
            u.base.write_json(output/'selected-dev-predictions.json', predictions)
        else:
            stale += 1
        history.append({'epoch': epoch, 'loss': sum(losses)/len(losses), 'dev': metrics, 'selected_epoch': best_epoch})
        u.base.write_json(output/'progress.json', {'epoch': epoch, 'selected_epoch': best_epoch, 'status': 'running'})
        print(json.dumps(history[-1]), flush=True)
        if stale >= patience:
            break
    model.load_state_dict(torch.load(output/'checkpoints/best.pt', map_location=device, weights_only=True), strict=True)
    assert all(torch.equal(value, model.state_dict()[key].detach().cpu()) for key, value in reference.items())
    checkpoint = output/'checkpoints/best.pt'; digest = u.base.sha(checkpoint)
    meta = {**u.GATES, 'schema': u.SCHEMA, 'config': original['metadata']['config'],
            'checkpoint': 'checkpoints/best.pt', 'checkpoint_sha256': digest,
            'support': u.role_support(train_rows, labels), 'roles_label_source': 'assistant_synthetic_chinese'}
    u.base.write_json(output/'model.json', meta)
    result = {**u.GATES, 'status': 'completed', 'training_started': True, 'actual_training_device': str(device),
              'gpu': torch.cuda.get_device_name(device), 'torch': str(torch.__version__), 'cuda': torch.version.cuda,
              'initialization': initialization, 'checkpoint': meta['checkpoint'], 'checkpoint_sha256': digest,
              'source_package': provenance['sha256'], 'initial_model': original['inputs'],
              'before': before, 'selected': history[best_epoch-1]['dev'], 'epochs_completed': len(history),
              'selected_epoch': best_epoch, 'history': history, 'unknown_train': train_blocked, 'unknown_dev': dev_blocked,
              'known_train_count': len(train_rows), 'known_dev_count': len(dev_rows),
              'backbone_bitwise_unchanged': True, 'gloss_dev_predictions_identical': True,
              'config': {'epochs': epochs, 'patience': patience, 'batch': batch, 'lr': lr, 'seed': seed},
              'checkpoint_selection': 'max known-character role dev exact, earliest tie; not frozen contrast',
              'limitations': ['Synthetic Chinese roles, not CSL supervision.', 'Shared frozen encoder limits lexical generalization.',
                              'Unknown characters excluded rather than trained.', 'Dev selected, not independent test.']}
    u.base.write_json(output/'report.json', result); u.seal(output)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('analyze'); p.add_argument('--package', type=Path, required=True); p.add_argument('--model', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('train'); p.add_argument('--package', type=Path, required=True); p.add_argument('--initial', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.package, args.model, args.output) if args.command == 'analyze' else train(args.package, args.initial, args.output)
    print(json.dumps(result, ensure_ascii=False))
