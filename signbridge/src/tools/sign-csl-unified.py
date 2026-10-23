"""CUDA-only research multitask trainer; CPU predict never produces playable motion.

train --package ROOT --initial-model ROOT --output NEW_ROOT [--device cuda]
predict --model ROOT --text TEXT
Frozen train/dev only; roles are synthetic Chinese labels, not CSL supervision.
External checkpoints contain state_dict only; recovery files also retain optimizer/RNG.
"""
import argparse
from collections import Counter, defaultdict
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import re
import sys
import time

_spec = importlib.util.spec_from_file_location('unified_gloss_base', Path(__file__).with_name('sign-ce-csl-gloss.py'))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
SCHEMA = 'signbridge-csl-unified-v1'
INITIAL_SHA = '606880a672338eca766a12a43aff25356bcde6375e848c241ffac5f29a1088fa'
ROLE_LABELS = ['O'] + [p + r for r in ['actor', 'predicate', 'patient', 'goal', 'time',
    'negation', 'modal', 'question', 'aspect', 'politeness', 'degree'] for p in ['B-', 'I-']]
GATES = dict(research_only=True, human_approved=False, training_ready=False,
             model_training_ready=False, deployment_ready=False, can_play=False,
             candidate_approval_state_unchanged=True, csl_translation_trained=False,
             text_to_motion_trained=False, test_read=False)


def safe_path(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Unsafe path traversal')
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError('Input/output symlink rejected: ' + str(part))
    return path


def checked(root, name, manifest, consumed):
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise ValueError('Unsafe relative path: ' + name)
    path = safe_path(root / relative)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Missing/unsafe input path: ' + name)
    content = path.read_bytes()
    import hashlib
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest.get(name):
        raise ValueError('Input digest differs: ' + name)
    consumed[name] = digest
    return content


def read_manifest(root):
    path = safe_path(root / 'SHA256SUMS')
    content = path.read_bytes()
    import hashlib
    consumed, manifest = {'SHA256SUMS': hashlib.sha256(content).hexdigest()}, {}
    for line in content.decode('utf-8').splitlines():
        digest, name = line.split('  ', 1)
        if name in manifest or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid/duplicate digest entry')
        manifest[name] = digest
    return manifest, consumed


def read_package(root):
    root = safe_path(root); manifest, consumed = read_manifest(root)
    labels = json.loads(checked(root, 'role-labels.json', manifest, consumed))
    report = json.loads(checked(root, 'report.json', manifest, consumed))
    if labels != ROLE_LABELS or any(report.get(k) is not False for k in
            ['test_read', 'training_ready', 'model_training_ready', 'human_approved']):
        raise ValueError('Invalid labels or package gates')
    data, identities = {}, set()
    for task in ['gloss', 'roles']:
        data[task] = {}
        for split in ['train', 'dev']:
            name = f'{task}-{split}.jsonl'
            rows = [json.loads(line) for line in checked(root, name, manifest, consumed).decode('utf-8').splitlines() if line.strip()]
            if not rows:
                raise ValueError('Empty split: ' + name)
            for row in rows:
                text = row.get('text'); identity = row.get('id')
                source = 'ce_csl_dataset' if task == 'gloss' else 'assistant_synthetic_chinese'
                if (not isinstance(identity, str) or not identity or identity in identities
                        or not isinstance(text, str) or not 1 <= len(base.normalize(text)) <= 126
                        or row.get('task') != task or row.get('label_source') != source
                        or row.get('human_approved') is not False):
                    raise ValueError('Invalid sample identity, text or provenance: ' + name)
                identities.add(identity)
                target = row.get('gloss_sequence' if task == 'gloss' else 'tags')
                if not isinstance(target, list) or not target:
                    raise ValueError('Missing target sequence')
                if task == 'gloss':
                    if len(target) > 62 or any(not isinstance(t, str) or not t or t in base.SPECIALS for t in target):
                        raise ValueError('Invalid gloss sequence')
                elif (text != base.normalize(text) or len(target) != len(text)
                        or any(type(t) is not int or not 0 <= t < len(labels) for t in target)):
                    raise ValueError('Invalid/alignment-ambiguous role tags')
            if 'counts' in report and report['counts'].get(f'{task}-{split}') != len(rows):
                raise ValueError('Package report count differs')
            data[task][split] = rows
        training = data[task]['train']; heldout = data[task]['dev']
        if {base.normalize(r['text']) for r in training} & {base.normalize(r['text']) for r in heldout}:
            raise ValueError('Train/dev text overlap')
        if task == 'gloss':
            if {tuple(r['gloss_sequence']) for r in training} & {tuple(r['gloss_sequence']) for r in heldout}:
                raise ValueError('Train/dev gloss overlap')
            if ({r.get('video_sha256') for r in training} & {r.get('video_sha256') for r in heldout}) - {None}:
                raise ValueError('Train/dev video overlap')
    return data, labels, {'sha256': consumed, 'report': report}


def build_vocab(data):
    vocab = base.build_vocab([dict(r, proposed_text=r['text']) for r in data['gloss']['train']])
    vocab['source'] = base.SPECIALS + sorted(set(vocab['source'][4:]) | {c for r in data['roles']['train'] for c in r['text']})
    return vocab


def validate_vocab(vocab):
    if not isinstance(vocab, dict) or set(vocab) != {'source', 'target'}:
        raise ValueError('Invalid vocabulary')
    for tokens in vocab.values():
        if (not isinstance(tokens, list) or tokens[:4] != base.SPECIALS
                or any(not isinstance(t, str) or not t for t in tokens) or len(set(tokens)) != len(tokens)):
            raise ValueError('Invalid vocabulary tokens')


def read_initial(root):
    import torch
    root = safe_path(root); manifest, consumed = read_manifest(root)
    meta = json.loads(checked(root, 'model.json', manifest, consumed))
    vocab = json.loads(checked(root, 'vocab.json', manifest, consumed)); validate_vocab(vocab)
    report = json.loads(checked(root, 'report.json', manifest, consumed))
    name = meta.get('checkpoint')
    if (meta.get('schema') != 'signbridge-ce-csl-text-to-gloss-v1' or meta.get('research_only') is not True
            or not isinstance(name, str) or meta.get('checkpoint_sha256') != INITIAL_SHA
            or report.get('status') != 'completed' or report.get('checkpoint') != name
            or report.get('checkpoint_sha256') != INITIAL_SHA):
        raise ValueError('Initial checkpoint/report not bound to pinned digest')
    content = checked(root, name, manifest, consumed)
    if consumed[name] != INITIAL_SHA:
        raise ValueError('Initial checkpoint digest differs')
    return {'metadata': meta, 'vocab': vocab, 'state': torch.load(io.BytesIO(content), map_location='cpu', weights_only=True),
            'inputs': consumed, 'source_checkpoint_sha256': INITIAL_SHA}


def initialize_model(vocab, labels, initial):
    from torch import nn
    validate_vocab(vocab); validate_vocab(initial['vocab'])
    if labels != ROLE_LABELS:
        raise ValueError('Invalid role labels')
    model = base.make_model(vocab, initial['metadata']['config'])
    old, state = initial['state'], model.state_dict()
    if not isinstance(old, dict) or set(old) != set(state):
        raise ValueError('Initial parameters do not strictly match backbone')
    remap = {'source.weight': 'source', 'target.weight': 'target', 'output.weight': 'target', 'output.bias': 'target'}
    for key, destination in state.items():
        source = old[key]
        if source.dtype != destination.dtype:
            raise ValueError('Initial parameters dtype differs: ' + key)
        if key in remap:
            side = remap[key]; previous = initial['vocab'][side]
            if source.shape != (len(previous), *destination.shape[1:]):
                raise ValueError('Initial parameters shape differs: ' + key)
            lookup = {token: i for i, token in enumerate(previous)}
            for i, token in enumerate(vocab[side]):
                if token in lookup:
                    destination[i].copy_(source[lookup[token]])
        else:
            if source.shape != destination.shape:
                raise ValueError('Initial parameters shape differs: ' + key)
            destination.copy_(source)
    model.load_state_dict(state, strict=True)
    model.role_head = nn.Linear(initial['metadata']['config']['width'], len(labels))
    info = {'mode': 'weights_only_initialization', 'optimizer_state_restored': False,
            'source_checkpoint_sha256': initial.get('source_checkpoint_sha256'), 'new_optimizer': 'AdamW'}
    for side in ['source', 'target']:
        info[side + '_tokens_added'] = sorted(set(vocab[side]) - set(initial['vocab'][side]))
        info[side + '_tokens_lost'] = sorted(set(initial['vocab'][side]) - set(vocab[side]))
    return model, info


def task_batch(rows, task, vocab, device):
    import torch
    source, target = base.batch_tensors([dict(r, proposed_text=r['text'], gloss_sequence=r.get('gloss_sequence', [])) for r in rows], vocab, device)
    if task == 'roles':
        target = torch.full_like(source, -100)
        for i, row in enumerate(rows):
            target[i, 1:len(row['tags']) + 1] = torch.tensor(row['tags'], device=device)
    elif task != 'gloss':
        raise ValueError('Unknown task')
    return source, target


def task_loss(model, source, target, task):
    from torch.nn.functional import cross_entropy
    if task == 'roles':
        logits = model.role_head(model.encode(source))
        return cross_entropy(logits.flatten(0, 1), target.flatten(), ignore_index=-100)
    if task != 'gloss':
        raise ValueError('Unknown task')
    logits = model(source, target[:, :-1])
    return cross_entropy(logits.flatten(0, 1), target[:, 1:].reshape(-1), ignore_index=0, label_smoothing=.05)


def training_batches(data, batch_size):
    orders = {task: list(data[task]['train']) for task in ['gloss', 'roles']}
    for rows in orders.values():
        random.shuffle(rows)
    for start in range(0, max(map(len, orders.values())), batch_size):
        for task, rows in orders.items():
            if start < len(rows):
                yield task, rows[start:start + batch_size]


def evaluate(model, data, vocab, device, batch_size=64, max_length=62):
    import torch
    model.eval(); predictions = {'gloss': [], 'roles': []}
    for task in predictions:
        rows = data[task]['dev']
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]; source, _ = task_batch(batch, task, vocab, device)
            with torch.inference_mode():
                if task == 'gloss':
                    predicted = base.greedy_decode(model, source, vocab, max_length=max_length)
                else:
                    tags = model.role_head(model.encode(source)).argmax(-1).cpu().tolist()
                    predicted = [t[1:len(r['tags']) + 1] for r, t in zip(batch, tags)]
            for row, prediction in zip(batch, predicted):
                predictions[task].append({'id': row['id'], 'text': row['text'], 'task': task,
                    'reference': row['gloss_sequence' if task == 'gloss' else 'tags'], 'predicted': prediction})
    refs = [r['reference'] for r in predictions['roles']]; hyps = [r['predicted'] for r in predictions['roles']]
    tokens = sum(map(len, refs)); correct = sum(a == b for r, h in zip(refs, hyps) for a, b in zip(r, h))
    exact = sum(r == h for r, h in zip(refs, hyps))
    return {'gloss': base.metrics([r['reference'] for r in predictions['gloss']], [r['predicted'] for r in predictions['gloss']]),
            'roles': {'samples': len(refs), 'tokens': tokens, 'correct_tokens': correct, 'token_accuracy': correct / tokens,
                      'exact_matches': exact, 'exact_match_rate': exact / len(refs), 'label_source': 'assistant_synthetic_chinese'}}, predictions


def parse_roles(text, tags, labels, support=None):
    raw = [labels[t] for t in tags]; spans, reasons = [], []
    for i, tag in enumerate(raw):
        if tag == 'O':
            reasons.append('unresolved_O'); continue
        role = tag[2:]
        if tag.startswith('I-'):
            if not spans or spans[-1]['role'] != role or spans[-1]['end'] != i:
                reasons.append('invalid_BIO'); continue
            spans[-1].update(end=i + 1, text=spans[-1]['text'] + text[i])
        else:
            spans.append({'role': role, 'start': i, 'end': i + 1, 'text': text[i]})
    counts = Counter(s['role'] for s in spans)
    if counts['actor'] != 1 or counts['predicate'] != 1 or any(c > 1 for c in counts.values()):
        reasons.append('unsupported_role_structure')
    if counts['negation'] + counts['modal'] > 1:
        reasons.append('operator_scope_unresolved')
    roles = {s['role']: s['text'] for s in spans}
    if support is not None:
        if [s['role'] for s in spans] not in support.get('orders', []):
            reasons.append('unseen_role_order')
        if any(s['text'] not in support.get('values', {}).get(s['role'], []) for s in spans):
            reasons.append('outside_training_role_support')
        arguments = support.get('arguments', {}).get(roles.get('predicate'), {})
        if any(roles[k] not in arguments.get(k, []) for k in ['patient', 'goal'] if k in roles):
            reasons.append('outside_training_argument_support')
    return {'raw_tags': raw, 'spans': spans, 'roles': {} if reasons else roles, 'scope': None,
            'uncertainty': sorted(set(reasons)), 'confidence': None}


def role_support(rows, labels):
    orders, values, arguments = set(), defaultdict(set), defaultdict(lambda: defaultdict(set))
    for row in rows:
        parsed = parse_roles(row['text'], row['tags'], labels)
        if parsed['uncertainty']:
            continue
        orders.add(tuple(s['role'] for s in parsed['spans']))
        for role, value in parsed['roles'].items():
            values[role].add(value)
            if role in ['patient', 'goal']:
                arguments[parsed['roles']['predicate']][role].add(value)
    return {'orders': [list(o) for o in sorted(orders)], 'values': {k: sorted(v) for k, v in values.items()},
            'arguments': {p: {k: sorted(v) for k, v in a.items()} for p, a in arguments.items()}}


def cuda_device(name):
    if name != 'cuda':
        raise ValueError('CUDA is the only training device; no CPU fallback')
    import torch
    if not torch.cuda.is_available():
        raise ValueError('CUDA unavailable; no CPU fallback')
    return torch.device('cuda')


def new_output(path, inputs):
    path = safe_path(path)
    if path.exists() or any(path == p or path.is_relative_to(p) or p.is_relative_to(path) for p in map(safe_path, inputs)):
        raise ValueError('Choose a NEW output separate from all inputs')
    return path


def save_weights(path, model):
    import torch
    torch.save({k: v.detach().cpu() for k, v in model.state_dict().items()}, path)


def save_recovery(path, model, optimizer, epoch, steps, selection):
    import torch
    torch.save({'model': {k: v.detach().cpu() for k, v in model.state_dict().items()},
        'optimizer': optimizer.state_dict(), 'epoch': epoch, 'steps': steps, 'selection': selection,
        'python_rng': random.getstate(), 'torch_rng': torch.get_rng_state(),
        'cuda_rng': torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}, path)


def seal(output):
    (output / 'SHA256SUMS').write_text(''.join(f'{base.sha(p)}  {p.relative_to(output).as_posix()}\n'
        for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'), encoding='utf-8')


def train(args):
    import torch
    if (not 1 <= args.epochs <= 200 or not 1 <= args.batch_size <= 256 or not 1 <= args.threads <= 64
            or args.patience < 1 or any(not math.isfinite(x) or x <= 0 for x in [args.learning_rate, args.role_weight])):
        raise ValueError('Invalid bounded training arguments')
    device = cuda_device(args.device)
    output = new_output(args.output, [args.package, args.initial_model])
    data, labels, package = read_package(args.package); initial = read_initial(args.initial_model)
    torch.set_num_threads(args.threads); random.seed(args.seed); torch.manual_seed(args.seed); torch.cuda.manual_seed_all(args.seed)
    vocab = build_vocab(data); model, initialization = initialize_model(vocab, labels, initial)
    config = initial['metadata']['config']; model = model.to(device)
    if next(model.parameters()).device.type != 'cuda':
        raise ValueError('Actual model training device is not CUDA')
    max_length = min(62, config['max_target'] - 1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=.01)
    output.mkdir(parents=True); (output / 'checkpoints').mkdir()
    base.write_json(output / 'vocab.json', vocab); base.write_json(output / 'role-labels.json', labels)
    runtime = {'python': sys.version, 'executable': sys.executable, 'torch': str(torch.__version__),
        'device': str(next(model.parameters()).device), 'cuda_runtime': torch.version.cuda,
        'gpu_name': torch.cuda.get_device_name(device), 'threads': args.threads,
        'sha256': {str(Path(p).resolve()): base.sha(Path(p).resolve()) for p in [sys.executable, torch.__file__, torch._C.__file__]}}
    report = {**GATES, 'schema': SCHEMA, 'status': 'running', 'training_started': True,
        'initialization': initialization, 'source_files_sha256': {'package': package['sha256'], 'initial_model': initial['inputs']},
        'package_report': package['report'], 'runtime': runtime, 'actual_training_device': runtime['device'],
        'tool_sha256': {Path(p).name: base.sha(p) for p in [__file__, base.__file__]},
        'arguments': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, 'config': config,
        'split_counts': {t: {s: len(r) for s, r in splits.items()} for t, splits in data.items()},
        'vocabulary_source': 'train_only_both_tasks', 'selection': 'minimum dev Gloss GER among training epochs only',
        'roles_label_source': 'assistant_synthetic_chinese', 'roles_are_csl_supervision': False,
        'limits': ['Synthetic Chinese roles are not CSL translation or action generation.',
                   'Historical initialization may have seen prior dev overlaps; dev is not an independent final test.'],
        'initial_weights_sha256': base.weights_hash(model), 'optimizer_steps': 0}
    base.write_json(output / 'report.json', report)
    best, best_epoch, stale, steps = math.inf, 0, 0, 0
    task_steps = {'gloss': 0, 'roles': 0}; candidates = []; started = time.monotonic()
    try:
        initial_dev, initial_predictions = evaluate(model, data, vocab, device, args.batch_size, max_length)
        report['initial_dev'] = initial_dev
        save_weights(output / 'checkpoints/epoch-000.pt', model)
        base.write_json(output / 'initial-dev-predictions.json', initial_predictions)
        with (output / 'training.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'epoch': 0, 'optimizer_steps': 0, 'dev': initial_dev}) + '\n')
        for epoch in range(1, args.epochs + 1):
            model.train(); losses = {'gloss': [], 'roles': []}; epoch_start = time.monotonic()
            for task, rows in training_batches(data, args.batch_size):
                source, target = task_batch(rows, task, vocab, device)
                optimizer.zero_grad(set_to_none=True); raw_loss = task_loss(model, source, target, task)
                loss = raw_loss * (args.role_weight if task == 'roles' else 1.)
                if not bool(torch.isfinite(loss)):
                    raise ValueError('Nonfinite loss')
                loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.); optimizer.step()
                steps += 1; task_steps[task] += 1; losses[task].append(float(raw_loss.detach()))
            dev, predictions = evaluate(model, data, vocab, device, args.batch_size, max_length)
            score = dev['gloss']['gloss_error_rate']; improved = score < best
            if improved:
                best, best_epoch, stale = score, epoch, 0
                selected = f'checkpoints/epoch-{epoch:03d}.pt'; save_weights(output / selected, model)
                candidates.append({'epoch': epoch, 'checkpoint': selected, 'checkpoint_sha256': base.sha(output / selected),
                                   'weights_sha256': base.weights_hash(model), 'dev': dev})
                base.write_json(output / 'selected-dev-predictions.json', predictions)
                report.update(selected_dev=dev, checkpoint=selected, selected_epoch=epoch)
            else:
                stale += 1
            selection = {'selected_epoch': best_epoch, 'best_ger': best, 'stale': stale, 'task_steps': dict(task_steps)}
            save_recovery(output / 'checkpoints/recovery-last.pt', model, optimizer, epoch, steps, selection)
            if improved:
                save_recovery(output / 'checkpoints/recovery-best.pt', model, optimizer, epoch, steps, selection)
            record = {'epoch': epoch, 'optimizer_steps': steps, 'task_steps': dict(task_steps), 'dev': dev,
                'train_loss': {k: sum(v) / len(v) for k, v in losses.items()}, 'selected_epoch': best_epoch,
                'epoch_seconds': time.monotonic() - epoch_start}
            with (output / 'training.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
            report.update(optimizer_steps=steps, task_steps=dict(task_steps), epochs_completed=epoch, candidates=candidates)
            base.write_json(output / 'report.json', report); print(json.dumps(record, ensure_ascii=False), flush=True)
            if stale >= args.patience:
                break
        report['last_weights_sha256'] = base.weights_hash(model)
        model.load_state_dict(torch.load(output / report['checkpoint'], map_location=device, weights_only=True), strict=True)
        report.update(status='completed', checkpoint_sha256=base.sha(output / report['checkpoint']),
            selected_weights_sha256=base.weights_hash(model), elapsed_seconds=time.monotonic() - started,
            improved_over_initial_dev=best < initial_dev['gloss']['gloss_error_rate'], promoted=False,
            gloss_metrics=report['selected_dev']['gloss'], roles_metrics=report['selected_dev']['roles'])
        base.write_json(output / 'model.json', {**GATES, 'schema': SCHEMA, 'config': config,
            'checkpoint': report['checkpoint'], 'checkpoint_sha256': report['checkpoint_sha256'],
            'support': role_support(data['roles']['train'], labels), 'roles_label_source': 'assistant_synthetic_chinese'})
        base.write_json(output / 'report.json', report); seal(output)
        return report
    except Exception as error:
        report.update(status='failed', error=repr(error), optimizer_steps=steps, task_steps=task_steps)
        base.write_json(output / 'report.json', report); seal(output)
        raise


def infer(root, text):
    import torch
    root = safe_path(root); manifest, consumed = read_manifest(root)
    meta = json.loads(checked(root, 'model.json', manifest, consumed))
    vocab = json.loads(checked(root, 'vocab.json', manifest, consumed)); validate_vocab(vocab)
    labels = json.loads(checked(root, 'role-labels.json', manifest, consumed))
    if meta.get('schema') != SCHEMA or meta.get('research_only') is not True or labels != ROLE_LABELS:
        raise ValueError('Unsupported research model/labels')
    content = checked(root, meta['checkpoint'], manifest, consumed)
    if consumed[meta['checkpoint']] != meta.get('checkpoint_sha256'):
        raise ValueError('Model checkpoint digest differs')
    normalized = base.normalize(text) if isinstance(text, str) else ''
    out = {**GATES, 'schema': SCHEMA, 'status': 'unsupported', 'input': text, 'normalized_text': normalized,
           'gloss_candidate': [], 'roles': {}, 'spans': [], 'raw_tags': [], 'scope': None, 'confidence': None,
           'uncertainty': [], 'device': 'cpu', 'files_sha256': consumed, 'roles_label_source': 'assistant_synthetic_chinese'}
    unseen = sorted(set(normalized) - set(vocab['source'])); out['unseen_input_characters'] = unseen
    if not 1 <= len(normalized) <= min(126, meta['config']['max_source'] - 2):
        out['uncertainty'] = ['invalid_or_overlong_text']; return out
    if unseen:
        out['uncertainty'] = ['outside_training_character_support']; return out
    torch.set_num_threads(4)
    model = base.make_model(vocab, meta['config']); model.role_head = torch.nn.Linear(meta['config']['width'], len(labels))
    model.load_state_dict(torch.load(io.BytesIO(content), map_location='cpu', weights_only=True), strict=True); model.eval()
    source, _ = task_batch([{'text': normalized, 'gloss_sequence': []}], 'gloss', vocab, 'cpu')
    with torch.inference_mode():
        tags = model.role_head(model.encode(source)).argmax(-1)[0, 1:len(normalized) + 1].tolist()
        out.update(parse_roles(normalized, tags, labels, meta.get('support', {})))
        out['gloss_candidate'] = base.greedy_decode(model, source, vocab, max_length=min(62, meta['config']['max_target'] - 1))[0]
    if re.search(r'[，,。.!！?？；;]', text.strip().rstrip('。.!！?？；;')):
        out['uncertainty'].append('internal_clause_boundary')
    if any(t in base.SPECIALS for t in out['gloss_candidate']) or not out['gloss_candidate']:
        out['uncertainty'].append('unsupported_gloss_sequence')
    if out['uncertainty']:
        out['roles'] = {}
    else:
        out['status'] = 'research_candidate_only'
    return out


def parser():
    result = argparse.ArgumentParser(description=__doc__); sub = result.add_subparsers(dest='command', required=True)
    fit = sub.add_parser('train')
    for name in ['package', 'initial-model', 'output']:
        fit.add_argument('--' + name, type=Path, required=True)
    fit.add_argument('--device', choices=['cuda'], default='cuda')
    for name, default in [('epochs', 30), ('batch-size', 64), ('seed', 20261023), ('patience', 8), ('threads', 4)]:
        fit.add_argument('--' + name, type=int, default=default)
    fit.add_argument('--learning-rate', type=float, default=.0002); fit.add_argument('--role-weight', type=float, default=.3)
    prediction = sub.add_parser('predict'); prediction.add_argument('--model', type=Path, required=True); prediction.add_argument('--text', required=True)
    return result


if __name__ == '__main__':
    arguments = parser().parse_args()
    value = train(arguments) if arguments.command == 'train' else infer(arguments.model, arguments.text)
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
