"""Bounded, digest-bound tutorial WiLoR inference; MANO candidates, no SMPL-X replacement."""
import argparse
import gc
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def sibling(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wilor = sibling('sign-wilor-pilot')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validate_ids(ids):
    if not 1 <= len(ids) <= 8 or len(set(ids)) != len(ids) or any(
            not isinstance(x, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', x) is None for x in ids):
        raise ValueError('One to eight unique safe annotation IDs required')
    return ids


def validate_keyframe_order(order):
    if not order or len(order) > 5 or len(set(order)) != len(order) or any(type(i) is not int or not 0 <= i < 5 for i in order):
        raise ValueError('Unique saved keyframe indices from zero to four required')
    return order


def compare_observations(projected, left, right, left_detected, right_detected, width, height):
    projected = np.asarray(projected)
    if projected.shape != (21, 2) or not np.isfinite(projected).all() or width <= 0 or height <= 0:
        raise ValueError('Invalid projected joint contract')
    slots = {}
    for side, points, detected in [('left', left, left_detected), ('right', right, right_detected)]:
        points = np.asarray(points)
        if points.shape != (21, 2) or type(detected) not in (bool, np.bool_):
            raise ValueError('Invalid observed hand contract')
        slots[side] = None
        if not detected or not np.isfinite(points).all() or (points < 0).any() or (points > 1).any():
            continue
        pixels = points * [width, height]
        palm = float(np.median(np.linalg.norm(pixels[[5, 9, 13, 17]] - pixels[0], axis=1)))
        if palm < 15:
            continue
        errors = np.linalg.norm(projected - pixels, axis=1)
        slots[side] = {'median_error_pixels': float(np.median(errors)), 'mean_error_pixels': float(errors.mean()),
                       'wrist_error_pixels': float(errors[0]), 'median_error_in_palm_lengths': float(np.median(errors) / palm),
                       'palm_pixels': palm, 'per_joint_errors_pixels': errors.tolist()}
    return {'comparison_target': 'independent model-estimated 2D observations; not ground truth',
            'estimated_slots': slots, 'handedness_verified': False, 'training_ready': False}


def prepare(args):
    import cv2
    root, out = args.reference_root.resolve(), args.output.resolve()
    validate_ids(args.annotation_id)
    keyframe_order = validate_keyframe_order(args.keyframe_index)
    if out.exists() or root in out.parents or out in root.parents:
        raise ValueError('Fresh output outside reference delivery required')
    rows = {r['annotation_id']: r for r in read_lines(root / 'fitting-reference-index.jsonl')}
    selected = [rows[x] for x in args.annotation_id]
    sources = {r['source_id']: r for r in json.loads((root / 'sources.json').read_text())['sources']}
    for row in selected:
        if row['human_approved'] or row['training_ready'] or row['mirror_status'] != 'unknown':
            raise ValueError('Unexpected tutorial research state')
        if wilor.sha256(row['source_absolute_path']) != row['source_sha256']:
            raise ValueError('Original tutorial source digest changed')
        for asset in row['artifacts'].values():
            path = (root / asset['relative_path']).resolve()
            if root not in path.parents or wilor.sha256(path) != asset['sha256']:
                raise ValueError('Reference artifact escaped root or changed digest')
    out.mkdir(parents=True)
    cases = []
    skipped = []
    for row in selected:
        keyframes = json.loads((root / row['artifacts']['keyframes.json']['relative_path']).read_text())['frames']
        flags = read_lines(root / row['artifacts']['reference-flags.jsonl']['relative_path'])
        preferred = [keyframes[i] for i in keyframe_order if i < len(keyframes)]
        chosen = []
        for frame in preferred:
            number = frame['frame_1based']
            if any(flags[number-1][s]['eligible_for_2d_fit'] for s in ['left', 'right']):
                chosen.append(frame)
            if len(chosen) == 2:
                break
        if not chosen:
            skipped.append({'annotation_id': row['annotation_id'], 'reason': 'no_eligible_saved_keyframe'})
        with np.load(root / row['artifacts']['observations-2d.npz']['relative_path'], allow_pickle=False) as arrays:
            for frame in chosen:
                number = frame['frame_1based']
                case_id = row['annotation_id'] + '-f%06d' % number
                folder = out / 'cases' / case_id
                folder.mkdir(parents=True)
                source_image = (root / frame['image']).resolve()
                if root not in source_image.parents:
                    raise ValueError('Frame path escaped delivery')
                shutil.copy2(source_image, folder / 'original.jpg')
                image = cv2.imread(str(folder / 'original.jpg'))
                if image is None or list(image.shape[1::-1]) != row['clip_dimensions']:
                    raise ValueError('Decoded reference geometry mismatch')
                np.savez_compressed(folder / 'observations.npz',
                    left=arrays['left_xy_normalized'][number-1], right=arrays['right_xy_normalized'][number-1],
                    left_detected=arrays['left_detected'][number-1], right_detected=arrays['right_detected'][number-1])
                cases.append({'case_id': case_id, 'annotation_id': row['annotation_id'], 'label': row['label'],
                    'source_id': row['source_id'], 'source_sha256': row['source_sha256'],
                    'frame_1based': number, 'source_seconds_nominal': frame['source_seconds_nominal'],
                    'image': str((folder / 'original.jpg').relative_to(out)), 'image_sha256': wilor.sha256(folder / 'original.jpg'),
                    'observations': str((folder / 'observations.npz').relative_to(out)),
                    'observations_sha256': wilor.sha256(folder / 'observations.npz'), 'mirror_status': 'unknown',
                    'anatomical_handedness': 'unverified', 'human_approved': False, 'training_ready': False})
    if not cases:
        raise ValueError('No eligible inference cases')
    plan = {'schema': 'signbridge-tutorial-native-hands-plan-v1', 'cases': cases, 'skipped': skipped,
            'reference_root': str(root), 'reference_index_sha256': wilor.sha256(root / 'fitting-reference-index.jsonl'),
            'training_ready': False, 'full_sequence_refined': False, 'saved_keyframe_order': keyframe_order,
            'time_contract': 'decoded reference frame and nominal source time; original source PTS not measured'}
    write_json(out / 'plan.json', plan)
    (out / 'plan.sha256').write_text(wilor.sha256(out / 'plan.json') + '  plan.json\n')
    print(json.dumps({'plan': str(out / 'plan.json'), 'sha256': wilor.sha256(out / 'plan.json'), 'cases': len(cases)}))


def check_plan(path, digest):
    if wilor.sha256(path) != digest:
        raise ValueError('Explicit plan digest differs')
    plan = json.loads(path.read_text())
    if plan.get('schema') != 'signbridge-tutorial-native-hands-plan-v1' or plan.get('training_ready') is not False:
        raise ValueError('Unexpected tutorial plan contract')
    reference_index = Path(plan['reference_root']) / 'fitting-reference-index.jsonl'
    if wilor.sha256(reference_index) != plan['reference_index_sha256']:
        raise ValueError('Reference index digest changed')
    references = {r['annotation_id']: r for r in read_lines(reference_index)}
    checked_sources = set()
    cases = plan['cases']
    if not 1 <= len(cases) <= 16 or len({r['case_id'] for r in cases}) != len(cases):
        raise ValueError('Bounded unique case scope required')
    for row in cases:
        validate_ids([row['case_id']])
        reference = references.get(row['annotation_id'])
        if not reference or row['source_id'] != reference['source_id'] or row['source_sha256'] != reference['source_sha256']:
            raise ValueError('Case source differs from reference index')
        number = row['frame_1based']
        if type(number) is not int or not 1 <= number <= reference['frames'] or row['case_id'] != row['annotation_id'] + '-f%06d' % number:
            raise ValueError('Case frame identity differs from reference')
        nominal = reference['source_window_seconds'][0] + (number - 1) / reference['reference_fps']
        if not np.isfinite(row['source_seconds_nominal']) or abs(row['source_seconds_nominal'] - nominal) > 1e-8:
            raise ValueError('Case nominal source time differs')
        original = reference['source_absolute_path']
        if original not in checked_sources:
            if wilor.sha256(original) != reference['source_sha256']:
                raise ValueError('Original source digest changed')
            checked_sources.add(original)
        if row['mirror_status'] != 'unknown' or row['anatomical_handedness'] != 'unverified' or row['human_approved'] or row['training_ready']:
            raise ValueError('Do not infer tutorial approval or handedness')
        for key in ['image', 'observations']:
            p = (path.parent / row[key]).resolve()
            if path.parent.resolve() not in p.parents or wilor.sha256(p) != row[key + '_sha256']:
                raise ValueError('Case input escaped plan or changed digest')
    return plan


def run(args):
    out, root, mano = args.output.resolve(), args.wilor_root.resolve(), args.mano_model.resolve()
    plan = check_plan(args.plan.resolve(), args.plan_sha256)
    if out.exists() or any(p == out or p in out.parents or out in p.parents for p in [root, mano.parent, args.plan.parent.resolve(), Path(plan['reference_root'])]):
        raise ValueError('Fresh inference output separate from inputs required')
    out.mkdir(parents=True)
    report = {'schema': 'signbridge-tutorial-native-hands-result-v1', 'status': 'running', 'cases': [],
              'plan_sha256': args.plan_sha256, 'created_at': datetime.now(timezone.utc).isoformat(),
              'device_requested': args.device, 'training_ready': False, 'training_started': False,
              'human_approved': False, 'full_sequence_refined': False, 'smplx_parameters_created': False,
              'visualization': 'native MANO wireframe projection; no EGL surface rendering'}
    report['tool_sha256'] = wilor.sha256(Path(__file__))
    write_json(out / 'report.json', report)
    stage = 'assets'
    start = time.monotonic()
    try:
        if subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() != wilor.COMMIT:
            raise ValueError('Wrong pinned WiLoR commit')
        wilor.check_source(root)
        report['assets'] = {name: wilor.check_asset(root / name, size, digest) for name, (size, digest) in wilor.ASSETS.items()}
        report['assets']['MANO_RIGHT.pkl'] = wilor.check_asset(mano, wilor.MANO_BYTES, wilor.MANO_SHA)
        report['last_stage'] = stage
        write_json(out / 'report.json', report)
        stage = 'model_load'
        os.environ['YOLO_CONFIG_DIR'] = str(out / 'yolo-settings')
        os.environ.setdefault('MPLBACKEND', 'Agg')
        # Native WiLoR imports renderer modules even with rendering disabled.
        # Select the installed platform before those modules default to Linux EGL.
        os.environ.setdefault('PYOPENGL_PLATFORM', 'darwin' if sys.platform == 'darwin' else 'egl')
        import torch
        import cv2
        from PIL import Image, ImageDraw
        sys.path.insert(0, str(root))
        from wilor.models import WiLoR
        from wilor.configs import get_config
        from wilor.datasets.vitdet_dataset import ViTDetDataset
        from wilor.utils import recursive_to
        from wilor.utils.renderer import cam_crop_to_full
        from ultralytics import YOLO
        torch.manual_seed(20261010)
        torch.set_num_threads(4)
        if args.device == 'mps' and not torch.backends.mps.is_available() or args.device == 'cuda' and not torch.cuda.is_available():
            raise ValueError('Requested accelerator unavailable')
        device = torch.device(args.device)
        cfg = get_config(str(root / 'pretrained_models/model_config.yaml'), update_cachedir=False)
        cfg.defrost()
        cfg.MODEL.BBOX_SHAPE = [192, 256]
        cfg.MODEL.BACKBONE.pop('PRETRAINED_WEIGHTS', None)
        cfg.MANO.MODEL_PATH = str(mano)
        cfg.MANO.DATA_DIR = str(mano.parent)
        cfg.MANO.MEAN_PARAMS = str(root / 'mano_data/mano_mean_params.npz')
        cfg.freeze()
        model = WiLoR(cfg, init_renderer=False)
        weights = torch.load(root / 'pretrained_models/wilor_final.ckpt', map_location='cpu', weights_only=True)
        model.load_state_dict(weights['state_dict'], strict=True)
        del weights
        gc.collect()
        model.requires_grad_(False).eval().to(device)
        detector = YOLO(str(root / 'pretrained_models/detector.pt'))
        if detector.names != {0: 'left', 1: 'right'}:
            raise ValueError('Unexpected detector class vocabulary')
        report.update(checkpoint_strict_load_passed=True, wilor_commit=wilor.COMMIT,
                      runtime={'torch': torch.__version__, 'python': sys.version.split()[0], 'device': str(device), 'detector_device': 'cpu', 'cuda_available': torch.cuda.is_available()})
        report['last_stage'] = 'model_loaded'
        write_json(out / 'report.json', report)
        for case in plan['cases']:
            folder = out / case['case_id']
            folder.mkdir()
            input_image = args.plan.parent / case['image']
            image = cv2.imread(str(input_image))
            height, width = image.shape[:2]
            shutil.copy2(input_image, folder / 'original.jpg')
            stage = 'detector:' + case['case_id']
            detected = detector.predict(image, conf=.3, device='cpu', verbose=False, max_det=6)[0]
            boxes = detected.boxes.xyxy.cpu().numpy()
            classes = detected.boxes.cls.cpu().numpy()
            confidence = detected.boxes.conf.cpu().numpy()
            if not np.isfinite(boxes).all() or not np.isfinite(confidence).all() or not np.isin(classes, [0, 1]).all() or not (boxes[:, 2:] > boxes[:, :2]).all():
                raise ValueError('Invalid detector boxes')
            record = {**case, 'hands': [], 'detector_count': len(boxes)}
            report['cases'].append(record)
            overlay = image.copy()
            with np.load(args.plan.parent / case['observations'], allow_pickle=False) as observations:
                dataset = ViTDetDataset(cfg, image, boxes, classes, rescale_factor=2., fp16=False)
                for i, batch in enumerate(torch.utils.data.DataLoader(dataset, batch_size=1, num_workers=0)):
                    stage = 'native_forward:' + case['case_id']
                    report['last_stage'] = stage
                    write_json(out / 'report.json', report)
                    # Crop metadata is emitted as float64 by NumPy. The pinned
                    # model is float32 and MPS cannot transfer float64 tensors.
                    converted = [k for k, v in batch.items() if isinstance(v, torch.Tensor) and v.dtype == torch.float64]
                    batch = {k: v.float() if k in converted else v for k, v in batch.items()}
                    record['metadata_float32_cast_fields'] = converted
                    batch = recursive_to(batch, device)
                    with torch.inference_mode():
                        prediction = model(batch)
                        camera = prediction['pred_cam'].clone()
                        is_right = bool(int(batch['right'][0].item()))
                        camera[:, 1] *= 1 if is_right else -1
                        focal = float(cfg.EXTRA.FOCAL_LENGTH / cfg.MODEL.IMAGE_SIZE * max(width, height))
                        translation = cam_crop_to_full(camera, batch['box_center'].float(), batch['box_size'].float(), batch['img_size'].float(), focal)[0].cpu().numpy()
                    arrays = {k: prediction[v][0].cpu().numpy() for k, v in [('vertices', 'pred_vertices'), ('joints', 'pred_keypoints_3d')]}
                    arrays.update({k: prediction['pred_mano_params'][k][0].cpu().numpy() for k in ['global_orient', 'hand_pose', 'betas']})
                    arrays['camera_translation'] = translation
                    wilor.check_outputs(arrays)
                    vertices, joints, faces = wilor.to_image_handedness(arrays['vertices'], arrays['joints'], model.mano.faces, is_right)
                    xy = wilor.project_full(joints + translation, focal, width, height)
                    mesh_xy = wilor.project_full(vertices + translation, focal, width, height)
                    arrays.update(image_vertices=vertices, image_joints=joints, image_faces=faces, projected_joints=xy,
                                  detector_bbox=boxes[i], detector_confidence=np.asarray(confidence[i]), right=np.asarray(is_right),
                                  focal_length=np.asarray(focal), image_size=np.asarray([width, height]))
                    name = 'hand-%02d' % i
                    np.savez_compressed(folder / (name + '.npz'), **arrays)
                    import trimesh
                    trimesh.Trimesh(vertices=vertices, faces=faces, process=False).export(folder / (name + '.obj'))
                    color = (200, 170, 0) if is_right else (180, 80, 210)
                    wire = overlay.copy()
                    triangles = np.rint(mesh_xy[faces]).astype(np.int32)
                    cv2.polylines(wire, triangles, True, color, 1, cv2.LINE_AA)
                    overlay = cv2.addWeighted(wire, .65, overlay, .35, 0)
                    for point in np.rint(xy).astype(int):
                        cv2.circle(overlay, tuple(point), 2, color, -1)
                    cv2.rectangle(overlay, tuple(boxes[i, :2].astype(int)), tuple(boxes[i, 2:].astype(int)), color, 2)
                    agreement = compare_observations(xy, observations['left'], observations['right'], bool(observations['left_detected']), bool(observations['right_detected']), width, height)
                    record['hands'].append({'detection_index': i, 'detector_class': 'right' if is_right else 'left',
                        'detector_class_is_anatomically_verified': False, 'confidence': float(confidence[i]), 'bbox': boxes[i].tolist(),
                        'parameters': str((folder / (name + '.npz')).relative_to(out)), 'mesh': str((folder / (name + '.obj')).relative_to(out)),
                        'parameters_sha256': wilor.sha256(folder / (name + '.npz')), 'numerical_outputs_passed': True,
                        'observation_comparison': agreement, 'pose_accepted_for_training': False})
            cv2.imwrite(str(folder / 'wireframe-projection.jpg'), overlay)
            sheet = Image.new('RGB', (960, 520), 'white')
            for x, img in [(0, image), (480, overlay)]:
                panel = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB));panel.thumbnail((470, 470))
                sheet.paste(panel, (x + (480-panel.width)//2, 40))
            draw = ImageDraw.Draw(sheet)
            draw.text((10, 10), 'Original decoded reference frame', fill='black')
            draw.text((490, 10), 'WiLoR MANO wireframe / unverified hand classes', fill='black')
            sheet.save(folder / 'compare.jpg', quality=92)
            record['comparison_image'] = str((folder / 'compare.jpg').relative_to(out))
            write_json(out / 'report.json', report)
            print(json.dumps({'case_id': case['case_id'], 'hands': len(record['hands']), 'device': str(device)}), flush=True)
        check_plan(args.plan.resolve(), args.plan_sha256)
        report.update(status='native_keyframe_inference_completed_pending_quality_review', elapsed_seconds=time.monotonic()-start,
                      completed_cases=len(report['cases']), mano_candidate_count=sum(len(c['hands']) for c in report['cases']))
    except Exception as error:
        report.update(status='failed', failure_stage=stage, error=str(error), traceback=traceback.format_exc(), elapsed_seconds=time.monotonic()-start)
        raise
    finally:
        write_json(out / 'report.json', report)
    (out / 'SHA256SUMS').write_text(''.join(wilor.sha256(p)+'  '+str(p.relative_to(out))+'\n' for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--reference-root', type=Path, required=True)
    p.add_argument('--annotation-id', nargs='+', required=True)
    p.add_argument('--keyframe-index', nargs='+', type=int, default=[2, 3, 4, 0, 1])
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('run')
    for key in ['plan', 'wilor-root', 'mano-model', 'output']:
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--plan-sha256', required=True)
    p.add_argument('--device', choices=['cpu', 'mps', 'cuda'], default='cpu')
    args = parser.parse_args()
    (prepare if args.command == 'prepare' else run)(args)


if __name__ == '__main__':
    main()
