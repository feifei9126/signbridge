"""Import CE-CSL labels and video metadata into a separate, non-playable candidate library.

Standard library only. Original CSVs, gloss variants and dataset splits stay intact.
No frames, motion arrays, word boundaries, approvals or model weights are generated.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unicodedata

SPLITS = ('train', 'dev', 'test')
HEADERS = ['Number', 'Translator', 'Chinese Sentences', 'Gloss', 'Note']
CANDIDATE_FLAGS = {
    'human_approved': False, 'word_boundaries_verified': False,
    'training_ready': False, 'model_training_ready': False,
    'native_3d_available': False, 'can_play': False,
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(dumps(row) + '\n')


def contained(root, relative):
    path = root / relative
    if (Path(relative).is_absolute() or '..' in Path(relative).parts or '\\' in str(relative)
            or not path.resolve().is_relative_to(root)):
        raise ValueError('Unsafe source path: ' + str(relative))
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Source symlink rejected: ' + str(relative))
    return path


def gloss_tokens(raw):
    result = []
    for position, part in enumerate(raw.split('/')):
        label = part.strip()
        kind = ('empty' if not label else 'punctuation'
                if all(unicodedata.category(c).startswith('P') for c in label) else 'gloss')
        result.append({'position': position, 'raw': part, 'label': label, 'kind': kind})
    return result


def read_labels(root):
    rows, inputs, originals = [], [], {}
    for split in SPLITS:
        relative = f'label/{split}.csv'
        path = contained(root, relative)
        raw_bytes = path.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        inputs.append({'relative_path': relative, 'sha256': checksum, 'bytes': len(raw_bytes)})
        originals[relative] = raw_bytes
        reader = csv.reader(io.StringIO(raw_bytes.decode('utf-8-sig'), newline=''), strict=True)
        if next(reader, None) != HEADERS:
            raise ValueError('Unexpected CE-CSL CSV columns: ' + relative)
        identities = set()
        for number, fields in enumerate(reader, 1):
            if not fields:
                continue
            if len(fields) != len(HEADERS):
                raise ValueError(f'Wrong CSV field count: {relative}:{reader.line_num}')
            raw = dict(zip(HEADERS, fields))
            identity, translator = raw['Number'], raw['Translator']
            if (not re.fullmatch(re.escape(split) + r'-[0-9]+', identity)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', translator)
                    or identity in identities or not raw['Chinese Sentences'].strip()
                    or not raw['Gloss'].strip()):
                raise ValueError(f'Invalid or duplicated CSV identity/label: {relative}:{reader.line_num}')
            identities.add(identity)
            tokens = gloss_tokens(raw['Gloss'])
            rows.append({
                'schema': 'signbridge-ce-csl-sample-v1',
                'id': 'csl_ce_csl_' + identity.replace('-', '_'),
                'dataset': 'CE-CSL', 'source_id': identity,
                'source_split': split, 'source_translator': translator,
                'source_translator_scope': 'dataset_code_only_not_cross_dataset_identity',
                'source_label': {'relative_path': relative, 'sha256': checksum,
                                 'record_number': number, 'csv_line_end': reader.line_num,
                                 'record_sha256': hashlib.sha256(dumps(raw).encode('utf-8')).hexdigest()},
                'raw': raw, 'proposed_text': raw['Chinese Sentences'],
                'gloss_tokens': tokens,
                'gloss_sequence': [t['label'] for t in tokens if t['kind'] == 'gloss'],
                'video_relative_path': f'video/{split}/{translator}/{identity}.mp4',
                'text_verified': '', 'word_spans': [], 'project_split': 'unassigned',
                'signer_id': None, 'mirror_status': 'unknown',
                'anatomical_handedness': 'unverified',
                'annotation_scope': 'dataset_provided_sequence_level_only',
                **CANDIDATE_FLAGS,
            })
    return rows, inputs, originals


def probe_video(path, executable):
    result = subprocess.run(
        [str(executable), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=codec_name,width,height,avg_frame_rate,r_frame_rate,time_base,nb_frames,duration:format=duration',
         '-of', 'json', str(path)], capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace')[:500])
    raw = json.loads(result.stdout)
    stream = raw.get('streams', [{}])[0]
    fps = float(Fraction(stream.get('avg_frame_rate', '0/1')))
    duration = float(stream.get('duration', raw.get('format', {}).get('duration', 'nan')))
    frames = stream.get('nb_frames')
    metadata = {
        'width': int(stream.get('width', 0)), 'height': int(stream.get('height', 0)),
        'fps': fps, 'duration_seconds': duration,
        'container_reported_frames': int(frames) if frames and frames.isdecimal() else None,
        'codec': stream.get('codec_name'), 'time_base': stream.get('time_base'),
        'avg_frame_rate': stream.get('avg_frame_rate'),
    }
    if (not math.isfinite(fps) or fps <= 0 or not math.isfinite(duration) or duration <= 0
            or metadata['width'] <= 0 or metadata['height'] <= 0):
        raise ValueError('Invalid video header timebase or dimensions')
    return {'status': 'passed', 'full_decode_performed': False, 'metadata': metadata, 'raw_probe': raw}


def signature(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def inspect_video(root, relative, probe):
    path = contained(root, relative)
    if not path.is_file():
        return {'relative_path': relative, 'status': 'missing', 'sha256': None}
    before = signature(path)
    checksum = sha(path)
    try:
        inspected = probe(path)
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError, subprocess.TimeoutExpired) as error:
        inspected = {'status': 'failed', 'error': str(error)[:500], 'full_decode_performed': False}
    if signature(path) != before:
        raise ValueError('Video changed during inspection: ' + relative)
    return {'relative_path': relative, 'source_absolute_path': str(path),
            'source_uri': path.as_uri(), 'sha256': checksum, 'bytes': before[2],
            'status': 'present', 'probe': inspected, 'stat_signature': before}


def duplicate_groups(rows, key_function):
    grouped = defaultdict(list)
    for row in rows:
        value = key_function(row)
        if value:
            grouped[value].append(row)
    return [{'key': key, 'ids': [r['id'] for r in group],
             'splits': sorted({r['source_split'] for r in group}),
             'cross_split': len({r['source_split'] for r in group}) > 1}
            for key, group in sorted(grouped.items()) if len(group) > 1]


def build_lexicon(rows):
    terms = {}
    for row in rows:
        for token in row['gloss_tokens']:
            if token['kind'] != 'gloss':
                continue
            label = token['label']
            if label not in terms:
                terms[label] = {
                    'schema': 'signbridge-ce-csl-gloss-candidate-v1',
                    'id': 'csl_ce_csl_gloss_' + hashlib.sha256(label.encode('utf-8')).hexdigest()[:20],
                    'gloss': label, 'proposed_text': label,
                    'counts_by_split': dict.fromkeys(SPLITS, 0),
                    'occurrences': [], 'text_verified': '', 'word_spans': [],
                    'annotation_scope': 'sequence_membership_only_no_word_time_alignment',
                    **CANDIDATE_FLAGS,
                }
            term = terms[label]
            term['counts_by_split'][row['source_split']] += 1
            term['occurrences'].append({'sample_id': row['id'], 'source_split': row['source_split'],
                                        'token_position': token['position']})
    return sorted(terms.values(), key=lambda term: (-term['counts_by_split']['train'], term['gloss']))


def create_database(path, rows, terms):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE samples (id TEXT PRIMARY KEY, source_split TEXT, sentence TEXT, record_json TEXT)')
        db.execute('CREATE TABLE gloss_terms (id TEXT PRIMARY KEY, gloss TEXT UNIQUE, record_json TEXT)')
        db.execute('CREATE TABLE occurrences (sample_id TEXT, gloss_id TEXT, position INTEGER, '
                   'PRIMARY KEY(sample_id, position), FOREIGN KEY(sample_id) REFERENCES samples(id), '
                   'FOREIGN KEY(gloss_id) REFERENCES gloss_terms(id))')
        db.execute('PRAGMA foreign_keys=ON')
        db.executemany('INSERT INTO samples VALUES (?,?,?,?)',
                       [(r['id'], r['source_split'], r['proposed_text'], dumps(r)) for r in rows])
        db.executemany('INSERT INTO gloss_terms VALUES (?,?,?)',
                       [(t['id'], t['gloss'], dumps(t)) for t in terms])
        db.executemany('INSERT INTO occurrences VALUES (?,?,?)',
                       [(o['sample_id'], t['id'], o['token_position']) for t in terms for o in t['occurrences']])
        db.execute('CREATE INDEX samples_split ON samples(source_split)')
        db.execute('CREATE INDEX occurrences_gloss ON occurrences(gloss_id)')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Candidate database integrity check failed')


def query(library, gloss=None, text=None, split='train', limit=20):
    if split not in (*SPLITS, 'all') or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Query split/limit invalid')
    path = Path(library).resolve() / 'candidates.sqlite'
    clauses, values = [], []
    if split != 'all':
        clauses.append('s.source_split=?')
        values.append(split)
    if gloss is not None:
        clauses.append('EXISTS (SELECT 1 FROM occurrences o JOIN gloss_terms t ON t.id=o.gloss_id '
                       'WHERE o.sample_id=s.id AND t.gloss=?)')
        values.append(gloss)
    if text is not None:
        clauses.append('instr(s.sentence,?)>0')
        values.append(text)
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        sql = ('SELECT s.record_json FROM samples s' +
               (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY s.id LIMIT ?')
        return [json.loads(row[0]) for row in db.execute(sql, [*values, limit])]


def write_csv(path, columns, records):
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for record in records:
            # Keep exact source values in JSONL; spreadsheet exports escape formula prefixes.
            writer.writerow(["'" + str(value) if str(value).startswith(('=', '+', '-', '@', '\t', '\r'))
                             else value for value in record])


def run_import(source, output, authorization_note, probe=None, workers=4, ffprobe=None,
               dictionary=None, progress=None):
    source_path = Path(source)
    root, output = source_path.resolve(), Path(output).resolve()
    if source_path.is_symlink() or not root.is_dir():
        raise ValueError('Expected regular dataset root')
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('Output must be separate from source')
    if output.exists():
        raise FileExistsError('Use a new output directory; preserve previous evidence')
    if not isinstance(authorization_note, str) or not authorization_note.strip():
        raise ValueError('Record the user-confirmed project-use authorization')
    if not 1 <= workers <= 16:
        raise ValueError('Workers must be between 1 and 16')
    rows, label_inputs, originals = read_labels(root)
    expected = {r['video_relative_path'] for r in rows}
    discovered = {p.relative_to(root).as_posix() for p in (root / 'video').rglob('*.mp4')}
    video_names = sorted(expected | discovered)
    tool_hash = sha(Path(__file__))
    runtime = {'python': __import__('sys').version, 'probe': 'caller_supplied' if probe else 'ffprobe'}
    if probe is None:
        executable = Path(ffprobe or shutil.which('ffprobe') or '')
        if not executable.is_file():
            raise ValueError('ffprobe is required for video metadata inspection')
        executable = executable.resolve()
        runtime.update({'ffprobe_path': str(executable), 'ffprobe_sha256': sha(executable),
                        'ffprobe_version': subprocess.run([str(executable), '-version'], capture_output=True,
                                                          text=True, timeout=10, check=True).stdout.splitlines()[0]})
        probe = lambda path: probe_video(path, executable)
    dictionary_rows, dictionary_input = [], None
    if dictionary is not None:
        dictionary_path = Path(dictionary).resolve()
        dictionary_input = {'path': str(dictionary_path), 'sha256': sha(dictionary_path)}
        dictionary_rows = json.loads(dictionary_path.read_text(encoding='utf-8'))['entries']
    inspected = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for info in pool.map(lambda name: inspect_video(root, name, probe), video_names):
            inspected.append(info)
            if progress and (len(inspected) % 500 == 0 or len(inspected) == len(video_names)):
                progress({'videos_inspected': len(inspected), 'videos_expected': len(video_names)})
    # Check that labels, tool and input identities remained unchanged throughout this snapshot.
    for item in label_inputs:
        if sha(root / item['relative_path']) != item['sha256']:
            raise ValueError('Source CSV changed during import')
    if sha(Path(__file__)) != tool_hash:
        raise ValueError('Importer changed during import')
    for info in inspected:
        if info['status'] == 'present' and tuple(info['stat_signature']) != signature(root / info['relative_path']):
            raise ValueError('Video changed during import: ' + info['relative_path'])
    by_path = {info['relative_path']: info for info in inspected}
    for row in rows:
        row['video'] = {k: v for k, v in by_path[row['video_relative_path']].items()
                        if k not in ('raw_probe', 'stat_signature')}
    terms = build_lexicon(rows)
    duplicates = {
        'schema': 'signbridge-ce-csl-duplicates-v1', 'deletion_performed': False,
        'video_sha256': duplicate_groups(rows, lambda r: r['video'].get('sha256')),
        'sentence': duplicate_groups(rows, lambda r: r['raw']['Chinese Sentences']),
        'gloss_sequence': duplicate_groups(rows, lambda r: dumps(r['gloss_sequence'])),
    }
    translator_splits = {split: sorted({r['source_translator'] for r in rows if r['source_split'] == split})
                         for split in SPLITS}
    report = {
        'schema': 'signbridge-ce-csl-import-v1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'metadata_imported_candidate_only', 'source_root': str(root),
        'authorization': {'status': 'user_reported', 'note': authorization_note,
                          'scope': 'local_project_research_candidate_intake', 'redistribution_inferred': False},
        'license': {'local_license_files': sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                                               if p.is_file() and re.search(r'license|licence|notice|readme', p.name, re.I)),
                    'upstream_license_verified': False},
        'samples': len(rows), 'unique_gloss_candidates': len(terms),
        'gloss_occurrences': sum(sum(t['counts_by_split'].values()) for t in terms),
        'split_counts': {split: sum(r['source_split'] == split for r in rows) for split in SPLITS},
        'gloss_counts_by_split': {split: sum(t['counts_by_split'][split] > 0 for t in terms) for split in SPLITS},
        'punctuation_counts': dict(Counter(t['label'] for r in rows for t in r['gloss_tokens'] if t['kind'] == 'punctuation')),
        'empty_gloss_tokens': sum(t['kind'] == 'empty' for r in rows for t in r['gloss_tokens']),
        'notes_nonempty': sum(bool(r['raw']['Note']) for r in rows),
        'translator_codes_by_split': translator_splits,
        'translator_codes_shared_all_splits': sorted(set.intersection(*(set(v) for v in translator_splits.values()))),
        'source_split_is_signer_independent': False,
        'videos_found': len(discovered), 'video_bytes_hashed': sum(v.get('bytes', 0) for v in inspected),
        'missing_videos': [v['relative_path'] for v in inspected if v['status'] == 'missing'],
        'unlabeled_videos': sorted(discovered - expected),
        'video_metadata_failures': [v['relative_path'] for v in inspected if v.get('probe', {}).get('status') == 'failed'],
        'video_header_checks_passed': sum(v.get('probe', {}).get('status') == 'passed' for v in inspected),
        'video_full_decode_performed': False,
        'container_reported_total_frames': sum(v.get('probe', {}).get('metadata', {}).get('container_reported_frames') or 0 for v in inspected),
        'container_reported_duration_seconds': sum(v.get('probe', {}).get('metadata', {}).get('duration_seconds') or 0 for v in inspected),
        'duplicate_groups': {key: len(value) for key, value in duplicates.items() if isinstance(value, list)},
        'cross_split_duplicate_groups': {key: sum(v['cross_split'] for v in value) for key, value in duplicates.items() if isinstance(value, list)},
        'label_inputs': label_inputs, 'import_tool_sha256': tool_hash, 'runtime': runtime,
        'dictionary_input': dictionary_input,
        'training_started': False, 'training_weights_updated': False, **CANDIDATE_FLAGS,
    }
    labels_to_ids = defaultdict(list)
    for item in dictionary_rows:
        for label in {item['gloss'], *item['texts']}:
            labels_to_ids[label].append(item['id'])
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=output.name + '.partial-', dir=output.parent))
    try:
        for name, raw_bytes in originals.items():
            (stage / Path(name).parent).mkdir(exist_ok=True)
            (stage / name).write_bytes(raw_bytes)
        write_jsonl(stage / 'samples.jsonl', rows)
        write_jsonl(stage / 'gloss-lexicon.jsonl', terms)
        write_jsonl(stage / 'video-inventory.jsonl', inspected)
        for split in SPLITS:
            selected = [r for r in rows if r['source_split'] == split]
            write_jsonl(stage / 'splits' / split / 'samples.jsonl', selected)
            write_jsonl(stage / 'splits' / split / 'gloss-lexicon.jsonl', build_lexicon(selected))
        write_json(stage / 'duplicates.json', duplicates)
        write_json(stage / 'report.json', report)
        write_csv(stage / 'gloss-frequency.csv', ['candidate_id', 'gloss', *SPLITS, 'timed_word_verified'],
                  [(t['id'], t['gloss'], *(t['counts_by_split'][s] for s in SPLITS), False) for t in terms])
        write_csv(stage / 'samples.csv', ['candidate_id', 'source_split', 'translator', 'Chinese Sentences', 'Gloss', 'Note', 'video', 'sha256'],
                  [(r['id'], r['source_split'], r['source_translator'], r['raw']['Chinese Sentences'],
                    r['raw']['Gloss'], r['raw']['Note'], r['video_relative_path'], r['video'].get('sha256')) for r in rows])
        write_csv(stage / 'project-label-overlap.csv', ['candidate_id', 'gloss', 'existing_ids_exact_label_only', 'same_sign_verified'],
                  [(t['id'], t['gloss'], '|'.join(sorted(set(labels_to_ids[t['gloss']]))), False) for t in terms])
        create_database(stage / 'candidates.sqlite', rows, terms)
        top = '\n'.join(f"| {t['gloss'].replace('|', '｜')} | {t['counts_by_split']['train']} | {t['counts_by_split']['dev']} | {t['counts_by_split']['test']} |" for t in terms[:20])
        (stage / 'REVIEW.md').write_text(
            '# CE-CSL 候选库\n\n'
            f"已导入 {len(rows):,} 条序列标签、{len(terms):,} 个不同Gloss候选；划分 {report['split_counts']}。\n\n"
            '这是本地文件快照的统计，不宣称覆盖官方所有版本。原始CSV复制保留；视频只记录绝对路径和摘要，不复制、不上传。\n\n'
            'Gloss编号（如考试1/考试2）原样保留；句末标点不算词条。Note仅保留为原始备注，不自动当成释义。\n\n'
            '候选只有整段序列成员关系，没有词级开始/结束时间，不是可播放动作或已对齐的3D训练数据。人工批准、训练就绪、可播放状态均为false。\n\n'
            '原train/dev/test保留；query默认train。全量词表只作盘点，不能把dev/test样本并进训练。Translator是数据集原编号，未关联既有六批人物；同编号跨集合出现，不能据此宣称人物独立评估。\n\n'
            f"视频头信息检查 {report['video_header_checks_passed']}/{len(video_names)}，未逐帧解码。缺失 {len(report['missing_videos'])}；元数据异常 {len(report['video_metadata_failures'])}。\n\n"
            f"跨集合重复组 {report['cross_split_duplicate_groups']}，详见duplicates.json；不删除来源。\n\n"
            '## 词频前20项（不是手语能力榜）\n\n| Gloss | train次数 | dev次数 | test次数 |\n|---|---:|---:|---:|\n' + top + '\n\n'
            '## 使用\n\n从项目仓库根运行（把<候选库>换成本目录绝对路径）：\n\n'
            '```sh\n.venv-sign-data/bin/python signbridge/src/tools/sign-ce-csl-import.py query --library "<候选库>" --gloss 去 --split train --limit 10\n```\n\n'
            'samples.csv可供表格筛选；gloss-frequency.csv查看词频；candidates.sqlite提供只读参数查询。'
            'splits/train下只含train来源，不应将全量词频或dev/test标签用于拟合。project-label-overlap.csv仅比文字相同，不能证明手型/语义相同。\n\n'
            '授权按用户明确陈述登记；本地未发现许可文件不等于获得公开分发许可。当前原片/标签/库均不进入GitHub和插件分发。\n', encoding='utf-8')
        (stage / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(stage).as_posix()}\n'
                                                for p in sorted(stage.rglob('*')) if p.is_file()), encoding='utf-8')
        stage.rename(output)
    except Exception:
        # Preserve partial evidence and input sources if a write/validation fails.
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    intake = sub.add_parser('import')
    intake.add_argument('--source', type=Path, required=True)
    intake.add_argument('--output', type=Path, required=True)
    intake.add_argument('--authorization-note', required=True)
    intake.add_argument('--workers', type=int, default=4)
    intake.add_argument('--ffprobe', type=Path)
    intake.add_argument('--dictionary', type=Path)
    lookup = sub.add_parser('query')
    lookup.add_argument('--library', type=Path, required=True)
    lookup.add_argument('--gloss')
    lookup.add_argument('--text')
    lookup.add_argument('--split', choices=(*SPLITS, 'all'), default='train')
    lookup.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if args.command == 'query':
        print(json.dumps(query(args.library, args.gloss, args.text, args.split, args.limit), ensure_ascii=False, indent=2))
    else:
        result = run_import(args.source, args.output, args.authorization_note, workers=args.workers,
                            ffprobe=args.ffprobe, dictionary=args.dictionary,
                            progress=lambda value: print(dumps(value), flush=True))
        print(dumps({key: result[key] for key in ('status', 'samples', 'unique_gloss_candidates', 'split_counts', 'missing_videos', 'video_metadata_failures')}))


if __name__ == '__main__':
    main()
