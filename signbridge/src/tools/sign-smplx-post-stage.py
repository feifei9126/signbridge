#!/usr/bin/env python3
"""Freeze pending review; consolidate only complete, numerically quiet candidates.

No model fitting, training features, smoothing, semantic approval or Demo changes.
Each output is new. Native arrays retain exact dtype/shape/value/frame order.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile

import numpy as np


HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_tool = load('stage_audit', 'sign-smplx-post-audit.py')
review_tool = load('stage_review', 'sign-smplx-post-review.py')
FLAGS = {**review_tool.FLAGS, 'feature_extraction_allowed': False,
         'missing_frames_filled': False, 'demo_integration_ready': False}
SHAPES = {'global_orient': (1, 3), 'body_pose': (21, 3),
          'left_hand_pose': (15, 3), 'right_hand_pose': (15, 3),
          'jaw_pose': (1, 3), 'leye_pose': (1, 3), 'reye_pose': (1, 3),
          'betas': (1, 10), 'expression': (1, 10), 'transl': (1, 3)}
ROTATIONS = ('global_orient', 'jaw_pose', 'leye_pose', 'reye_pose')
TIERS = audit_tool.TIERS
sha = review_tool.sha256
contained = audit_tool.contained
require = audit_tool.require


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def partition(rows):
    manual, eligible, seen = [], [], set()
    for row in rows:
        uid = row.get('uid')
        require(isinstance(uid, str) and uid and uid not in seen, 'Missing/duplicate UID')
        seen.add(uid)
        for key, expected in FLAGS.items():
            require(row.get(key, expected) == expected, 'Unconfirmed candidate flag differs: ' + key)
        require(row.get('quality_tier') in TIERS, 'Unknown quality tier')
        n, fps = row.get('frames_expected'), row.get('fps')
        require(type(n) is int and n > 0, 'Invalid native frame count')
        require(type(fps) in (int, float) and math.isfinite(fps) and fps > 0, 'Invalid FPS')
        if row['quality_tier'] == 'no_automatic_motion_red_flag':
            require(row.get('missing_detection_frames') == [] and row.get('technical_errors') == []
                    and row.get('motion_review_flags') == [], 'Automatic candidate has unresolved errors')
            eligible.append(row)
        else:
            manual.append(row)
    return manual, eligible


@lru_cache(maxsize=128)
def manifest_entries(manifest):
    result = {}
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        audit_tool.relative_path(name)
        require(name not in result and len(digest) == 64 and
                all(c in '0123456789abcdef' for c in digest), 'Invalid source manifest')
        result[name] = digest
    return result


def read_native(row):
    fit = Path(row['fit_directory'])
    attempt = fit.parent.parent
    manifest = contained(attempt, 'SHA256SUMS')
    inventory = manifest_entries(manifest)
    n = row['frames_expected']
    arrays, sources = {key: [] for key in SHAPES}, []
    for folder, suffix in (('smplx', '.npz'), ('meta', '.json')):
        directory = contained(fit, folder, directory=True)
        require({p.name for p in directory.iterdir()} == {f'{i:05d}_0{suffix}' for i in range(1, n + 1)},
                'Exact native/metadata frame set differs')
    for frame in range(1, n + 1):
        for folder, suffix in (('smplx', '.npz'), ('meta', '.json')):
            file = contained(fit, f'{folder}/{frame:05d}_0{suffix}')
            relative = file.relative_to(attempt).as_posix()
            digest = sha(file)
            require(inventory.get(relative) == digest, 'Source hash mismatch: ' + relative)
            sources.append({'path': relative, 'sha256': digest})
        file = fit / 'smplx' / f'{frame:05d}_0.npz'
        with np.load(file, allow_pickle=False) as values:
            require(set(values.files) == set(SHAPES), 'Unexpected native parameter keys')
            for key, shape in SHAPES.items():
                value = values[key]
                require(value.shape == shape and value.dtype.kind == 'f' and np.isfinite(value).all(),
                        'Invalid full native parameter: ' + key)
                require(not arrays[key] or arrays[key][0].dtype == value.dtype, 'Native dtype changes within clip')
                arrays[key].append(value.copy())
    arrays = {key: np.stack(values) for key, values in arrays.items()}
    arrays['frame_ids_1based'] = np.arange(1, n + 1, dtype=np.int64)
    rotations, flags = {}, []
    for key in ROTATIONS:
        metric = audit_tool.rotation_metrics(arrays[key].reshape(n, -1, 3))
        rotations[key] = metric
        if metric['max_adjacent_deg'] is not None and metric['max_adjacent_deg'] > 90:
            flags.append(key + ':adjacent_over_90deg')
        if metric['midpoint_residual_max_deg'] is not None and metric['midpoint_residual_max_deg'] > 30:
            flags.append(key + ':midpoint_over_30deg')
    if n < 3:
        flags.append('insufficient_frames_for_temporal_check')
    diagnostics = {}
    for key in ('transl', 'betas', 'expression'):
        steps = np.linalg.norm(np.diff(arrays[key].reshape(n, -1).astype(np.float64), axis=0), axis=1)
        diagnostics[key] = {'max_adjacent_l2': float(steps.max()) if steps.size else None,
                            'adjacent_l2_p95': float(np.percentile(steps, 95)) if steps.size else None,
                            'meaning': 'raw numeric change only; not a collision or semantic test'}
    return arrays, sources, {'raw_extra_rotation_metrics': rotations, 'raw_numeric_diagnostics': diagnostics,
                            'additional_rotation_flags': flags, 'thresholds': audit_tool.THRESHOLDS,
                            'source_manifest_sha256': sha(manifest)}


def content_hash(arrays, fps):
    digest = hashlib.sha256(float(fps).hex().encode())
    for key, array in sorted(arrays.items()):
        value = np.ascontiguousarray(array)
        descriptor = json.dumps([key, value.dtype.str, list(value.shape)], separators=(',', ':')).encode()
        digest.update(len(descriptor).to_bytes(8, 'big'))
        digest.update(descriptor)
        digest.update(value.tobytes())
    return digest.hexdigest()


def seal(root):
    files = sorted(p for p in root.rglob('*') if p.is_file() and p != root / 'SHA256SUMS')
    (root / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(root).as_posix()}\n' for p in files))


def archive(root):
    target = root.with_suffix('.zip')
    require(not target.exists(), 'Archive already exists')
    files = sorted(p for p in root.rglob('*') if p.is_file())
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as output:
        for file in files:
            require(not file.is_symlink(), 'Archive symlink refused')
            output.write(file, root.name + '/' + file.relative_to(root).as_posix())
    entries = manifest_entries(root / 'SHA256SUMS')
    with zipfile.ZipFile(target) as packed:
        require(set(packed.namelist()) == {root.name + '/' + p.relative_to(root).as_posix() for p in files}
                and len(packed.namelist()) == len(files), 'Archive member set differs')
        require(packed.read(root.name + '/SHA256SUMS') == (root / 'SHA256SUMS').read_bytes(),
                'Archived manifest differs')
        for name, expected in entries.items():
            digest = hashlib.sha256()
            with packed.open(root.name + '/' + name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            require(digest.hexdigest() == expected, 'Archived internal hash mismatch: ' + name)
    digest = sha(target)
    target.with_suffix('.zip.sha256').write_text(f'{digest}  {target.name}\n')
    return {'archive': str(target), 'sha256': digest, 'bytes': target.stat().st_size,
            'verified_files': len(entries), 'verified_archive_members': len(files)}


def copy_review(rows, source_root, source_report, output, purpose):
    output.mkdir(parents=True)
    records = []
    for row in rows:
        record = json.loads(json.dumps(row))
        for media in record['media'].values():
            require(isinstance(media, dict), 'Missing previously generated review media')
            file = contained(source_root, media['path'])
            require(sha(file) == media['sha256'], 'Frozen media hash mismatch')
            target = output / media['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
            require(sha(target) == media['sha256'], 'Copied media hash mismatch')
        record.update(FLAGS)
        record['flags'] = dict(FLAGS)
        records.append(record)
    summary = {'total_records': len(records), 'successful_candidates': len(records),
               'failed_candidates': 0, 'successful_media': len(records) * 3, 'failure_count': 0,
               'frames_expected': sum(r['frames_expected'] for r in records),
               'processed_frames': sum(r['processed_frames'] for r in records),
               'quarantined_candidates': sum(bool(r['missing_detection_frames']) for r in records), **FLAGS}
    report = {**{k: v for k, v in source_report.items() if k not in ('records', 'summary')},
              'purpose': purpose, 'summary': summary, 'records': records, **FLAGS}
    write_json(output / 'report.json', report)
    for name in ('index.html', 'review.js', 'review.css'):
        file = contained(source_root, name)
        expected = manifest_entries(source_root / 'SHA256SUMS').get(name)
        require(sha(file) == expected, 'Frozen review application hash mismatch')
        shutil.copyfile(file, output / name)
    (output / 'review-data.js').write_text(
        'globalThis.SIGNBRIDGE_POST_FIT_LOCALES=' + review_tool.safe_json(review_tool.scoped_locales()) + ';\n'
        'globalThis.SIGNBRIDGE_POST_FIT_REVIEW=' + review_tool.safe_json(report) + ';\n')
    return report


def build(audit_path, review_root, output):
    audit_path, review_root, output = Path(audit_path).resolve(), Path(review_root).resolve(), Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'Output must be a new directory')
    require(not output.resolve().is_relative_to(review_root) and not review_root.is_relative_to(output.resolve()),
            'Output overlaps review input')
    data = audit_tool.read_json(audit_path)
    review = audit_tool.read_json(review_root / 'report.json')
    require(data.get('audit_complete') is True and data.get('status') == 'audit_completed_pending_human_review',
            'Expected a completed, unapproved audit')
    require(review.get('audit_sha256') == sha(audit_path), 'Review and audit hashes differ')
    require(sha(review_root / 'report.json') == manifest_entries(review_root / 'SHA256SUMS').get('report.json'),
            'Frozen review report hash mismatch')
    manual, eligible = partition(data['records'])
    media = {r['uid']: r for r in review['records']}
    require(len(media) == len(review['records']) and set(media) == {r['uid'] for r in data['records']},
            'Audit/review ID coverage differs')
    output.mkdir(parents=True)
    native_root = output / 'technical-round' / 'native'
    native_root.mkdir(parents=True)
    records, extra, failures, seen_content = [], [], [], {}
    aliases_by_chunk = {}
    for index, row in enumerate(eligible):
        try:
            arrays, sources, metrics = read_native(row)
            if metrics['additional_rotation_flags']:
                extra.append({**row, 'source_quality_tier': row['quality_tier'],
                              'quality_tier': 'high_priority_motion_review',
                              'additional_technical_check': metrics})
                continue
            chunk = row['chunk']
            if chunk not in aliases_by_chunk:
                chunks = Path(data['results']) / 'chunks'
                file = contained(chunks, chunk + '/aliases.jsonl')
                require(sha(file) == manifest_entries(chunks / chunk / 'SHA256SUMS').get('aliases.jsonl'),
                        'Alias manifest mismatch')
                aliases_by_chunk[chunk] = [json.loads(line) for line in file.read_text().splitlines() if line.strip()]
            aliases = [a for a in aliases_by_chunk[chunk] if a['fit_sequence_id'] == row['annotation_id']]
            require(bool(aliases) and all(a['source_sha256'] == row['source_sha256'] and
                    a.get('human_approved') is False and a.get('text_verified') == '' for a in aliases),
                    'Alias identity/approval mismatch')
            digest = content_hash(arrays, row['fps'])
            target = native_root / (digest + '.npz')
            duplicate = seen_content.get(digest)
            if duplicate is None:
                np.savez_compressed(target, **arrays)
                with np.load(target, allow_pickle=False) as saved:
                    require(set(saved.files) == set(arrays), 'Saved native keys differ')
                    for key, value in arrays.items():
                        require(saved[key].dtype == value.dtype and np.array_equal(saved[key], value),
                                'Saved native array differs')
                seen_content[digest] = row['uid']
            record = {**row, **FLAGS, 'aliases': aliases, 'native_source_files': sources,
                      'native_content_sha256': digest, 'native_asset': 'native/' + target.name,
                      'native_asset_sha256': sha(target), 'exact_duplicate_of': duplicate,
                      'parameter_shapes': {k: list(v.shape) for k, v in arrays.items()},
                      'parameter_dtypes': {k: v.dtype.str for k, v in arrays.items()},
                      'technical_check': metrics, 'source_parameters_modified': False,
                      'semantic_status': 'unverified', 'collision_status': 'unassessed',
                      'library_status': 'raw_native_candidate_for_technical_research'}
            records.append(record)
        except Exception as error:
            failures.append({'uid': row['uid'], 'error': str(error)})
            extra.append({**row, 'source_quality_tier': row['quality_tier'], 'quality_tier': 'technical_error',
                          'additional_technical_error': str(error)})
        finally:
            if (index + 1) % 20 == 0 or index + 1 == len(eligible):
                print(json.dumps({'checked': index + 1, 'eligible': len(eligible),
                                  'retained': len(records), 'sent_to_review': len(extra)}, separators=(',', ':')),
                      flush=True)
    pending = manual + extra
    manual_rows = []
    for row in pending:
        item = {**media[row['uid']], 'quality_tier': row['quality_tier']}
        for key in ('source_quality_tier', 'additional_technical_check', 'additional_technical_error'):
            if key in row:
                item[key] = row[key]
        manual_rows.append(item)
    manual_root = output / 'manual-review'
    copy_review(manual_rows, review_root, review, manual_root, 'pending_review_frozen_no_followup_scheduled')
    with (manual_root / 'review-decisions.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        fields = ['uid', 'label_candidate', 'quality_tier', 'comparison_video', 'motion_decision',
                  'meaning_decision', 'boundary_decision', 'mirror_handedness', 'reviewer', 'notes']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({**{k: r[k] for k in fields[:3]},
                         'comparison_video': r['media']['comparison']['path']} for r in manual_rows)
    (manual_root / 'README.txt').write_text(
        f'人工审阅暂存包：{len(pending)}段。解压后打开 index.html。\n'
        '包含原片、原片/网格对照视频、关键帧、原始风险指标；漏检仍保留。\n'
        'review-decisions.csv 的审阅栏为空，按实际结果填写；不预置批准。\n'
        '仅暂存，待审阅后另开新轮次。本包没有后续训练或处理计划。\n'
        '标签、词界、镜像、手性、人物身份仍未核准。原始证据保留在原交付目录。\n', encoding='utf-8')
    technical = output / 'technical-round'
    copy_review([media[r['uid']] for r in records], review_root, review, technical / 'evidence',
                'raw_native_candidate_technical_preparation_only')
    summary = {'input_sequences': len(data['records']), 'initial_manual_review': len(manual),
               'initial_automatic_candidates': len(eligible), 'new_review_risks': len(extra),
               'manual_review_sequences': len(pending), 'technical_candidate_sequences': len(records),
               'technical_frames': sum(r['frames_expected'] for r in records),
               'unique_native_assets': len(seen_content),
               'exact_native_duplicates': sum(r['exact_duplicate_of'] is not None for r in records),
               'candidate_aliases': sum(len(r['aliases']) for r in records),
               'distinct_unverified_labels': len({a['label_candidate'] for r in records for a in r['aliases']}),
               'technical_errors': len(failures), **FLAGS}
    require(len(pending) + len(records) == len(data['records']) and
            not ({r['uid'] for r in pending} & {r['uid'] for r in records}), 'Partition coverage differs')
    provenance = {'audit_sha256': sha(audit_path), 'review_report_sha256': sha(review_root / 'report.json'),
                  'tool_sha256': sha(Path(__file__)), 'audit_tool_sha256': sha(HERE / 'sign-smplx-post-audit.py'),
                  'input_index_sha256': data.get('input_index_sha256'),
                  'legacy_provenance': 'Inherited without upgrading: attempt_proofs_verified=' +
                  str(data['summary'].get('attempt_proofs_verified'))}
    library = {'schema': 'signbridge-native-candidate-library-v1', 'summary': summary,
               'provenance': provenance, 'records': records, 'failures': failures, **FLAGS}
    write_json(technical / 'index.json', library)
    (technical / 'README.txt').write_text(
        f'技术整理已完成：{len(records)}段、{summary["technical_frames"]}帧。\n'
        'native/ 是逐帧原始参数的无损堆叠，保留 dtype、形状、帧号、手部、面部和位移。\n'
        '只合并全参数、帧率及数据类型完全相同的文件；同文字不等于同动作。\n'
        'index.json 保留来源文件哈希、全部别名及额外根部/颌部/眼部时序检查。\n'
        '未做平滑、补帧或训练特征提取；没有训练模型或接入 Demo。\n'
        '自动阈值未触发不代表零抖动、无穿插或手语表达正确，语义/词界仍待核准。\n', encoding='utf-8')
    seal(manual_root)
    seal(technical)
    archives = [archive(manual_root), archive(technical)]
    report = {'schema': 'signbridge-post-fit-partition-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'status': 'manual_frozen_technical_preparation_completed', 'summary': summary,
              'provenance': provenance, 'manual_uids': [r['uid'] for r in pending],
              'technical_uids': [r['uid'] for r in records], 'additional_review_records': extra,
              'archives': archives, **FLAGS}
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = build(args.audit, args.review, args.output)
    except Exception as error:
        print(json.dumps({'error': str(error), **FLAGS}), file=sys.stderr)
        return 2
    print(json.dumps(result['summary'], ensure_ascii=False))
    return 2 if result['summary']['technical_errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
