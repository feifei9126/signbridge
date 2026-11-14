"""Resume local video annotation using source hashes and cached OCR; never approve labels."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_lines(path, rows):
    Path(path).write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows))


def group_by_hash(rows):
    result = defaultdict(list)
    for row in rows:
        result[row['sha256']].append(row)
    return dict(result)


def language_hint(title):
    return 'HKSL_title_hint_unverified' if re.search('香港.*手[语語]', title) else 'unconfirmed'


def conservative_source_group(relative_path, source_id):
    if re.search('中国手语培训教程|国家通用标准规范手语', relative_path):
        return 'unverified-csl-standard-course-family'
    if '欢行手语' in relative_path:
        return 'unverified-huanxing-course-family'
    return 'unverified-source-' + source_id


def panel_text(lines):
    """Caption layout observed in the supplied lesson series, not a general OCR rule."""
    selected = []
    for line in lines:
        box = line['bounding_box']
        if len(box) != 4 or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in box):
            raise ValueError('Invalid OCR bounding box')
        x, y, width, height = box
        if not -.02 <= x <= 1.02 or not -.02 <= y <= 1.02 or not 0 < width <= 1.02 or not 0 < height <= 1.02:
            raise ValueError('OCR bounding box outside image')
        text = line['text'].strip()
        if .5 < x and .55 < y < .90 and height >= .025 and re.search('[\u4e00-\u9fff]', text) and not re.search('手语学校|公益', text):
            selected.append((y, text))
    text = ''.join(value for _, value in sorted(selected, reverse=True))
    return text if 2 <= len(text) <= 60 else ''


def panel_demonstrations(rows, duration, interval=2.):
    """Choose the last stable, instruction-free candidate for each literal caption."""
    runs, active, previous = [], None, None
    for row in rows:
        seconds = row['source_seconds']
        if not math.isfinite(seconds) or not 0 <= seconds < duration or previous is not None and seconds <= previous:
            raise ValueError('Invalid OCR timeline')
        previous = seconds
        text = panel_text(row['lines'])
        instruction = any(.55 < line['bounding_box'][0] and .12 < line['bounding_box'][1] < .43 and re.search('[\u4e00-\u9fff]', line['text']) for line in row['lines'])
        if not text or instruction:
            active = None
            continue
        evidence = {key: row[key] for key in ('image', 'image_sha256')}
        evidence['source_seconds'] = seconds
        if active and active['text_candidate'] == text and seconds - active['observed_times'][-1] <= interval * 1.01:
            active['observed_times'].append(seconds)
            active['evidence'].append(evidence)
        else:
            active = {'text_candidate': text, 'observed_times': [seconds], 'evidence': [evidence]}
            runs.append(active)
    result = {}
    for run in runs:
        if len(run['observed_times']) < 2:
            continue
        start, end = max(0., run['observed_times'][0] - interval / 2), min(duration, run['observed_times'][-1] + interval / 2)
        if not 4 <= end - start <= 24:
            continue
        run.update(start_seconds=start, end_seconds=end, training_ready=False,
                   semantics_approved=False, boundaries_approved=False,
                   selection_basis='last repeated right-top caption run without lower-right decomposition text; not verified signing boundaries')
        result[run['text_candidate']] = run
    return list(result.values())


def verify_evidence(root, evidence):
    root = Path(root).resolve()
    for row in evidence:
        relative = Path(row['image'])
        file = (root / relative).resolve()
        if relative.is_absolute() or root not in file.parents or not file.is_file() or sha(file) != row['image_sha256']:
            raise ValueError('OCR image evidence missing, unsafe or changed')


def build_index(args):
    root, dataset, output = args.source_root.resolve(), args.dataset.resolve(), args.output.resolve()
    if output.exists() or root == output or root in output.parents or output in root.parents:
        raise ValueError('New output outside source directory required')
    data = load_tool('sign-data')
    candidate = load_tool('sign-source-candidates')
    manifests = [dataset / 'sign-language-pilot/sources.json',
                 dataset / 'tutorial-hand-reference-20261010-v1/sources.json',
                 dataset / 'tutorial-hand-reference-20261010-v2/sources.json',
                 args.new_manifest.resolve()]
    known = defaultdict(list)
    screens = {}
    provenance = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        provenance.append({'path': str(manifest_path), 'sha256': sha(manifest_path)})
        for source in manifest['sources']:
            known[source['sha256']].append((manifest_path, source))
            proposed = manifest_path.parent / 'screen' / source['source_id']
            if (proposed / 'ocr.jsonl').is_file():
                screens[source['sha256']] = {'file': proposed / 'ocr.jsonl', 'root': manifest_path.parent}
    prior_screen = dataset / 'data-expansion-20261010/source-screen'
    if (prior_screen / 'screen.json').exists():
        for source in json.loads((prior_screen / 'screen.json').read_text())['sources']:
            checksum = source['source_sha256']
            if checksum not in screens:
                screens[checksum] = {'file': prior_screen / source['source_id'] / 'ocr.jsonl', 'root': prior_screen}
    for source in json.loads((args.new_screen.resolve() / 'screen.json').read_text())['sources']:
        screens[source['source_sha256']] = {'file': args.new_screen.resolve() / source['source_id'] / 'ocr.jsonl', 'root': args.new_screen.resolve()}

    files = []
    for file in sorted(root.rglob('*')):
        if file.is_file() and file.suffix.lower() in data.VIDEO_EXTENSIONS:
            if root not in file.resolve().parents:
                raise ValueError('Video symlink outside source root')
            files.append({'relative_path': str(file.relative_to(root)), 'sha256': sha(file), 'bytes': file.stat().st_size})
    groups = group_by_hash(files)
    refs = defaultdict(list)
    for rel in ('tutorial-hand-reference-20261010-v2/hand-reference-pack/references.jsonl',
                'tutorial-hand-reference-20261010-v2/new-hand-reference-pack/references.jsonl',
                'tutorial-shouyu-expansion-20261012/reference-pack/references.jsonl'):
        file = dataset / rel
        if file.is_file():
            for row in read_lines(file):
                refs[row['source_sha256']].append({'id': row['annotation_id'], 'label': row['label'], 'path': str(file), 'training_ready': False})
    motions = defaultdict(list)
    for rel in ('remaining14-research-20261010/verified/motions/motions.jsonl',
                'full-sequence-20261009/curated-motions-final/motions.jsonl',
                'data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1/motions.jsonl'):
        file = dataset / rel
        if file.is_file():
            for row in read_lines(file):
                motions[row['source_sha256']].append({'id': row['segment_id'], 'text': row['text_verified'], 'motion_review_status': row['motion_review_status'], 'path': str(file), 'model_training_ready': row['model_training_ready']})

    registry, sources, annotations, lessons = [], [], [], []
    for checksum, aliases in groups.items():
        if checksum not in known:
            raise ValueError('New video has appeared since scan; run a new source scan: ' + aliases[0]['relative_path'])
        manifest_path, source = known[checksum][-1]
        current = {**source, 'relative_path': aliases[0]['relative_path'], 'aliases': [item['relative_path'] for item in aliases]}
        sources.append(current)
        registry.append({'source_id': current['source_id'], 'sha256': checksum, 'aliases': current['aliases'],
                         'prior_manifests': [{'path': str(p), 'source_id': r['source_id']} for p, r in known[checksum]],
                         'cached_ocr': str(screens[checksum]['file']) if checksum in screens else None,
                         'prior_reference_windows': refs[checksum], 'prior_continuous_motions': motions[checksum],
                         'proposed_split_group': conservative_source_group(current['relative_path'], current['source_id']),
                         'stage': 'continuous_motion_present_pending_quality' if motions[checksum] else 'reference_windows_present_pending_review' if refs[checksum] else 'caption_screened_pending_reference' if checksum in screens else 'inventory_only',
                         'language_hint': language_hint(current['relative_path']), 'training_ready': False})
        if manifest_path != args.new_manifest.resolve() or checksum not in screens:
            continue
        screen = screens[checksum]
        rows = read_lines(screen['file'])
        if re.search('第.+课：', current['relative_path']):
            selected = panel_demonstrations(rows, current['duration_seconds'])
            kind = 'right_caption_sentence_candidate'
        else:
            spans = candidate.caption_spans(rows, current['duration_seconds'], 2.)
            selected = [span for span in spans if span['section'] == 'single_person_demo' and len(span['observed_times']) >= 2 and 4 <= span['end_seconds'] - span['start_seconds'] <= 16 and not span['text_candidate'].endswith(('，', '、', '：'))]
            for span in selected:
                span['evidence'] = [{k: row[k] for k in ('image', 'image_sha256', 'source_seconds')} for row in rows if row['source_seconds'] in span['observed_times']]
            kind = 'single_person_marker_sentence_candidate'
        unique = {}
        for span in selected:
            unique[span['text_candidate']] = span
        for number, span in enumerate(unique.values(), 1):
            verify_evidence(screen['root'], span['evidence'])
            evidence = [{**value, 'image': str((screen['root'] / value['image']).resolve())} for value in span['evidence']]
            old_matches = [r['id'] for rows_ in motions.values() for r in rows_ if candidate.normalized_text(r['text']) == candidate.normalized_text(span['text_candidate'])]
            annotations.append({'annotation_id': 'catchup-' + current['source_id'][-16:] + '-%03d' % number,
                                'source_id': current['source_id'], 'source_sha256': checksum,
                                'start_seconds': span['start_seconds'], 'end_seconds': span['end_seconds'],
                                'label': span['text_candidate'], 'sample_type': 'word_candidate',
                                'candidate_content_kind': kind, 'label_evidence': 'positioned_original_OCR_with_image_hashes',
                                'boundary_review': 'sparse_ocr_window', 'mirror_status': 'unknown',
                                'signer_identity': 'unconfirmed', 'split': 'unassigned',
                                'split_group': 'unverified-textbook-family' if '倪兰' in current['relative_path'] else 'unverified-puji-course-family' if re.search('第.+课：', current['relative_path']) else conservative_source_group(current['relative_path'], current['source_id']),
                                'language': 'unconfirmed', 'language_hint': language_hint(current['relative_path']),
                                'human_approved': False, 'training_ready': False, 'semantics_approved': False,
                                'boundaries_approved': False, 'evidence': evidence,
                                'matches_previous_reference_text': old_matches,
                                'signing_content_duplicate_confirmed': False,
                                'hand_shape_note': '同片原画面手部参考；未凭词名推测手型或数值关节角；可能含讲解、准备、重复和对话两句。',
                                'selection_basis': span.get('selection_basis', 'repeated caption in a single-person-labelled chapter; label and boundaries unverified')})
        lessons.append({'source_id': current['source_id'], 'relative_path': current['relative_path'],
                        'sha256': checksum, 'duration_seconds': current['duration_seconds'],
                        'ocr': str(screen['file']), 'ocr_samples': len(rows), 'candidate_windows': len(unique),
                        'language_hint': language_hint(current['relative_path']), 'training_ready': False})
    output.mkdir(parents=True)
    manifest = {'schema': 'signbridge-catchup-source-manifest-v1', 'source_root': str(root), 'sources': sources,
                'source_files_modified': False, 'training_ready': False, 'created_at': datetime.now(timezone.utc).isoformat()}
    write_json(output / 'sources.json', manifest)
    write_json(output / 'source-registry.json', {'schema': 'signbridge-source-registry-v1', 'files': files, 'sources': registry,
                                               'manifest_provenance': provenance, 'training_ready': False})
    write_lines(output / 'sentence-reference-candidates.jsonl', annotations)
    write_lines(output / 'lessons.jsonl', lessons)
    summary = {'schema': 'signbridge-source-catchup-index-v1', 'source_paths': len(files), 'unique_sources': len(groups),
               'duplicate_paths': len(files) - len(groups), 'new_screened_sources': len(lessons),
               'sentence_reference_candidates': len(annotations), 'candidate_sources': len({r['source_id'] for r in annotations}),
               'candidate_seconds': sum(r['end_seconds'] - r['start_seconds'] for r in annotations),
               'prior_text_overlap_candidates': sum(bool(r['matches_previous_reference_text']) for r in annotations),
               'new_verified_sign_labels': 0, 'training_ready': False, 'source_files_modified': False,
               'stage_counts': {stage: sum(row['stage'] == stage for row in registry) for stage in sorted({row['stage'] for row in registry})},
               'tool_sha256': sha(__file__), 'manifest_provenance': provenance}
    write_json(output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False))



def even_indices(count, maximum=5):
    if not isinstance(count, int) or count < 1 or not isinstance(maximum, int) or maximum < 2:
        raise ValueError('Nonempty frame list and at least two requested samples required')
    return sorted({round(i * (count - 1) / (min(count, maximum) - 1)) for i in range(min(count, maximum))}) if count > 1 else [0]


def source_observations(args):
    """Five independent estimated frames per source lacking a detailed reference."""
    import cv2
    import mediapipe as mp
    import numpy as np
    from PIL import Image, ImageDraw
    tutorial = load_tool('sign-tutorial-reference')
    index, output = args.index.resolve(), args.output.resolve()
    manifest = json.loads((index / 'sources.json').read_text())
    registry = json.loads((index / 'source-registry.json').read_text())
    sources = {r['source_id']: r for r in manifest['sources']}
    pending = {r['source_id'] for r in read_lines(args.selection)}
    if output.exists() or output == index or index in output.parents:
        raise ValueError('New isolated observation output required')
    chosen = [r for r in registry['sources'] if r['stage'] == 'caption_screened_pending_reference' and r['source_id'] not in pending]
    output.mkdir(parents=True)
    report = {'schema': 'signbridge-source-observations-v1', 'status': 'running', 'sources': [],
              'frames_are_temporally_contiguous': False, 'training_ready': False, 'source_files_modified': False,
              'tool_sha256': sha(__file__), 'registry_sha256': sha(index / 'source-registry.json'),
              'limitations': ['Five sampled frames locate hands; they do not exhaustively annotate the video.',
                             'Extractor slots are unverified anatomical sides; missing points stay NaN.',
                             'Observations are image coordinates, not SMPL-X rotations or metric 3D.']}
    write_json(output / 'report.json', report)
    with mp.solutions.holistic.Holistic(static_image_mode=True, model_complexity=1, smooth_landmarks=False) as holistic:
        for record in chosen:
            sid = record['source_id']; source = sources[sid]
            original = Path(manifest['source_root']) / source['relative_path']
            if sha(original) != source['sha256']:
                raise ValueError('Original video digest changed')
            ocr_path = Path(record['cached_ocr'])
            # Modern screening stores paths relative to screen/; tutorial screening stores screen/<id>/.
            screen_root = ocr_path.parent.parent
            rows = read_lines(ocr_path)
            relative = Path(rows[0]['image'])
            if not (screen_root / relative).is_file():
                screen_root = screen_root.parent
            folder = output / sid; folder.mkdir()
            arrays = {key: [] for key in ('left_hand_image', 'right_hand_image', 'pose_image')}
            notes, rendered = [], []
            for number, position in enumerate(even_indices(len(rows)), 1):
                row = rows[position]; verify_evidence(screen_root, [row])
                image_path = (screen_root / row['image']).resolve()
                bgr = cv2.imread(str(image_path))
                if bgr is None:
                    raise ValueError('Cannot decode OCR evidence image')
                height, width = bgr.shape[:2]
                result = holistic.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                for name, shape in [('left_hand_image', (21, 3)), ('right_hand_image', (21, 3)), ('pose_image', (33, 4))]:
                    value = np.full(shape, np.nan, dtype=np.float32)
                    landmarks = getattr(result, name.replace('_image', '_landmarks'))
                    if landmarks is not None:
                        value[:, :3] = [[v.x, v.y, v.z] for v in landmarks.landmark]
                        if shape[1] == 4: value[:, 3] = [v.visibility for v in landmarks.landmark]
                    arrays[name].append(value)
                left, right = arrays['left_hand_image'][-1], arrays['right_hand_image'][-1]
                flag = tutorial.reference_hand_flags(left, right, bool(np.isfinite(left).all()), bool(np.isfinite(right).all()), width, height)
                note = {'sample_index': number, 'source_seconds_nominal': row.get('source_seconds', row.get('source_seconds_nominal')),
                        'evidence_image': str(image_path), 'image_sha256': row['image_sha256'], 'width': width, 'height': height,
                        'observation_flags': flag, 'original_frame_pts_measured': False, 'training_ready': False}
                notes.append(note)
                drawn = bgr.copy()
                for name, connections in [('left_hand_landmarks', mp.solutions.holistic.HAND_CONNECTIONS), ('right_hand_landmarks', mp.solutions.holistic.HAND_CONNECTIONS)]:
                    mp.solutions.drawing_utils.draw_landmarks(drawn, getattr(result, name), connections)
                preview = folder / f'sample-{number:02d}.jpg'
                cv2.imwrite(str(preview), drawn)
                note['preview'] = str(preview.relative_to(output))
                rendered.append((Image.fromarray(cv2.cvtColor(drawn, cv2.COLOR_BGR2RGB)), note['source_seconds_nominal']))
            np.savez_compressed(folder / 'observations-2d.npz', **{k: np.stack(v) for k, v in arrays.items()},
                                source_seconds_nominal=np.array([n['source_seconds_nominal'] for n in notes]),
                                left_detected=np.array([n['observation_flags']['left']['detected'] for n in notes]),
                                right_detected=np.array([n['observation_flags']['right']['detected'] for n in notes]))
            sheet = Image.new('RGB', (1000, 480), 'white'); draw = ImageDraw.Draw(sheet)
            for i, (image, seconds) in enumerate(rendered):
                image.thumbnail((196, 430)); sheet.paste(image, (i * 200 + (200 - image.width) // 2, 28))
                draw.text((i * 200 + 4, 4), f'{seconds:.1f}s / independent', fill='black')
            sheet.save(folder / 'sheet.jpg', quality=88)
            write_json(folder / 'frames.json', notes)
            entry = {'source_id': sid, 'source_sha256': source['sha256'], 'samples': len(notes),
                     'language_hint': record['language_hint'], 'relative_path': source['relative_path'],
                     'left_eligible_frames': sum(n['observation_flags']['left']['eligible_for_2d_fit'] for n in notes),
                     'right_eligible_frames': sum(n['observation_flags']['right']['eligible_for_2d_fit'] for n in notes),
                     'observations': str((folder / 'observations-2d.npz').relative_to(output)),
                     'frames': str((folder / 'frames.json').relative_to(output)), 'sheet': str((folder / 'sheet.jpg').relative_to(output)),
                     'training_ready': False, 'human_approved': False}
            report['sources'].append(entry); write_json(output / 'report.json', report)
            print(json.dumps({'source': sid, 'samples': len(notes), 'completed': len(report['sources']), 'total': len(chosen)}), flush=True)
    report.update(status='source_observations_completed_pending_review', sampled_frames=sum(r['samples'] for r in report['sources']))
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', action='store_true')
    parser.add_argument('--index', type=Path)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--new-manifest', type=Path)
    parser.add_argument('--new-screen', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    required = ('index', 'selection') if args.observations else ('source_root', 'dataset', 'new_manifest', 'new_screen')
    if any(getattr(args, key) is None for key in required):
        parser.error('Missing fields: ' + ', '.join(required))
    source_observations(args) if args.observations else build_index(args)


if __name__ == '__main__':
    main()
