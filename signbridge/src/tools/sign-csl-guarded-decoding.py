"""Bounded character-Gloss decoding study and reference-free research inference.

No optimization, label lookup, motion integration or semantic certification.
Preserves raw failures and legitimate repeats; G remains development-only.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import time
import unicodedata


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


f = load('sign-csl-fit-study.py')
t, u = f.t, f.u
SCHEMA = 'signbridge-guarded-character-decoding-v1'
BASELINE_SHA = 'ce686c381227bf49cd7f8527767e74a8e58169d164835aea3149b03adfee08e7'
CONFIGS = [('syntax-greedy', 1, 0.), ('syntax-beam4', 4, .6)]
RAW_CONFIG = ('raw-greedy', 1, 0.)
GATES = {**f.GATES, 'training_started': False, 'semantics_approved': False,
         'boundaries_approved': False, 'text_verified': '', 'independent_test': False}


def source_hashes():
    return {**f.source_hashes(), Path(__file__).name: u.base.sha(Path(__file__))}


def input_text(value):
    if (not isinstance(value, str) or len(value) > 512 or
            any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError('Input must be text without control characters, at most 512 raw characters')
    normalized = u.base.normalize(value)
    if not 1 <= len(normalized) <= 126:
        raise ValueError('Input must contain 1..126 normalized characters; no truncation')
    return normalized


def repeat_limit(train):
    longest = 1
    for row in train:
        prior, run = None, 0
        for label in row['gloss_sequence']:
            run = run + 1 if label == prior else 1
            longest, prior = max(longest, run), label
    return longest


def assess(prediction, limit):
    reasons = list(prediction.get('representation_errors', []))
    if not prediction.get('terminated'): reasons.append('missing_eos')
    if not prediction.get('predicted'): reasons.append('empty_prediction')
    if any(x.startswith(t.c.INVALID) for x in prediction.get('predicted', [])):
        reasons.append('invalid_gloss')
    if repeat_limit([{'gloss_sequence': prediction.get('predicted', [])}]) > limit:
        reasons.append('repetition_beyond_training_support')
    return {**GATES, 'status': 'abstained' if reasons else 'research_candidate',
            'reasons': sorted(set(reasons)), 'repetition_limit_from_train': limit,
            'confidence': None,
            'meaning': 'Structural research candidate only; validity does not establish correct CSL translation.'}


def grammar_scores(logits, previous, end_id):
    """Mask AFTER log-softmax, preserving original cross-hypothesis probabilities."""
    import torch
    if not torch.isfinite(logits).all(): raise ValueError('Nonfinite decoder logits')
    scores = torch.log_softmax(logits, dim=-1)
    scores[:, :3] = -torch.inf  # PAD, UNK and BOS are never output content.
    scores[:, 3] = scores[:, 3].masked_fill(previous.ne(end_id), -torch.inf)
    scores[:, end_id] = scores[:, end_id].masked_fill(previous.eq(2) | previous.eq(end_id), -torch.inf)
    return scores


def search(model, source, size, end_id, width=4, max_steps=63, alpha=.6, syntax=True):
    """Project-native cumulative-score beam pruning; length reranking at the end.

    Finished hypotheses remain in the beam with unchanged score/length. At the
    budget, incomplete hypotheses still compete and are reported as failures.
    No forced EOS, reference words, repeat suppression or output deduplication.
    """
    import torch
    if (width not in (1, 4) or alpha not in (0., .6) or not 1 <= max_steps <= 63
            or source.ndim != 2 or not 1 <= source.size(1) <= 128 or not 4 <= end_id < size):
        raise ValueError('Invalid structural search configuration')
    model.eval()
    batch = source.size(0)
    with torch.inference_mode():
        memory = model.encode(source).repeat_interleave(width, 0)
        padding = source.eq(0).repeat_interleave(width, 0)
        tokens = torch.full((batch, width, 1), 2, dtype=torch.long, device=source.device)
        scores = torch.full((batch, width), -torch.inf, device=source.device)
        scores[:, 0] = 0.
        lengths = torch.zeros((batch, width), dtype=torch.long, device=source.device)
        ended = torch.zeros_like(lengths, dtype=torch.bool)
        for _ in range(max_steps):
            flat = tokens.reshape(batch * width, -1)
            logits = model.decode(flat, memory, padding)[:, -1]
            if syntax:
                logp = grammar_scores(logits, flat[:, -1], end_id)
            else:
                if not torch.isfinite(logits).all(): raise ValueError('Nonfinite decoder logits')
                logp = torch.log_softmax(logits, -1)
                logp[:, 0] = -torch.inf
                logp[:, 2] = -torch.inf
            logp = logp.reshape(batch, width, size)
            logp = logp.masked_fill(ended.unsqueeze(-1), -torch.inf)
            logp[:, :, 3] = torch.where(ended, torch.zeros_like(scores), logp[:, :, 3])
            scores, indices = (scores.unsqueeze(-1) + logp).reshape(batch, -1).topk(width, dim=-1)
            parent, token = indices // size, indices % size
            tokens = torch.cat([tokens.gather(1, parent.unsqueeze(-1).expand(-1, -1, tokens.size(-1))), token.unsqueeze(-1)], -1)
            prior_ended = ended.gather(1, parent)
            lengths = lengths.gather(1, parent) + (~prior_ended).long()
            ended = prior_ended | token.eq(3)
            if bool(ended.all()): break
        normalized = scores / (((5 + lengths.clamp(min=1)) / 6) ** alpha)
        winners = normalized.argmax(-1).cpu().tolist()
        token_rows, score_rows, length_rows = tokens.cpu().tolist(), scores.cpu().tolist(), lengths.cpu().tolist()
    return [{'tokens': token_rows[i][j][1:1 + length_rows[i][j]],
             'score': score_rows[i][j], 'length': length_rows[i][j]}
            for i, j in enumerate(winners)]


def source_batch(rows, tokenizer, device):
    source = tokenizer([input_text(r['text']) for r in rows], padding=True, truncation=False,
                       return_tensors='pt')['input_ids']
    if tokenizer.pad_token_id != 0 or source.ndim != 2 or source.size(0) != len(rows) or source.size(1) > 128:
        raise ValueError('Unexpected source tokens/shape; no truncation')
    return source.to(device)


def record(row, candidate, vocab, limit):
    if (not isinstance(candidate.get('tokens'), list) or not 1 <= len(candidate['tokens']) <= 63
            or candidate.get('length') != len(candidate['tokens'])
            or not isinstance(candidate.get('score'), (int, float)) or not math.isfinite(candidate['score'])
            or any(type(i) is not int or not 0 <= i < len(vocab['target']) for i in candidate['tokens'])
            or (3 in candidate['tokens'] and candidate['tokens'].index(3) != len(candidate['tokens']) - 1)):
        raise ValueError('Invalid raw search evidence')
    ids = candidate['tokens']
    terminated = 3 in ids
    if terminated: ids = ids[:ids.index(3)]
    tokens = [vocab['target'][i] for i in ids]
    decoded = t.c.decode_gloss(tokens)
    if not terminated:
        decoded['errors'].append('missing_eos')
        decoded['gloss'].append(t.c.INVALID + 'eos')
    result = {'id': row['id'], 'text': row['text'], 'predicted': decoded['gloss'],
              'target_character_tokens': tokens, 'terminated': terminated,
              'representation_errors': sorted(set(decoded['errors'])),
              'search': candidate, 'score_is_calibrated_confidence': False}
    if 'gloss_sequence' in row: result['reference'] = row['gloss_sequence']
    result['quality'] = assess(result, limit)
    return result


def generate(model, rows, vocab, tokenizer, device, config, limit, batch_size=32):
    name, width, alpha = config
    if config not in [RAW_CONFIG, *CONFIGS]: raise ValueError('Unregistered decoder')
    output = []
    for start in range(0, len(rows), batch_size):
        part = rows[start:start + batch_size]
        source = source_batch(part, tokenizer, device)
        candidates = search(model, source, len(vocab['target']), vocab['target'].index(t.c.END), width, 63, alpha, name != 'raw-greedy')
        output.extend(record(row, candidate, vocab, limit) for row, candidate in zip(part, candidates))
    return output


def prepare(control, baseline, output):
    control, baseline, output = map(u.safe_path, [control, baseline, output])
    u.new_output(output, [control, baseline])
    data, vocab, prior, control_plan, inputs = f.read_control(control)
    manifest, used = u.read_manifest(baseline)
    report = json.loads(u.checked(baseline, 'report.json', manifest, used))
    saved = json.loads(u.checked(baseline, 'selection-predictions.json', manifest, used))
    weights = u.checked(baseline, 'checkpoints/best.pt', manifest, used)
    if (report.get('schema') != f.SCHEMA or report.get('status') != 'completed'
            or report.get('inputs') != inputs or report.get('plan') != control_plan
            or report.get('tool_sha256') != f.source_hashes()
            or report.get('frozen_encoder_unchanged') is not True
            or report.get('checkpoint_sha256') != BASELINE_SHA or used['checkpoints/best.pt'] != BASELINE_SHA
            or any(report.get(k) is not False for k in ['holdout_H_read', 'test_read', 'official_test_read', 'promoted', 'training_ready', 'model_training_ready'])):
        raise ValueError('LR baseline provenance differs')
    f.verify_predictions(data['selection'], saved)
    if t.c.metrics(data['selection'], saved) != report['selected_metrics']:
        raise ValueError('Baseline metrics differ')
    output.mkdir(parents=True)
    t.copy_verified_inputs(control / 'original-prepared/input', output / 'input', inputs['prepared']['grouped'])
    u.base.write_json(output / 'vocab.json', vocab)
    (output / 'best.pt').write_bytes(weights)
    (output / 'baseline-report.json').write_bytes(u.checked(baseline, 'report.json', manifest, used))
    (output / 'baseline-predictions.json').write_bytes(u.checked(baseline, 'selection-predictions.json', manifest, used))
    plan = {**GATES, 'schema': SCHEMA, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'configs': CONFIGS, 'max_steps': 63, 'checkpoint_sha256': BASELINE_SHA,
            'baseline_hashes': used, 'grouped_hashes': inputs['prepared']['grouped'],
            'encoder_inputs': report['encoder_inputs'], 'frozen_encoder_hash': report['frozen_encoder_final_hash'],
            'trainable_hash': report['selected_trainable_hash'], 'counts': {k: len(v) for k, v in data.items()},
            'repeat_limit_from_train': repeat_limit(data['train']), 'tool_sha256': source_hashes(),
            'selection_rule': 'Minimum unfiltered G GER among candidates passing every baseline guardrail; earliest tie. Otherwise raw baseline with abstention.',
            'hypothesis': 'Boundary-aware search may fix incomplete/looping greedy paths without changing weights or legitimate repeats.',
            'limits': ['G was repeatedly used for development; no independent generalization score.',
                       'Syntax and repetition checks cannot certify semantic correctness.',
                       'No reference-conditioned decoding, trained-label trie, forced EOS, output deduplication or filtering from GER.',
                       'No optimizer updates; no H/test/motion source reads.']}
    u.base.write_json(output / 'plan.json', plan)
    u.seal(output)
    return plan


def read_prepared(root):
    root = u.safe_path(root)
    manifest, used = u.read_manifest(root)
    plan = json.loads(u.checked(root, 'plan.json', manifest, used))
    vocab = json.loads(u.checked(root, 'vocab.json', manifest, used))
    baseline = json.loads(u.checked(root, 'baseline-report.json', manifest, used))
    saved = json.loads(u.checked(root, 'baseline-predictions.json', manifest, used))
    weights = u.checked(root, 'best.pt', manifest, used)
    data, grouped = t.c.load_data(root / 'input')
    if (plan.get('schema') != SCHEMA or plan.get('tool_sha256') != source_hashes()
            or plan.get('configs') != [list(x) for x in CONFIGS] or plan.get('max_steps') != 63
            or plan.get('checkpoint_sha256') != BASELINE_SHA or used['best.pt'] != BASELINE_SHA
            or plan.get('grouped_hashes') != grouped['sha256']
            or plan.get('counts') != {'train': 4368, 'selection': 489}
            or plan.get('repeat_limit_from_train') != repeat_limit(data['train'])
            or vocab != t.c.build_vocab(data['train'])
            or used['baseline-report.json'] != plan['baseline_hashes']['report.json']
            or used['baseline-predictions.json'] != plan['baseline_hashes']['selection-predictions.json']
            or baseline.get('checkpoint_sha256') != BASELINE_SHA
            or plan.get('frozen_encoder_hash') != baseline.get('frozen_encoder_final_hash')
            or plan.get('trainable_hash') != baseline.get('selected_trainable_hash')
            or plan.get('encoder_inputs') != baseline.get('encoder_inputs')
            or any(plan.get(k) != value for k, value in GATES.items())):
        raise ValueError('Prepared experiment contract differs')
    f.verify_predictions(data['selection'], saved)
    if t.c.metrics(data['selection'], saved) != baseline['selected_metrics']:
        raise ValueError('Baseline prediction metrics differ')
    return data, vocab, plan, baseline, saved, weights, used


def runtime(prepared, encoder_root, device):
    import torch
    data, vocab, plan, baseline, saved, weights, inputs = read_prepared(prepared)
    torch.set_num_threads(4)
    encoder, tokenizer, encoder_inputs, _ = t.load_encoder(encoder_root)
    if encoder_inputs != plan['encoder_inputs']: raise ValueError('Encoder assets differ')
    model = t.make_model(encoder, vocab)
    t.load_trainable(model, torch.load(io.BytesIO(weights), map_location='cpu', weights_only=True))
    if u.base.weights_hash(encoder) != plan['frozen_encoder_hash'] or t.state_hash(t.trainable_state(model)) != plan['trainable_hash']:
        raise ValueError('Loaded weights differ')
    model.to(device).eval()
    return model, tokenizer, data, vocab, plan, baseline, saved, inputs


def score(rows, predictions):
    f.verify_predictions(rows, predictions)
    return {**t.c.metrics(rows, predictions),
            'abstained_rows': sum(p['quality']['status'] == 'abstained' for p in predictions),
            'structural_candidate_rows': sum(p['quality']['status'] == 'research_candidate' for p in predictions)}


def evaluate(prepared, encoder_root, output):
    import torch
    device = u.cuda_device('cuda')
    prepared, encoder_root, output = map(u.safe_path, [prepared, encoder_root, output])
    u.new_output(output, [prepared, encoder_root])
    model, tokenizer, data, vocab, plan, baseline, saved, inputs = runtime(prepared, encoder_root, device)
    output.mkdir(parents=True)
    report = {**GATES, 'schema': SCHEMA, 'status': 'running', 'inputs': inputs, 'plan': plan,
              'optimizer_steps': 0, 'results': {}, 'runtime': {'python': sys.version, 'torch': str(torch.__version__),
              'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(device)}, 'tool_sha256': source_hashes()}
    try:
        start = time.perf_counter()
        replay = t.generate(model, data['selection'], vocab, tokenizer, device, 64)
        if replay != saved: raise ValueError('Raw GPU baseline no longer reproduces every saved G output')
        reference_free = generate(model, data['selection'], vocab, tokenizer, device, RAW_CONFIG, plan['repeat_limit_from_train'], 64)
        if any({k: p[k] for k in old} != old for p, old in zip(reference_free, saved)):
            raise ValueError('Reference-free raw decoder differs from original baseline')
        replay = reference_free
        report['results']['raw-greedy'] = {'metrics': score(data['selection'], replay), 'seconds': time.perf_counter() - start}
        u.base.write_json(output / 'raw-greedy-predictions.json', replay)
        for config in CONFIGS:
            start = time.perf_counter()
            predictions = generate(model, data['selection'], vocab, tokenizer, device, config, plan['repeat_limit_from_train'])
            metrics = score(data['selection'], predictions)
            gates = f.adoption_gates(metrics, baseline['selected_metrics'])
            gates['no_structural_abstentions'] = metrics['abstained_rows'] == 0
            report['results'][config[0]] = {'metrics': metrics, 'guardrails': gates, 'seconds': time.perf_counter() - start}
            u.base.write_json(output / (config[0] + '-predictions.json'), predictions)
            u.base.write_json(output / 'report.json', report)
            print(json.dumps({'decoder': config[0], **report['results'][config[0]]}), flush=True)
        eligible = [c[0] for c in CONFIGS if all(report['results'][c[0]]['guardrails'].values())]
        preferred = min(eligible, key=lambda n: report['results'][n]['metrics']['raw_gloss']['gloss_error_rate']) if eligible else 'raw-greedy'
        if u.base.weights_hash(model.encoder) != plan['frozen_encoder_hash'] or t.state_hash(t.trainable_state(model)) != plan['trainable_hash']:
            raise ValueError('Inference changed parameters')
        report.update(status='completed', finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      preferred_research_decoder=preferred, baseline_reproduced=True,
                      reference_free_baseline_reproduced=True, weights_unchanged=True)
        u.base.write_json(output / 'report.json', report)
        u.seal(output)
    except Exception as error:
        report.update(status='failed', error=repr(error))
        u.base.write_json(output / 'report.json', report)
        u.seal(output)
        raise
    return report


def read_result(root, state):
    _, _, data, vocab, plan, baseline, saved, inputs = state
    manifest, used = u.read_manifest(root)
    report = json.loads(u.checked(root, 'report.json', manifest, used))
    if (report.get('schema') != SCHEMA or report.get('status') != 'completed'
            or report.get('inputs') != inputs or report.get('plan') != plan
            or report.get('weights_unchanged') is not True or report.get('optimizer_steps') != 0
            or report.get('baseline_reproduced') is not True
            or report.get('reference_free_baseline_reproduced') is not True
            or report.get('tool_sha256') != source_hashes()
            or any(report.get(k) != value for k, value in GATES.items())):
        raise ValueError('Decoder result contract differs')
    names = [RAW_CONFIG[0], *(c[0] for c in CONFIGS)]
    if set(report.get('results', {})) != set(names): raise ValueError('Incomplete decoder results')
    for name in names:
        predictions = json.loads(u.checked(root, name + '-predictions.json', manifest, used))
        f.verify_predictions(data['selection'], predictions)
        for row, prediction in zip(data['selection'], predictions):
            if prediction != record(row, prediction.get('search', {}), vocab, plan['repeat_limit_from_train']):
                raise ValueError('Prediction decoding/quality evidence differs')
        measured = score(data['selection'], predictions)
        if report['results'][name].get('metrics') != measured:
            raise ValueError('Recomputed decoder metrics differ')
        if name == RAW_CONFIG[0]:
            if any({k: p[k] for k in old} != old for p, old in zip(predictions, saved)):
                raise ValueError('Baseline reproduction evidence differs')
        else:
            gates = {**f.adoption_gates(measured, baseline['selected_metrics']),
                     'no_structural_abstentions': measured['abstained_rows'] == 0}
            if report['results'][name].get('guardrails') != gates:
                raise ValueError('Recomputed decoder guardrails differ')
    eligible = [c[0] for c in CONFIGS if all(report['results'][c[0]]['guardrails'].values())]
    expected = min(eligible, key=lambda n: report['results'][n]['metrics']['raw_gloss']['gloss_error_rate']) if eligible else 'raw-greedy'
    if report.get('preferred_research_decoder') != expected: raise ValueError('Research decoder selection differs')
    return expected, used


def predict_loaded(state, decoder, text):
    model, tokenizer, _, vocab, plan, _, _, _ = state
    normalized = input_text(text)
    device = next(model.parameters()).device
    row = {'id': 'research-input', 'text': normalized}
    config = next(c for c in [RAW_CONFIG, *CONFIGS] if c[0] == decoder)
    p = generate(model, [row], vocab, tokenizer, device, config, plan['repeat_limit_from_train'], 1)[0]
    return {**GATES, 'input': text, 'normalized_input': normalized, 'decoder': decoder,
            'checkpoint_sha256': BASELINE_SHA, 'prediction': p,
            'notice': '研究输出，不能据此认定中国手语翻译正确；不驱动人物动作。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for name in ['control', 'baseline', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('evaluate')
    for name in ['prepared', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    for command in ['predict', 'interactive']:
        p = sub.add_parser(command)
        for name in ['prepared', 'encoder-root', 'result']: p.add_argument('--' + name, type=Path, required=True)
        if command == 'predict':
            p.add_argument('--text', required=True)
            p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare(args.control, args.baseline, args.output)
    elif args.command == 'evaluate': result = evaluate(args.prepared, args.encoder_root, args.output)
    else:
        if args.command == 'predict': input_text(args.text)
        state = runtime(u.safe_path(args.prepared), u.safe_path(args.encoder_root), 'cpu')
        decoder, _ = read_result(u.safe_path(args.result), state)
        if args.command == 'interactive':
            print('中国手语 Gloss 研究终端。输入中文；输入 /quit 退出。结果仅供研究，不连接人物播放。', flush=True)
            for line in sys.stdin:
                text = line.rstrip('\r\n')
                if text == '/quit': break
                try: result = predict_loaded(state, decoder, text)
                except ValueError as error: result = {**GATES, 'error': str(error)}
                print(json.dumps(result, ensure_ascii=False), flush=True)
            return
        output = u.new_output(args.output, [args.prepared, args.encoder_root, args.result])
        result = predict_loaded(state, decoder, args.text)
        output.mkdir(parents=True)
        u.base.write_json(output / 'prediction.json', result)
        u.seal(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
