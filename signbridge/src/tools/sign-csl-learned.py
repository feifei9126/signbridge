#!/usr/bin/env python3
"""Train/evaluate a bounded Chinese semantic tagger; this is NOT a CSL translator.

All labels generated here are assistant synthetic Chinese supervision. No video
labels, CSL grammar claims, checkpoint promotion or human approval are inferred.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time
import unicodedata

import numpy as np

SCHEMA = 'signbridge-learned-chinese-roles-v1'
ROLES = ['actor', 'predicate', 'patient', 'goal', 'time', 'negation', 'modal',
         'question', 'aspect', 'politeness', 'degree']
LABELS = ['O'] + [prefix + role for role in ROLES for prefix in ['B-', 'I-']]
PUNCT = set(' ，,。.!！?？；;、\t\n\r')
CHALLENGE = [
    ('我帮你', {'actor': '我', 'predicate': '帮', 'patient': '你'}),
    ('你帮我', {'actor': '你', 'predicate': '帮', 'patient': '我'}),
    ('我今天去学校', {'actor': '我', 'time': '今天', 'predicate': '去', 'goal': '学校'}),
    ('今天我去学校', {'actor': '我', 'time': '今天', 'predicate': '去', 'goal': '学校'}),
    ('她明天来医院', {'actor': '她', 'time': '明天', 'predicate': '来', 'goal': '医院'}),
    ('明天她来医院', {'actor': '她', 'time': '明天', 'predicate': '来', 'goal': '医院'}),
    ('我们昨天没有看电影', {'actor': '我们', 'time': '昨天', 'negation': '没有', 'predicate': '看', 'patient': '电影'}),
    ('你喜欢看电影吗', None),
    ('你去吗', {'actor': '你', 'predicate': '去', 'question': '吗'}),
    ('我没有去', {'actor': '我', 'negation': '没有', 'predicate': '去'}),
    ('我想去', {'actor': '我', 'modal': '想', 'predicate': '去'}),
    ('我必须去', {'actor': '我', 'modal': '必须', 'predicate': '去'}),
    ('我喜欢你', {'actor': '我', 'predicate': '喜欢', 'patient': '你'}),
    ('我爱你', {'actor': '我', 'predicate': '爱', 'patient': '你'}),
    ('我买了书', {'actor': '我', 'predicate': '买', 'aspect': '了', 'patient': '书'}),
    ('请你帮助我', {'politeness': '请', 'actor': '你', 'predicate': '帮助', 'patient': '我'}),
    ('他非常开心', {'actor': '他', 'degree': '非常', 'predicate': '开心'}),
    ('你能学习手语吗', {'actor': '你', 'modal': '能', 'predicate': '学习', 'patient': '手语', 'question': '吗'}),
    ('我喝书', None), ('我买医院', None), ('我去水', None), ('我们去你', None),
    ('我去火星', None), ('如果你来我就去', None), ('我不想去', None),
    ('我想不去', None), ('我帮你你帮我', None), ('我被你帮助', None),
    ('不是我帮你', None), ('谁帮助谁', None), ('我去了学校以后回家', None),
    ('我喜欢他也喜欢你', None), ('我把书给你', None), ('😀', None),
]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def clean(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c not in PUNCT)


def features(text, index):
    at = lambda i: text[i] if 0 <= i < len(text) else ('^' if i < 0 else '$')
    out = ['bias']
    out.extend(f'c{o}={at(index + o)}' for o in range(-2, 3))
    out.extend(f'b{o}={at(index + o)}{at(index + o + 1)}' for o in range(-2, 2))
    return out


def legal_transitions():
    mask = np.zeros((len(LABELS), len(LABELS)), dtype=np.float64)
    for j, tag in enumerate(LABELS):
        if tag.startswith('I-'):
            for i, prev in enumerate(LABELS):
                if prev not in ['B-' + tag[2:], tag]:
                    mask[i, j] = -1e9
    start = np.array([-1e9 if t.startswith('I-') else 0 for t in LABELS])
    return mask, start


MASK, START = legal_transitions()


def decode(encoded, weights, transitions):
    emission = np.stack([weights[ids].sum(axis=0) for ids in encoded])
    scores = emission[0] + START
    pointers = []
    for row in emission[1:]:
        candidates = scores[:, None] + transitions + MASK
        best = candidates.argmax(axis=0)
        pointers.append(best)
        scores = candidates[best, np.arange(len(LABELS))] + row
    current = int(scores.argmax())
    path = [current]
    for pointer in reversed(pointers):
        current = int(pointer[current])
        path.append(current)
    return list(reversed(path))


def corpus(count=5000, seed=17):
    rng = random.Random(seed)
    people = ['我', '你', '他', '她', '我们', '你们', '他们']
    times = ['', '今天', '明天', '昨天', '现在', '上午', '下午', '晚上', '周末']
    groups = [
        (['去', '来', '到', '回'], ['学校', '医院', '家', '公园', '图书馆', '北京', '公司'], 'goal'),
        (['帮', '帮助', '爱', '喜欢', '认识', '看见', '找到', '告诉', '等'], people, 'patient'),
        (['买', '卖'], ['书', '水', '东西'], 'patient'),
        (['看'], ['书', '电影'], 'patient'),
        (['学习'], ['手语'], 'patient'),
        (['找'], ['书', '工作', '东西'], 'patient'),
        (['需要', '准备'], ['水', '工作', '东西', '书'], 'patient'),
        (['借'], ['书'], 'patient'),
        (['喝'], ['水', '茶', '牛奶'], 'patient'),
        (['吃'], ['饭', '苹果', '面包'], 'patient'),
        (['知道', '明白', '工作', '休息', '学习', '去', '来'], [''], 'patient'),
        (['开心', '高兴', '累', '忙', '难过'], [''], 'patient'),
    ]
    rows = {}
    reserved = {clean(text) for text, _ in CHALLENGE}
    while len(rows) < count:
        actor = rng.choice(people)
        predicates, patients, role = rng.choice(groups)
        predicate, patient = rng.choice(predicates), rng.choice(patients)
        temporal = rng.choice(times)
        operator = rng.choice(['', '', '', '不', '没', '没有', '想', '必须', '应该', '能', '可以'])
        mood = rng.choice(['', '', '', '吗'])
        aspect = rng.choice(['', '', '', '了', '过']) if not operator and predicate in ['买', '看', '去', '来', '学', '找到'] else ''
        degree = rng.choice(['', '很', '非常']) if predicate in ['开心', '高兴', '累', '忙', '难过'] else ''
        if predicate in ['开心', '高兴', '累', '忙', '难过']:
            operator = '' if degree else rng.choice(['', '不'])
        # Requests are a dedicated simple imperative stratum; do not fabricate
        # past-time requests or politely demand a feeling/state.
        polite = ''
        if rng.random() < .10 and predicate in ['去', '来', '帮', '帮助', '看', '学习', '找', '准备', '喝', '吃']:
            polite, actor = '请', rng.choice(['你', '你们'])
            temporal = operator = mood = aspect = degree = ''
        head = [('time', temporal), ('actor', actor)] if rng.random() < .5 else [('actor', actor), ('time', temporal)]
        parts = [('politeness', polite)] + head
        parts += [('negation' if operator in ['不', '没', '没有'] else 'modal', operator),
                  ('degree', degree), ('predicate', predicate), ('aspect', aspect), (role, patient), ('question', mood)]
        parts = [(r, t) for r, t in parts if t]
        text = ''.join(t for _, t in parts)
        if text in reserved or text in rows:
            continue
        tags = [LABELS.index(prefix + r) for r, t in parts for prefix in ['B-'] + ['I-'] * (len(t) - 1)]
        # All variants of a participant/predicate/object tuple share one split.
        group = '|'.join([actor, predicate, patient])
        bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 10
        split = 'test' if bucket == 0 else 'validation' if bucket == 1 else 'train'
        rows[text] = {'text': text, 'tags': tags, 'roles': dict(parts), 'split': split,
                      'split_group': group, 'label_source': 'assistant_synthetic_chinese',
                      'human_approved': False, 'csl_supervision': False}
    return list(rows.values())


class Parser:
    def __init__(self, metadata, weights, transitions):
        self.metadata, self.weights, self.transitions = metadata, weights, transitions
        self.lookup = {value: i for i, value in enumerate(metadata['features'])}
        self.characters = set(metadata['characters'])
        self.allowed_orders = {tuple(x) for x in metadata['role_orders']}
        self.allowed_values = {k: set(v) for k, v in metadata['role_values'].items()}
        self.argument_support = metadata['argument_support']

    def predict(self, text):
        out = {'schema': SCHEMA, 'model_id': self.metadata['model_id'],
               'model_kind': 'averaged_structured_perceptron', 'target_language': 'CSL',
               'csl_translation_trained': False, 'human_approved': False,
               'motion_status': 'requires_csl_alignment_review', 'status': 'abstained',
               'roles': {}, 'spans': [], 'reasons': []}
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            out['reasons'] = ['invalid_or_overlong_text']
            return out
        normalized = clean(text)
        out['normalized_text'] = normalized
        if not normalized or any(c not in self.characters for c in normalized):
            out['reasons'] = ['outside_training_character_support']
            return out
        encoded = [[self.lookup[f] for f in features(normalized, i) if f in self.lookup] for i in range(len(normalized))]
        predicted = decode(encoded, self.weights, self.transitions)
        spans = []
        for i, tag_id in enumerate(predicted):
            tag = LABELS[tag_id]
            if tag == 'O':
                out['reasons'].append('unresolved_character')
                continue
            role = tag[2:]
            if tag.startswith('B-') or not spans or spans[-1]['role'] != role:
                spans.append({'role': role, 'start': i, 'end': i + 1, 'text': normalized[i]})
            else:
                spans[-1]['end'] = i + 1
                spans[-1]['text'] += normalized[i]
        counts = Counter(s['role'] for s in spans)
        if counts['actor'] != 1 or counts['predicate'] != 1 or any(v > 1 for v in counts.values()):
            out['reasons'].append('unsupported_role_structure')
        if counts['negation'] and counts['modal']:
            out['reasons'].append('operator_scope_requires_review')
        if tuple(s['role'] for s in spans) not in self.allowed_orders:
            out['reasons'].append('unseen_role_order')
        if any(s['text'] not in self.allowed_values.get(s['role'], set()) for s in spans):
            out['reasons'].append('outside_training_role_support')
        roles = {s['role']: s['text'] for s in spans}
        support = self.argument_support.get(roles.get('predicate'), {})
        if any(roles[r] not in support.get(r, []) for r in ['patient', 'goal'] if r in roles):
            out['reasons'].append('outside_training_argument_support')
        if out['reasons']:
            return out
        out['status'], out['spans'] = 'parsed', spans
        out['roles'] = {s['role']: s['text'] for s in spans}
        out['meaning_key'] = hashlib.sha256(json.dumps(out['roles'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        # Scores of this perceptron are not calibrated probabilities.
        out['confidence'] = None
        return out


def evaluate(parser, rows):
    errors, matched, parsed = [], 0, 0
    slots = Counter()
    totals = Counter()
    start = time.perf_counter()
    for row in rows:
        prediction = parser.predict(row['text'])
        expected = row['roles']
        ok = prediction['status'] == 'abstained' if expected is None else prediction['status'] == 'parsed' and prediction['roles'] == expected
        matched += ok
        parsed += prediction['status'] == 'parsed'
        for role, value in (expected or {}).items():
            totals[role] += 1
            slots[role] += prediction['roles'].get(role) == value
        if not ok:
            errors.append({'text': row['text'], 'expected': expected, 'actual': prediction})
    return {'examples': len(rows), 'exact_matches': matched, 'exact_accuracy': matched / max(1, len(rows)),
            'parsed': parsed, 'abstained': len(rows) - parsed,
            'per_slot_accuracy': {r: slots[r] / n for r, n in totals.items()},
            'elapsed_seconds': time.perf_counter() - start, 'errors': errors}


def train_run(output, count=5000, epochs=12, seed=17):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = corpus(count, seed)
    partitions = {split: [r for r in rows if r['split'] == split] for split in ['train', 'validation', 'test']}
    for split, values in partitions.items():
        (output / f'{split}.jsonl').write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))
    training = partitions['train']
    names = sorted({f for row in training for i in range(len(row['text'])) for f in features(row['text'], i)})
    lookup = {f: i for i, f in enumerate(names)}
    encoded = [([[lookup[f] for f in features(r['text'], i)] for i in range(len(r['text']))], r['tags']) for r in training]
    weights = np.zeros((len(names), len(LABELS)))
    transitions = np.zeros((len(LABELS), len(LABELS)))
    total_w, total_t = weights.copy(), transitions.copy()
    stamp_w, stamp_t = weights.copy(), transitions.copy()
    rng = random.Random(seed)
    steps, history = 0, []
    started = time.perf_counter()
    for epoch in range(epochs):
        order = list(range(len(encoded)))
        rng.shuffle(order)
        mistakes = 0
        for index in order:
            steps += 1
            x, y = encoded[index]
            pred = decode(x, weights, transitions)
            if pred == y:
                continue
            mistakes += 1
            for ids, gold, guess in zip(x, y, pred):
                if gold != guess:
                    for label, delta in [(gold, 1), (guess, -1)]:
                        total_w[ids, label] += (steps - stamp_w[ids, label]) * weights[ids, label]
                        stamp_w[ids, label] = steps
                        weights[ids, label] += delta
            for seq, delta in [(y, 1), (pred, -1)]:
                for previous, current in zip(seq, seq[1:]):
                    total_t[previous, current] += (steps - stamp_t[previous, current]) * transitions[previous, current]
                    stamp_t[previous, current] = steps
                    transitions[previous, current] += delta
        history.append({'epoch': epoch + 1, 'mistaken_sequences': mistakes})
    weights = (total_w + (steps - stamp_w) * weights) / max(1, steps)
    transitions = (total_t + (steps - stamp_t) * transitions) / max(1, steps)
    np.savez_compressed(output / 'weights.npz', weights=weights, transitions=transitions)
    role_values = {role: sorted({r['roles'][role] for r in training if role in r['roles']}) for role in ROLES}
    orders = sorted({tuple(LABELS[t][2:] for i, t in enumerate(r['tags']) if LABELS[t].startswith('B-')) for r in training})
    argument_support = {}
    for row in training:
        predicate = row['roles']['predicate']
        support = argument_support.setdefault(predicate, {})
        for role in ['patient', 'goal']:
            if role in row['roles']:
                support.setdefault(role, set()).add(row['roles'][role])
    argument_support = {p: {r: sorted(v) for r, v in roles.items()} for p, roles in argument_support.items()}
    identity = hashlib.sha256((digest(output / 'weights.npz') + json.dumps(argument_support, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
    metadata = {'schema': SCHEMA, 'model_id': 'csl-chinese-roles-' + identity[:16],
                'argument_support': argument_support,
                'created_at': datetime.now(timezone.utc).isoformat(), 'features': names, 'labels': LABELS,
                'characters': ''.join(sorted({c for r in training for c in r['text']})),
                'role_orders': orders, 'role_values': role_values,
                'weights_sha256': digest(output / 'weights.npz'), 'algorithm': 'averaged_structured_perceptron',
                'seed': seed, 'epochs': epochs, 'label_source': 'assistant_synthetic_chinese',
                'csl_translation_trained': False, 'human_approved': False, 'model_training_ready': False,
                'scope': 'bounded Chinese role extraction, no CSL realization or video recognition',
                'split_policy': 'participant/predicate/object group disjoint; challenge texts excluded from all generated splits'}
    write_json(output / 'model.json', metadata)
    parser = load_model(output)
    metrics = {split: evaluate(parser, values) for split, values in partitions.items() if split != 'train'}
    metrics['challenge'] = evaluate(parser, [{'text': text, 'roles': roles} for text, roles in CHALLENGE])
    metrics['training'] = {'examples': len(training), 'history': history, 'steps': steps,
                           'elapsed_seconds': time.perf_counter() - started}
    metrics['limitations'] = ['Synthetic Chinese supervision only; no real-world CSL accuracy is estimated.',
                              'No signer-independent evaluation; no source video was used to update these weights.',
                              'Role support and scope guards abstain; no calibrated confidence or motion generation.']
    write_json(output / 'evaluation.json', metrics)
    write_json(output / 'provenance.json', {'tool_sha256': digest(__file__), 'numpy': np.__version__,
               'inputs': {f'{s}.jsonl': digest(output / f'{s}.jsonl') for s in partitions},
               'model_sha256': digest(output / 'model.json'), 'label_source': 'assistant_synthetic_chinese',
               'candidate_video_labels_used': False, 'existing_checkpoints_modified': False})
    (output / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in sorted(output.iterdir()) if p.is_file()))
    return metrics


def load_model(root):
    root = Path(root)
    metadata_path = root / 'model.json'
    if metadata_path.stat().st_size > 5_000_000:
        raise ValueError('Model metadata size exceeds limit')
    meta = json.loads(metadata_path.read_text())
    if meta.get('schema') != SCHEMA or meta.get('labels') != LABELS:
        raise ValueError('Unsupported model schema')
    path = root / 'weights.npz'
    if path.stat().st_size > 30_000_000 or digest(path) != meta['weights_sha256']:
        raise ValueError('Model weights digest mismatch or excessive size')
    with np.load(path, allow_pickle=False) as archive:
        weights, transitions = archive['weights'], archive['transitions']
    if (weights.shape != (len(meta['features']), len(LABELS)) or transitions.shape != MASK.shape
            or not np.isfinite(weights).all() or not np.isfinite(transitions).all()):
        raise ValueError('Invalid model weights shape/values')
    return Parser(meta, weights, transitions)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--examples', type=int, default=5000)
    ap.add_argument('--epochs', type=int, default=12)
    ap.add_argument('--seed', type=int, default=17)
    args = ap.parse_args()
    if not 500 <= args.examples <= 30000 or not 1 <= args.epochs <= 40:
        ap.error('examples must be 500..30000; epochs 1..40')
    report = train_run(args.output, args.examples, args.epochs, args.seed)
    print(json.dumps({key: {k: v for k, v in report[key].items() if k != 'errors'} for key in ['validation', 'test', 'challenge']}, ensure_ascii=False))
