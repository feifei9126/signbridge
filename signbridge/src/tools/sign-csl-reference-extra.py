"""Attach hash-verified additional course sources and existing caption candidates."""
import csv
import importlib.util
import json
from pathlib import Path
import sqlite3

SPEC = importlib.util.spec_from_file_location('reference_extra_core', Path(__file__).with_name('sign-csl-reference-database.py'))
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def raw_csv(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=core.HEADERS)
        writer.writeheader()
        writer.writerows(x['raw'] for x in samples)


def prepare(stage, intake, media, existing_terms):
    """Return extra rows; labels only from stored candidates, never a lesson filename."""
    intake = Path(intake).resolve()
    inventory_raw, inv_sha = core.snapshot(intake/'inventory.json')
    report_raw, report_sha = core.snapshot(intake/'report.json')
    inventory, report = json.loads(inventory_raw), json.loads(report_raw)
    if report.get('status') not in {'passed', 'verified', 'completed', 'source_metadata_and_prior_candidates_indexed'}:
        raise ValueError('Additional intake checks must pass first')
    candidates, candidates_sha = core.rows(intake/'prior-window-candidates.jsonl')
    if report.get('issues') or report.get('summary', {}).get('issue_count', 0):
        raise ValueError('Additional intake has unresolved technical issues')
    sources = inventory['sources']
    for source in sources:
        core.safe_id(source['source_id'])
        core.safe_id(source['folder_id'])
    if len({x['source_id'] for x in sources}) != len(sources):
        raise ValueError('Duplicate extra source IDs')
    sources_by_sha = {x['sha256']: x for x in sources}
    ce_labels = {x['label']: x['id'] for x in existing_terms if x['in_ce_csl']}
    datasets = [{'id': 'additional-course-sources', 'kind': 'full_courses_without_invented_sequence_labels', **core.GATES},
                {'id': 'additional-caption-candidates', 'kind': 'existing_source_bound_caption_windows_not_word_truth', **core.GATES}]
    samples, windows, duplicate_windows, source_map = [], [], [], []
    seen, prior_reports = {}, {}
    for source in sources:
        sid, folder = source['source_id'], source['folder_id']
        path = Path(source.get('absolute_path', source.get('path', '')))
        location = f'additional-sources/video/reference/{folder}/{sid}.mp4'
        media.copy(path, source['sha256'], location)
        item = {'id': sid, 'dataset_id': 'additional-course-sources', 'source_split': 'reference', 'project_split': 'unassigned',
                'status': 'reference_unlabeled_course', 'media_sha256': source['sha256'], 'local_video': location,
                'raw': {'Number': sid, 'Translator': folder, 'Chinese Sentences': '', 'Gloss': '',
                        'Note': core.ce.dumps({'annotation_status': 'unlabeled_full_lesson', 'display_filename_not_label': path.name,
                                              'translator_scope': 'folder_source_code_not_person_identity', **core.GATES})},
                'source_id': sid, 'source_sha256': source['sha256'], 'source_folder': folder,
                'display_title_not_label': path.name, 'video_metadata': source.get('probe'),
                'human_approved': False, 'word_spans': [], 'mirror_status': 'unknown', **core.GATES}
        samples.append(item)
        source_map.append({'id': sid, 'sha256': source['sha256'], 'folder_id': folder, 'local_video': location,
                           'aliases': source.get('aliases', [str(path)]), 'no_sequence_gloss_inferred_from_title': True})
    for wrapper in candidates:
        row = wrapper.get('original_record', wrapper.get('candidate', wrapper))
        sid = core.safe_id(row['id'])
        source = sources_by_sha.get(row['source_sha256'])
        if source is None:
            raise ValueError('Extra caption candidate is not from an included video SHA')
        label = row.get('proposed_text', row.get('label_candidate'))
        window = row.get('source_window_seconds')
        if not isinstance(label, str) or not label.strip() or not isinstance(window, list) or len(window)!=2 or not 0<=window[0]<window[1]:
            raise ValueError('Invalid source caption label/window')
        if row.get('human_approved') is not False or row.get('training_ready') is not False or row.get('model_training_ready') is not False:
            raise ValueError('Extra candidate approval cannot be inferred or promoted')
        key = (row['source_sha256'], label, window[0], window[1])
        # Require the original candidate report binding; no path from a title/attached instruction is executed.
        bound = wrapper.get('intake', {})
        report_path = Path(bound.get('prior_report_absolute_path', wrapper.get('candidate_report', inventory.get('candidate_report', '/missing'))))
        expected_report_sha = bound.get('prior_report_sha256', wrapper.get('candidate_report_sha256', inventory.get('candidate_report_sha256')))
        if str(report_path) not in prior_reports:
            original_bytes, actual = core.snapshot(report_path)
            if actual != expected_report_sha:
                raise ValueError('Existing candidate report provenance changed or missing')
            prior_reports[str(report_path)] = (actual, {x['id']: x for x in json.loads(original_bytes)['candidates']}, original_bytes)
        actual, original_candidates, original_bytes = prior_reports[str(report_path)]
        original = original_candidates.get(sid)
        if actual != expected_report_sha or not original or any(row.get(k) != v for k,v in original.items()):
            raise ValueError('Candidate record differs from its frozen source report')
        if window[1] > source['duration_seconds'] + .05:
            raise ValueError('Caption candidate exceeds its original source duration')
        if key in seen:
            duplicate_windows.append({'id': sid, 'canonical_id': seen[key], 'reason': 'exact_source_sha_label_nominal_window'})
            continue
        seen[key] = sid
        clip = core.ce.contained(report_path.parent, row['reference_clip'])
        location = f'additional-candidates/video/candidates/{source["folder_id"]}/{sid}.mp4'
        media.copy(clip, row['clip_sha256'], location)
        decoded = row.get('decoded_video', {})
        frames, fps = decoded.get('frames'), decoded.get('fps')
        if type(frames) is not int or frames<1 or not isinstance(fps,(int,float)) or fps<=0:
            raise ValueError('Existing clip metadata contract missing')
        item = {'id': sid, 'dataset_id': 'additional-caption-candidates', 'source_split': 'candidates',
                'project_split': 'unassigned', 'status': 'unverified_caption_window',
                'media_sha256': row['clip_sha256'], 'local_video': location,
                'raw': {'Number': sid, 'Translator': source['folder_id'], 'Chinese Sentences': label, 'Gloss': label,
                        'Note': core.ce.dumps({'label_status': 'prior_caption_candidate_only', 'nominal_source_window': window,
                                              'word_boundary_verified': False, 'translator_scope': 'source_folder_not_signer_identity', **core.GATES})},
                'source_id': source['source_id'], 'source_sha256': source['sha256'], 'source_folder': source['folder_id'],
                'source_window_seconds_nominal': window, 'frames': frames, 'reference_fps': fps,
                'source_pts_measured': False, 'word_spans': [], 'human_approved': False,
                'anatomical_handedness': 'unverified', 'mirror_status': 'unknown', **core.GATES}
        samples.append(item)
        windows.append({'id': sid, 'source_id': source['source_id'], 'source_sha256': source['sha256'], 'label_candidate': label,
                        'matched_ce_term_id': ce_labels.get(label),
                        'ce_relation': 'exact_label_overlap_only' if label in ce_labels else 'no_exact_ce_label',
                        'same_sign_verified': False, 'source_window_seconds_nominal': window,
                        'local_video': location, 'local_video_sha256': row['clip_sha256'],
                        'original_candidate': row, 'source_report_sha256': expected_report_sha, **core.GATES})
    for folder in sorted({x['folder_id'] for x in sources}):
        raw_csv(stage/f'additional-sources/label/{folder}.csv', [x for x in samples if x['dataset_id']=='additional-course-sources' and x['source_folder']==folder])
        raw_csv(stage/f'additional-candidates/label/{folder}.csv', [x for x in samples if x['dataset_id']=='additional-caption-candidates' and x['source_folder']==folder])
    core.write_jsonl(stage/'additional-sources/source-map.jsonl', source_map)
    core.write_jsonl(stage/'additional-candidates/windows.jsonl', windows)
    core.write_json(stage/'additional-candidates/duplicate-windows.json', duplicate_windows)
    core.write_json(stage/'additional-candidates/label-index.json', {'labels': sorted({x['label_candidate'] for x in windows}),
                     'ce_label_overlap': sorted({x['label_candidate'] for x in windows if x['matched_ce_term_id']}),
                     'not_in_ce_exact_labels': sorted({x['label_candidate'] for x in windows if not x['matched_ce_term_id']}),
                     'all_unverified_caption_candidates': True, 'not_added_to_verified_lexicon': True})
    (stage/'provenance/additional-inventory.json').write_bytes(inventory_raw)
    (stage/'provenance/additional-intake-report.json').write_bytes(report_raw)
    core.write_json(stage/'provenance/additional-inputs.json', {'inventory_sha256': inv_sha, 'report_sha256': report_sha,
                     'prior_candidates_sha256': candidates_sha, 'tool_sha256': core.ce.sha(Path(__file__))})
    for filename,(digest,_,raw) in prior_reports.items():
        if core.ce.sha(Path(filename)) != digest: raise ValueError('Prior candidate report changed during merge')
        target=core.new_target(stage, 'provenance/additional-prior-reports/'+digest+'.json')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    if core.ce.sha(intake/'report.json')!=report_sha or core.ce.sha(intake/'inventory.json')!=inv_sha or core.ce.sha(intake/'prior-window-candidates.jsonl')!=candidates_sha:
        raise ValueError('Additional intake changed during merge')
    summary = {'source_video_contents': len(sources), 'source_video_aliases': sum(len(x.get('aliases', [x.get('absolute_path')])) for x in sources),
               'retained_caption_windows': len(windows), 'raw_candidate_labels': len({x['label_candidate'] for x in windows}),
               'exact_ce_label_overlap_unique': len({x['label_candidate'] for x in windows if x['matched_ce_term_id']}),
               'new_unverified_caption_labels_unique': len({x['label_candidate'] for x in windows if not x['matched_ce_term_id']}),
               'collapsed_exact_window_duplicates': len(duplicate_windows), 'new_approved_labels': 0,
               'corpus_translator_codes_are_not_verified_persons': True}
    return datasets, samples, windows, summary


def add_windows_database(path, windows):
    c = sqlite3.connect(path)
    try:
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('CREATE TABLE caption_candidates(id TEXT PRIMARY KEY REFERENCES samples(id), label_candidate TEXT NOT NULL, matched_ce_term_id TEXT REFERENCES terms(id), record_json TEXT NOT NULL)')
        c.executemany('INSERT INTO caption_candidates VALUES (?,?,?,?)', [(x['id'],x['label_candidate'],x['matched_ce_term_id'],core.ce.dumps(x)) for x in windows])
        c.execute('CREATE INDEX caption_labels ON caption_candidates(label_candidate)')
        c.commit()
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Extra caption foreign key error')
    finally:
        c.close()
