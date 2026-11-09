"""Expand the frozen CSL reference corpus without upgrading unverified gestures."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


foundation = load_tool('sign-csl-foundation.py')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def jsonl(path, records):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in records))


def checked_path(root, name):
    path = root / name
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe source artifact: ' + name)
    if any(root.joinpath(*relative.parts[:n]).is_symlink() for n in range(1, len(relative.parts) + 1)) or not path.is_file():
        raise ValueError('Missing or symlinked source artifact: ' + name)
    return path


def manifest(root):
    result = {}
    for line in (root / 'SHA256SUMS').read_text().splitlines():
        code, name = line.split('  ', 1)
        if len(code) != 64 or name in result or any(c not in '0123456789abcdef' for c in code):
            raise ValueError('Invalid manifest')
        result[name] = code
    return result


def read_frozen(root, name, hashes):
    path = checked_path(root, name)
    expected = manifest(root).get(name)
    if sha(path) != expected:
        raise ValueError('Frozen input changed: ' + str(path))
    hashes[str(path)] = expected
    return lines(path) if path.suffix == '.jsonl' else json.loads(path.read_text())


def entry_key(kind, text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Empty lexical label')
    return kind, text.strip()


def add_unit(entries, kind, text, sense, base_id=None):
    key = entry_key(kind, text)
    if key not in entries:
        entries[key] = {
            'id': base_id or 'expanded-' + digest(list(key))[:24], 'text': key[1],
            'unit_type': kind, 'base_foundation_ids': [], 'source_senses': [],
            'action_ids': [], 'category': '来源分类待细化',
            'label_grouping_scope': 'exact_typed_written_label_not_equated_sign_forms',
            'word_boundary_verified': False, 'human_approved': False,
            'training_ready': False, 'model_training_ready': False,
        }
    unit = entries[key]
    if base_id:
        if unit['base_foundation_ids'] and base_id not in unit['base_foundation_ids']:
            raise ValueError('Duplicate foundation spelling with incompatible IDs')
        unit['id'] = base_id
        if base_id not in unit['base_foundation_ids']:
            unit['base_foundation_ids'].append(base_id)
    if any(x['id'] == sense['id'] for x in unit['source_senses']):
        raise ValueError('Duplicate source sense ID')
    unit['source_senses'].append(sense)
    return unit


def motion_status(action):
    if not action or not action.get('action_version_sha256'):
        return {'passed': False, 'full_action_two_round_passes': 0, 'reasons': ['missing_native_action']}
    result = foundation.gate(action, action.get('validation_rounds', []))
    # A partial count of individual passes cannot promote a full action.
    return {'passed': result['training_allowed'], 'full_action_two_round_passes': 2 if result['training_allowed'] else 0, 'reasons': result['reasons']}


def caption_classification(row, foundation_units):
    if row.get('lexicon_eligible', True) is False:
        return None, None
    mapping = {'word_candidate': 'word', 'phrase_candidate': 'phrase', 'sentence_candidate': 'sentence'}
    proposed = mapping.get(row['refined_unit_type'], row['refined_unit_type'].removesuffix('_candidate'))
    matches = [x for x in foundation_units if row['id'] in x['source_caption_ids'] and x['text'].strip() == row['clean_text'].strip()]
    types = {x['unit_type'] for x in matches}
    if len(types) == 1 and proposed not in types:
        actual = next(iter(types))
        return actual, {'original_candidate_type': row['refined_unit_type'], 'effective_chinese_type': actual,
                        'foundation_ids': [x['id'] for x in matches],
                        'basis': 'same_caption_ID_and_exact_text_already_classified_in_foundation',
                        'motion_or_word_boundary_approval': False}
    return proposed, None


def gloss_index(samples, reference_rows):
    rows = {}
    for source in reference_rows:
        if not source.get('in_ce_csl'):
            continue
        label = source['label']
        rows[label] = {'id': source['id'], 'text': label, 'unit_type': 'dataset_gloss',
                       'declared_original_occurrences_by_split': source['ce_occurrences_by_split'],
                       'occurrences_retained_by_split': {}, 'occurrences_all_by_split': {},
                       'sample_ids': [], 'retained_sample_ids': [], 'quarantined_sample_ids': [],
                       'word_boundary_verified': False, 'training_ready': False, 'model_training_ready': False}
    for sample in samples:
        if sample.get('dataset_id') != 'CE-CSL':
            continue
        for label in sample['gloss_sequence']:
            if label not in rows:
                rows[label] = {'id': 'ce-gloss-' + digest(label)[:24], 'text': label, 'unit_type': 'dataset_gloss',
                               'declared_original_occurrences_by_split': {}, 'occurrences_retained_by_split': {},
                               'occurrences_all_by_split': {}, 'sample_ids': [], 'retained_sample_ids': [], 'quarantined_sample_ids': [],
                               'word_boundary_verified': False, 'training_ready': False, 'model_training_ready': False}
            row = rows[label]
            split = sample['source_split']
            row['occurrences_all_by_split'][split] = row['occurrences_all_by_split'].get(split, 0) + 1
            row['sample_ids'].append(sample['id'])
            if sample['status'] == 'retained':
                row['occurrences_retained_by_split'][split] = row['occurrences_retained_by_split'].get(split, 0) + 1
                row['retained_sample_ids'].append(sample['id'])
            else:
                row['quarantined_sample_ids'].append(sample['id'])
    for row in rows.values():
        row['sample_ids'] = sorted(set(row['sample_ids']))
        row['retained_sample_ids'] = sorted(set(row['retained_sample_ids']))
        row['quarantined_sample_ids'] = sorted(set(row['quarantined_sample_ids']))
        row['has_train_source'] = row['occurrences_retained_by_split'].get('train', 0) > 0
    return sorted(rows.values(), key=lambda row: row['text'])


def native_audit_impl(job):
    base, action = job
    h = load_tool('sign-hand-refine.py')
    compare = load_tool('sign-csl-foundation-compare.py')
    sid = action['id']
    if not action.get('local_native_directory'):
        return {'id': sid, 'status': 'missing_native_action', 'full_action_pass': False, 'training_ready': False}
    root = Path(base) / action['local_native_directory']
    inventory = compare.verify_action({**action['native_comparison'], 'native_directory': str(root)})
    parameter_files = sorted((root / 'smplx').glob('*.npz'))
    for file in parameter_files:
        h.read_native(file)
    return {'id': sid, 'status': 'native_structure_verified_not_motion_certified',
            'frames_expected': action['frames'], 'native_frames_finite_shapes_verified': len(parameter_files),
            'all_frames_native_complete': len(parameter_files) == action['frames'],
            'original_action_version_sha256': action['action_version_sha256'],
            'exact_native_metadata_render_inventory_sha256': digest(inventory),
            'full_action_pass': motion_status(action)['passed'], 'training_ready': False}


def native_audit(job):
    try:
        return native_audit_impl(job)
    except Exception as error:
        return {'id': job[1]['id'], 'status': 'native_reverification_failed',
                'error_type': type(error).__name__, 'error': str(error),
                'full_action_pass': False, 'training_ready': False}


def build(base, reference, output, correction=None):
    base, reference, output = map(lambda p: Path(p).resolve(), [base, reference, output])
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in [base, reference]):
        raise ValueError('New separate output required')
    hashes = {str(base / 'SHA256SUMS'): sha(base / 'SHA256SUMS'), str(reference / 'SHA256SUMS'): sha(reference / 'SHA256SUMS')}
    original = read_frozen(base, 'foundation-units.jsonl', hashes)
    refined = read_frozen(base, 'refined-tutorial.jsonl', hashes)
    captions = read_frozen(base, 'refined-captions.jsonl', hashes)
    actions = read_frozen(base, 'action-checks.jsonl', hashes)
    characters = read_frozen(base, 'characters.jsonl', hashes)
    lexical = read_frozen(reference, 'tutorial/lexical-evidence.jsonl', hashes)
    lexicon = read_frozen(reference, 'lexicon.jsonl', hashes)
    samples = read_frozen(reference, 'samples.jsonl', hashes)
    conflicts = read_frozen(reference, 'duplicates-and-conflicts.json', hashes)
    media = read_frozen(reference, 'media-inventory.jsonl', hashes)
    lexical_by_id = {x['id']: x for x in lexical}
    sample_by_id = {x['id']: x for x in samples}
    action_by_id = {x['id']: x for x in actions}
    if any(len(rows) != len({r['id'] for r in rows}) for rows in [original, lexical, samples, actions]):
        raise ValueError('Duplicate primary source IDs')
    if {x['original_lexical_id'] for x in refined} != set(lexical_by_id):
        raise ValueError('Refinement does not cover every lexical source')
    output.mkdir(parents=True)
    (output / 'provenance').mkdir()
    (output / 'source-snapshots').mkdir()
    (output / 'validation').mkdir()
    entries, evidence = {}, []
    for row in original:
        sense = {'id': 'foundation:' + row['id'], 'kind': 'foundation', 'meaning': row['meaning'],
                 'do_not_equate': row['do_not_equate'], 'source_lexical_ids': row['source_lexical_ids'],
                 'source_caption_ids': row['source_caption_ids'], 'prior_full_motion_verified': False}
        unit = add_unit(entries, row['unit_type'], row['text'], sense, row['id'])
        unit['category'] = row['category']
        unit['action_ids'] = list(row['action_ids'])
        evidence.append(sense)
    lexical_actions = defaultdict(list)
    for sample in samples:
        if sample['dataset_id'] == 'tutorial-basic-candidates':
            note = json.loads(sample['raw']['Note'])
            for lexical_id in note.get('lexical_ids', []):
                lexical_actions[lexical_id].append(sample['id'])
    for row in refined:
        source = lexical_by_id[row['original_lexical_id']]
        if row['source_id'] != source['source_id'] or row['source_sha256'] != source['source_sha256'] or row['meaning_clean'] != source['meaning']:
            raise ValueError('Source-specific meaning/identity mismatch')
        sense = {'id': 'tutorial:' + source['id'], 'kind': 'tutorial', 'meaning': row['meaning_clean'],
                 'source_id': source['source_id'], 'source_sha256': source['source_sha256'],
                 'source_video': source['source_video'], 'source_intervals': source['source_intervals'],
                 'manual_form_note': source['manual_form_note'], 'nonmanual_note': source['nonmanual_note'],
                 'source_unit_type': row['source_unit_type'], 'refined_unit_type': row['refined_unit_type'],
                 'classification_reason': row['classification_reason'], 'do_not_equate': row['do_not_equate'],
                 'uncertainties': row['review_uncertainties'], 'evidence_status': row['evidence_status'],
                 'word_motion_alignment_verified': False, 'human_approved': False}
        unit = add_unit(entries, row['refined_unit_type'], row['canonical_text'], sense)
        if unit['category'] == '来源分类待细化':
            unit['category'] = source['category']
        unit['action_ids'].extend(lexical_actions.get(source['id'], []))
        evidence.append(sense)
    excluded = []
    for row in captions:
        sample = sample_by_id[row['id']]
        if sample['source_sha256'] != row['source_sha256']:
            raise ValueError('Caption/source identity mismatch')
        sense = {'id': 'caption:' + row['id'], 'kind': 'caption', 'raw_text': row['raw_text'],
                 'clean_text': row['clean_text'], 'meaning': None, 'source_id': sample['source_id'],
                 'source_sha256': row['source_sha256'], 'clip_sha256': sample['media_sha256'],
                 'local_video': sample['local_video'], 'source_window_seconds_nominal': sample['source_window_seconds_nominal'],
                 'classification_reason': row['reason'], 'lexicon_eligible': row['lexicon_eligible'],
                 'visual_correction': row['visual_correction'], 'human_approved': False, 'word_motion_alignment_verified': False}
        kind, normalization = caption_classification(row, original)
        sense['original_refined_unit_type'] = row['refined_unit_type']
        sense['effective_chinese_unit_type'] = kind
        sense['classification_normalization'] = normalization
        evidence.append(sense)
        if not row['lexicon_eligible']:
            excluded.append(sense)
            continue
        unit = add_unit(entries, kind, row['clean_text'], sense)
        if row['id'] in action_by_id:
            unit['action_ids'].append(row['id'])
    gloss = gloss_index(samples, lexicon)
    units = sorted(entries.values(), key=lambda row: (not row['base_foundation_ids'], row['unit_type'], row['text']))
    by_text = defaultdict(list)
    for unit in units:
        unit['action_ids'] = sorted(set(unit['action_ids']))
        by_text[unit['text']].append(unit['id'])
        unit['source_evidence_ids'] = [s['id'] for s in unit['source_senses']]
        unit['evidence_version_sha256'] = digest(unit)
        unit['motion_status_by_action'] = {sid: motion_status(action_by_id.get(sid)) for sid in unit['action_ids']}
        unit['full_action_two_round_passes'] = 0
        unit['passed'] = False
        unit['remaining_issues'] = ['word_boundary_not_verified', 'same_version_complete_motion_rounds_not_passed']
        if not unit['action_ids']:
            unit['remaining_issues'].append('no_isolated_native_action_mapping')
        unit['technical_validation'] = {'round1': 'assembly_source_bindings_checked_not_full_acceptance', 'round2': 'pending_independent_source_audit'}
    for row in gloss:
        row['exact_written_label_matches'] = by_text.get(row['text'], [])
        row['sign_equivalence_certified'] = False
        row['evidence_version_sha256'] = digest(row)
    sentence_rows = []
    for sample in samples:
        if sample['dataset_id'] != 'CE-CSL':
            continue
        sentence_rows.append({'id': sample['id'], 'chinese': sample['raw']['Chinese Sentences'],
                              'raw_gloss': sample['raw']['Gloss'], 'gloss_sequence': sample['gloss_sequence'],
                              'source_split': sample['source_split'], 'status': sample['status'],
                              'media_sha256': sample['media_sha256'], 'local_video': sample['local_video'],
                              'source_label': sample['source_label'], 'word_spans': sample['word_spans'],
                              'whole_sequence_only_not_word_frame_alignment': True,
                              'training_ready': False, 'model_training_ready': False})
    duplicates = {'exact_typed_label_grouping': [{'id': x['id'], 'text': x['text'], 'source_senses': len(x['source_senses'])} for x in units if len(x['source_senses']) > 1],
                  'same_spelling_different_type_preserved': {k: v for k, v in by_text.items() if len(v) > 1},
                  'source_media_and_label_conflicts': conflicts, 'source_files_deleted': False,
                  'same_text_does_not_prove_same_sign': True}
    tables = {'units': units, 'gloss-index': gloss, 'source-evidence': evidence, 'sentences': sentence_rows,
              'written-characters': characters, 'source-samples': samples, 'actions': actions, 'excluded-labels': excluded,
              'media-inventory': media}
    for name, rows in tables.items():
        jsonl(output / (name + '.jsonl'), rows)
    write(output / 'duplicates-and-conflicts.json', duplicates)
    connection = sqlite3.connect(output / 'database.sqlite')
    try:
        for name, rows in tables.items():
            table = name.replace('-', '_')
            connection.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            connection.executemany(f'INSERT INTO "{table}" VALUES (?,?)', [(row.get('id') or row.get('character') or row.get('sha256'), json.dumps(row, ensure_ascii=False, allow_nan=False)) for row in rows])
        connection.commit()
    finally:
        connection.close()
    print(json.dumps({'stage': 'expanded_rows_built', 'units': len(units), 'gloss_labels': len(gloss), 'samples': len(samples)}, ensure_ascii=False), flush=True)
    # Reopen native files: reused structure evidence is not silently promoted into gesture approval.
    with ProcessPoolExecutor(max_workers=3) as pool:
        native_records = []
        for item in pool.map(native_audit, [(str(base), row) for row in actions]):
            native_records.append(item)
            if len(native_records) % 30 == 0:
                print(json.dumps({'stage': 'native_reverification', 'checked': len(native_records), 'expected': len(actions)}), flush=True)
    jsonl(output / 'validation/native-reverification.jsonl', native_records)
    correction_note = None
    if correction:
        correction = Path(correction).resolve()
        status_file = correction / 'delivery-status.json'
        if not status_file.is_file():
            raise ValueError('Missing prior correction status')
        correction_note = json.loads(status_file.read_text())
        if correction_note['training_ready'] or correction_note['full_action_two_round_passes']:
            raise ValueError('Unreviewed prior correction unexpectedly promoted')
        write(output / 'validation/latest-correction-still-not-passed.json', correction_note)
        hashes[str(status_file)] = sha(status_file)
    for name, code in hashes.items():
        if sha(name) != code:
            raise ValueError('Frozen source changed during expansion')
        target = output / 'source-snapshots' / (code[:16] + '-' + Path(name).name)
        shutil.copy2(name, target)
    write(output / 'provenance/input-hashes.json', hashes)
    shutil.copy2(Path(__file__), output / 'provenance/sign-csl-expanded.py')
    shutil.copy2(Path(__file__).with_name('sign-csl-foundation.py'), output / 'provenance/sign-csl-foundation.py')
    report = {'schema': 'signbridge-expanded-foundation-v1', 'status': 'expanded_candidate_database_not_motion_approved',
              'created_at_utc': datetime.now(timezone.utc).isoformat(), 'base': str(base), 'reference': str(reference),
              'base_foundation_preserved': len(original), 'typed_written_entries': len(units),
              'new_typed_entries_beyond_foundation': sum(not x['base_foundation_ids'] for x in units),
              'unit_type_counts': dict(Counter(x['unit_type'] for x in units)),
              'ce_gloss_labels': len(gloss), 'ce_samples_all': len(sentence_rows),
              'ce_samples_retained': sum(x['status'] == 'retained' for x in sentence_rows),
              'ce_samples_quarantined': sum(x['status'] != 'retained' for x in sentence_rows),
              'source_samples': len(samples), 'source_evidence_records': len(evidence),
              'written_characters': len(characters), 'excluded_caption_labels': len(excluded),
              'caption_classification_normalizations': [x for x in evidence if x.get('classification_normalization')],
              'entries_with_prior_motion_candidates': sum(bool(x['action_ids']) for x in units),
              'prior_motion_records_reopened': len(native_records),
              'prior_native_frames_reverified': sum(x.get('native_frames_finite_shapes_verified', 0) for x in native_records),
              'native_reverification_failures': sum(x['status'] == 'native_reverification_failed' for x in native_records),
              'prior_native_complete': sum(x.get('all_frames_native_complete', False) for x in native_records),
              'full_action_two_round_accepted_entries': 0, 'training_ready': False, 'model_training_ready': False,
              'network_training_started': False, 'demo_library_modified': False,
              'local_only': True, 'media_copied_into_this_metadata_database': False,
              'source_directories_required': [str(base), str(reference)],
              'source_snapshot_sha256': digest(hashes), 'tool_sha256': sha(__file__)}
    write(output / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['base', 'reference', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--correction', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.reference, args.output, args.correction), ensure_ascii=False), flush=True)
