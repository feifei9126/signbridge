"""GPU-only bounded Chinese kind/BIO learning; explicit composition, no CSL output.

Frozen verified Chinese BERT features feed a small trainable BiGRU and two heads.
Training uses only train/dev. Already-consumed diagnostic contrasts stay outside
training, and are evaluated after checkpoint selection, never for selection.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import re
import sys


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


s = load('sign-csl-semantic-round.py')
t, u = s.g.t, s.u
SCHEMA = 'signbridge-typed-chinese-semantics-v1'
GATES = {**s.GATES, 'independent_test': False}
KINDS = ['reject', 'entity', 'event']
SETTINGS = {'seed': 20261106, 'epochs': 18, 'batch_size': 128, 'learning_rate': .001,
            'weight_decay': .01, 'clip_grad': 1., 'encoder_frozen': True,
            'sampling': 'inverse-kind-frequency sampling with replacement; len(train) examples/epoch; no extra unique data',
            'head_width': 128, 'dropout': .1, 'selection': 'minimum dev wrong acceptance, then maximum correct coverage, earliest tie'}
OPERATORS = [[], [('negation', '不')], [('negation', '没')], [('modal', '想')], [('modal', '能')],
             [('modal', '可以')], [('negation', '不'), ('modal', '想')], [('modal', '想'), ('negation', '不')],
             [('negation', '不'), ('modal', '能')], [('modal', '可以'), ('negation', '不')]]


def source_hashes():
    return {**s.upper.source_hashes(), Path(s.__file__).name: u.base.sha(Path(s.__file__)),
            Path(s.contrast.__file__).name: u.base.sha(Path(s.contrast.__file__)),
            Path(s.contrast.scope.__file__).name: u.base.sha(Path(s.contrast.scope.__file__)),
            Path(s.base.__file__).name: u.base.sha(Path(s.base.__file__)),
            Path(__file__).name: u.base.sha(Path(__file__))}


def sample(parts, group, split, family, text=None):
    spans, tags, roles = [], [], {}
    if parts is None:
        kind, operators, tags, roles = 'reject', None, None, None
    else:
        text = ''
        for role, value in parts:
            start = len(text); text += value
            spans.append({'role': role, 'text': value, 'start': start, 'end': len(text)})
            tags += [s.base.LABELS.index('B-' + role)] + [s.base.LABELS.index('I-' + role)] * (len(value) - 1)
            roles[role] = value
        kind = 'event' if 'predicate' in roles else 'entity'
        operators = [role + ':' + word for role, word in parts if role in ('negation', 'modal')]
    return {'id': 'typed-' + hashlib.sha256(text.encode()).hexdigest()[:20], 'text': text,
            'partition': split, 'split_group': group, 'template_group': family + '_' + split,
            'expected_kind': kind, 'expected_roles': roles, 'expected_operators': operators,
            'tags': tags, 'spans': spans, 'pair_id': None, 'pair_relation': 'different',
            'label_source': 'assistant_synthetic_chinese', 'human_approved': False, 'csl_supervision': False}


def corpus(reserved, reserved_train=()):
    result, seen = {'train': [], 'dev': []}, {}
    def add(parts, group, family, text=None, split=None):
        split = split or ('dev' if int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 5 == 0 else 'train')
        row = sample(parts, group, split, family, text)
        normalized = s.normalize(row['text'])
        if normalized in reserved: return
        if split == 'train' and normalized in reserved_train: return
        signature = (row['expected_kind'], row['expected_roles'], row['expected_operators'])
        if normalized in seen:
            if seen[normalized] != signature: raise ValueError('Synthetic ambiguous supervision collision: ' + normalized)
            return
        seen[normalized] = signature
        result[split].append(row)
    for actor in s.PEOPLE:
        add([('actor', actor)], 'entity|' + actor, 'entity', split='dev' if len(actor) > 1 else 'train')
        events = [('工作', None), ('学习', None), ('休息', None)]
        events += [(p, ('goal', goal)) for p in ['去', '来', '回'] for goal in ['家', '学校', '医院']]
        events += [(p, ('patient', person)) for p in ['帮', '帮助', '等', '告诉'] for person in s.PEOPLE if person != actor]
        events += [(p, ('patient', obj)) for p, objects in [('买', ['书', '水', '东西']), ('看', ['书', '电影']), ('喝', ['水', '茶', '牛奶'])] for obj in objects]
        events += [('去', None), ('来', None)]
        for predicate, argument in events:
            group = '|'.join([actor, predicate, argument[1] if argument else ''])
            ending = [('predicate', predicate)] + ([argument] if argument else [])
            for time_parts, placement in [([], 'none'), ([('time', '今天')], 'front'), ([('time', '明天')], 'after')]:
                prefix = time_parts + [('actor', actor)] if placement == 'front' else [('actor', actor)] + time_parts
                for operators in OPERATORS:
                    add(prefix + operators + ending, group, 'compound_scope' if len(operators) == 2 else 'simple_event')
                for aspect in ['了', '过']:
                    add(prefix + [('predicate', predicate), ('aspect', aspect)] + ([argument] if argument else []), group, 'aspect')
            for op in ['不不', '想想', '不想不能']:
                add(None, group, 'duplicate_operator', text=actor + op + predicate + (argument[1] if argument else ''))
            add(None, group, 'multi_clause', text=actor + predicate + (argument[1] if argument else '') + '然后你学习')
            add(None, group, 'double_time', text=actor + '今天明天' + predicate + (argument[1] if argument else ''))
        for word in ['工作', '年龄', '时间', '钱', '能力', '办法', '机会']:
            group = 'ambiguous-possession|' + actor + '|' + word
            add(None, group, 'ambiguous_possession', text=actor + '没有' + word)
            add(None, group, 'ambiguous_possession', text='今天' + actor + '没有' + word)
        for predicate, objects in [('喝', ['书', '电影', '学校']), ('买', ['医院', '学校']), ('学习', ['牛奶', '水'])]:
            for obj in objects:
                add(None, 'unsupported-argument|' + actor + '|' + predicate + '|' + obj, 'unsupported_argument', text=actor + predicate + obj)
    validate_data(result, reserved, reserved_train)
    return result


def validate_data(data, reserved, reserved_train=()):
    s.validate_cases(data['train'] + data['dev'])
    if {r['split_group'] for r in data['train']} & {r['split_group'] for r in data['dev']}:
        raise ValueError('Participant/predicate/argument group crosses train/dev')
    if {s.normalize(r['text']) for r in data['train']} & set(reserved_train): raise ValueError('Prior development text entered train')
    for rows in data.values():
        if {r['expected_kind'] for r in rows} != set(KINDS): raise ValueError('Missing entity/event/reject supervision')
        orders = {tuple(r['expected_operators']) for r in rows if r['expected_operators']}
        if not {('negation:不', 'modal:想'), ('modal:想', 'negation:不')} <= orders:
            raise ValueError('Missing opposite compound scope supervision')
        if any(s.normalize(r['text']) in reserved for r in rows): raise ValueError('Reserved diagnostic text entered training/dev')


def interpret(text, tags, kind):
    result = {**GATES, 'status': 'abstained', 'kind': kind, 'roles': {}, 'spans': [], 'operators': [],
              'model_kind': 'learned_BiGRU_kind_and_BIO_with_explicit_graph_composition', 'confidence': None, 'reasons': []}
    if (kind not in KINDS or not isinstance(tags, list) or len(tags) != len(text)
            or any(type(i) is not int or not 0 <= i < len(s.base.LABELS) for i in tags)):
        raise ValueError('Invalid typed head output/BIO evidence')
    if kind == 'reject': result['reasons'] = ['learned_outside_contract']; return result
    spans = []
    for i, tag_id in enumerate(tags):
        if type(tag_id) is not int or not 0 <= tag_id < len(s.base.LABELS): raise ValueError('Invalid BIO label ID')
        tag = s.base.LABELS[tag_id]
        if tag == 'O': result['reasons'].append('unresolved_character'); continue
        role = tag[2:]
        if tag.startswith('B-'):
            spans.append({'role': role, 'text': text[i], 'start': i, 'end': i + 1})
        elif not spans or spans[-1]['role'] != role or spans[-1]['end'] != i:
            result['reasons'].append('illegal_BIO_continuation')
        else:
            spans[-1]['text'] += text[i]; spans[-1]['end'] = i + 1
    counts = Counter(x['role'] for x in spans)
    if any(v > 1 for v in counts.values()): result['reasons'].append('duplicate_semantic_role')
    if kind == 'entity' and (counts != Counter({'actor': 1})): result['reasons'].append('entity_kind_role_mismatch')
    if kind == 'event' and (counts['actor'] != 1 or counts['predicate'] != 1): result['reasons'].append('event_kind_role_mismatch')
    if not result['reasons'] and not supported_graph(spans, kind): result['reasons'].append('explicit_role_value_argument_order_contract')
    if result['reasons']: result['reasons'] = sorted(set(result['reasons'])); return result
    roles = {x['role']: x['text'] for x in spans}
    graph = {'type': 'entity', 'roles': roles} if kind == 'entity' else s.contrast.scope.event_graph(roles, spans)
    result.update(status='parsed', roles=roles, spans=spans, event_graph=graph,
                  event_key=s.contrast.scope.graph_key(graph), operators=[x['role'] + ':' + x['text'] for x in spans if x['role'] in ('negation', 'modal')])
    return result


def supported_graph(spans, kind):
    """Validate learned roles only; never reparses text or supplies missing roles.

    An explicit finite Chinese contract is a guard, not evidence of learned CSL.
    """
    roles = {x['role']: x['text'] for x in spans}; order = [x['role'] for x in spans]
    if roles.get('actor') not in s.PEOPLE: return False
    if kind == 'entity': return order == ['actor']
    predicate = roles.get('predicate')
    patients = {'帮': s.PEOPLE, '帮助': s.PEOPLE, '等': s.PEOPLE, '告诉': s.PEOPLE,
                '买': ['书', '水', '东西'], '看': ['书', '电影'], '喝': ['水', '茶', '牛奶']}
    predicates = set(patients) | {'工作', '学习', '休息', '去', '来', '回'}
    if predicate not in predicates: return False
    if 'patient' in roles and roles['patient'] not in patients.get(predicate, []): return False
    if 'goal' in roles and (predicate not in ['去', '来', '回'] or roles['goal'] not in ['家', '学校', '医院']): return False
    if 'goal' in roles and 'patient' in roles: return False
    if roles.get('time') not in (None, '今天', '明天'): return False
    if roles.get('aspect') not in (None, '了', '过'): return False
    if set(roles) - {'actor', 'predicate', 'patient', 'goal', 'time', 'aspect', 'negation', 'modal'}: return False
    operators = [(x['role'], x['text']) for x in spans if x['role'] in ('negation', 'modal')]
    if operators not in OPERATORS or operators and 'aspect' in roles: return False
    prefix = ['actor']
    if 'time' in roles:
        prefix = ['time', 'actor'] if order[0] == 'time' else ['actor', 'time']
    expected = prefix + [role for role, _ in operators] + ['predicate']
    if 'aspect' in roles: expected += ['aspect']
    if 'patient' in roles: expected += ['patient']
    if 'goal' in roles: expected += ['goal']
    return order == expected


def make_model():
    import torch
    from torch import nn
    class Typed(nn.Module):
        def __init__(self):
            super().__init__(); width = SETTINGS['head_width']
            self.projection = nn.Sequential(nn.Linear(768, width), nn.LayerNorm(width), nn.GELU())
            self.gru = nn.GRU(width, width, batch_first=True, bidirectional=True)
            self.dropout = nn.Dropout(SETTINGS['dropout'])
            self.kind = nn.Linear(width * 2, len(KINDS))
            self.bio = nn.Linear(width * 2, len(s.base.LABELS))
        def forward(self, features, lengths):
            embedded = self.projection(features)
            packed = nn.utils.rnn.pack_padded_sequence(embedded, lengths.cpu(), batch_first=True, enforce_sorted=False)
            packed, _ = self.gru(packed)
            hidden, _ = nn.utils.rnn.pad_packed_sequence(packed, batch_first=True, total_length=features.size(1))
            mask = torch.arange(features.size(1), device=features.device)[None] < lengths.to(features.device)[:, None]
            pooled = (hidden * mask[:, :, None]).sum(1) / lengths.to(features.device)[:, None]
            return self.kind(self.dropout(pooled)), self.bio(self.dropout(hidden))
    return Typed()


def restore(model, state):
    import torch
    expected = model.state_dict()
    if (not isinstance(state, dict) or set(state) != set(expected) or any(not isinstance(v, torch.Tensor)
            or v.shape != expected[k].shape or v.dtype != expected[k].dtype or not torch.isfinite(v).all() for k, v in state.items())):
        raise ValueError('Typed checkpoint keys/shapes/dtypes/finite contract differs')
    model.load_state_dict(state, strict=True)


def quality_gates(metrics):
    threshold = lambda key: isinstance(metrics.get(key), (float, int)) and math.isfinite(metrics[key]) and metrics[key] >= .98
    return {'supported_correct_at_least_98pct': threshold('supported_correct_rate'),
            'no_wrong_acceptance': metrics['wrong_accepts'] == 0,
            'no_unsupported_false_acceptance': metrics['unsupported_false_accepts'] == 0,
            'all_entity_correct': metrics['entity_correct_rate'] == 1.,
            'scope_correct_at_least_98pct': threshold('scope_correct_rate'),
            'all_complete_pairs_correct': metrics['complete_pairs_pass_rate'] == 1.}


def prepare(previous, legacy_fixture, encoder_root, output):
    previous, legacy_fixture, encoder_root, output = map(u.safe_path, [previous, legacy_fixture, encoder_root, output])
    u.new_output(output, [previous, legacy_fixture, encoder_root])
    manifest, used = u.read_manifest(previous)
    frozen_content = u.checked(previous, 'frozen-cases.json', manifest, used)
    fixture = json.loads(frozen_content); s.validate_cases(fixture['rows'])
    if (fixture.get('schema') != s.SCHEMA or fixture.get('frozen_before_current_round_evaluation') is not True
            or any(fixture.get(k) != value for k, value in s.GATES.items())):
        raise ValueError('Previous diagnostic fixture provenance differs')
    legacy = json.loads(legacy_fixture.read_text())
    # Prior dev is train-forbidden, prior challenge/legacy forbidden in both.
    reserved = {s.normalize(r['text']) for r in fixture['rows'] if r['partition'] == 'challenge'}
    reserved |= {s.normalize(r['text']) for r in legacy['rows']}
    reserved_train = {s.normalize(r['text']) for r in fixture['rows'] if r['partition'] == 'dev'}
    data = corpus(reserved, reserved_train)
    # Bare plural dev examples may overlap prior dev; dev is already development.
    old_train_overlap = [r['id'] for r in data['train'] if r['text'] in {x['text'] for x in fixture['rows'] if x['partition'] == 'train'}]
    encoder_hashes = t.check_encoder(encoder_root)
    output.mkdir(parents=True)
    for split, rows in data.items():
        (output / (split + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    (output / 'diagnostic.json').write_bytes(frozen_content)
    (output / 'legacy-diagnostic.json').write_bytes(legacy_fixture.read_bytes())
    u.base.write_json(output / 'reserved-texts.json', sorted(reserved))
    u.base.write_json(output / 'train-reserved-texts.json', sorted(reserved_train))
    plan = {**GATES, 'schema': SCHEMA, 'status': 'prepared', 'settings': SETTINGS, 'labels': s.base.LABELS, 'kinds': KINDS,
            'counts': {k: len(v) for k, v in data.items()}, 'encoder_inputs': encoder_hashes,
            'source_hashes': source_hashes(), 'previous_fixture_sha256': used['frozen-cases.json'],
            'legacy_fixture_sha256': u.base.sha(legacy_fixture), 'previous_train_reused_ids': old_train_overlap,
            'group_policy': 'all time/aspect/operator variants of actor/predicate/argument tuple stay together; entity singular train/plural dev',
            'diagnostic_policy': 'Prior developer-authored dev/challenge, already consumed. Evaluate only after train/dev selection; no independent generalization claim.',
            'feature_contract': 'one pinned BERT token per normalized Chinese character, checked against tokenize; features frozen and no targets supplied to encoder',
            'diagnostic_loading': 'Diagnostic JSON is parsed only for frozen target/reservation verification; no diagnostic evaluation/loss/checkpoint selection during training.',
            'readiness': {'typed_trainer_implemented': True, 'compound_scope_train_dev_present': True, 'reject_train_dev_present': True},
            'limits': ['Synthetic Chinese supervision only; no Gloss/CSL/motion targets.', 'Finite known lexicon and single-event contract; no broad natural-language guarantee.',
                       'No H or CE-CSL test/source/video/pose inputs.', 'Explicit BIO validation and graph composition do not count as learned CSL realization.']}
    u.base.write_json(output / 'plan.json', plan); u.seal(output)
    return plan


def read_prepared(root):
    root = u.safe_path(root); manifest, used = u.read_manifest(root)
    plan = json.loads(u.checked(root, 'plan.json', manifest, used))
    reserved = set(json.loads(u.checked(root, 'reserved-texts.json', manifest, used)))
    reserved_train = set(json.loads(u.checked(root, 'train-reserved-texts.json', manifest, used)))
    legacy = json.loads(u.checked(root, 'legacy-diagnostic.json', manifest, used))
    frozen = u.checked(root, 'diagnostic.json', manifest, used)
    if (plan.get('schema') != SCHEMA or plan.get('settings') != SETTINGS or plan.get('labels') != s.base.LABELS
            or plan.get('kinds') != KINDS or plan.get('source_hashes') != source_hashes()
            or used['diagnostic.json'] != plan.get('previous_fixture_sha256')
            or used['legacy-diagnostic.json'] != plan.get('legacy_fixture_sha256')
            or any(plan.get(k) != v for k, v in GATES.items())):
        raise ValueError('Typed preparation contract differs')
    rows = json.loads(frozen)['rows']; s.validate_cases(rows)
    if not {s.normalize(r['text']) for r in rows if r['partition'] == 'challenge'} <= reserved:
        raise ValueError('Diagnostic reserved text missing')
    if (not {s.normalize(r['text']) for r in legacy['rows']} <= reserved
            or reserved_train != {s.normalize(r['text']) for r in rows if r['partition'] == 'dev'}):
        raise ValueError('Legacy/prior dev reservation binding differs')
    data = {split: [json.loads(x) for x in u.checked(root, split + '.jsonl', manifest, used).decode().splitlines()]
            for split in ['train', 'dev']}
    validate_data(data, reserved, reserved_train)
    if data != corpus(reserved, reserved_train) or {k: len(v) for k, v in data.items()} != plan['counts']:
        raise ValueError('Synthetic targets differ from frozen generator/settings')
    for row in legacy['rows']:
        copied = dict(row, id='legacy-' + row['id'], pair_id='legacy-' + row['pair_id'] if row.get('pair_id') else None,
                      expected_kind='reject' if row['expected_roles'] is None else 'event',
                      partition='legacy_diagnostic')
        rows.append(copied)
    return data, rows, plan, used


def char_ids(text, tokenizer):
    # No truncation, OOV replacement, punctuation erasure or multi-token collapse.
    if (not isinstance(text, str) or not 1 <= len(text) <= 64 or
            any(not ('\u3400' <= c <= '\u9fff') for c in text)):
        raise ValueError('outside_single_clause_Chinese_character_contract')
    tokens = tokenizer.tokenize(text)
    if tokens != list(text): raise ValueError('unaligned_or_unknown_BERT_tokens')
    ids = tokenizer.convert_tokens_to_ids(tokens)
    if tokenizer.unk_token_id in ids: raise ValueError('unknown_encoder_character')
    return ids


def features(encoder, tokenizer, rows, device, batch_size=128):
    import torch
    encoder.to(device).eval(); result = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            chunk = rows[start:start + batch_size]
            ids = [[tokenizer.cls_token_id, *char_ids(r['text'], tokenizer), tokenizer.sep_token_id] for r in chunk]
            longest = max(map(len, ids))
            source = torch.tensor([x + [0] * (longest - len(x)) for x in ids], device=device)
            hidden = encoder(input_ids=source, attention_mask=source.ne(0), return_dict=True).last_hidden_state
            if not torch.isfinite(hidden).all(): raise ValueError('Nonfinite encoder features')
            result.extend(hidden[i, 1:len(row['text']) + 1].detach().cpu().clone() for i, row in enumerate(chunk))
    return result


def batch(rows, cached, indices, device):
    import torch
    lengths = torch.tensor([len(rows[i]['text']) for i in indices], dtype=torch.long)
    padded = torch.nn.utils.rnn.pad_sequence([cached[i] for i in indices], batch_first=True).to(device)
    target = torch.full((len(indices), int(lengths.max())), -100, dtype=torch.long, device=device)
    for j, i in enumerate(indices):
        if rows[i]['tags'] is not None: target[j, :len(rows[i]['tags'])] = torch.tensor(rows[i]['tags'], device=device)
    kinds = torch.tensor([KINDS.index(rows[i]['expected_kind']) for i in indices], device=device)
    return padded, lengths, kinds, target


def predict_cached(model, rows, cached, device):
    import torch
    model.eval(); outputs = []
    with torch.inference_mode():
        for start in range(0, len(rows), SETTINGS['batch_size']):
            indices = list(range(start, min(len(rows), start + SETTINGS['batch_size'])))
            x, lengths, _, _ = batch(rows, cached, indices, device)
            kind_logits, tag_logits = model(x, lengths)
            if not torch.isfinite(kind_logits).all() or not torch.isfinite(tag_logits).all(): raise ValueError('Nonfinite typed prediction logits')
            kinds, tags = kind_logits.argmax(-1).cpu().tolist(), tag_logits.argmax(-1).cpu().tolist()
            for index, kind, labels in zip(indices, kinds, tags):
                text = rows[index]['text']; output = interpret(text, labels[:len(text)], KINDS[kind])
                outputs.append({'id': rows[index]['id'], 'text': text, 'raw_kind': KINDS[kind], 'raw_BIO': labels[:len(text)], 'prediction': output})
    return outputs


def metrics(rows, outputs):
    validate_predictions(rows, outputs)
    if len(rows) != len(outputs) or any(r['id'] != p['id'] or r['text'] != p['text'] for r, p in zip(rows, outputs)):
        raise ValueError('Typed prediction identity/order mismatch')
    correct, accepted, wrong, supported, negative, false, entity, entity_ok, scope, scope_ok = (0,) * 10
    by_id = {}; groups = defaultdict(list)
    for row, output in zip(rows, outputs):
        p = output['prediction']; parsed = p['status'] == 'parsed'; ok = (parsed and row['expected_kind'] != 'reject'
            and p['kind'] == row['expected_kind'] and p['roles'] == row['expected_roles'] and p['operators'] == row['expected_operators'])
        correct += ok; accepted += parsed; supported += row['expected_kind'] != 'reject'; negative += row['expected_kind'] == 'reject'
        wrong += parsed and not ok; false += parsed and row['expected_kind'] == 'reject'
        entity += row['expected_kind'] == 'entity'; entity_ok += ok and row['expected_kind'] == 'entity'
        is_scope = row['expected_operators'] is not None and len(row['expected_operators']) >= 2
        scope += is_scope; scope_ok += ok and is_scope
        by_id[row['id']] = (ok, p.get('event_key'))
        if row.get('pair_id'): groups[row['pair_id']].append(row)
    pairs = []
    for pair, group in groups.items():
        if len(group) != 2: continue
        a, b = [by_id[r['id']] for r in group]
        pairs.append({'id': pair, 'passed': a[0] and b[0] and ((a[1] == b[1]) == (group[0]['pair_relation'] == 'same'))})
    return {'samples': len(rows), 'supported': supported, 'supported_correct': correct,
            'supported_correct_rate': correct / supported if supported else None, 'accepted': accepted,
            'selective_accuracy': correct / accepted if accepted else None, 'wrong_accepts': wrong,
            'unsupported': negative, 'unsupported_false_accepts': false, 'correct_rejections': negative - false,
            'entity_cases': entity, 'entity_correct': entity_ok, 'entity_correct_rate': entity_ok / entity if entity else None,
            'scope_cases': scope, 'scope_correct': scope_ok, 'scope_correct_rate': scope_ok / scope if scope else None,
            'complete_pairs': len(pairs), 'complete_pairs_passed': sum(p['passed'] for p in pairs),
            'complete_pairs_pass_rate': sum(p['passed'] for p in pairs) / len(pairs) if pairs else None,
            'pairs': pairs}


def validate_predictions(rows, outputs):
    if (len(rows) != len(outputs) or len({p.get('id') for p in outputs}) != len(outputs)
            or any(r['id'] != p.get('id') or r['text'] != p.get('text') for r, p in zip(rows, outputs))):
        raise ValueError('Typed prediction identities/text differ')
    for p in outputs:
        if p.get('prediction') != interpret(p['text'], p.get('raw_BIO', []), p.get('raw_kind')):
            raise ValueError('Typed prediction differs from raw learned outputs')


def input_text(text):
    if not isinstance(text, str) or len(text) > 200: raise ValueError('invalid_or_overlong_input')
    text = text.strip().rstrip('。.!！?？').strip()
    if not 1 <= len(text) <= 64 or any(not ('\u3400' <= c <= '\u9fff') for c in text):
        raise ValueError('outside_single_clause_Chinese_character_contract')
    return text


def train(prepared, encoder_root, output):
    import torch
    device = u.cuda_device('cuda'); prepared, encoder_root, output = map(u.safe_path, [prepared, encoder_root, output])
    u.new_output(output, [prepared, encoder_root]); data, _, plan, inputs = read_prepared(prepared)
    torch.set_num_threads(4); random.seed(SETTINGS['seed']); torch.manual_seed(SETTINGS['seed']); torch.cuda.manual_seed_all(SETTINGS['seed'])
    encoder, tokenizer, hashes, _ = t.load_encoder(encoder_root)
    if hashes != plan['encoder_inputs']: raise ValueError('Typed encoder assets differ')
    frozen = u.base.weights_hash(encoder)
    output.mkdir(parents=True); (output / 'checkpoints').mkdir()
    report = {**GATES, 'training_started': True, 'weights_updated': True, 'schema': SCHEMA, 'status': 'running',
              'plan': plan, 'inputs': inputs, 'history': [], 'encoder_initial_hash': frozen,
              'runtime': {'python': sys.version, 'torch': str(torch.__version__), 'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(device)},
              'source_hashes': source_hashes(), 'diagnostic_evaluated_during_selection': False}
    try:
        cached = {split: features(encoder, tokenizer, rows, device) for split, rows in data.items()}
        if u.base.weights_hash(encoder) != frozen: raise ValueError('Frozen encoder features changed parameters')
        del encoder; torch.cuda.empty_cache()
        model = make_model().to(device); initial = t.state_hash(model.state_dict())
        optimizer = torch.optim.AdamW(model.parameters(), lr=SETTINGS['learning_rate'], weight_decay=SETTINGS['weight_decay'])
        best, steps = None, 0
        for epoch in range(1, SETTINGS['epochs'] + 1):
            model.train()
            counts = Counter(r['expected_kind'] for r in data['train'])
            order = random.choices(list(range(len(data['train']))), weights=[1. / counts[r['expected_kind']] for r in data['train']], k=len(data['train']))
            losses = []
            for start in range(0, len(order), SETTINGS['batch_size']):
                indices = order[start:start + SETTINGS['batch_size']]
                x, lengths, kind, target = batch(data['train'], cached['train'], indices, device)
                optimizer.zero_grad(set_to_none=True); kl, tl = model(x, lengths)
                kind_loss = torch.nn.functional.cross_entropy(kl, kind)
                token_loss = torch.nn.functional.cross_entropy(tl.flatten(0, 1), target.reshape(-1), ignore_index=-100) if bool(target.ne(-100).any()) else tl.sum() * 0.
                loss = kind_loss + token_loss
                if not torch.isfinite(loss): raise ValueError('Nonfinite typed loss')
                loss.backward()
                if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()): raise ValueError('Nonfinite typed gradient')
                torch.nn.utils.clip_grad_norm_(model.parameters(), SETTINGS['clip_grad']); optimizer.step(); steps += 1; losses.append(float(loss.detach()))
            predictions = predict_cached(model, data['dev'], cached['dev'], device); measured = metrics(data['dev'], predictions)
            key = (measured['wrong_accepts'], -measured['supported_correct'], -measured['correct_rejections'])
            if best is None or key < best:
                best = key; report['selected_epoch'] = epoch; report['selected_dev_metrics'] = measured
                torch.save({k: v.detach().cpu() for k, v in model.state_dict().items()}, output / 'checkpoints/best.pt')
                u.base.write_json(output / 'dev-predictions.json', predictions)
            torch.save({'model': {k: v.detach().cpu() for k, v in model.state_dict().items()}, 'optimizer': optimizer.state_dict(),
                        'epoch': epoch, 'steps': steps, 'python_rng': random.getstate(), 'torch_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state_all()},
                       output / 'checkpoints/recovery-last.pt')
            item = {'epoch': epoch, 'steps': steps, 'train_loss': sum(losses) / len(losses), 'dev': measured}
            report['history'].append(item); report.update(epochs_completed=epoch, optimizer_steps=steps)
            u.base.write_json(output / 'report.json', report); print(json.dumps(item), flush=True)
        expected_steps = ((len(data['train']) + SETTINGS['batch_size'] - 1) // SETTINGS['batch_size']) * SETTINGS['epochs']
        if steps != expected_steps: raise ValueError('Typed update budget differs')
        restore(model, torch.load(output / 'checkpoints/best.pt', map_location='cpu', weights_only=True))
        replay = predict_cached(model, data['dev'], cached['dev'], device)
        if replay != json.loads((output / 'dev-predictions.json').read_text()): raise ValueError('Typed selected checkpoint replay differs')
        report.update(status='completed', finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      checkpoint='checkpoints/best.pt', checkpoint_sha256=u.base.sha(output / 'checkpoints/best.pt'),
                      selected_parameter_hash=t.state_hash(model.state_dict()), initial_parameter_hash=initial,
                      encoder_final_hash=frozen, encoder_unchanged=True, encoder_assets_unchanged=t.check_encoder(encoder_root) == hashes)
        u.base.write_json(output / 'report.json', report); u.seal(output)
    except Exception as error:
        report.update(status='failed', error=repr(error)); u.base.write_json(output / 'report.json', report); u.seal(output); raise
    return report


def read_result(prepared, results):
    data, diagnostic, plan, inputs = read_prepared(prepared)
    results = u.safe_path(results); manifest, used = u.read_manifest(results)
    report = json.loads(u.checked(results, 'report.json', manifest, used))
    expected_steps = ((len(data['train']) + SETTINGS['batch_size'] - 1) // SETTINGS['batch_size']) * SETTINGS['epochs']
    if (report.get('schema') != SCHEMA or report.get('status') != 'completed' or report.get('plan') != plan
            or report.get('inputs') != inputs or report.get('source_hashes') != source_hashes()
            or report.get('epochs_completed') != SETTINGS['epochs'] or report.get('optimizer_steps') != expected_steps
            or len(report.get('history', [])) != SETTINGS['epochs'] or report.get('encoder_unchanged') is not True
            or report.get('encoder_assets_unchanged') is not True or report.get('encoder_initial_hash') != report.get('encoder_final_hash')
            or report.get('diagnostic_evaluated_during_selection') is not False
            or any(report.get(k) != v for k, v in GATES.items() if k not in ('training_started', 'weights_updated', 'optimizer_steps'))
            or report.get('training_started') is not True or report.get('weights_updated') is not True):
        raise ValueError('Typed completed run contract differs')
    saved = json.loads(u.checked(results, 'dev-predictions.json', manifest, used))
    measured = metrics(data['dev'], saved)
    selected = min(report['history'], key=lambda h: (h['dev']['wrong_accepts'], -h['dev']['supported_correct'], -h['dev']['correct_rejections']))
    if (measured != report.get('selected_dev_metrics') or measured != selected['dev']
            or selected['epoch'] != report.get('selected_epoch')):
        raise ValueError('Typed checkpoint/dev selection differs')
    weights = u.checked(results, 'checkpoints/best.pt', manifest, used)
    if report.get('checkpoint') != 'checkpoints/best.pt' or report.get('checkpoint_sha256') != used['checkpoints/best.pt']:
        raise ValueError('Typed checkpoint digest binding differs')
    return data, diagnostic, plan, report, weights, used


def load_runtime(prepared, results, encoder_root, device='cpu'):
    import torch
    data, diagnostic, plan, report, weights, used = read_result(prepared, results)
    torch.set_num_threads(4)
    encoder, tokenizer, hashes, _ = t.load_encoder(encoder_root)
    if hashes != plan['encoder_inputs'] or u.base.weights_hash(encoder) != report['encoder_final_hash']:
        raise ValueError('Typed inference encoder provenance differs')
    model = make_model()
    restore(model, torch.load(io.BytesIO(weights), map_location='cpu', weights_only=True))
    if t.state_hash(model.state_dict()) != report['selected_parameter_hash']: raise ValueError('Typed restored parameter hash differs')
    model.to(device).eval()
    return {'model': model, 'encoder': encoder, 'tokenizer': tokenizer, 'device': device,
            'characters': {c for r in data['train'] for c in r['text']}, 'checkpoint_sha256': report['checkpoint_sha256'],
            'data': data, 'diagnostic': diagnostic, 'plan': plan, 'report': report, 'inputs': used}


def predict_texts(runtime, texts):
    # No references/targets are passed to the frozen encoder or learned heads.
    rows, rejected = [], {}
    for i, text in enumerate(texts):
        try:
            normalized = input_text(text)
            if any(c not in runtime['characters'] for c in normalized): raise ValueError('outside_training_character_support')
            char_ids(normalized, runtime['tokenizer'])
            rows.append({'id': str(i), 'text': normalized, 'tags': None, 'expected_kind': 'reject'})
        except ValueError as error:
            rejected[str(i)] = {**GATES, 'status': 'abstained', 'kind': 'reject', 'roles': {}, 'spans': [], 'operators': [],
                                'reasons': [str(error)], 'confidence': None, 'accepted_by': 'explicit_input_contract'}
    predictions = {}
    if rows:
        cached = features(runtime['encoder'], runtime['tokenizer'], rows, runtime['device'])
        predictions = {p['id']: p for p in predict_cached(runtime['model'], rows, cached, runtime['device'])}
    return [{**GATES, 'input': text, 'checkpoint_sha256': runtime['checkpoint_sha256'],
             'result': rejected.get(str(i), predictions.get(str(i))),
             'notice': '受限中文语义研究模型；不是中国手语翻译或人物动作，不提供经校准的置信度。'}
            for i, text in enumerate(texts)]


def audit(prepared, results, encoder_root, output):
    output = u.new_output(output, [prepared, results, encoder_root])
    state = load_runtime(prepared, results, encoder_root)
    output.mkdir(parents=True)
    rows = [r for r in state['diagnostic'] if r['partition'] in ('dev', 'challenge', 'legacy_diagnostic')]
    envelopes = predict_texts(state, [r['text'] for r in rows]); outputs = []
    for row, envelope in zip(rows, envelopes):
        result = envelope['result']
        if result.get('prediction'):
            result = {**result, 'id': row['id']}
        else:
            result = {'id': row['id'], 'text': row['text'], 'explicit_contract_rejection': True, 'prediction': result}
        outputs.append(result)
    # Explicit input-contract abstentions are distinct from learned rejections.
    class Adapter:
        def __init__(self, selected): self.predictions = iter(selected)
        def predict(self, text): return next(self.predictions)['prediction']
    measured = s.evaluate(Adapter(outputs), rows)
    train_texts = {r['text'] for r in state['data']['train']}; dev_texts = {r['text'] for r in state['data']['dev']}
    overlap = {'train': [r['id'] for r in rows if r['text'] in train_texts], 'dev': [r['id'] for r in rows if r['text'] in dev_texts]}
    nonoverlap = [(r, p) for r, p in zip(rows, outputs) if r['text'] not in train_texts | dev_texts]
    nonoverlap_metrics = s.evaluate(Adapter([p for _, p in nonoverlap]), [r for r, _ in nonoverlap])
    by_id = {p['id']: p for p in measured['records']}
    entity_ids = [r['id'] for r in rows if r['expected_kind'] == 'entity']
    scope_ids = [r['id'] for r in rows if r['expected_operators'] and len(r['expected_operators']) >= 2]
    paired = measured['pairs']; measured_metrics = measured['metrics']
    quality = {'supported_correct_rate': measured_metrics['correct_supported_parse_rate'],
               'wrong_accepts': measured_metrics['accepted'] - measured_metrics['correct_parses'],
               'unsupported_false_accepts': measured_metrics['false_accepts'],
               'entity_correct_rate': sum(by_id[i]['correct_parse'] for i in entity_ids) / len(entity_ids) if entity_ids else None,
               'scope_correct_rate': sum(by_id[i]['correct_parse'] for i in scope_ids) / len(scope_ids) if scope_ids else None,
               'complete_pairs_pass_rate': sum(p['passed'] for p in paired) / len(paired) if paired else None}
    # CPU replay is mandatory before this local audit may finish.
    cached = features(state['encoder'], state['tokenizer'], state['data']['dev'], 'cpu')
    dev_predicted = predict_cached(state['model'], state['data']['dev'], cached, 'cpu')
    manifest, consumed = u.read_manifest(u.safe_path(results))
    old = json.loads(u.checked(u.safe_path(results), 'dev-predictions.json', manifest, consumed))
    if dev_predicted != old: raise ValueError('CPU selected dev output differs from GPU evidence')
    report = {**GATES, 'schema': SCHEMA, 'status': 'completed_audit', 'CPU_dev_replay_exact': True,
              'dev_metrics': metrics(state['data']['dev'], dev_predicted), 'diagnostic': measured,
              'bounded_Chinese_diagnostic_quality': quality, 'bounded_Chinese_quality_gates': quality_gates(quality),
              'CSL_quality_improvement_verified': False,
              'diagnostic_excluding_train_dev_overlap': nonoverlap_metrics,
              'diagnostic_training_overlap': overlap, 'checkpoint_sha256': state['checkpoint_sha256'],
              'limits': ['Diagnostic was previously consumed engineering data, not independent test.',
                         'Dev overlap and train overlap disclosed; no new CSL/motion or human approval.',
                         'Explicit input guards and BIO/graph composition are not learned translation.']}
    u.base.write_json(output / 'report.json', report); u.base.write_json(output / 'diagnostic-predictions.json', outputs)
    u.base.write_json(output / 'dev-predictions.json', dev_predicted); u.seal(output); return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for name in ['previous', 'legacy-fixture', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('train')
    for name in ['prepared', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('audit')
    for name in ['prepared', 'results', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('interactive')
    for name in ['prepared', 'results', 'encoder-root']: p.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare(args.previous, args.legacy_fixture, args.encoder_root, args.output)
    elif args.command == 'train': result = train(args.prepared, args.encoder_root, args.output)
    elif args.command == 'audit': result = audit(args.prepared, args.results, args.encoder_root, args.output)
    else:
        runtime = load_runtime(args.prepared, args.results, args.encoder_root)
        print('受限中文语义研究终端；输入中文，/quit退出。不是中国手语翻译。', flush=True)
        for line in sys.stdin:
            text = line.rstrip('\r\n')
            if text == '/quit': break
            print(json.dumps(predict_texts(runtime, [text])[0], ensure_ascii=False), flush=True)
        sys.exit(0)
    print(json.dumps(result, ensure_ascii=False, indent=2))
