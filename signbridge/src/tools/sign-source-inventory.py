"""Inventory a scanned intake against previous batches without self-matching."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def discover_manifests(dataset, excluded_roots):
    excluded = [Path(root).resolve() for root in excluded_roots]
    found = []
    for file in sorted(Path(dataset).resolve().rglob('*.json')):
        path = file.resolve()
        if any(path == root or root in path.parents for root in excluded):
            continue
        if any('training-master-report' in part or part.startswith('provenance-') for part in path.parts):
            continue
        if path.name in {'sources.json', 'inventory.json', 'source-registry.json'} or path.name.endswith('manifest.json'):
            found.append(path)
    return found


def classify(title):
    if re.search('中国手语VS美国|世界手语不一样|国际手语', title):
        return 'cross_language_or_international_unconfirmed'
    if re.search('舞蹈|手语舞|麦田之歌|这世界那么多人|世界赠予我的|感谢（手语版）', title):
        return 'song_or_choreography_candidate'
    if re.search('手形_[A-Za-z]|入手学习-字母', title):
        return 'handshape_or_alphabet_reference'
    if re.search('有何好处|看得清、听得懂|语序差别|手语鉴定|鉴定一下|如何避雷|质量的资源|高频问题|究竟在忙什么|Q[&＆]A', title, re.I):
        return 'explanation_or_service_unconfirmed'
    if '国家通用手语' in title:
        return 'standard_csl_tutorial_candidate'
    if '自然手语' in title:
        return 'regional_natural_sign_candidate'
    if re.search('金融|征信|银行卡|诈骗|消费者权益|国庆节', title):
        return 'continuous_topic_sign_candidate'
    if re.search('日常交流|自我介绍|问路|新年祝福|早上好|中午好|晚上好', title):
        return 'daily_sentence_or_word_candidate'
    return 'tutorial_content_unconfirmed'


def group_sources(sources, prior):
    grouped = defaultdict(list)
    for row in sources:
        checksum = row.get('sha256')
        if not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise ValueError('Source requires a SHA-256 digest')
        grouped[checksum].append(row)
    output = []
    for checksum, rows in grouped.items():
        rows = sorted(rows, key=lambda row: row['relative_path'])
        output.append({**rows[0], 'content_class': classify(rows[0]['relative_path']),
                       'same_content_paths': [row['relative_path'] for row in rows],
                       'duplicate_with_prior_registry': bool(prior.get(checksum)),
                       'prior_matches': prior.get(checksum, []), 'training_ready': False,
                       'human_approved': False, 'language': 'unconfirmed',
                       'signer_identity': 'unconfirmed', 'mirror_status': 'unknown', 'split': 'unassigned'})
    return output


def build(args):
    manifest_path, output = args.manifest.resolve(), args.output.resolve()
    intake = json.loads(manifest_path.read_text())
    source_root = Path(intake['source_root']).resolve()
    if output.exists() or output == source_root or source_root in output.parents:
        raise ValueError('Output must be new and separate from source videos')
    exclusions = args.exclude_root or [output.parent]
    files = discover_manifests(args.dataset, exclusions)
    prior, registries, skipped = defaultdict(list), [], []
    for path in files:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            skipped.append({'path': str(path), 'reason': str(error)})
            continue
        rows = data.get('sources', data.get('files', [])) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            continue
        count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            checksum = row.get('sha256', row.get('source_sha256'))
            if not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum):
                continue
            if not row.get('relative_path') and not row.get('source_id'):
                continue
            count += 1
            match = {'manifest': str(path), 'source_id': row.get('source_id'),
                     'relative_path': row.get('relative_path'), 'stage': row.get('stage', 'registered_source')}
            if match not in prior[checksum]:
                prior[checksum].append(match)
        if count:
            registries.append({'path': str(path), 'sha256': sha(path), 'source_rows': count})
    unique = group_sources(intake['sources'], prior)
    new = [row for row in unique if not row['duplicate_with_prior_registry']]
    excluded_classes = {'cross_language_or_international_unconfirmed', 'song_or_choreography_candidate',
                        'handshape_or_alphabet_reference', 'explanation_or_service_unconfirmed'}
    screenable = [row for row in new if row['content_class'] not in excluded_classes]
    summary = {'schema': 'signbridge-new-intake-inventory-v1',
               'created_at': datetime.now(timezone.utc).isoformat(), 'source_root': str(source_root),
               'scanned_video_files': len(intake['sources']), 'unique_content_hashes': len(unique),
               'same_batch_duplicate_paths': len(intake['sources']) - len(unique),
               'prior_duplicate_unique_sources': len(unique) - len(new), 'new_unique_sources': len(new),
               'new_screenable_sources': len(screenable),
               'total_bytes': sum(row['size_bytes'] for row in intake['sources']),
               'total_duration_seconds': sum(row['duration_seconds'] for row in intake['sources']),
               'new_source_classes': dict(Counter(row['content_class'] for row in new)),
               'intake_manifest_sha256': sha(manifest_path), 'prior_registry_manifests': registries,
               'registry_read_errors': skipped, 'excluded_current_roots': [str(Path(p).resolve()) for p in exclusions],
               'classification_basis': 'filename hints only; no language/semantics/signer approval',
               'source_files_modified': False, 'training_started': False, 'training_ready': False,
               'unique_sources': unique}
    output.mkdir(parents=True)
    for name, value in [('inventory.json', summary),
                        ('candidate-manifest.json', {'schema': 'signbridge-new-source-manifest-v1',
                         'source_root': str(source_root), 'sources': screenable, 'training_ready': False}),
                        ('all-new-source-manifest.json', {'schema': 'signbridge-new-source-manifest-v1',
                         'source_root': str(source_root), 'sources': new, 'training_ready': False})]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    (output/'exposed-tasks.jsonl').write_text(''.join(json.dumps({'source_id': values[0]['source_id'] or 'legacy-'+checksum[:16],
        'source_sha256': checksum}, ensure_ascii=False)+'\n' for checksum, values in sorted(prior.items()) if values))
    (output/'SHA256SUMS').write_text(''.join(sha(path)+'  '+path.name+'\n' for path in sorted(output.iterdir()) if path.is_file()))
    print(json.dumps({k: v for k, v in summary.items() if k not in {'unique_sources', 'prior_registry_manifests'}}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--exclude-root', type=Path, action='append')
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args())


if __name__ == '__main__':
    main()
