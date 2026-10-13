"""Build an audited local review and same-frame fitting reference from catch-up clips."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

spec = importlib.util.spec_from_file_location('source_catchup', Path(__file__).with_name('sign-source-catchup.py'))
catchup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catchup)


def verify_named_artifacts(root, entries):
    root = Path(root).resolve()
    for name, record in entries.items():
        relative = Path(record['relative_path'])
        file = (root / relative).resolve()
        if relative.is_absolute() or root not in file.parents or not file.is_file() or catchup.sha(file) != record['sha256']:
            raise ValueError('Unsafe or changed reference artifact: ' + name)


def link(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def stage_badges(row, observed, selected):
    return {'source_id': row['source_id'], 'source_sha256': row['sha256'], 'aliases': row['aliases'],
            'stage_before': row['stage'], 'cached_ocr': bool(row['cached_ocr']),
            'prior_reference_windows': len(row['prior_reference_windows']),
            'prior_continuous_motions': len(row['prior_continuous_motions']),
            'new_sentence_windows': sum(r['source_id'] == row['source_id'] for r in selected),
            'new_independent_observation_frames': observed.get(row['source_id'], {}).get('samples', 0),
            'language_hint': row['language_hint'], 'training_ready': False,
            'remaining': ['确认字幕含义和完整动作边界', '确认镜像、手部侧别、来源分组', '连续 SMPL-X 重建/动作质量审核']}


def build(args):
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    index, pack, observations, out = [value.resolve() for value in (args.index, args.pack, args.observations, args.output)]
    if out.exists() or any(out == p or p in out.parents or out in p.parents for p in (index, pack, observations)):
        raise ValueError('New review output separate from inputs required')
    manifest = json.loads((index / 'sources.json').read_text())
    source_root = Path(manifest['source_root']).resolve()
    if out == source_root or source_root in out.parents or out in source_root.parents:
        raise ValueError('Review must remain outside original videos')
    references = catchup.read_lines(pack / 'references.jsonl')
    report = json.loads((pack / 'report.json').read_text())
    if report['samples'] != len(references) or report['frames'] != sum(r['frames'] for r in references) or report['training_ready'] is not False:
        raise ValueError('Reference extraction did not finish')
    expected_manifest = catchup.sha(index / 'sources.json')
    if report['manifest_sha256'] != expected_manifest:
        raise ValueError('Reference manifest digest differs')
    observed_report = json.loads((observations / 'report.json').read_text())
    if observed_report['status'] != 'source_observations_completed_pending_review':
        raise ValueError('Observation audit incomplete')
    registry = json.loads((index / 'source-registry.json').read_text())
    sources = {r['source_id']: r for r in manifest['sources']}
    out.mkdir(parents=True)
    catchup.write_json(out / 'sources.json', manifest)
    link(index / 'source-registry.json', out / 'source-registry.json')
    link(index / 'sentence-reference-candidates.jsonl', out / 'all-sentence-candidates.jsonl')
    font_path = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
    font = ImageFont.truetype(font_path, 18) if Path(font_path).exists() else ImageFont.load_default()
    fit_rows, ui = [], []
    for row in references:
        source = sources[row['source_id']]
        sid = row['annotation_id']
        media = out / 'reference-media' / sid
        assets = {}
        for name, relative in row['artifacts'].items():
            file = (pack / relative).resolve()
            if pack not in file.parents or not file.is_file():
                raise ValueError('Input reference artifact escaped pack')
            link(file, media / name)
            assets[name] = {'relative_path': str((media / name).relative_to(out)), 'sha256': catchup.sha(file)}
        flags = catchup.read_lines(pack / row['artifacts']['reference-flags.jsonl'])
        if len(flags) != row['frames']:
            raise ValueError('Hand quality frame count differs')
        folder = out / 'fitting-reference' / sid
        folder.mkdir(parents=True)
        with np.load(pack / row['artifacts']['landmarks.npz'], allow_pickle=False) as a:
            catchup.load_tool('sign-data').validate_landmark_arrays(a, row['frames'])
            left, right = a['left_hand_image'][..., :2].copy(), a['right_hand_image'][..., :2].copy()
            times, source_times = a['timestamps_seconds'].copy(), a['source_timestamps_seconds'].copy()
            if not np.allclose(times, np.arange(row['frames']) / row['fps']) or not np.allclose(source_times, times + row['start_seconds']):
                raise ValueError('Reference timeline differs')
            masks = {f'{side}_detected': a[f'{side}_hand_image_detected'].copy() for side in ('left', 'right')}
            masks.update({f'{side}_eligible_for_2d_fit': np.array([f[side]['eligible_for_2d_fit'] for f in flags], dtype=bool) for side in ('left', 'right')})
        observations_file = folder / 'observations-2d.npz'
        scale = np.array([row['width'], row['height']], dtype=np.float32)
        np.savez_compressed(observations_file, frame_1based=np.arange(1, row['frames'] + 1, dtype=np.int32),
                            clip_timestamps_seconds=times, source_timestamps_seconds_nominal=source_times,
                            left_xy_normalized=left, right_xy_normalized=right,
                            left_xy_clip_pixels=left * scale, right_xy_clip_pixels=right * scale,
                            overlapping_observations=np.array([f['reason'] == 'overlapping_hand_observations' for f in flags]), **masks)
        selected = catchup.even_indices(row['frames'])
        sheet = Image.new('RGB', (1200, 55 + 210 * len(selected)), 'white'); draw = ImageDraw.Draw(sheet)
        draw.text((8, 5), row['label'] + ' / OCR candidate / unverified', font=font, fill='black')
        capture = cv2.VideoCapture(str(media / 'clip.mp4')); frames = []
        try:
            for n, number in enumerate(selected):
                capture.set(cv2.CAP_PROP_POS_FRAMES, number); ok, bgr = capture.read()
                if not ok:
                    raise ValueError('Reference keyframe decode failed')
                image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                frame_file = folder / f'frame-{number + 1:06d}.jpg'; image.save(frame_file, quality=90)
                item = {'frame_1based': number + 1, 'source_seconds_nominal': float(source_times[number]),
                        'image': str(frame_file.relative_to(out)), 'image_sha256': catchup.sha(frame_file), 'crops': {}}
                y = 55 + n * 210
                draw.text((8, y), f'{number + 1} / {source_times[number]:.2f}s nominal', font=font, fill='black')
                thumb = image.copy(); thumb.thumbnail((450, 175)); sheet.paste(thumb, (8, y + 28))
                for side, x, points in (('left', 475, left[number]), ('right', 835, right[number])):
                    draw.text((x, y), side + ' slot / ' + flags[number][side]['reason'], font=font, fill='black')
                    if not masks[f'{side}_detected'][number] or not np.isfinite(points).all():
                        continue
                    pixels = points * scale
                    lo, hi = pixels.min(axis=0), pixels.max(axis=0)
                    margin = max(8., .22 * float(max(hi - lo)))
                    lo = np.maximum(0, lo - margin).astype(int); hi = np.minimum(scale, hi + margin).astype(int)
                    if not (hi > lo).all():
                        continue
                    crop = image.crop((*lo, *hi)); dest = folder / f'frame-{number + 1:06d}-{side}.jpg'; crop.save(dest, quality=90)
                    thumb = crop.copy(); thumb.thumbnail((350, 175)); sheet.paste(thumb, (x, y + 28))
                    item['crops'][side] = {'image': str(dest.relative_to(out)), 'bbox_xyxy_clip_pixels': [*lo.tolist(), *hi.tolist()],
                                           'estimated_slot': side, 'eligible_for_2d_fit': bool(masks[f'{side}_eligible_for_2d_fit'][number])}
                frames.append(item)
        finally:
            capture.release()
        sheet.save(folder / 'keyframes.jpg', quality=88)
        catchup.write_json(folder / 'keyframes.json', {'selection': 'five uniformly spaced reference frames; not labelled signing phases', 'frames': frames, 'training_ready': False})
        for file in (observations_file, folder / 'keyframes.jpg', folder / 'keyframes.json'):
            assets[file.name] = {'relative_path': str(file.relative_to(out)), 'sha256': catchup.sha(file)}
        fit = {'schema': 'signbridge-tutorial-fitting-reference-v1', 'annotation_id': sid,
               'source_id': row['source_id'], 'source_sha256': row['source_sha256'],
               'source_absolute_path': str(source_root / source['relative_path']),
               'label': row['label'], 'sample_type': 'word_candidate', 'candidate_content_kind': row['candidate_content_kind'],
               'hand_shape_note': row['hand_shape_note'], 'source_window_seconds': [row['start_seconds'], row['end_seconds']],
               'source_nominal_fps': source.get('average_fps', source.get('fps')), 'reference_fps': row['fps'],
               'frames': row['frames'], 'clip_dimensions': [row['width'], row['height']],
               'source_metadata_dimensions': [source['width'], source['height']], 'artifacts': assets,
               'split_group': row['split_group'], 'split': 'unassigned', 'language': 'unconfirmed',
               'time_contract': 'decoded reference time is exact; original frame PTS not measured; source time is nominal',
               'pixel_contract': 'image-normalized xy and decoded reference pixels; do not copy coordinates to another video',
               'mirror_status': 'unknown', 'anatomical_handedness': 'unverified', 'human_approved': False,
               'training_ready': False, 'smplx_parameters_created': False}
        verify_named_artifacts(out, assets)
        fit_rows.append(fit)
        ui.append({'id': sid, 'text': row['label'], 'sourceId': row['source_id'], 'kind': row['candidate_content_kind'],
                   'start': row['start_seconds'], 'end': row['end_seconds'], 'frames': row['frames'],
                   'leftEligible': row['usable_hand_observation_frames']['left'], 'rightEligible': row['usable_hand_observation_frames']['right'],
                   'clip': assets['clip.mp4']['relative_path'], 'overlay': assets['overlay.mp4']['relative_path'],
                   'sheet': assets['keyframes.jpg']['relative_path'], 'trainingReady': False})
    catchup.write_lines(out / 'fitting-reference-index.jsonl', fit_rows)
    observed = {r['source_id']: r for r in observed_report['sources']}
    source_ui = [stage_badges(r, observed, references) for r in registry['sources']]
    for row in source_ui:
        if row['source_id'] in observed:
            entry = observed[row['source_id']]
            file = out / 'source-observations' / (row['source_id'] + '.jpg')
            link(observations / entry['sheet'], file)
            row['sheet'] = str(file.relative_to(out))
    original_files = registry['files']
    for row in original_files:
        if catchup.sha(source_root / row['relative_path']) != row['sha256']:
            raise ValueError('Source video changed after catch-up inventory')
    subtitle_rows = []
    for row in registry['sources']:
        if row['cached_ocr']:
            for sampled in catchup.read_lines(row['cached_ocr']):
                parts = [line['text'] for line in sampled['lines'] if re.search('[\u4e00-\u9fff]', line['text'])]
                subtitle_rows.append({'sourceId': row['source_id'], 'seconds': sampled.get('source_seconds', sampled.get('source_seconds_nominal')), 'text': ' | '.join(parts)})
    gpu = json.loads(args.gpu_status.read_text()) if args.gpu_status else {'state': 'not_checked'}
    summary = {'schema': 'signbridge-catchup-delivery-v1', 'status': 'local_reference_preparation_completed',
               'created_at': datetime.now(timezone.utc).isoformat(), 'source_paths': len(original_files), 'unique_sources': len(source_ui),
               'new_screened_sources': json.loads((index / 'summary.json').read_text())['new_screened_sources'],
               'reference_windows': len(ui), 'reference_frames': sum(r['frames'] for r in ui),
               'independent_audit_sources': len(observed), 'independent_audit_frames': observed_report['sampled_frames'],
               'new_verified_sign_labels': 0, 'training_ready': False, 'training_started': False,
               'source_files_modified': False, 'sources_without_reference_or_observation_or_motion': [r['source_id'] for r in source_ui if not any((r['prior_reference_windows'], r['prior_continuous_motions'], r['new_sentence_windows'], r['new_independent_observation_frames']))],
               'gpu_state': gpu['state'], 'gpu_connection_evidence_sha256': catchup.sha(args.gpu_status) if args.gpu_status else None,
               'limits': ['候选字幕可能有错字、多轮问答或讲解；76段尚未经手语者核验。', '缺失关键点保留NaN；左右是估计槽，镜像和解剖侧别未确认。', '73个来源只有5帧抽样手部观测，不能视为整段动作标注。', '没有新增SMPL-X参数、133维训练序列或新模型权重。']}
    catchup.write_json(out / 'summary.json', summary)
    payload = {'summary': summary, 'references': ui, 'sources': source_ui, 'subtitles': subtitle_rows}
    catchup.write_json(out / 'review-data.json', payload)
    # Data goes through textContent in the UI; escaping '<' prevents ending the script element.
    (out / 'review-data.js').write_text('window.CATCHUP_DATA=' + json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c') + ';\n')
    template_root = Path(__file__).with_name('catchup-review')
    for file in ('index.html', 'review.js', 'review.css'):
        if file == 'review.js':
            subprocess.run([str(Path(__file__).resolve().parents[2] / 'node_modules/.bin/esbuild'), str(template_root / file), '--bundle', '--format=esm', '--outfile=' + str(out / file)], check=True, capture_output=True)
        else:
            shutil.copy2(template_root / file, out / file)
    (out / 'SHA256SUMS').write_text(''.join(catchup.sha(file) + '  ' + str(file.relative_to(out)) + '\n' for file in sorted(out.rglob('*')) if file.is_file() and file.name != 'SHA256SUMS'))
    print(json.dumps(summary, ensure_ascii=False))
    return summary



def prepare_gpu_inputs(plan_path, output):
    plan_path, output = Path(plan_path).resolve(), Path(output).resolve()
    plan = json.loads(plan_path.read_text())
    cases = plan['cases']
    if output.exists() or plan_path.parent == output or plan_path.parent in output.parents or output in plan_path.parent.parents:
        raise ValueError('Fresh GPU input directory separate from plan required')
    if plan['training_ready'] is not False or not 1 <= len(cases) <= 500 or len({r['case_id'] for r in cases}) != len(cases):
        raise ValueError('Bounded unique unapproved case scope required')
    output.mkdir(parents=True)
    converted = []
    for index, case in enumerate(cases, 1):
        if case['training_ready'] is not False or case['human_approved'] is not False:
            raise ValueError('GPU packaging cannot promote approval')
        row = dict(case)
        for key, target in [('image', output / 'images' / ('%06d.jpg' % index)),
                            ('observations', output / 'cases' / case['case_id'] / 'observations-2d.npz')]:
            relative = Path(case[key]); source = (plan_path.parent / relative).resolve()
            if relative.is_absolute() or plan_path.parent not in source.parents or catchup.sha(source) != case[key + '_sha256']:
                raise ValueError('GPU input changed or escaped plan')
            link(source, target)
            row[key] = str(target.relative_to(output))
            row[key + '_sha256'] = catchup.sha(target)
        row['gpu_input_frame_1based'] = index
        converted.append(row)
    value = {'schema': 'signbridge-tutorial-smplerx-independent-frames-v2', 'cases': converted,
             'frames': len(converted), 'frames_are_temporally_contiguous': False, 'training_ready': False,
             'status': 'prepared_not_dispatched', 'source_files_modified': False, 'model_weights_included': False,
             'fit_purpose': 'independent same-frame SMPL-X/MANO candidates; no sequence training or automatic approval',
             'plan_sha256': catchup.sha(plan_path)}
    catchup.write_json(output / 'manifest.json', value)
    return value


def audit(args):
    from concurrent.futures import ThreadPoolExecutor
    import cv2
    root = args.index.resolve()
    data = catchup.load_tool('sign-data')
    manifest = json.loads((root / 'sources.json').read_text())
    registry = json.loads((root / 'source-registry.json').read_text())
    rows = catchup.read_lines(root / 'fitting-reference-index.jsonl')
    source_root = Path(manifest['source_root'])
    for file in registry['files']:
        if catchup.sha(source_root / file['relative_path']) != file['sha256']:
            raise ValueError('Source has changed after inventory')
    def check(row):
        verify_named_artifacts(root, row['artifacts'])
        assets = {key: root / value['relative_path'] for key, value in row['artifacts'].items()}
        count = row['frames']
        with np.load(assets['landmarks.npz'], allow_pickle=False) as raw:
            data.validate_landmark_arrays(raw, count)
            with np.load(assets['observations-2d.npz'], allow_pickle=False) as fitted:
                if not np.array_equal(fitted['frame_1based'], np.arange(1, count + 1)):
                    raise ValueError('Fitting reference sequence lost frame identity')
                for side in ('left', 'right'):
                    if not np.array_equal(fitted[side + '_xy_normalized'], raw[side + '_hand_image'][..., :2], equal_nan=True):
                        raise ValueError('Hand observation values changed')
                    if not np.array_equal(fitted[side + '_detected'], raw[side + '_hand_image_detected']):
                        raise ValueError('Hand detection mask differs')
                    pixels = raw[side + '_hand_image'][..., :2] * np.asarray(row['clip_dimensions'], dtype=np.float32)
                    if not np.array_equal(fitted[side + '_xy_clip_pixels'], pixels, equal_nan=True):
                        raise ValueError('Pixel conversion differs')
                if not np.array_equal(fitted['source_timestamps_seconds_nominal'], raw['source_timestamps_seconds']):
                    raise ValueError('Fitting nominal time differs')
            detected = {key: int(raw[key + '_detected'].sum()) for key in ('pose_image', 'face_image', 'left_hand_image', 'right_hand_image')}
        quality = json.loads(assets['quality.json'].read_text())
        if quality['frames'] != count or any(quality['detections'][key]['detected_frames'] != value for key, value in detected.items()):
            raise ValueError('Reported quality differs from raw masks')
        for key in ('clip.mp4', 'overlay.mp4'):
            capture = cv2.VideoCapture(str(assets[key])); actual = 0
            if not capture.isOpened() or abs(capture.get(cv2.CAP_PROP_FPS) - row['reference_fps']) > .001:
                raise ValueError('Video unavailable or wrong FPS')
            try:
                while True:
                    ok, image = capture.read()
                    if not ok: break
                    if list(image.shape[1::-1]) != row['clip_dimensions']:
                        raise ValueError('Decoded video geometry differs')
                    actual += 1
            finally:
                capture.release()
            if actual != count:
                raise ValueError('Fully decoded video frame count differs')
        if row['training_ready'] is not False or row['human_approved'] is not False:
            raise ValueError('Reference approval was changed')
        return {'id': row['annotation_id'], 'frames': count, 'videos_fully_decoded': 2,
                'mask_and_pixel_parity': 'passed', 'training_ready': False, 'detected_frames': detected}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(check, rows))
    checksums = (root / 'SHA256SUMS').read_text().splitlines()
    for line in checksums:
        checksum, relative = line.split('  ', 1)
        file = (root / relative).resolve()
        if root not in file.parents or catchup.sha(file) != checksum:
            raise ValueError('Delivery checksum mismatch: ' + relative)
    value = {'schema': 'signbridge-catchup-validation-v1', 'status': 'passed', 'references': len(results),
             'frames': sum(r['frames'] for r in results), 'videos_fully_decoded': len(results) * 2,
             'original_files_sha256_verified': len(registry['files']), 'checksum_files_verified': len(checksums),
             'results': results, 'training_ready': False, 'semantic_sign_accuracy': 'not_assessed',
             'checked_at': datetime.now(timezone.utc).isoformat()}
    catchup.write_json(args.output, value)
    print(json.dumps({k: v for k, v in value.items() if k != 'results'}))
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--gpu-inputs', action='store_true')
    parser.add_argument('--gpu-status', type=Path, help='Actual connection-check JSON; omitted means not checked')
    for key in ('index', 'pack', 'observations', 'output', 'plan'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    required = ('index', 'output') if args.audit else ('plan', 'output') if args.gpu_inputs else ('index', 'pack', 'observations', 'output')
    if any(getattr(args, key) is None for key in required):
        parser.error('Missing fields: ' + ', '.join(required))
    if args.audit:
        audit(args)
    elif args.gpu_inputs:
        value = prepare_gpu_inputs(args.plan, args.output)
        print(json.dumps({'cases': value['frames'], 'status': value['status'], 'training_ready': False}))
    else:
        build(args)


if __name__ == '__main__':
    main()
