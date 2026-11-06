"""Paired GPU-only warm continuation, with/without the last two BERT blocks.

Uses only frozen train/G inputs. Original encoder assets and prior checkpoints
are immutable. Both arms keep encoder dropout off and use the same update budget.
"""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import random
import sys

import importlib.util


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


g = load('sign-csl-guarded-decoding.py')
t, u = g.t, g.u
SCHEMA = 'signbridge-upper2-transfer-v1'
GATES = dict(g.GATES)
ARMS = ['frozen-continuation', 'upper2-adaptation']
SETTINGS = {'epochs': 8, 'expected_steps_per_arm': 552, 'batch_size': 64, 'seed': 20261106,
            'decoder_lr': .0002, 'encoder_lr': .00002, 'weight_decay': .01,
            'label_smoothing': .05, 'clip_grad': 1., 'encoder_dropout': False,
            'selection': 'minimum unfiltered G raw Gloss GER, earliest epoch tie', 'early_stop': False}
UPPER = ('encoder.encoder.layer.10.', 'encoder.encoder.layer.11.')


def source_hashes():
    return {**g.source_hashes(), Path(__file__).name: u.base.sha(Path(__file__))}


def make_model(encoder, vocab, upper):
    base = t.make_model(encoder, vocab)
    class Adapted(type(base)):
        def encode(self, source):
            # Frozen lower layers automatically have no gradient graph. Only the
            # explicitly enabled final blocks and projection receive gradients.
            hidden = self.encoder(input_ids=source, attention_mask=source.ne(0), return_dict=True).last_hidden_state
            return self.memory_norm(self.projection(hidden))
    del base
    model = Adapted()
    for name, parameter in model.named_parameters():
        if name.startswith('encoder.'):
            parameter.requires_grad_(bool(upper and name.startswith(UPPER)))
    return model


def trainable_state(model):
    return {name: parameter.detach().cpu() for name, parameter in model.named_parameters() if parameter.requires_grad}


def frozen_hash(model):
    names = {name for name, parameter in model.named_parameters() if parameter.requires_grad}
    return t.state_hash({name: value.detach().cpu() for name, value in model.state_dict().items() if name not in names})


def load_trainable(model, state):
    import torch
    expected = trainable_state(model)
    if (not isinstance(state, dict) or set(state) != set(expected)
            or any(not isinstance(value, torch.Tensor) or value.shape != expected[name].shape
                   or value.dtype != expected[name].dtype or not torch.isfinite(value).all() for name, value in state.items())):
        raise ValueError('Adaptation checkpoint keys/shapes/dtypes/values differ')
    result = model.load_state_dict(state, strict=False)
    if result.unexpected_keys or set(result.missing_keys) != set(model.state_dict()) - set(expected):
        raise ValueError('Adaptation checkpoint missing frozen keys differ')


def prepare(baseline_prepared, decoding_results, output):
    baseline_prepared, decoding_results, output = map(u.safe_path, [baseline_prepared, decoding_results, output])
    u.new_output(output, [baseline_prepared, decoding_results])
    data, vocab, prior, baseline, saved, _, inputs = g.read_prepared(baseline_prepared)
    _, decoded_hashes = g.read_result(decoding_results, (None, None, data, vocab, prior, baseline, saved, inputs))
    output.mkdir(parents=True); target = output / 'baseline-input'; target.mkdir()
    # Exact allowlist: never recursively copy unknown test/video files.
    names = ['plan.json', 'vocab.json', 'baseline-report.json', 'baseline-predictions.json', 'best.pt', 'SHA256SUMS',
             'input/train.jsonl', 'input/selection.jsonl', 'input/report.json', 'input/SHA256SUMS']
    hashes = {}
    for name in names:
        src = u.safe_path(baseline_prepared / name)
        dest = target / name; dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(src.read_bytes()); hashes[name] = u.base.sha(dest)
    plan = {**GATES, 'schema': SCHEMA, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'settings': SETTINGS, 'arms': ARMS, 'input_hashes': hashes, 'baseline_inputs': inputs,
            'decoding_result_hashes': decoded_hashes, 'baseline_metrics': baseline['selected_metrics'],
            'source_hashes': source_hashes(), 'warm_checkpoint_sha256': g.BASELINE_SHA,
            'hypothesis': 'Matched warm continuation separates extra decoder fitting from adapting the final two Chinese encoder blocks.',
            'decision_rule': 'Prefer the lowest-G-GER arm passing every original overall/person/negation/deletion/validity guardrail and no runaway repetition. Otherwise retain the old guarded baseline.',
            'limits': ['G is reused development data, not an independent test.', 'Both arms use a NEW AdamW; no optimizer state exists for the selected epoch12 warm checkpoint.',
                       'Encoder dropout stays disabled in both arms; only explicit top-two trainability/encoder optimizer group differs.',
                       'No H/test/videos/motions or semantic approval; no automatic Demo integration.']}
    u.base.write_json(output / 'plan.json', plan); u.seal(output)
    return plan


def read_prepared(root):
    root = u.safe_path(root); manifest, used = u.read_manifest(root)
    plan = json.loads(u.checked(root, 'plan.json', manifest, used))
    expected_names = {'plan.json', 'vocab.json', 'baseline-report.json', 'baseline-predictions.json', 'best.pt', 'SHA256SUMS',
                      'input/train.jsonl', 'input/selection.jsonl', 'input/report.json', 'input/SHA256SUMS'}
    if (plan.get('schema') != SCHEMA or plan.get('settings') != SETTINGS or plan.get('arms') != ARMS
            or plan.get('source_hashes') != source_hashes() or plan.get('warm_checkpoint_sha256') != g.BASELINE_SHA
            or set(plan.get('input_hashes', {})) != expected_names
            or any(plan.get(k) != value for k, value in GATES.items())):
        raise ValueError('Upper transfer experiment contract differs')
    for name, digest in plan['input_hashes'].items():
        path = u.safe_path(root / 'baseline-input' / name)
        if u.base.sha(path) != digest: raise ValueError('Warm input digest differs: ' + name)
    state = g.read_prepared(root / 'baseline-input')
    if state[-1] != plan['baseline_inputs'] or state[3]['selected_metrics'] != plan['baseline_metrics']:
        raise ValueError('Warm baseline/data binding differs')
    return state, plan, used


def guardrails(metrics, baseline):
    return {**g.f.adoption_gates(metrics, baseline), 'no_structural_abstentions': metrics['abstained_rows'] == 0}


def preferred_arm(results, baseline):
    if set(results) != set(ARMS): raise ValueError('Both controlled arms are required')
    for result in results.values():
        if result.get('guardrails') != guardrails(result['metrics'], baseline):
            raise ValueError('Arm guardrails differ from measured metrics')
    eligible = [name for name in ARMS if all(results[name]['guardrails'].values())]
    return min(eligible, key=lambda n: results[n]['metrics']['raw_gloss']['gloss_error_rate']) if eligible else 'previous-baseline'


def train(prepared, encoder_root, output):
    import torch
    device = u.cuda_device('cuda')
    prepared, encoder_root, output = map(u.safe_path, [prepared, encoder_root, output])
    u.new_output(output, [prepared, encoder_root]); state, plan, inputs = read_prepared(prepared)
    data, vocab, prior, baseline, _, warm, _ = state
    torch.set_num_threads(4)
    output.mkdir(parents=True)
    report = {**GATES, 'training_started': True, 'schema': SCHEMA, 'status': 'running',
              'plan': plan, 'inputs': inputs, 'arms': {}, 'runtime': {'python': sys.version, 'torch': str(torch.__version__),
              'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(device)}, 'source_hashes': source_hashes()}
    try:
        for arm in ARMS:
            torch.manual_seed(SETTINGS['seed']); torch.cuda.manual_seed_all(SETTINGS['seed']); random.seed(SETTINGS['seed'])
            encoder, tokenizer, encoder_inputs, _ = t.load_encoder(encoder_root)
            if encoder_inputs != prior['encoder_inputs']: raise ValueError('Encoder asset inputs differ')
            model = make_model(encoder, vocab, arm == 'upper2-adaptation')
            t.load_trainable(model, torch.load(io.BytesIO(warm), map_location='cpu', weights_only=True))
            if (t.state_hash(t.trainable_state(model)) != prior['trainable_hash']
                    or u.base.weights_hash(encoder) != prior['frozen_encoder_hash']):
                raise ValueError('Warm initialization differs between arms/baseline')
            frozen = frozen_hash(model); initial = t.state_hash(trainable_state(model)); model.to(device)
            decoder_params = [p for n, p in model.named_parameters() if p.requires_grad and not n.startswith('encoder.')]
            encoder_params = [p for n, p in model.named_parameters() if p.requires_grad and n.startswith(UPPER)]
            groups = [{'params': decoder_params, 'lr': SETTINGS['decoder_lr']}]
            if encoder_params: groups.append({'params': encoder_params, 'lr': SETTINGS['encoder_lr']})
            optimizer = torch.optim.AdamW(groups, weight_decay=SETTINGS['weight_decay'])
            folder = output / arm; folder.mkdir(); (folder / 'checkpoints').mkdir()
            record = {'status': 'running', 'history': [], 'optimizer_steps': 0, 'initial_trainable_hash': initial,
                      'frozen_initial_hash': frozen, 'trainable_parameters': sum(p.numel() for p in model.parameters() if p.requires_grad),
                      'encoder_trainable_parameters': sum(p.numel() for p in encoder_params), 'encoder_inputs': encoder_inputs}
            report['arms'][arm] = record
            best, steps = float('inf'), 0
            for epoch in range(1, SETTINGS['epochs'] + 1):
                model.train(); assert not encoder.training
                order = list(data['train']); random.shuffle(order); losses = []
                for start in range(0, len(order), SETTINGS['batch_size']):
                    source, target = t.batch(order[start:start + SETTINGS['batch_size']], vocab, tokenizer, device)
                    optimizer.zero_grad(set_to_none=True)
                    logits = model(source, target[:, :-1])
                    loss = torch.nn.functional.cross_entropy(logits.flatten(0, 1), target[:, 1:].reshape(-1),
                        ignore_index=0, label_smoothing=SETTINGS['label_smoothing'])
                    if not torch.isfinite(loss): raise ValueError('Nonfinite loss')
                    loss.backward()
                    for name, parameter in model.named_parameters():
                        if not parameter.requires_grad and parameter.grad is not None: raise ValueError('Frozen gradient: ' + name)
                        if parameter.grad is not None and not torch.isfinite(parameter.grad).all(): raise ValueError('Nonfinite gradient: ' + name)
                    torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], SETTINGS['clip_grad'])
                    optimizer.step(); steps += 1; losses.append(float(loss.detach()))
                predictions = g.generate(model, data['selection'], vocab, tokenizer, device, g.RAW_CONFIG, prior['repeat_limit_from_train'], 64)
                measured = g.score(data['selection'], predictions); score = measured['raw_gloss']['gloss_error_rate']
                if score < best:
                    best = score; record['selected_epoch'] = epoch; record['metrics'] = measured
                    torch.save(trainable_state(model), folder / 'checkpoints/best.pt')
                    u.base.write_json(folder / 'selection-predictions.json', predictions)
                torch.save({'model': trainable_state(model), 'optimizer': optimizer.state_dict(), 'epoch': epoch, 'steps': steps,
                            'python_rng': random.getstate(), 'torch_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state_all()},
                           folder / 'checkpoints/recovery-last.pt')
                history = {'epoch': epoch, 'steps': steps, 'train_loss': sum(losses) / len(losses), 'G_metrics': measured}
                record['history'].append(history); record.update(epochs_completed=epoch, optimizer_steps=steps)
                u.base.write_json(output / 'report.json', report)
                print(json.dumps({'arm': arm, **history}), flush=True)
            if steps != SETTINGS['expected_steps_per_arm']: raise ValueError('Fixed update budget differs')
            load_trainable(model, torch.load(folder / 'checkpoints/best.pt', map_location='cpu', weights_only=True))
            if frozen_hash(model) != frozen: raise ValueError('Frozen lower parameters changed')
            fit = {}
            for split in ['train', 'selection']:
                scores, predictions, forced = g.f.evaluate_fit(model, tokenizer, data[split], data['train'], vocab, device, 64)
                fit[split] = scores
                u.base.write_json(folder / (split + '-fit-predictions.json'), predictions)
                u.base.write_json(folder / (split + '-teacher-forcing.json'), forced)
            if fit['selection']['free_generation'] != {k: v for k, v in record['metrics'].items() if k not in ('abstained_rows', 'structural_candidate_rows')}:
                raise ValueError('Selected checkpoint free generation replay differs')
            record.update(status='completed', checkpoint=arm + '/checkpoints/best.pt',
                          checkpoint_sha256=u.base.sha(folder / 'checkpoints/best.pt'),
                          selected_trainable_hash=t.state_hash(trainable_state(model)),
                          frozen_final_hash=frozen_hash(model), frozen_parameters_unchanged=True,
                          guardrails=guardrails(record['metrics'], plan['baseline_metrics']), fit=fit)
            u.seal(folder); del model, encoder, optimizer; torch.cuda.empty_cache()
        report.update(status='completed', finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      preferred_research_arm=preferred_arm(report['arms'], plan['baseline_metrics']),
                      encoder_assets_unchanged=t.check_encoder(encoder_root) == prior['encoder_inputs'])
        u.base.write_json(output / 'report.json', report); u.seal(output)
    except Exception as error:
        report.update(status='failed', error=repr(error)); u.base.write_json(output / 'report.json', report); u.seal(output); raise
    return report


def read_result(root, prepared):
    state, plan, inputs = read_prepared(prepared)
    data, vocab, prior, baseline, _, _, _ = state
    manifest, used = u.read_manifest(root)
    report = json.loads(u.checked(root, 'report.json', manifest, used))
    if (report.get('schema') != SCHEMA or report.get('status') != 'completed' or report.get('plan') != plan
            or report.get('inputs') != inputs or report.get('source_hashes') != source_hashes()
            or report.get('training_started') is not True or report.get('encoder_assets_unchanged') is not True
            or any(report.get(k) != value for k, value in GATES.items() if k != 'training_started')
            or set(report.get('arms', {})) != set(ARMS)):
        raise ValueError('Adaptation result contract differs')
    for arm in ARMS:
        record = report['arms'][arm]
        predictions = json.loads(u.checked(root, arm + '/selection-predictions.json', manifest, used))
        g.f.verify_predictions(data['selection'], predictions)
        for row, prediction in zip(data['selection'], predictions):
            if prediction != g.record(row, prediction.get('search', {}), vocab, prior['repeat_limit_from_train']):
                raise ValueError('Adaptation prediction raw evidence differs')
        metrics = g.score(data['selection'], predictions)
        if (record.get('status') != 'completed' or record.get('optimizer_steps') != 552 or record.get('epochs_completed') != 8
                or len(record.get('history', [])) != 8 or record.get('metrics') != metrics
                or record.get('frozen_parameters_unchanged') is not True or record.get('frozen_initial_hash') != record.get('frozen_final_hash')):
            raise ValueError('Adaptation arm budget/metrics/frozen evidence differs')
        selected = min(record['history'], key=lambda h: h['G_metrics']['raw_gloss']['gloss_error_rate'])
        if record.get('selected_epoch') != selected['epoch'] or record['metrics'] != selected['G_metrics']:
            raise ValueError('Adaptation epoch selection differs')
        expected = arm + '/checkpoints/best.pt'
        u.checked(root, expected, manifest, used)
        if record.get('checkpoint') != expected or record.get('checkpoint_sha256') != used[expected]:
            raise ValueError('Adaptation checkpoint binding differs')
    if report.get('preferred_research_arm') != preferred_arm(report['arms'], baseline['selected_metrics']):
        raise ValueError('Adaptation arm selection differs')
    return state, report, used


def load_runtime(prepared, results, encoder_root):
    import torch
    state, report, used = read_result(u.safe_path(results), u.safe_path(prepared))
    data, vocab, prior, baseline, saved, warm, _ = state
    torch.set_num_threads(4)
    encoder, tokenizer, hashes, _ = t.load_encoder(encoder_root)
    if hashes != prior['encoder_inputs']: raise ValueError('Inference encoder assets differ')
    arm = report['preferred_research_arm']
    model = make_model(encoder, vocab, arm == 'upper2-adaptation')
    if arm == 'previous-baseline':
        t.load_trainable(model, torch.load(io.BytesIO(warm), map_location='cpu', weights_only=True))
        checkpoint_sha = g.BASELINE_SHA
    else:
        manifest, consumed = u.read_manifest(results); record = report['arms'][arm]
        content = u.checked(results, record['checkpoint'], manifest, consumed)
        load_trainable(model, torch.load(io.BytesIO(content), map_location='cpu', weights_only=True))
        if t.state_hash(trainable_state(model)) != record['selected_trainable_hash'] or frozen_hash(model) != record['frozen_final_hash']:
            raise ValueError('Inference weights/frozen state differ')
        checkpoint_sha = record['checkpoint_sha256']
    model.eval()
    return model, tokenizer, vocab, prior['repeat_limit_from_train'], arm, checkpoint_sha


def predict_loaded(runtime, text):
    model, tokenizer, vocab, limit, arm, checkpoint_sha = runtime
    normalized = g.input_text(text)
    prediction = g.generate(model, [{'id': 'research-input', 'text': normalized}], vocab, tokenizer, 'cpu', g.RAW_CONFIG, limit, 1)[0]
    return {**GATES, 'input': text, 'normalized_input': normalized, 'arm': arm,
            'checkpoint_sha256': checkpoint_sha, 'prediction': prediction,
            'notice': '研究候选，不保证中国手语语义正确，不连接人物动作；拒绝结果保留原始输出。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for name in ['baseline-prepared', 'decoding-results', 'output']: p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('train')
    for name in ['prepared', 'encoder-root', 'output']: p.add_argument('--' + name, type=Path, required=True)
    for command in ['predict', 'interactive']:
        p = sub.add_parser(command)
        for name in ['prepared', 'results', 'encoder-root']: p.add_argument('--' + name, type=Path, required=True)
        if command == 'predict':
            p.add_argument('--text', required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare(args.baseline_prepared, args.decoding_results, args.output)
    elif args.command == 'train': result = train(args.prepared, args.encoder_root, args.output)
    else:
        if args.command == 'predict': g.input_text(args.text)
        runtime = load_runtime(args.prepared, args.results, args.encoder_root)
        if args.command == 'interactive':
            print('中文到Gloss研究终端；输入中文，/quit退出。结果不能直接当作正确手语。', flush=True)
            for line in sys.stdin:
                text = line.rstrip('\r\n')
                if text == '/quit': break
                try: result = predict_loaded(runtime, text)
                except ValueError as error: result = {**GATES, 'error': str(error)}
                print(json.dumps(result, ensure_ascii=False), flush=True)
            return
        output = u.new_output(args.output, [args.prepared, args.results, args.encoder_root])
        result = predict_loaded(runtime, args.text); output.mkdir(parents=True)
        u.base.write_json(output / 'prediction.json', result); u.seal(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
