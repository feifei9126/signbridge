#!/usr/bin/env python3
"""Snapshot six-batch semantic gaps and verify existing tutorial asset bytes.

This does not approve language labels, word boundaries or motion quality.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

FOCUS = {'去', '来', '今天', '昨天', '明天'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_artifact(root, artifact):
    relative = artifact.get('relative_path', '')
    path = (root / relative).resolve()
    if not relative or Path(relative).is_absolute() or not path.is_relative_to(root):
        return {'status': 'unsafe_path'}
    result = {'path': str(path), 'expected_sha256': artifact.get('sha256')}
    if not path.is_file():
        return {**result, 'status': 'missing'}
    actual = sha(path)
    return {**result, 'actual_sha256': actual, 'status': 'verified' if actual == artifact.get('sha256') else 'digest_mismatch'}


def run(report_path, reference_root, output, decode_focus=False):
    report_path, reference_root, output = Path(report_path).resolve(), Path(reference_root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    audit = json.loads(report_path.read_text())
    index = reference_root / 'fitting-reference-index.jsonl'
    references = [json.loads(line) for line in index.read_text().splitlines() if line.strip()]
    verified, queue = [], []
    for row in references:
        artifacts = {name: verify_artifact(reference_root, asset) for name, asset in row['artifacts'].items()}
        entry = {'annotation_id': row['annotation_id'], 'proposed_text': row['label'], 'source_sha256': row['source_sha256'],
                 'source_window_seconds': row.get('source_window_seconds'), 'artifacts': artifacts,
                 'human_approved': False, 'word_boundaries_verified': False, 'model_training_ready': False,
                 'original_source_video_rehashed': False}
        if decode_focus and row['label'] in FOCUS:
            video = artifacts.get('clip.mp4', {})
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise RuntimeError('ffmpeg required for --decode-focus')
            if video.get('status') == 'verified':
                result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', video['path'], '-f', 'null', '-'], capture_output=True, timeout=120)
                entry['clip_full_decode'] = {'passed': result.returncode == 0 and not result.stderr, 'exit_code': result.returncode,
                                             'stderr': result.stderr.decode(errors='replace')[:1000]}
        verified.append(entry)
        queue.append({'id': row['annotation_id'], 'kind': 'tutorial_word_or_step_candidate',
                      'proposed_text': row['label'], 'source_sha256': row['source_sha256'],
                      'source_window_seconds': row.get('source_window_seconds'),
                      'clip': artifacts.get('clip.mp4', {}).get('path'), 'text_verified': '', 'word_spans': [],
                      'signer_id': None, 'mirror_status': 'unknown', 'handedness': 'unconfirmed',
                      'nonmanuals': [], 'human_approved': False, 'training_ready': False, 'model_training_ready': False})
    for row in audit['records']:
        if row['kind'] not in ['native', 'reference2d']:
            continue
        complete = row['kind'] == 'native' and not row.get('errors') and not row.get('missing_frames') and not row.get('invalid_parameters')
        queue.append({'id': row['uid'], 'kind': row['kind'], 'source_batches': row['batches'],
                      'proposed_text': row.get('text', ''), 'clip': row.get('clip'), 'source_sha256': row.get('source_sha256'),
                      'source_window_seconds': row.get('source_window_seconds'),
                      'structurally_complete_native': bool(complete), 'structural_errors': row.get('errors', []),
                      'missing_frames': row.get('missing_frames', []), 'motion_risk_flags': row.get('risk_flags', []),
                      'semantic_status': 'not_reassessed_by_this_tool',
                      'text_verified': '', 'word_spans': [], 'signer_id': None,
                      'mirror_status': 'unknown', 'handedness': 'unconfirmed', 'nonmanuals': [],
                      'human_approved': False, 'training_ready': False, 'model_training_ready': False})
    counts = Counter(a['status'] for row in verified for a in row['artifacts'].values())
    summary = {'schema': 'signbridge-csl-semantic-readiness-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
               'audit': {'path': str(report_path), 'sha256': sha(report_path)},
               'tutorial_index': {'path': str(index), 'sha256': sha(index)},
               'counts_by_source_batch': audit['counts_by_source_batch'],
               'stage_record_counts': dict(Counter(r['kind'] for r in audit['records'])),
               'tutorial_candidates': len(references), 'tutorial_asset_checks': dict(counts),
               'review_queue_records': len(queue), 'tutorial_evidence': verified,
               'ready_word_aligned_csl_pairs_established_by_this_tool': 0,
               'text_verified': '', 'human_approved': False, 'training_ready': False, 'model_training_ready': False,
               'limitations': ['No labels, word spans, signer identity or split independence are invented.',
                               'Existing approvals remain in their original evidence; this queue does not revoke or extend them.',
                               'Stage counts are not unique words or sentences.',
                               'Asset hash/decode checks establish byte integrity, not CSL semantic correctness.',
                               'Original source videos were not rehashed by this tool; recorded source digests are provenance only.']}
    (output / 'readiness.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (output / 'alignment-review-queue.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in queue))
    (output / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(output.iterdir()) if p.is_file()))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--tutorial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--decode-focus', action='store_true')
    args = parser.parse_args()
    result = run(args.audit, args.tutorial, args.output, args.decode_focus)
    print(json.dumps({k: v for k, v in result.items() if k not in ['tutorial_evidence', 'counts_by_source_batch']}, ensure_ascii=False))
