"""Compare hash-bound CE-CSL dev predictions; no training, inference or test reads."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

_spec = importlib.util.spec_from_file_location('ce_gloss_contract',
                                             Path(__file__).with_name('sign-ce-csl-gloss.py'))
gloss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gloss)


def align(reference, prediction):
    """Minimum edit alignment; tie order matches the existing training metric."""
    n, m = len(reference), len(prediction)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        table[i][0] = i
    for j in range(m + 1):
        table[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            table[i][j] = min(table[i - 1][j - 1] + (reference[i - 1] != prediction[j - 1]),
                              table[i - 1][j] + 1, table[i][j - 1] + 1)
    i, j, operations = n, m, []
    while i or j:
        if i and j and reference[i - 1] == prediction[j - 1] and table[i][j] == table[i - 1][j - 1]:
            kind, r, h = 'match', reference[i - 1], prediction[j - 1]
            i -= 1; j -= 1
        elif i and j and table[i][j] == table[i - 1][j - 1] + 1:
            kind, r, h = 'substitution', reference[i - 1], prediction[j - 1]
            i -= 1; j -= 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            kind, r, h = 'deletion', reference[i - 1], None
            i -= 1
        else:
            kind, r, h = 'insertion', None, prediction[j - 1]
            j -= 1
        operations.append({'operation': kind, 'reference': r, 'predicted': h})
    return list(reversed(operations))


def is_number(token):
    return bool(re.fullmatch(r'(?:[0-9]+(?:[.,][0-9]+)?|[零〇一二三四五六七八九十百千万亿两]+)', token))


def variant_surface(token):
    return re.sub(r'(?<=[^0-9])[0-9]+$', '', token) if not is_number(token) else token


def diagnose(reference, prediction, frequencies):
    operations = align(reference, prediction)
    counts = Counter(x['operation'] for x in operations)
    adjacent = lambda seq: sum(a == b for a, b in zip(seq, seq[1:]))
    return {
        'substitutions': counts['substitution'], 'deletions': counts['deletion'],
        'insertions': counts['insertion'],
        'edit_errors': sum(counts[k] for k in ['substitution', 'deletion', 'insertion']),
        'exact_match': reference == prediction, 'predicted_length': len(prediction),
        'order_only_clue': reference != prediction and Counter(reference) == Counter(prediction),
        'adjacent_repeat_excess': max(0, adjacent(prediction) - adjacent(reference)),
        'variant_surface_confusions': sum(x['operation'] == 'substitution'
            and variant_surface(x['reference']) == variant_surface(x['predicted']) for x in operations),
        'rare_reference_error_occurrences': sum(x['reference'] is not None
            and 0 < frequencies[x['reference']] <= 2 and x['operation'] != 'match' for x in operations),
        'unseen_reference_error_occurrences': sum(x['reference'] is not None
            and frequencies[x['reference']] == 0 and x['operation'] != 'match' for x in operations),
        'numeric_reference_error_occurrences': sum(x['reference'] is not None
            and is_number(x['reference']) and x['operation'] != 'match' for x in operations),
        'operations': operations,
    }


def pooled(rows):
    return gloss.metrics([x['reference'] for x in rows], [x['predicted'] for x in rows])


def csv_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def regular_file(root, name):
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise ValueError('Unsafe input path: ' + name)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Input symlink rejected: ' + name)
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('Unsafe or missing input file: ' + name)
    return path


def checked_read(root, name, manifest, consumed):
    path = regular_file(root, name)
    if gloss.sha(path) != manifest.get(name):
        raise ValueError('Input digest/path differs: ' + name)
    consumed[str(path)] = manifest[name]
    return path.read_text(encoding='utf-8')


def read_manifest(root, consumed):
    path = regular_file(root, 'SHA256SUMS')
    consumed[str(path)] = gloss.sha(path)
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        if name in result or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid/duplicate manifest entry')
        result[name] = digest
    return result


def read_run(root, train, dev, input_hashes, consumed):
    manifest = read_manifest(root, consumed)
    read = lambda name: checked_read(root, name, manifest, consumed)
    report = json.loads(read('report.json'))
    if (report.get('schema') != 'signbridge-ce-csl-text-to-gloss-v1'
            or report.get('status') != 'completed' or report.get('research_only') is not True
            or report.get('deployment_ready') is not False):
        raise ValueError('Expected completed research model report')
    if any(report.get('source_files_sha256', {}).get(k) != v for k, v in input_hashes.items()):
        raise ValueError('Run dataset digests differ from analyzed train/dev')
    vocab = json.loads(read('vocab.json'))
    if vocab != gloss.build_vocab(train):
        raise ValueError('Run vocabulary differs from train-only vocabulary')
    checkpoint = report.get('checkpoint')
    if (not isinstance(checkpoint, str) or not re.fullmatch(r'checkpoints/[a-zA-Z0-9_-]+\.pt', checkpoint)
            or manifest.get(checkpoint) != report.get('checkpoint_sha256')):
        raise ValueError('Selected checkpoint digest/path differs')
    # Hash only: never deserialize model weights or import a training runtime.
    path = regular_file(root, checkpoint)
    if gloss.sha(path) != manifest.get(checkpoint):
        raise ValueError('Selected checkpoint digest/path differs')
    consumed[str(path)] = manifest[checkpoint]
    rows = [json.loads(line) for line in read('dev-predictions.jsonl').splitlines() if line.strip()]
    if len(rows) != len(dev):
        raise ValueError('Dev prediction count differs')
    flags = gloss.overlap_flags(train, dev)
    target = set(vocab['target']) - {'<pad>', '<bos>', '<eos>'}
    for row, expected, flag in zip(rows, dev, flags):
        if (row.get('id') != expected['id'] or row.get('text') != expected['proposed_text']
                or row.get('reference') != expected['gloss_sequence']
                or row.get('overlap_reasons') != flag['reasons']
                or row.get('can_play') is not False or row.get('human_approved') is not False
                or not isinstance(row.get('predicted'), list)
                or any(not isinstance(t, str) or t not in target for t in row['predicted'])):
            raise ValueError('Prediction identity/reference/metadata differs from dev')
    actual = gloss.sliced_metrics(dev, [x['predicted'] for x in rows], flags)
    if actual != report.get('evaluation', {}).get('dev', {}).get('transformer'):
        raise ValueError('Saved dev metrics differ from raw-label recomputation')
    return rows


def slice_tags(row, frequencies):
    reference = row['reference']
    tags = ['official_all']
    if not row['overlap_reasons']:
        tags.append('nonoverlap_with_train')
    if any(is_number(t) for t in reference):
        tags.append('numeric_reference')
    if any(0 < frequencies[t] <= 2 for t in reference):
        tags.append('rare_reference_train_count_le2')
    if any(frequencies[t] == 0 for t in reference):
        tags.append('unseen_reference')
    if any(variant_surface(t) != t for t in reference):
        tags.append('numbered_variant_reference')
    if any(variant_surface(t) in {'不', '没', '没有', '不是', '不能', '不要', '不想', '不用'} for t in reference):
        tags.append('negation_label_clue')
    if len(reference) <= 3:
        tags.append('short_reference_le3')
    if len(reference) >= 6:
        tags.append('long_reference_ge6')
    return tags


def analyze(library, prior, continuation, output):
    paths = [Path(x).absolute() for x in [library, prior, continuation]]
    if any(x.is_symlink() for x in paths):
        raise ValueError('Input roots cannot be symlinks')
    library, prior, continuation = [x.resolve() for x in paths]
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError('Choose a NEW diagnostic output directory')
    resolved = output.resolve()
    if any(resolved == p or resolved in p.parents or p in resolved.parents for p in [library, prior, continuation]):
        raise ValueError('Diagnostic output overlaps inputs')
    consumed = {}
    manifest = read_manifest(library, consumed)
    data, hashes, ids = {}, {}, set()
    # Deliberately no call to read_data(): it hashes test bytes even with skip-test.
    for split in ['train', 'dev']:
        name = f'splits/{split}/samples.jsonl'
        data[split] = [gloss.validate_sample(json.loads(x), split) for x in
                       checked_read(library, name, manifest, consumed).splitlines() if x.strip()]
        if not data[split]:
            raise ValueError('Empty train/dev split')
        hashes[name] = manifest[name]
        for row in data[split]:
            if row['id'] in ids:
                raise ValueError('Duplicate train/dev identity')
            ids.add(row['id'])
    runs = {name: read_run(path, data['train'], data['dev'], hashes, consumed)
            for name, path in [('prior', prior), ('continuation', continuation)]}
    frequencies = Counter(t for row in data['train'] for t in row['gloss_sequence'])
    cases, confusion = [], {name: Counter() for name in runs}
    for a, b in zip(runs['prior'], runs['continuation']):
        case = {'id': a['id'], 'text': a['text'], 'reference': a['reference'],
                'slices': slice_tags(a, frequencies), 'overlap_reasons': a['overlap_reasons'],
                'can_play': False, 'human_approved': False}
        for name, row in [('prior', a), ('continuation', b)]:
            info = diagnose(row['reference'], row['predicted'], frequencies)
            case[name] = {'predicted': row['predicted'], **info}
            if not row['overlap_reasons']:
                for op in info['operations']:
                    if op['operation'] != 'match':
                        confusion[name][(op['operation'], op['reference'], op['predicted'])] += 1
        delta = case['continuation']['edit_errors'] - case['prior']['edit_errors']
        case.update(edit_delta=delta, change='improved' if delta < 0 else 'regressed' if delta > 0 else 'tied')
        cases.append(case)
    comparison = {}
    for tag in sorted({t for case in cases for t in case['slices']}):
        selected = [x for x in cases if tag in x['slices']]
        counts = Counter(x['change'] for x in selected)
        item = {'samples': len(selected), **{k: counts[k] for k in ['improved', 'regressed', 'tied']}}
        for name in runs:
            rows = [{'reference': x['reference'], 'predicted': x[name]['predicted']} for x in selected]
            item[name] = {**pooled(rows),
                'predicted_tokens': sum(x[name]['predicted_length'] for x in selected),
                'shorter_than_reference': sum(x[name]['predicted_length'] < len(x['reference']) for x in selected),
                'longer_than_reference': sum(x[name]['predicted_length'] > len(x['reference']) for x in selected),
                'order_only_clue_rows': sum(x[name]['order_only_clue'] for x in selected),
                'adjacent_repeat_excess': sum(x[name]['adjacent_repeat_excess'] for x in selected),
                'variant_surface_confusions': sum(x[name]['variant_surface_confusions'] for x in selected),
                'rare_reference_error_occurrences': sum(x[name]['rare_reference_error_occurrences'] for x in selected),
                'unseen_reference_error_occurrences': sum(x[name]['unseen_reference_error_occurrences'] for x in selected),
                'numeric_reference_error_occurrences': sum(x[name]['numeric_reference_error_occurrences'] for x in selected),
                'max_predicted_length': max(x[name]['predicted_length'] for x in selected)}
            item[name]['common_reference_error_occurrences'] = (item[name]['substitutions']
                + item[name]['deletions'] - item[name]['rare_reference_error_occurrences']
                - item[name]['unseen_reference_error_occurrences'])
        comparison[tag] = item
    provenance = {'inputs_sha256': consumed, 'analysis_tool_sha256': gloss.sha(Path(__file__)),
                  'metric_tool_sha256': gloss.sha(Path(gloss.__file__)), 'test_read': False}
    report = {'schema': 'signbridge-ce-csl-dev-error-analysis-v1', 'status': 'completed',
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'rows_compared': len(cases),
        'test_read': False, 'training_started': False, 'training_ready': False,
        'model_training_ready': False, 'deployment_ready': False,
        'train_gloss_types': len(frequencies), 'train_gloss_tokens': sum(frequencies.values()),
        'train_single_occurrence_types': sum(n == 1 for n in frequencies.values()),
        'train_types_observed_le2': sum(n <= 2 for n in frequencies.values()),
        'comparison': comparison,
        'limitations': ['Dev was used for checkpoint selection and this analysis; it is not an independent test.',
            'Slices overlap; do not add their row counts or edit errors.',
            'Edit alignment has ties; token-level error attribution is diagnostic, not a unique linguistic analysis.',
            'Rare threshold <=2 is a descriptive slice, not a selected training hyperparameter.',
            'Variant surfaces are clues only; raw numbered labels remain distinct in all metrics.',
            'Order/repetition/negation/number clues are not CSL meaning or word-boundary approval.']}
    top = {name: [{'operation': op, 'reference': r, 'predicted': h, 'count': count,
                  'reference_train_count': frequencies[r] if r is not None else None,
                  'predicted_train_count': frequencies[h] if h is not None else None}
                  for (op, r, h), count in counts.most_common(40)] for name, counts in confusion.items()}
    # Recheck only the consumed files before emitting output; test is never consumed.
    for name, checksum in consumed.items():
        path = Path(name)
        owner = next(p for p in [library, prior, continuation] if path.is_relative_to(p))
        path = regular_file(owner, path.relative_to(owner).as_posix())
        if gloss.sha(path) != checksum:
            raise ValueError('Diagnostic source changed during analysis')
    output.mkdir(parents=True)
    for name, value in [('report.json', report), ('source-provenance.json', provenance), ('top-confusions.json', top)]:
        gloss.write_json(output / name, value)
    with (output / 'cases.jsonl').open('x', encoding='utf-8') as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False, allow_nan=False) + '\n')
    with (output / 'cases.csv').open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'text', 'reference', 'prior', 'continuation', 'prior_errors', 'continuation_errors', 'edit_delta', 'change', 'slices'])
        for case in cases:
            writer.writerow([csv_cell(v) for v in [case['id'], case['text'], '/'.join(case['reference']),
                '/'.join(case['prior']['predicted']), '/'.join(case['continuation']['predicted']),
                case['prior']['edit_errors'], case['continuation']['edit_errors'], case['edit_delta'],
                case['change'], ','.join(case['slices'])]])
    table = ['# CE-CSL Dev 错误分析', '', '仅分析已保存的 dev 预测；不读取 test、不训练、不加载模型、不更改批准。', '',
             '| 切片 | 条数 | 首轮错误率 | 续训错误率 | 改善/退步/持平 |',
             '|---|---:|---:|---:|---|']
    for tag, item in comparison.items():
        table.append(f"| {tag} | {item['samples']} | {item['prior']['gloss_error_rate']:.2%} | {item['continuation']['gloss_error_rate']:.2%} | {item['improved']}/{item['regressed']}/{item['tied']} |")
    table += ['', '切片重叠不可相加。编号标签不合并；编辑对齐有并列路径，词级归因仅为线索。',
              '逐句详情见 cases.csv / cases.jsonl；来源摘要见 source-provenance.json。',
              '不把 dev 分析当独立泛化评估，不由重复/语序线索自动修改 Gloss 或审批状态。', '']
    (output / 'REPORT.md').write_text('\n'.join(table), encoding='utf-8')
    (output / 'SHA256SUMS').write_text(''.join(f'{gloss.sha(p)}  {p.name}\n'
        for p in sorted(output.iterdir()) if p.is_file()), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--continuation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.library, args.prior, args.continuation, args.output)
    print(json.dumps({'status': report['status'], 'rows_compared': report['rows_compared'],
                      'test_read': False, 'training_started': False, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
