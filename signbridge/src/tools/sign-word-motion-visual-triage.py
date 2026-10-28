"""CPU-only visibility review risks; never verify a person, sign, or word boundary.

Run with the existing .venv-sign-data Python (OpenCV/numpy already installed):
  python -B sign-word-motion-visual-triage.py --report candidates-v2/report.json
      --output NEW-sidecar-directory --expected-count 2132 --workers 4

Reads the exporter's three-cell contact sheets without changing videos or params.
Metrics exclude the exporter's light padding and timestamp footer. Unknown or
missing images produce null measurements, never synthetic black/zero images.
No detections means unknown visibility, NOT evidence that no person is present.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import threading

import cv2
import numpy as np


RULES = {'dark_pixel_luma_max': 32, 'dark_mean_luma_max': 18,
         'dark_fraction_min': .90, 'blank_std_luma_max': 2,
         'blank_luma_range_max': 8, 'fade_luma_range_min': 25,
         'fade_requires_mean_luma_below': 50}
LIMITATIONS = [
    'Technical review risks only: no semantic rejection, approval, or verified action.',
    'A Haar face detection does not establish signer identity, language, hands, or sign motion.',
    'No face detection is unknown, not proof of person absence; small/profile/occluded faces may be missed.',
    'Three keyframes cannot establish continuous captured motion or word boundaries.',
    'Existing nominal frame selections and source windows are preserved; original PTS are not measured.',
    'Static or dark teaching slides remain review risks, never automatic semantic rejections.']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def contained(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or '\n' in relative:
        raise ValueError('Invalid artifact path')
    name = Path(relative)
    if name.is_absolute() or '..' in name.parts:
        raise ValueError('Artifact escaped candidate root')
    path = root / name
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise ValueError('Artifact is not a contained regular file')
    return path


class FaceDetector:
    def __init__(self, mode='haar'):
        if mode not in ('haar', 'off'): raise ValueError('Unknown face detector')
        cv2.setNumThreads(1)
        cv2.ocl.setUseOpenCL(False)
        self.local = threading.local()
        self.path = Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml' if mode == 'haar' else None
        self.available = self.path is not None and self.path.is_file()

    def metadata(self):
        return {'mode': 'bundled_haar_frontalface' if self.path else 'off',
                'available': self.available, 'execution_device': 'cpu', 'opencl_enabled': False,
                'cascade_path': str(self.path) if self.path else None,
                'cascade_sha256': sha(self.path) if self.available else None,
                'scale_factor': 1.1, 'min_neighbors': 4, 'min_size_pixels': [20, 20]}

    def detect(self, gray):
        result = {'status': 'unknown_detector_unavailable', 'face_count': None, 'boxes_xywh': None,
                  'person_absence_proven': False, 'signer_identity_verified': False}
        if not self.available: return result
        try:
            if not hasattr(self.local, 'cascade'):
                self.local.cascade = cv2.CascadeClassifier(str(self.path))
            if self.local.cascade.empty(): raise ValueError('Bundled Haar cascade cannot be loaded')
            boxes = self.local.cascade.detectMultiScale(cv2.equalizeHist(gray), scaleFactor=1.1,
                                                       minNeighbors=4, minSize=(20, 20))
            result.update(face_count=len(boxes), boxes_xywh=[[int(v) for v in box] for box in boxes],
                          status='face_detected_role_unknown' if len(boxes) else 'unknown_no_face_detection')
        except (cv2.error, ValueError) as error:
            result.update(status='unknown_detector_error', error=str(error))
        return result


def image_metrics(image):
    if image is None or not image.size or image.dtype != np.uint8:
        raise ValueError('Missing/invalid decoded image; no zero fill')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean, std = float(gray.mean()), float(gray.std())
    dark = float(np.mean(gray <= RULES['dark_pixel_luma_max']))
    value_range = int(gray.max()) - int(gray.min())
    blank = std <= RULES['blank_std_luma_max'] and value_range <= RULES['blank_luma_range_max']
    is_dark = mean <= RULES['dark_mean_luma_max'] or dark >= RULES['dark_fraction_min']
    return {'mean_luma_0_255': mean, 'std_luma_0_255': std, 'luma_range_0_255': value_range,
            'dark_fraction': dark, 'dark': bool(is_dark), 'blank_low_variation': bool(blank),
            'dark_or_blank': bool(is_dark or blank)}


def analyze_candidate(candidate, root, detector):
    root = Path(root).resolve()
    selected = candidate.get('selected_keyframes_1based', [])
    result = {key: candidate.get(key) for key in ('id', 'proposed_text', 'source_sha256',
              'source_window_seconds', 'selected_keyframes_1based', 'decoded_video', 'reference_clip',
              'clip_sha256', 'native_asset', 'native_asset_sha256', 'evidence_kind')}
    result.update(candidate_record_sha256=hashlib.sha256(json.dumps(candidate, sort_keys=True,
                  ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                  original_review_flags=list(candidate.get('review_flags', [])),
                  status='technical_evidence_unavailable', risk_flags=[], keyframes=[],
                  dark_or_blank_keyframe_count=None, signer_visibility_status='unknown',
                  human_approved=False, semantics_approved=False, word_boundaries_verified=False,
                  verified_action=False, automatic_rejection=False, training_ready=False,
                  model_training_ready=False, source_pts_measured=False,
                  time_basis='existing selected clip frames / fps plus unchanged nominal source start')
    for slot, number in enumerate(selected):
        result['keyframes'].append({'slot': slot, 'selected_frame_1based': number,
            'metrics': None, 'face_detection': {'status': 'unknown_image_unavailable', 'face_count': None,
            'boxes_xywh': None, 'person_absence_proven': False, 'signer_identity_verified': False}})
    failure_flag = 'keyframe_evidence_missing_or_unreadable'
    try:
        path = contained(root, candidate.get('keyframes', candidate.get('contact_sheet')))
        raw = path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        result['contact_sheet'] = {'path': str(path), 'sha256': actual_sha,
                                   'expected_sha256': candidate.get('keyframes_sha256')}
        if actual_sha != candidate.get('keyframes_sha256'):
            failure_flag = 'keyframe_hash_mismatch'
            raise ValueError('Contact sheet differs from report SHA256')
        sheet = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if sheet is None or not sheet.size: raise ValueError('Contact sheet cannot be decoded')
        meta = candidate['decoded_video']
        width, height, fps, frames = meta['width'], meta['height'], meta['fps'], meta['frames']
        start = candidate['source_window_seconds'][0]
        failure_flag = 'unsupported_contact_sheet_layout'
        if (len(selected) != 3 or sheet.shape[:2] != (312, 960) or
                not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height, frames)) or
                not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0 or
                not isinstance(start, (int, float)) or not math.isfinite(start) or
                not all(isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= frames for n in selected) or
                sorted(set(selected)) != selected):
            raise ValueError('Expected exporter three-cell 320x312 sheet and exact frame metadata')
        scale = min(320 / width, 280 / height)
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        x, y = (320 - w) // 2, (280 - h) // 2
        keyframes = []
        for slot, number in enumerate(selected):
            image = sheet[y:y+h, slot*320+x:slot*320+x+w]
            metrics = image_metrics(image)
            keyframes.append({'slot': slot, 'selected_frame_1based': number,
                'reference_seconds': (number-1)/fps, 'source_seconds_nominal': start+(number-1)/fps,
                'source_pts_measured': False, 'contact_sheet_crop_xywh': [slot*320+x, y, w, h],
                'decoded_bgr_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
                'metrics': metrics, 'face_detection': detector.detect(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))})
        result.update(status='technical_metrics_available', keyframes=keyframes,
                      dark_or_blank_keyframe_count=sum(k['metrics']['dark_or_blank'] for k in keyframes))
        flags = result['risk_flags']
        if result['dark_or_blank_keyframe_count']: flags.append('dark_or_blank_keyframes')
        if result['dark_or_blank_keyframe_count'] == 3: flags.append('all_keyframes_dark_or_blank')
        means = [k['metrics']['mean_luma_0_255'] for k in keyframes]
        if max(means)-min(means) >= RULES['fade_luma_range_min'] and min(means) < RULES['fade_requires_mean_luma_below']:
            flags.append('fade_or_transition_keyframes_review_risk')
        detected = [bool(k['face_detection']['face_count']) for k in keyframes]
        if not any(detected):
            flags.append('signer_visibility_not_confirmed_by_face_detector')
            if (candidate.get('evidence_kind') in ('title_span_candidate', 'tutorial_reference') or
                    any(k['metrics']['dark_fraction'] >= .70 or k['metrics']['blank_low_variation'] for k in keyframes)):
                flags.append('teaching_title_or_static_scene_review_risk')
        elif not all(detected):
            flags.append('face_detection_missing_in_some_keyframes_review_risk')
        # Even a positive detector result does not confirm the person's role or sign action.
        if any(detected): result['face_detection_observation'] = 'face_detected_signer_role_unverified'
        return result
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as error:
        result.update(error=str(error), risk_flags=[failure_flag, 'signer_visibility_not_confirmed_by_face_detector'])
        return result


def snapshot_tree(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ValueError('Symlink in candidate input tree')
        if path.is_file(): result[str(path.relative_to(root))] = sha(path)
    return result


def build_report(report_path, output, expected_count=None, face_detector='haar', observations_path=None, workers=1):
    report_path, output = Path(report_path).resolve(strict=True), Path(output).resolve()
    root = report_path.parent
    if output == root or output.is_relative_to(root): raise ValueError('Sidecar must be outside candidate root')
    if output.exists(): raise FileExistsError('Use a NEW sidecar output directory')
    raw = report_path.read_bytes()
    report, source_sha = json.loads(raw), hashlib.sha256(raw).hexdigest()
    rows, summary = report['candidates'], report['summary']
    count = len(rows)
    if (summary.get('candidates') != count or summary.get('materialized') != count or
            summary.get('failures') != 0 or expected_count is not None and count != expected_count or
            report.get('status') in ('running', 'building', 'failed') or
            len({row.get('id') for row in rows}) != count or any(not row.get('id') for row in rows)):
        raise ValueError('Final complete report with unique IDs and expected candidate count required')
    if not 1 <= workers <= 16: raise ValueError('Workers must be between 1 and 16')
    detector = FaceDetector(face_detector)
    observations, observations_sha = {}, None
    if observations_path:
        observations_path = Path(observations_path).resolve(strict=True)
        observations_sha = sha(observations_path)
        by_id = {row['id']: row for row in rows}
        for sample in json.loads(observations_path.read_text())['samples']:
            candidate = by_id.get(sample['id'])
            if not candidate or sample.get('contact_sheet_sha256') != candidate.get('keyframes_sha256'):
                raise ValueError('Visual observation is not bound to this candidate contact sheet')
            observations[sample['id']] = {'file_path': str(observations_path),
                'file_sha256': observations_sha, 'observation_record': sample,
                'semantics_approved': False, 'word_boundaries_verified': False}
    before = snapshot_tree(root)
    output.mkdir(parents=True)
    (output/'source-report.snapshot.json').write_bytes(raw)
    write_json(output/'input-tree-before.json', before)
    if observations_path:
        (output/'assistant-observations.snapshot.json').write_bytes(observations_path.read_bytes())
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda row: analyze_candidate(row, root, detector), rows))
    for result in results:
        if result['id'] in observations:
            result['external_visual_observation'] = observations[result['id']]
            result['risk_flags'].append('external_visual_observation_requires_review')
    result_path = output/'triage.jsonl'
    with result_path.open('x') as stream:
        for result in results: stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False)+'\n')
    after = snapshot_tree(root)
    write_json(output/'input-tree-after.json', after)
    if before != after or sha(report_path) != source_sha or observations_path and sha(observations_path) != observations_sha:
        write_json(output/'FAILED-input-change.json', {'status':'failed_closed_input_changed', 'all_results_unapproved':True})
        raise ValueError('Candidate inputs or bound observations changed during triage')
    flags = Counter(flag for result in results for flag in result['risk_flags'])
    keyframes = [frame for result in results for frame in result['keyframes']]
    source = Path(__file__).resolve()
    output_report = {'schema':'signbridge-word-motion-visual-triage-v1',
        'created_at':datetime.now(timezone.utc).isoformat(), 'status':'complete_technical_review_only',
        'summary':{'candidates_examined':count, 'keyframes_examined':sum(k['metrics'] is not None for k in keyframes),
            'candidates_with_review_risks':sum(bool(r['risk_flags']) for r in results),
            'technical_evidence_unavailable':sum(r['status']=='technical_evidence_unavailable' for r in results),
            'keyframes_with_face_detection':sum(bool(k['face_detection']['face_count']) for k in keyframes),
            'keyframes_with_dark_or_blank_risk':sum(bool(k['metrics'] and k['metrics']['dark_or_blank']) for k in keyframes),
            'external_visual_observations_bound':len(observations)},
        'risk_counts':dict(sorted(flags.items())), 'input_tree_unchanged':True,
        'candidate_input_files_rehashed_before_and_after':len(before),
        'source_report':{'path':str(report_path),'sha256':source_sha,'original_summary':summary},
        'results':{'path':str(result_path),'sha256':sha(result_path),'rows':count},
        'tool':{'path':str(source),'sha256':sha(source),'python_executable':sys.executable,
                'python_version':sys.version,'opencv_version':cv2.__version__,'numpy_version':np.__version__,
                'argv':sys.argv,'workers':workers},
        'face_detector':detector.metadata(), 'thresholds':RULES,
        'contact_sheet_contract':{'cells':3,'cell_width':320,'cell_height':312,'image_area_height':280,
            'analysis_region':'actual resized image only, excluding light padding and timestamp footer'},
        'all_candidates_unapproved':True,'semantic_rejections':0,'new_word_bounds_created':0,
        'zero_filled_images_or_parameters':0,'video_or_original_parameters_modified':False,
        'training_ready':False,'model_training_ready':False,'limitations':LIMITATIONS}
    write_json(output/'report.json', output_report)
    (output/'README.md').write_text('# Visibility technical triage\n\n'+
        '\n'.join('- '+line for line in LIMITATIONS)+'\n\n'+
        'triage.jsonl contains every candidate ID, three frame measurements or explicit null unknowns, '+
        'unaltered source-window/frame selections, input hashes and review flags. Brightness uses grayscale '+
        'luma 0–255; dark fraction is pixels <=32. Dark risk is mean<=18 or fraction>=0.90; blank risk '+
        'is std<=2 and range<=8. Fade risk is sampled mean range>=25 with a mean below50. '+
        'Teaching/static risk combines no face detection with title metadata or dark/flat imagery; '+
        'it is not a scene/person classifier. Original files are opened read-only and every candidate '+
        'tree file is rehashed before/after. Missing, corrupt, mismatched or unknown-layout sheets '+
        'fail closed with null metrics. Detector off/unavailable yields null detection counts. '+
        'No network, installs, GPU, OCR, training, motion fitting or approvals.\n')
    write_json(output/'artifact-hashes.json', {p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    return output_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-count', type=int)
    parser.add_argument('--face-detector', choices=('haar','off'), default='haar')
    parser.add_argument('--observations', type=Path)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    report = build_report(args.report,args.output,args.expected_count,args.face_detector,args.observations,args.workers)
    print(json.dumps({'summary':report['summary'],'risk_counts':report['risk_counts'],
                      'report':str(args.output.resolve()/'report.json')},ensure_ascii=False))
    return 2 if report['summary']['technical_evidence_unavailable'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
