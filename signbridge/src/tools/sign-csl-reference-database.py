"""Build a new CE-CSL-shaped reference database without inventing word alignment."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

SPEC = importlib.util.spec_from_file_location('ce_reference_import', Path(__file__).with_name('sign-ce-csl-import.py'))
ce = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ce)
HEADERS = ce.HEADERS
GATES = {'training_ready': False, 'model_training_ready': False, 'can_play_in_demo': False}
KINDS = {'word', 'phrase', 'sentence', 'fingerspelling', 'number', 'grammar_concept', 'classifier_concept', 'name_sign_concept'}


def snapshot(path):
    raw = Path(path).read_bytes()
    return raw, hashlib.sha256(raw).hexdigest()


def rows(path):
    raw, digest = snapshot(path)
    return [json.loads(x) for x in raw.decode('utf-8').splitlines() if x.strip()], digest


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(ce.dumps(x) + '\n' for x in values))


def identifier(prefix, *parts):
    return prefix + '-' + hashlib.sha256(ce.dumps(parts).encode()).hexdigest()[:24]


def safe_id(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}', value) is None:
        raise ValueError('Unsafe source/candidate ID')
    return value


def new_target(root, relative):
    path = ce.contained(Path(root).resolve(), relative)
    if path.exists() or path.is_symlink():
        raise ValueError('Refusing output overwrite')
    return path


def reviewed_native(path, expected):
    import numpy as np
    raw, digest = snapshot(path)
    if digest != expected:
        raise ValueError('Reviewed parameter digest changed')
    from io import BytesIO
    shapes = {'global_orient': (1,3), 'body_pose': (21,3), 'left_hand_pose': (15,3), 'right_hand_pose': (15,3),
              'jaw_pose': (1,3), 'leye_pose': (1,3), 'reye_pose': (1,3), 'betas': (1,10), 'expression': (1,10), 'transl': (1,3)}
    with np.load(BytesIO(raw), allow_pickle=False) as a:
        if set(a.files) != set(shapes):
            raise ValueError('Reviewed artifact is not one complete native SMPL-X keyframe')
        for name, shape in shapes.items():
            if a[name].shape != shape or a[name].dtype.kind != 'f' or not np.isfinite(a[name]).all():
                raise ValueError('Reviewed native shape/dtype/value differs')
    return raw


def manifest(root):
    root = Path(root).resolve()
    entries = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = ce.contained(root, name)
        if name in entries or not path.is_file() or ce.sha(path) != digest:
            raise ValueError('Input manifest mismatch: ' + name)
        entries[name] = digest
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual - {'SHA256SUMS'} != set(entries):
        raise ValueError('Manifest does not cover exact input tree')
    return entries


def semantic_signature(row):
    return ce.dumps([row['raw'][x] for x in ['Chinese Sentences', 'Gloss', 'Note']])


def group_samples(samples):
    """Only identical media plus identical annotations can collapse into one sample."""
    by_sha = defaultdict(list)
    for row in samples:
        by_sha[row['video']['sha256']].append(row)
    status, aliases, conflicts = {}, [], []
    split_rank = {'test': 0, 'dev': 1, 'train': 2}
    for digest, group in sorted(by_sha.items()):
        if len({semantic_signature(x) for x in group}) > 1:
            conflicts.append({'video_sha256': digest, 'sample_ids': [r['id'] for r in group],
                              'source_rows': [r['raw'] for r in group], 'policy': 'quarantine_all_conflicting_annotations'})
            status.update({r['id']: 'quarantined_label_conflict' for r in group})
            continue
        # Keep the original protected evaluation split when identical bytes occur across sets.
        ordered = sorted(group, key=lambda r: (split_rank[r['source_split']], r['id']))
        first = ordered[0]
        status[first['id']] = 'retained'
        for row in ordered[1:]:
            status[row['id']] = 'duplicate_alias'
            aliases.append({'sample_id': row['id'], 'canonical_sample_id': first['id'],
                            'video_sha256': digest, 'source_split': row['source_split'],
                            'canonical_source_split': first['source_split'], 'reason': 'identical_video_and_exact_annotation'})
    return status, aliases, conflicts


def make_terms(samples, lexical):
    terms, occurrences, mappings = {}, [], []
    for sample in samples:
        for token in sample['gloss_tokens']:
            if token['kind'] != 'gloss':
                continue
            label = token['label']
            tid = identifier('ce-gloss', label)
            terms.setdefault(tid, {'id': tid, 'label': label, 'namespace': 'ce_csl_gloss',
                                  'unit_type': 'dataset_gloss', 'in_ce_csl': True,
                                  'new_label_candidate': False, 'ce_occurrences_by_split': {s: 0 for s in ce.SPLITS},
                                  'tutorial_lexical_ids': [], **GATES})
            terms[tid]['ce_occurrences_by_split'][sample['source_split']] += 1
            occurrences.append({'sample_id': sample['id'], 'position': token['position'],
                                'term_id': tid, 'raw_token': token['raw'], 'source_split': sample['source_split']})
    by_label = {t['label']: t['id'] for t in terms.values()}
    seen = set()
    for entry in lexical:
        if entry['id'] in seen or entry['unit_type'] not in KINDS:
            raise ValueError('Duplicate/unknown tutorial lexical record')
        seen.add(entry['id'])
        label, kind = entry['canonical_text'], entry['unit_type']
        if not label.strip() or not entry.get('meaning'):
            raise ValueError('Tutorial record lacks source-specific meaning')
        for gate in ['human_approved', 'semantics_approved', 'boundaries_approved', 'training_ready', 'model_training_ready']:
            if entry.get(gate) is not False:
                raise ValueError('Frozen assistant lexical audit cannot be silently promoted')
        label_overlap = label in by_label
        merge = kind in {'word', 'phrase'} and label_overlap
        tid = by_label[label] if merge else identifier('tutorial-term', label, kind)
        terms.setdefault(tid, {'id': tid, 'label': label, 'namespace': 'tutorial_' + kind,
                              'unit_type': kind, 'in_ce_csl': False,
                              'new_label_candidate': not label_overlap,
                              'ce_occurrences_by_split': {s: 0 for s in ce.SPLITS}, 'tutorial_lexical_ids': [], **GATES})
        terms[tid]['tutorial_lexical_ids'].append(entry['id'])
        mappings.append({'lexical_id': entry['id'], 'term_id': tid, 'canonical_text': label,
                         'unit_type': kind, 'source_id': entry['source_id'], 'source_sha256': entry['source_sha256'],
                         'label_present_in_ce_csl': label_overlap,
                         'relation': 'exact_label_overlap_sign_equivalence_unverified' if merge else
                                     'same_label_different_unit_type_kept_separate' if label_overlap else 'not_in_ce_csl_exact_labels',
                         'same_sign_verified': False, 'evidence_status': entry['evidence_status']})
    return sorted(terms.values(), key=lambda t: (t['namespace'], t['label'])), occurrences, mappings


class MediaCopies:
    """Deduplicate copies inside NEW output only; never hardlink original user media."""
    def __init__(self, root):
        self.root = root
        self.assets = {}
        self.aliases = []

    def copy(self, source, expected, relative):
        source = Path(source)
        target = new_target(self.root, relative)
        if source.is_symlink() or not source.is_file() or target.exists() or not target.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Unsafe/missing media or duplicate destination')
        before = ce.signature(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if expected in self.assets:
            prior = self.root / self.assets[expected]['relative_path']
            # Source must still be verified even when reusing a content-addressed copy.
            if ce.sha(source) != expected:
                raise ValueError('Aliased source media changed')
            os.link(prior, target)
        else:
            shutil.copyfile(source, target)
            if ce.sha(target) != expected:
                raise ValueError('Media copy checksum mismatch: ' + str(source))
            self.assets[expected] = {'sha256': expected, 'relative_path': relative,
                                     'bytes': target.stat().st_size, 'original_path': str(source)}
        if before != ce.signature(source) or source.stat().st_ino == target.stat().st_ino and source.stat().st_dev == target.stat().st_dev:
            raise ValueError('Source changed or new media aliases original source inode')
        self.aliases.append({'sha256': expected, 'relative_path': relative, 'source_path': str(source)})
        return relative


def create_database(path, datasets, samples, terms, occurrences, lexical, mappings, media, reviews, motions, duplicates, conflicts):
    connection = sqlite3.connect(path)
    try:
        connection.executescript('''
          PRAGMA foreign_keys=ON;
          CREATE TABLE datasets(id TEXT PRIMARY KEY, record_json TEXT NOT NULL);
          CREATE TABLE media(sha256 TEXT PRIMARY KEY, relative_path TEXT UNIQUE NOT NULL, bytes INTEGER NOT NULL, record_json TEXT NOT NULL);
          CREATE TABLE samples(id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id), source_split TEXT NOT NULL,
              status TEXT NOT NULL, chinese TEXT NOT NULL, gloss TEXT NOT NULL, media_sha256 TEXT NOT NULL REFERENCES media(sha256), record_json TEXT NOT NULL);
          CREATE TABLE terms(id TEXT PRIMARY KEY, label TEXT NOT NULL, namespace TEXT NOT NULL, unit_type TEXT NOT NULL,
              in_ce_csl INTEGER NOT NULL, record_json TEXT NOT NULL, UNIQUE(namespace,label));
          CREATE TABLE occurrences(sample_id TEXT NOT NULL REFERENCES samples(id), position INTEGER NOT NULL,
              term_id TEXT NOT NULL REFERENCES terms(id), raw_token TEXT NOT NULL, PRIMARY KEY(sample_id,position));
          CREATE TABLE lexical_evidence(id TEXT PRIMARY KEY, term_id TEXT NOT NULL REFERENCES terms(id), source_id TEXT NOT NULL,
              source_sha256 TEXT NOT NULL REFERENCES media(sha256), record_json TEXT NOT NULL);
          CREATE TABLE reviews(id TEXT PRIMARY KEY, record_json TEXT NOT NULL);
          CREATE TABLE motion_assets(id TEXT PRIMARY KEY, sample_id TEXT REFERENCES samples(id), review_id TEXT REFERENCES reviews(id), record_json TEXT NOT NULL);
          CREATE TABLE duplicate_aliases(sample_id TEXT PRIMARY KEY REFERENCES samples(id), canonical_id TEXT NOT NULL REFERENCES samples(id), record_json TEXT NOT NULL);
          CREATE TABLE conflicts(media_sha256 TEXT PRIMARY KEY REFERENCES media(sha256), record_json TEXT NOT NULL);
          CREATE INDEX occurrence_terms ON occurrences(term_id);
          CREATE INDEX sample_splits ON samples(source_split,status);
          CREATE VIEW retained_ce_samples AS SELECT * FROM samples WHERE dataset_id='CE-CSL' AND status='retained';
          CREATE VIEW ce_train_only AS SELECT * FROM retained_ce_samples WHERE source_split='train';
        ''')
        connection.executemany('INSERT INTO datasets VALUES (?,?)', [(r['id'], ce.dumps(r)) for r in datasets])
        connection.executemany('INSERT INTO media VALUES (?,?,?,?)', [(r['sha256'], r['relative_path'], r['bytes'], ce.dumps(r)) for r in media])
        connection.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?)', [(r['id'], r['dataset_id'], r['source_split'], r['status'], r['raw']['Chinese Sentences'], r['raw']['Gloss'], r['media_sha256'], ce.dumps(r)) for r in samples])
        connection.executemany('INSERT INTO terms VALUES (?,?,?,?,?,?)', [(r['id'], r['label'], r['namespace'], r['unit_type'], int(r['in_ce_csl']), ce.dumps(r)) for r in terms])
        connection.executemany('INSERT INTO occurrences VALUES (?,?,?,?)', [(r['sample_id'], r['position'], r['term_id'], r['raw_token']) for r in occurrences])
        map_by_id = {r['lexical_id']: r for r in mappings}
        connection.executemany('INSERT INTO lexical_evidence VALUES (?,?,?,?,?)', [(r['id'], map_by_id[r['id']]['term_id'], r['source_id'], r['source_sha256'], ce.dumps(r)) for r in lexical])
        connection.executemany('INSERT INTO reviews VALUES (?,?)', [(r['id'], ce.dumps(r)) for r in reviews])
        connection.executemany('INSERT INTO motion_assets VALUES (?,?,?,?)', [(r['id'], r.get('sample_id'), r.get('review_id'), ce.dumps(r)) for r in motions])
        connection.executemany('INSERT INTO duplicate_aliases VALUES (?,?,?)', [(r['sample_id'], r['canonical_sample_id'], ce.dumps(r)) for r in duplicates])
        connection.executemany('INSERT INTO conflicts VALUES (?,?)', [(r['video_sha256'], ce.dumps(r)) for r in conflicts])
        connection.commit()
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',) or connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Database integrity/foreign-key failure')
    finally:
        connection.close()


def validate_revalidation(check, source, intake, inventory):
    if check.get('status') != 'passed' or check.get('errors') or check.get('changes'):
        raise ValueError('Independent source revalidation must pass first')
    origins = check.get('sources', {})
    expected = {'ce_csl_root': Path(source).resolve(), 'candidate_library_root': Path(intake).resolve(), 'tutorial_inventory': Path(inventory).resolve()}
    if any(Path(origins.get(key, '/missing')).resolve() != path for key, path in expected.items()):
        raise ValueError('Independent revalidation belongs to different sources')
    required = {Path(inventory).resolve(), Path(intake).resolve()/'SHA256SUMS', Path(intake).resolve()/'report.json', Path(intake).resolve()/'samples.jsonl', Path(intake).resolve()/'video-inventory.jsonl'}
    required |= {Path(base).resolve()/'label'/f'{split}.csv' for base in [source,intake] for split in ce.SPLITS}
    supplied = [Path(row['path']).resolve() for row in check.get('input_snapshots', [])]
    if len(set(supplied)) != len(supplied) or not required.issubset(supplied):
        raise ValueError('Revalidation missing required source CSV/intake/inventory bindings')
    for row in check.get('input_snapshots', []):
        if ce.sha(Path(row['path'])) != row['sha256']:
            raise ValueError('Independent revalidation input changed')
    if not check.get('input_snapshots'):
        raise ValueError('Revalidation missing input bindings')


def validate_candidate_media(clip, observation, count, fps, pts, frame_ids):
    import numpy as np
    executable = shutil.which('ffprobe')
    if not executable:
        raise ValueError('ffprobe required for actual candidate frame verification')
    result = subprocess.run([executable, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                             '-show_entries', 'stream=nb_read_frames,avg_frame_rate', '-of', 'json', str(clip)],
                            text=True, capture_output=True, check=True, timeout=120)
    stream = json.loads(result.stdout)['streams'][0]
    num, den = map(int, stream['avg_frame_rate'].split('/'))
    if int(stream['nb_read_frames']) != count or abs(num/den-fps) > .001:
        raise ValueError('Candidate actual clip frame/fps differs')
    with np.load(observation, allow_pickle=False) as arrays:
        if not np.array_equal(arrays['source_frame_ids_0based'], frame_ids) or not np.array_equal(arrays['source_pts_seconds'], pts):
            raise ValueError('Candidate observations disagree with exact source frame/PTS mapping')
        for name, size in [('pose_image', 33), ('left_hand_image', 21), ('right_hand_image', 21), ('face_image', 468)]:
            values, mask = arrays[name], arrays[name+'_detected']
            if values.shape[:2] != (count, size) or mask.shape != (count,) or mask.dtype.kind != 'b':
                raise ValueError('Candidate observation shapes/masks differ')
            if not np.isfinite(values[mask]).all() or not np.isnan(values[~mask]).all():
                raise ValueError('Candidate missing observations must stay missing, never zero-filled')
    return {'frames_verified': count, 'fps': fps, 'exact_source_frame_mapping': True, 'missing_preserved': True}


def build(source, intake, tutorial_audit, tutorial_inventory, observations, review_path, output, validation, candidate_overrides=None, extra_intake=None):
    source, intake, tutorial_audit, observations = map(lambda p: Path(p).resolve(), [source, intake, tutorial_audit, observations])
    output = Path(output).absolute()
    protected = [source, intake, tutorial_audit, observations, Path(tutorial_inventory).resolve().parent]
    if output.exists() or any(output.resolve().is_relative_to(p) or p.is_relative_to(output.resolve()) for p in protected):
        raise ValueError('New output outside all frozen inputs required')
    check = json.loads(Path(validation).read_text())
    validate_revalidation(check, source, intake, tutorial_inventory)
    manifest(intake)
    manifest(tutorial_audit)
    current, inputs, originals = ce.read_labels(source)
    previous, previous_digest = rows(intake / 'samples.jsonl')
    by_id = {r['id']: r for r in previous}
    if len(by_id) != len(previous) or set(by_id) != {r['id'] for r in current}:
        raise ValueError('Current source and verified intake sample identities differ')
    for row in current:
        old = by_id[row['id']]
        if row['raw'] != old['raw'] or row['source_label']['sha256'] != old['source_label']['sha256'] or old['video']['status'] != 'present':
            raise ValueError('Current CSV and source-bound intake disagree')
        row['video'] = old['video']
    if any(originals[name] != (intake / name).read_bytes() for name in originals):
        raise ValueError('Original CSV bytes changed since frozen intake')
    lexical, lexical_digest = rows(tutorial_audit / 'lexical-entries.jsonl')
    inventory_raw, inventory_digest = snapshot(tutorial_inventory)
    inventory = json.loads(inventory_raw)
    for item in inventory['unique_sources']:
        safe_id(item['source_id'])
    obs_rows, obs_digest = rows(observations / 'observations-records.jsonl')
    for item in obs_rows:
        safe_id(item['id'])
        safe_id(item['source_id'])
    review_raw, review_digest = snapshot(review_path)
    review = json.loads(review_raw)
    overrides = json.loads(Path(candidate_overrides).read_text()) if candidate_overrides else {}
    if set(overrides) - {r['id'] for r in obs_rows}:
        raise ValueError('Override references unknown candidate')
    if len({r['id'] for r in obs_rows}) != len(obs_rows):
        raise ValueError('Duplicate basic candidate IDs')
    if review.get('statement') != '我已看过，“你”现在的动作是对的' or review.get('scope', {}).get('candidate_id') != 'basic-you':
        raise ValueError('Unexpected human review scope')
    if review.get('human_approved') is not True or review.get('training_ready') is not False or review.get('boundaries_approved') is not False:
        raise ValueError('Review scope cannot promote training or word alignment')
    for name, digest in review['bound_artifacts'].items():
        if ce.sha(Path(name)) != digest:
            raise ValueError('Reviewed motion/display changed')
    status, duplicates, conflicts = group_samples(current)
    terms, occurrences, mappings = make_terms(current, lexical)
    stage = Path(tempfile.mkdtemp(prefix=output.name + '.partial-', dir=output.parent))
    media = MediaCopies(stage)
    try:
        (stage / 'provenance').mkdir()
        for name, raw in originals.items():
            target = stage / 'provenance/original-ce-csl' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        samples = []
        for index, row in enumerate(current, 1):
            raw = row['raw']
            location = ('ce-csl' if status[row['id']] == 'retained' else 'quarantine/ce-csl') + '/' + row['video_relative_path']
            media.copy(ce.contained(source, row['video_relative_path']), row['video']['sha256'], location)
            item = {**row, 'dataset_id': 'CE-CSL', 'status': status[row['id']], 'media_sha256': row['video']['sha256'],
                    'local_video': location, 'project_split': 'unassigned', 'word_spans': [], **GATES}
            samples.append(item)
            if index % 500 == 0:
                print(ce.dumps({'copied_ce_samples': index, 'total': len(current)}), flush=True)
        for item in inventory['unique_sources']:
            media.copy(Path(item['path']), item['sha256'], f"tutorial-sources/video/{item['source_id']}.mp4")
        # Export only actual existing clips into the candidate set. The 573 teaching references are NOT fabricated isolated clips.
        candidates, motion_rows = [], []
        for row in obs_rows:
            matches = [m for m in mappings if m['source_id'] == row['source_id'] and m['source_sha256'] == row['source_sha256'] and
                       (m['canonical_text'] == row['text'] or row['text'] == '家' and m['canonical_text'] == '家（房子）')]
            if not matches:
                raise ValueError('Basic observation lacks source-bound semantic reference')
            number = 'candidate-' + row['id'].removeprefix('basic-')
            location = f'candidates/video/candidates/TUTORIAL/{number}.mp4'
            override = overrides.get(row['id'])
            frames, pts, frame_ids = row['decoded_frames'], row['source_pts_seconds'], row['source_frame_ids_0based']
            if len(pts) != frames or len(frame_ids) != frames or row['human_approved'] is not False or row['training_ready'] is not False:
                raise ValueError('Candidate frame/source/readiness contract differs')
            clip_source, clip_digest = ce.contained(observations, row['reference_clip']), row['reference_sha256']
            source_observation, observation_digest = ce.contained(observations, row['observations']), row['observations_sha256']
            if override:
                a, b = override['source_frame_selection_1based']
                if not (type(a) is int and type(b) is int and 1 <= a <= b <= frames and override['frames'] == b-a+1):
                    raise ValueError('Invalid exact candidate frame override')
                clip_source, clip_digest = Path(override['clip']), override['clip_sha256']
                source_observation, observation_digest = Path(override['observations']), override['observations_sha256']
                if ce.sha(Path(override['provenance'])) != override['provenance_sha256']:
                    raise ValueError('Boundary amendment changed')
                pts, frame_ids, frames = pts[a-1:b], frame_ids[a-1:b], b-a+1
            media.copy(clip_source, clip_digest, location)
            if ce.sha(source_observation) != observation_digest:
                raise ValueError('Source observations changed')
            target_obs = new_target(stage, 'candidates/observations/' + number + '.npz')
            target_obs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_observation, target_obs)
            candidate_check = validate_candidate_media(stage/location, target_obs, frames, row['reference_fps'], pts, frame_ids)
            raw = {'Number': number, 'Translator': 'TUTORIAL', 'Chinese Sentences': matches[0]['canonical_text'],
                   'Gloss': matches[0]['canonical_text'],
                   'Note': ce.dumps({'label_status': 'source_tutorial_candidate_not_ce_csl_annotation',
                                     'annotation_scope': 'assistant_coarse_teaching_window_not_certified_word_boundary',
                                     'translator_scope': 'source_family_code_not_signer_identity',
                                     'lexical_ids': [m['lexical_id'] for m in matches], 'human_approved': False,
                                     'training_ready': False, 'model_training_ready': False})}
            item = {'id': row['id'], 'dataset_id': 'tutorial-basic-candidates', 'source_split': 'candidates',
                    'project_split': 'unassigned', 'status': 'candidate_unaligned', 'raw': raw,
                    'media_sha256': clip_digest, 'local_video': location,
                    'source_id': row['source_id'], 'source_sha256': row['source_sha256'],
                    'source_pts_seconds': pts, 'source_frame_ids_0based': frame_ids,
                    'candidate_override': override, 'candidate_media_validation': candidate_check, 'frames': frames, 'reference_fps': row['reference_fps'], 'word_spans': [],
                    'mirror_status': 'unknown', 'anatomical_handedness': 'unverified',
                    'observations': str(target_obs.relative_to(stage)), 'human_approved': False, **GATES}
            samples.append(item)
            candidates.append(item)
        # User's statement attaches to the shown calibrated artifact, not to every CE-CSL 你 occurrence or the raw 73-frame baseline.
        review['id'] = identifier('review', review_digest)
        (stage / 'reviews').mkdir()
        (stage / 'reviews/basic-you-user-review.json').write_bytes(review_raw)
        for original, digest in review['bound_artifacts'].items():
            p = Path(original)
            if p.name == 'candidate.npz':
                native_bytes = reviewed_native(p, digest)
                target = new_target(stage, 'motions/basic-you-reviewed-keyframe/candidate.npz')
                target.parent.mkdir(parents=True)
                target.write_bytes(native_bytes)
                reviewed_native(target, digest)
                motion_rows.append({'id': 'basic-you-keyframe-44-reviewed', 'sample_id': 'basic-you', 'review_id': review['id'],
                                    'parameter_file': str(target.relative_to(stage)), 'sha256': digest, 'frames': 1,
                                    'representation': 'native_smplx_keyframe', 'human_approved': True,
                                    'semantic_review_scope': 'user_confirmed_displayed_current_you_expression',
                                    'full_sequence_approved': False, 'word_boundaries_verified': False, **GATES})
        for split in ce.SPLITS:
            selected = [r for r in samples if r['dataset_id'] == 'CE-CSL' and r['source_split'] == split and r['status'] == 'retained']
            target = stage / f'ce-csl/label/{split}.csv'
            target.parent.mkdir(parents=True, exist_ok=True)
            # Source fields stay verbatim. This is a dataset-format export, not a formula-mutating spreadsheet convenience export.
            import csv
            with target.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=HEADERS)
                writer.writeheader()
                writer.writerows(r['raw'] for r in selected)
            write_jsonl(stage / f'ce-csl/splits/{split}/samples.jsonl', selected)
            write_jsonl(stage / f'ce-csl/splits/{split}/gloss-lexicon.jsonl', ce.build_lexicon(selected))
        import csv
        for target, selected in [(stage / 'candidates/label/candidates.csv', candidates),
                                 (stage / 'quarantine/ce-csl/label/quarantined.csv', [r for r in samples if r['dataset_id'] == 'CE-CSL' and r['status'] != 'retained'])]:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=HEADERS)
                writer.writeheader()
                writer.writerows(r['raw'] for r in selected)
        datasets = [{'id': 'CE-CSL', 'kind': 'source_annotated_continuous_corpus', 'national_standard_dictionary_verified': False},
                    {'id': 'tutorial-basic-candidates', 'kind': 'source_specific_unaligned_teaching_candidates', **GATES}]
        extra_windows, extra_summary = [], None
        if extra_intake:
            spec = importlib.util.spec_from_file_location('reference_extra_attach', Path(__file__).with_name('sign-csl-reference-extra.py'))
            extra = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(extra)
            extra_datasets, extra_samples, extra_windows, extra_summary = extra.prepare(stage, extra_intake, media, terms)
            if {x['id'] for x in extra_samples} & {x['id'] for x in samples}:
                raise ValueError('Additional sample identities collide with current corpus')
            datasets += extra_datasets
            samples += extra_samples
        create_database(stage / 'database.sqlite', datasets, samples, terms, occurrences, lexical, mappings,
                        list(media.assets.values()), [review], motion_rows, duplicates, conflicts)
        if extra_intake:
            extra.add_windows_database(stage/'database.sqlite', extra_windows)
        write_jsonl(stage / 'samples.jsonl', samples)
        write_jsonl(stage / 'lexicon.jsonl', terms)
        write_jsonl(stage / 'tutorial/lexical-evidence.jsonl', lexical)
        write_jsonl(stage / 'tutorial/ce-csl-comparison.jsonl', mappings)
        novel_ids = {m['term_id'] for m in mappings if m['relation'] == 'not_in_ce_csl_exact_labels'}
        write_jsonl(stage / 'tutorial/not-in-ce-csl.jsonl', [t for t in terms if t['id'] in novel_ids])
        write_jsonl(stage / 'tutorial/unresolved.jsonl', [r for r in lexical if r['evidence_status'] == 'unresolved'])
        write_jsonl(stage / 'media-inventory.jsonl', media.assets.values())
        write_jsonl(stage / 'media-aliases.jsonl', media.aliases)
        write_json(stage / 'duplicates-and-conflicts.json', {'sample_duplicate_aliases': duplicates, 'label_conflicts': conflicts,
                   'same_sentence_different_video_preserved': ce.duplicate_groups(current, lambda r: r['raw']['Chinese Sentences']),
                   'same_gloss_sequence_different_video_preserved': ce.duplicate_groups(current, lambda r: ce.dumps(r['gloss_sequence'])),
                   'original_files_deleted': False})
        (stage/'provenance/tutorial-inventory.json').write_bytes(inventory_raw)
        (stage/'provenance/user-review.snapshot.json').write_bytes(review_raw)
        write_json(stage/'provenance/candidate-overrides.snapshot.json', overrides)
        override_evidence = {}
        for candidate_id, override in overrides.items():
            safe_id(candidate_id)
            original = Path(override['provenance'])
            raw, digest = snapshot(original)
            if digest != override['provenance_sha256']:
                raise ValueError('Candidate boundary provenance changed')
            target = new_target(stage, 'provenance/boundary-amendments/' + candidate_id + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            override_evidence[candidate_id] = {'original_path': str(original), 'relative_path': str(target.relative_to(stage)), 'sha256': digest}
        write_json(stage/'provenance/candidate-override-evidence.json', override_evidence)
        write_jsonl(stage/'tutorial/original-source-aliases.jsonl', inventory['unique_sources'])
        for name, digest in review['bound_artifacts'].items():
            path = Path(name)
            if path.suffix.lower() in {'.jpg', '.png', '.mp4', '.html'}:
                target = new_target(stage, 'reviews/displayed/' + path.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path,target)
                if ce.sha(target)!=digest: raise ValueError('Reviewed display artifact changed during copy')
        write_json(stage / 'provenance/source-inputs.json', {'ce_csv': inputs, 'old_sample_index_sha256': previous_digest,
                   'tutorial_lexical_sha256': lexical_digest, 'tutorial_inventory_sha256': inventory_digest,
                   'observations_index_sha256': obs_digest, 'review_sha256': review_digest,
                   'independent_revalidation_sha256': ce.sha(Path(validation)), 'tool_sha256': ce.sha(Path(__file__)),
                   'ce_parser_sha256': ce.sha(Path(ce.__file__)),
                   'candidate_overrides_sha256': ce.sha(Path(candidate_overrides)) if candidate_overrides else None})
        shutil.copyfile(validation, stage / 'provenance/source-revalidation.json')
        report = {'schema': 'signbridge-csl-reference-database-v1', 'status': 'rebuilt_reference_database_not_model_training',
                  'created_at_utc': datetime.now(timezone.utc).isoformat(), 'source_ce_samples': len(current),
                  'retained_ce_samples': sum(r['dataset_id'] == 'CE-CSL' and r['status'] == 'retained' for r in samples),
                  'source_ce_split_counts': dict(Counter(r['source_split'] for r in current)),
                  'retained_ce_split_counts': dict(Counter(r['source_split'] for r in samples if r['dataset_id'] == 'CE-CSL' and r['status'] == 'retained')),
                  'ce_gloss_labels': sum(t['in_ce_csl'] for t in terms), 'ce_gloss_occurrences': len(occurrences),
                  'tutorial_lexical_records': len(lexical), 'tutorial_unit_types': dict(Counter(r['unit_type'] for r in lexical)),
                  'tutorial_unique_typed_labels': len({(r['canonical_text'], r['unit_type']) for r in lexical}),
                  'tutorial_exact_label_overlap_records': sum(m['label_present_in_ce_csl'] for m in mappings),
                  'tutorial_new_exact_label_typed_entries': len(novel_ids),
                  'tutorial_new_exact_unique_labels': len({t['label'] for t in terms if t['id'] in novel_ids}), 'tutorial_total_terms_kept_separate': sum(not t['in_ce_csl'] for t in terms),
                  'union_index_terms': len(terms), 'unresolved_tutorial_records': sum(r['evidence_status'] == 'unresolved' for r in lexical),
                  'additional_source_intake': extra_summary, 'basic_candidate_clips': len(candidates), 'basic_candidate_frames': sum(r['frames'] for r in candidates), 'media_unique_bytes_copies': len(media.assets),
                  'media_path_aliases': len(media.aliases), 'media_unique_bytes': sum(m['bytes'] for m in media.assets.values()),
                  'conflicting_media_groups': len(conflicts), 'conflicting_samples_quarantined': sum(r['status'] == 'quarantined_label_conflict' for r in samples),
                  'identical_sample_aliases': len(duplicates), 'tutorial_duplicate_source_aliases_collapsed': inventory['counts']['exact_duplicates'],
                  'user_reviewed_motion_artifacts': len(motion_rows), 'user_review_scope': 'displayed_you_expression_only',
                  'source_raw_labels_and_variants_preserved': True, 'original_sources_modified': False,
                  'all_ce_videos_redecoded': False, 'all_ce_videos_reconstructed_to_skeleton': False,
                  'new_model_training_started': False, 'gpu_job_started': False, 'github_pushed': False,
                  'national_standard_gestures_verified': False, **GATES}
        # Recheck all small sources and source identities before making the successful output visible.
        if any(ce.sha(source / x['relative_path']) != x['sha256'] for x in inputs) or ce.sha(intake / 'samples.jsonl') != previous_digest or ce.sha(tutorial_audit / 'lexical-entries.jsonl') != lexical_digest or ce.sha(Path(review_path)) != review_digest:
            raise ValueError('Inputs changed during database rebuild')
        validate_revalidation(check, source, intake, tutorial_inventory)
        if ce.sha(Path(tutorial_inventory)) != inventory_digest or ce.sha(observations/'observations-records.jsonl') != obs_digest:
            raise ValueError('Tutorial or observation index changed during build')
        if candidate_overrides and json.loads(Path(candidate_overrides).read_text()) != overrides:
            raise ValueError('Candidate overrides changed during build')
        for motion in motion_rows:
            reviewed_native(stage/motion['parameter_file'], motion['sha256'])
        for original,digest in review['bound_artifacts'].items():
            if ce.sha(Path(original)) != digest: raise ValueError('Reviewed input changed before publication')
        shutil.copyfile(Path(__file__), stage / 'provenance/build-tool.py')
        write_json(stage / 'report.json', report)
        (stage / 'SHA256SUMS').write_text(''.join(ce.sha(p) + '  ' + p.relative_to(stage).as_posix() + '\n' for p in sorted(stage.rglob('*')) if p.is_file()))
        stage.rename(output)
        return report
    except Exception as error:
        if (stage/'report.json').exists():
            (stage/'report.json').replace(stage/'PREPUBLICATION-REPORT.snapshot.json')
        write_json(stage / 'BUILD-FAILED.json', {'error': repr(error), 'preserved_partial_output': str(stage)})
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['source', 'intake', 'tutorial-audit', 'tutorial-inventory', 'observations', 'review', 'validation', 'output']:
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--candidate-overrides', type=Path)
    p.add_argument('--extra-intake', type=Path)
    a = p.parse_args()
    print(ce.dumps(build(a.source, a.intake, a.tutorial_audit, a.tutorial_inventory,
                        a.observations, a.review, a.output, a.validation, a.candidate_overrides, a.extra_intake)), flush=True)


if __name__ == '__main__':
    main()
