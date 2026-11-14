"""Research-only Chinese text -> CE-CSL gloss sequence training, never motion generation.

Vocabularies use train only; dev selects the checkpoint; test is evaluated once
after selection. Uses the existing optional PyTorch runtime without modifying it.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys
import time
import unicodedata

SPECIALS = ['<pad>', '<unk>', '<bos>', '<eos>']


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def validate_sample(row, split):
    text, gloss = row.get('proposed_text'), row.get('gloss_sequence')
    if (not isinstance(row.get('id'), str) or row.get('source_split') != split
            or not isinstance(text, str) or not 1 <= len(normalize(text)) <= 126
            or not isinstance(gloss, list) or not 1 <= len(gloss) <= 62
            or any(not isinstance(t, str) or not t or t in SPECIALS for t in gloss)):
        raise ValueError('Invalid split or empty/overlong CE-CSL sequence')
    return row


def read_data(library, include_test=True):
    root = Path(library).resolve()
    manifest = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split('  ', 1)
        if name in manifest:
            raise ValueError('Duplicated input digest entry')
        manifest[name] = checksum
    data, inputs, identities = {}, {}, set()
    for split in ['train', 'dev', 'test']:
        relative = f'splits/{split}/samples.jsonl'
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or sha(path) != manifest.get(relative):
            raise ValueError('Dataset split digest differs: ' + relative)
        inputs[relative] = manifest[relative]
        if split == 'test' and not include_test:
            data[split] = []
            continue
        data[split] = [validate_sample(json.loads(line), split) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        for row in data[split]:
            if row['id'] in identities:
                raise ValueError('Duplicate sample identity across splits')
            identities.add(row['id'])
        if not data[split]:
            raise ValueError('Empty dataset split')
    return data, inputs


def build_vocab(train):
    return {'source': SPECIALS + sorted({c for r in train for c in normalize(r['proposed_text'])}),
            'target': SPECIALS + sorted({t for r in train for t in r['gloss_sequence']})}


def overlap_flags(train, rows):
    texts = {normalize(r['proposed_text']) for r in train}
    sequences = {tuple(r['gloss_sequence']) for r in train}
    videos = {r.get('video', {}).get('sha256') for r in train} - {None}
    result = []
    for row in rows:
        reasons = []
        if normalize(row['proposed_text']) in texts:
            reasons.append('normalized_source_in_train')
        if tuple(row['gloss_sequence']) in sequences:
            reasons.append('target_sequence_in_train')
        if row.get('video', {}).get('sha256') in videos:
            reasons.append('video_bytes_in_train')
        result.append({'id': row['id'], 'reasons': reasons})
    return result


class LexiconBaseline:
    """Train gloss frequencies select literal longest matches, with raw variants kept."""
    def __init__(self, train):
        counts = Counter(t for r in train for t in r['gloss_sequence'])
        options = defaultdict(list)
        for label, count in counts.items():
            surface = re.sub(r'(?<=[^0-9])[0-9]+$', '', label)
            if surface:
                options[surface].append((count, label))
        self.mapping = {surface: sorted(choices, key=lambda x: (-x[0], x[1]))[0][1]
                        for surface, choices in options.items()}
        self.max_length = max(map(len, self.mapping), default=1)

    def predict(self, text):
        text, index, result = normalize(text), 0, []
        while index < len(text):
            for length in range(min(self.max_length, len(text) - index), 0, -1):
                key = text[index:index + length]
                if key in self.mapping:
                    result.append(self.mapping[key]); index += length
                    break
            else:
                result.append(text[index]); index += 1
        return result


def edit_counts(reference, hypothesis):
    n, m = len(reference), len(hypothesis)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        table[i][0] = i
    for j in range(m + 1):
        table[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            table[i][j] = min(table[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]),
                              table[i - 1][j] + 1, table[i][j - 1] + 1)
    i, j, substitutions, deletions, insertions = n, m, 0, 0, 0
    while i or j:
        if i and j and reference[i - 1] == hypothesis[j - 1] and table[i][j] == table[i - 1][j - 1]:
            i -= 1; j -= 1
        elif i and j and table[i][j] == table[i - 1][j - 1] + 1:
            substitutions += 1; i -= 1; j -= 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            deletions += 1; i -= 1
        else:
            insertions += 1; j -= 1
    return substitutions, deletions, insertions


def metrics(references, predictions):
    if len(references) != len(predictions):
        raise ValueError('Prediction/reference count differs')
    sums = [0, 0, 0]
    for reference, prediction in zip(references, predictions):
        sums = [a + b for a, b in zip(sums, edit_counts(reference, prediction))]
    tokens = sum(map(len, references))
    exact = sum(r == p for r, p in zip(references, predictions))
    return {'samples': len(references), 'reference_gloss_tokens': tokens,
            'substitutions': sums[0], 'deletions': sums[1], 'insertions': sums[2],
            'gloss_error_rate': sum(sums) / tokens if tokens else None,
            'exact_matches': exact, 'exact_match_rate': exact / len(references) if references else None}


def sliced_metrics(rows, predictions, flags):
    refs = [r['gloss_sequence'] for r in rows]
    selected = [i for i, flag in enumerate(flags) if not flag['reasons']]
    return {'official_all': metrics(refs, predictions),
            'nonoverlap_with_train': metrics([refs[i] for i in selected], [predictions[i] for i in selected]),
            'overlap_rows': len(rows) - len(selected)}


def batch_tensors(rows, vocab, device):
    import torch
    source_ids = {token: i for i, token in enumerate(vocab['source'])}
    target_ids = {token: i for i, token in enumerate(vocab['target'])}
    source = [[2, *(source_ids.get(c, 1) for c in normalize(r['proposed_text'])), 3] for r in rows]
    target = [[2, *(target_ids.get(t, 1) for t in r['gloss_sequence']), 3] for r in rows]
    source = [s + [0] * (max(map(len, source)) - len(s)) for s in source]
    target = [s + [0] * (max(map(len, target)) - len(s)) for s in target]
    return torch.tensor(source, dtype=torch.long, device=device), torch.tensor(target, dtype=torch.long, device=device)


def make_model(vocab, config):
    import torch
    from torch import nn

    class GlossTransformer(nn.Module):
        def __init__(self):
            super().__init__()
            width = config['width']
            self.source = nn.Embedding(len(vocab['source']), width, padding_idx=0)
            self.target = nn.Embedding(len(vocab['target']), width, padding_idx=0)
            self.source_position = nn.Embedding(config['max_source'], width)
            self.target_position = nn.Embedding(config['max_target'], width)
            self.transformer = nn.Transformer(d_model=width, nhead=config['heads'],
                                              num_encoder_layers=config['layers'],
                                              num_decoder_layers=config['layers'],
                                              dim_feedforward=config['feedforward'],
                                              dropout=config['dropout'], batch_first=True)
            # Avoid prototype nested tensor conversion; padded attention masks remain explicit.
            self.transformer.encoder.use_nested_tensor = False
            self.output = nn.Linear(width, len(vocab['target']))

        def encode(self, source):
            embedded = self.source(source) * math.sqrt(config['width'])
            embedded = embedded + self.source_position(torch.arange(source.size(1), device=source.device))[None]
            return self.transformer.encoder(embedded, src_key_padding_mask=source.eq(0))

        def decode(self, target, memory, source_padding):
            embedded = self.target(target) * math.sqrt(config['width'])
            embedded = embedded + self.target_position(torch.arange(target.size(1), device=target.device))[None]
            mask = torch.ones(target.size(1), target.size(1), dtype=torch.bool, device=target.device).triu(1)
            return self.output(self.transformer.decoder(embedded, memory, tgt_mask=mask,
                                                        tgt_key_padding_mask=target.eq(0),
                                                        memory_key_padding_mask=source_padding))

        def forward(self, source, target):
            return self.decode(target, self.encode(source), source.eq(0))

    return GlossTransformer()


def greedy_decode(model, source, vocab, max_length=32):
    import torch
    model.eval()
    with torch.inference_mode():
        memory = model.encode(source)
        target = torch.full((source.size(0), 1), 2, dtype=torch.long, device=source.device)
        done = torch.zeros(source.size(0), dtype=torch.bool, device=source.device)
        for _ in range(max_length):
            logits = model.decode(target, memory, source.eq(0))[:, -1]
            logits[:, 0] = -torch.inf
            logits[:, 2] = -torch.inf
            token = logits.argmax(-1)
            token = torch.where(done, torch.full_like(token, 3), token)
            target = torch.cat((target, token[:, None]), dim=1)
            done = done | token.eq(3)
            if bool(done.all()):
                break
        result = []
        for row in target[:, 1:].cpu().tolist():
            if 3 in row:
                row = row[:row.index(3)]
            result.append([vocab['target'][index] for index in row])
        return result


def predict_rows(model, rows, vocab, device, batch_size=64):
    result = []
    for start in range(0, len(rows), batch_size):
        source, _ = batch_tensors(rows[start:start + batch_size], vocab, device)
        result.extend(greedy_decode(model, source, vocab))
    return result


def weights_hash(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(name.encode('utf-8'))
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def training_device(name):
    import torch
    if name == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA unavailable; GPU training requires the authorized GPU server. No CPU fallback.')
    if name == 'mps' and not torch.backends.mps.is_available():
        raise ValueError('Requested MPS unavailable')
    if name not in ('cuda', 'mps', 'cpu'):
        raise ValueError('Unsupported training device')
    return torch.device(name)


def load_initial_weights(model, vocab, config, model_root):
    import torch
    root = Path(model_root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Initial model directory must be a regular directory')
    root = root.resolve()
    metadata_path = root / 'model.json'
    vocab_path = root / 'vocab.json'
    report_path = root / 'report.json'
    if metadata_path.is_symlink() or vocab_path.is_symlink() or report_path.is_symlink():
        raise ValueError('Initial model metadata cannot be symlinks')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    if metadata.get('schema') != 'signbridge-ce-csl-text-to-gloss-v1' or metadata.get('research_only') is not True:
        raise ValueError('Initial model is not a compatible research checkpoint')
    if json.loads(vocab_path.read_text(encoding='utf-8')) != vocab:
        raise ValueError('Initial model vocabulary differs from current train-only vocabulary')
    if metadata.get('config') != config:
        raise ValueError('Initial model configuration differs from the current model')
    checkpoint_name = metadata.get('checkpoint')
    if not isinstance(checkpoint_name, str) or not checkpoint_name or Path(checkpoint_name).is_absolute():
        raise ValueError('Initial checkpoint path is invalid')
    checkpoint = root / checkpoint_name
    if (checkpoint.is_symlink() or not checkpoint.resolve().is_relative_to(root)
            or not checkpoint.is_file() or sha(checkpoint) != metadata.get('checkpoint_sha256')):
        raise ValueError('Initial checkpoint digest/path differs')
    source_report = None
    if report_path.is_file():
        source_report = json.loads(report_path.read_text(encoding='utf-8'))
        if (source_report.get('status') != 'completed'
                or source_report.get('checkpoint_sha256') != metadata['checkpoint_sha256']
                or source_report.get('checkpoint') != checkpoint_name):
            raise ValueError('Initial training report does not bind the selected checkpoint')
    state = torch.load(checkpoint, map_location='cpu', weights_only=True)
    if not isinstance(state, dict) or not state:
        raise ValueError('Initial checkpoint does not contain a model state dictionary')
    model.load_state_dict(state, strict=True)
    return {
        'mode': 'weights_only_initialization',
        'source_model_root': str(root),
        'source_checkpoint': checkpoint_name,
        'source_checkpoint_sha256': sha(checkpoint),
        'source_selected_epoch': (source_report or {}).get('selected_epoch'),
        'source_optimizer_steps': (source_report or {}).get('optimizer_steps'),
        'optimizer_state_restored': False,
        'optimizer_state_note': 'Checkpoint contains model weights only; a new AdamW optimizer is initialized.',
    }


def train(args):
    import torch
    library, output = args.library.resolve(), args.output.resolve()
    if (output == library or output.is_relative_to(library) or library.is_relative_to(output)
            or output.exists()):
        raise ValueError('Choose a NEW training output separate from candidate inputs')
    data, inputs = read_data(library, include_test=not args.skip_test)
    if not args.research_only:
        raise ValueError('Explicit research-only training scope is required')
    if args.epochs < 1 or args.epochs > 200 or not 1 <= args.batch_size <= 256:
        raise ValueError('Invalid bounded epoch/batch settings')
    torch.set_num_threads(args.threads)
    random.seed(args.seed); torch.manual_seed(args.seed)
    device = training_device(args.device)
    if device.type == 'cuda':
        torch.cuda.manual_seed_all(args.seed)
    vocab = build_vocab(data['train'])
    config = {'width': 128, 'heads': 4, 'layers': 2, 'feedforward': 384,
              'dropout': .15, 'max_source': 128, 'max_target': 64}
    model = make_model(vocab, config).to(device)
    initialization = None
    if args.initialize_from_model:
        initialization = load_initial_weights(model, vocab, config, args.initialize_from_model)
    initial_weights = weights_hash(model)
    selected_splits = ['dev'] if args.skip_test else ['dev', 'test']
    flags = {split: overlap_flags(data['train'], data[split]) for split in selected_splits}
    output.mkdir(parents=True)
    (output / 'checkpoints').mkdir()
    write_json(output / 'vocab.json', vocab)
    write_json(output / 'overlap-review.json', flags)
    baseline = LexiconBaseline(data['train'])
    metadata = {
        'schema': 'signbridge-ce-csl-text-to-gloss-v1', 'status': 'running',
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'experiment': ('Chinese character Transformer to CE-CSL gloss tokens; weights-only initialization'
                       if initialization else 'Chinese character Transformer to CE-CSL gloss tokens; from scratch'),
        'authorization': {'basis': 'explicit_user_request', 'statement': '开始下一步训练',
                          'scope': 'authorized_gpu_research_text_to_gloss_continuation'},
        'candidate_approval_state_unchanged': True,
        'research_only': True, 'human_approved': False, 'deployment_ready': False,
        'training_ready': False, 'model_training_ready': False,
        'text_to_motion_trained': False, 'video_recognition_trained': False,
        'training_started': True, 'old_checkpoints_modified': False,
        'source_library': str(library), 'source_files_sha256': inputs,
        'training_tool_sha256': sha(Path(__file__)),
        'runtime': {'python': sys.version, 'executable': sys.executable, 'torch': torch.__version__,
                    'device': str(device), 'threads': args.threads,
                    'cuda_runtime': torch.version.cuda if device.type == 'cuda' else None,
                    'gpu_name': torch.cuda.get_device_name(device) if device.type == 'cuda' else None},
        'config': config, 'arguments': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        'vocabulary_source': 'train_only', 'source_vocabulary_size': len(vocab['source']),
        'target_vocabulary_size': len(vocab['target']),
        'split_counts': {'train': len(data['train']), 'dev': len(data['dev']),
                         'test': len(data['test']) if not args.skip_test else None},
        'test_data_loaded': not args.skip_test,
        'test_digest_verified_without_parsing': args.skip_test,
        'initialization': initialization or {'mode': 'from_scratch'},
        'parameter_count': sum(p.numel() for p in model.parameters()),
        'initial_weights_sha256': initial_weights,
        'selection': 'minimum dev nonoverlap gloss edit error; test is excluded from this run'
                     if args.skip_test else 'minimum dev nonoverlap gloss edit error; test never used for selection',
        'evaluation_references': 'raw original gloss labels; eval-only labels stay unseen and count as errors',
        'preprocessing': 'NFKC Chinese characters without Unicode punctuation/whitespace; raw inputs unchanged',
        'limits': ['No pretrained language model; small dataset baseline.',
                   'Source translator codes overlap official splits; no signer-independent claim.',
                   'No video features, time alignment, face parameters, motion or semantic certification.'],
    }
    write_json(output / 'report.json', metadata)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=.01)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=0, label_smoothing=.05)
    best, selected_path, best_epoch, stale, steps = float('inf'), None, 0, 0, 0
    started = time.monotonic()
    try:
        for epoch in range(1, args.epochs + 1):
            epoch_start = time.monotonic()
            order = list(range(len(data['train']))); random.shuffle(order)
            total_loss, total_tokens = 0., 0
            model.train()
            for start in range(0, len(order), args.batch_size):
                rows = [data['train'][index] for index in order[start:start + args.batch_size]]
                source, target = batch_tensors(rows, vocab, device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(source, target[:, :-1])
                loss = criterion(logits.reshape(-1, len(vocab['target'])), target[:, 1:].reshape(-1))
                if not bool(torch.isfinite(loss)):
                    raise ValueError('Nonfinite training loss')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
                optimizer.step(); steps += 1
                count = int(target[:, 1:].ne(0).sum())
                total_loss += float(loss.detach()) * count; total_tokens += count
            record = {'epoch': epoch, 'optimizer_steps': steps, 'train_token_loss': total_loss / total_tokens}
            if epoch == 1 or epoch % args.evaluate_every == 0 or epoch == args.epochs:
                prediction = predict_rows(model, data['dev'], vocab, device, args.batch_size)
                record['dev'] = sliced_metrics(data['dev'], prediction, flags['dev'])
                score = record['dev']['nonoverlap_with_train']['gloss_error_rate']
                if score is None:
                    raise ValueError('No nonoverlapping dev examples for checkpoint selection')
                if score < best:
                    best, best_epoch, stale = score, epoch, 0
                    selected_path = output / 'checkpoints' / f'epoch-{epoch:03d}.pt'
                    torch.save({name: value.detach().cpu() for name, value in model.state_dict().items()}, selected_path)
                else:
                    stale += 1
            record['epoch_seconds'] = time.monotonic() - epoch_start
            with (output / 'training.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            write_json(output / 'progress.json', {**record, 'status': 'running', 'best_epoch': best_epoch})
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if stale >= args.patience:
                break
        model.load_state_dict(torch.load(selected_path, map_location=device, weights_only=True))
        selected_weights = weights_hash(model)
        if selected_weights == initial_weights:
            raise ValueError('Model weights did not change')
        final_metrics = {}
        for split in selected_splits:
            rows = data[split]
            predicted = predict_rows(model, rows, vocab, device, args.batch_size)
            baseline_predictions = [baseline.predict(r['proposed_text']) for r in rows]
            final_metrics[split] = {
                'transformer': sliced_metrics(rows, predicted, flags[split]),
                'literal_lexicon_baseline': sliced_metrics(rows, baseline_predictions, flags[split]),
                'unseen_target_types': sorted({t for r in rows for t in r['gloss_sequence']} - set(vocab['target'])),
            }
            with (output / f'{split}-predictions.jsonl').open('x', encoding='utf-8') as stream:
                for row, tokens, literal, flag in zip(rows, predicted, baseline_predictions, flags[split]):
                    stream.write(json.dumps({'id': row['id'], 'text': row['proposed_text'],
                                             'reference': row['gloss_sequence'], 'predicted': tokens,
                                             'literal_baseline': literal, 'overlap_reasons': flag['reasons'],
                                             'can_play': False, 'human_approved': False}, ensure_ascii=False) + '\n')
        for name, checksum in inputs.items():
            if sha(library / name) != checksum:
                raise ValueError('Training source changed during experiment')
        if sha(Path(__file__)) != metadata['training_tool_sha256']:
            raise ValueError('Training code changed during experiment')
        metadata.update({'status': 'completed', 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
                         'elapsed_seconds': time.monotonic() - started, 'epochs_completed': epoch,
                         'optimizer_steps': steps, 'selected_epoch': best_epoch,
                         'checkpoint': selected_path.relative_to(output).as_posix(),
                         'checkpoint_sha256': sha(selected_path), 'selected_weights_sha256': selected_weights,
                         'new_model_weights_updated': True, 'text_to_gloss_trained': True,
                         'test_evaluated_after_checkpoint_selection': not args.skip_test,
                         'evaluation': final_metrics})
        write_json(output / 'report.json', metadata)
        write_json(output / 'progress.json', {'status': 'completed', 'epochs_completed': epoch, 'selected_epoch': best_epoch})
        write_json(output / 'model.json', {key: metadata[key] for key in ['schema', 'checkpoint', 'checkpoint_sha256',
                                                                        'config', 'research_only', 'text_to_motion_trained',
                                                                        'video_recognition_trained', 'deployment_ready',
                                                                        'training_ready', 'model_training_ready']})
        (output / 'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.relative_to(output).as_posix()}\n'
                                                 for path in sorted(output.rglob('*')) if path.is_file()), encoding='utf-8')
        print(json.dumps({'status': 'completed', 'output': str(output), 'selected_epoch': best_epoch,
                          'evaluation': final_metrics}, ensure_ascii=False), flush=True)
        return metadata
    except Exception as error:
        metadata.update({'status': 'failed', 'error': repr(error), 'optimizer_steps': steps})
        write_json(output / 'report.json', metadata)
        raise


def infer(model_root, text):
    import torch
    root = Path(model_root).resolve()
    metadata = json.loads((root / 'model.json').read_text(encoding='utf-8'))
    checkpoint = root / metadata['checkpoint']
    if (not checkpoint.resolve().is_relative_to(root) or checkpoint.is_symlink()
            or sha(checkpoint) != metadata['checkpoint_sha256']):
        raise ValueError('Checkpoint digest/path differs')
    normalized = normalize(text)
    if not 1 <= len(normalized) <= 126:
        raise ValueError('Expected nonempty text of at most 126 normalized characters')
    vocab = json.loads((root / 'vocab.json').read_text(encoding='utf-8'))
    torch.set_num_threads(4)
    model = make_model(vocab, metadata['config'])
    model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True))
    source, _ = batch_tensors([{'proposed_text': text, 'gloss_sequence': []}], vocab, torch.device('cpu'))
    return {'schema': 'signbridge-ce-csl-gloss-prediction-v1', 'input': text,
            'gloss_candidate': greedy_decode(model, source, vocab)[0],
            'checkpoint_sha256': metadata['checkpoint_sha256'],
            'unseen_input_characters': sorted(set(normalized) - set(vocab['source'])),
            'status': 'research_candidate_only', 'can_play': False,
            'human_approved': False, 'text_to_motion_trained': False,
            'note': 'Uncalibrated text-to-gloss candidate; no video recognition or avatar motion generation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fit = sub.add_parser('train')
    fit.add_argument('--library', type=Path, required=True)
    fit.add_argument('--output', type=Path, required=True)
    fit.add_argument('--research-only', action='store_true')
    fit.add_argument('--epochs', type=int, default=40)
    fit.add_argument('--batch-size', type=int, default=64)
    fit.add_argument('--learning-rate', type=float, default=.0007)
    fit.add_argument('--seed', type=int, default=20261022)
    fit.add_argument('--threads', type=int, default=4)
    fit.add_argument('--device', choices=['cuda', 'mps', 'cpu'], default='cuda')
    fit.add_argument('--evaluate-every', type=int, default=2)
    fit.add_argument('--patience', type=int, default=6)
    fit.add_argument('--initialize-from-model', type=Path,
                     help='Initialize model weights from a compatible research model directory; optimizer state is not restored.')
    fit.add_argument('--skip-test', action='store_true',
                     help='Verify test split bytes but do not parse labels, evaluate, or save test predictions.')
    prediction = sub.add_parser('predict')
    prediction.add_argument('--model', type=Path, required=True)
    prediction.add_argument('--text', required=True)
    args = parser.parse_args()
    if args.command == 'train':
        train(args)
    else:
        print(json.dumps(infer(args.model, args.text), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
