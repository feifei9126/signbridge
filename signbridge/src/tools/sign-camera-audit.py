"""Full-sequence virtual-camera experiment. Proposals are not physical motion or training labels."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location('camera_evidence', Path(__file__).with_name('sign-contact-audit.py'))
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
COUNTS = {'pilot-greeting-hello-001': 166, 'pilot-hospital-cough-003': 218}


def validate_camera(camera):
    values = {k: np.asarray(camera[k], dtype=np.float64) for k in ('focal', 'princpt')}
    if any(x.shape != (2,) or not np.isfinite(x).all() for x in values.values()) or \
       not (values['focal'] > 0).all():
        raise ValueError('Invalid camera intrinsics')
    return values


def validate_meta(meta, expected_image):
    camera = validate_camera(meta)
    bbox = np.asarray(meta['bbox'], dtype=np.float64)
    detector = np.asarray(meta['bbox_mmdet'], dtype=np.float64)
    if meta.get('bbox_id') != 0 or meta.get('img_path') != expected_image or \
       bbox.shape != (4,) or detector.shape != (4,) or not np.isfinite(bbox).all() or \
       not np.isfinite(detector).all() or not (bbox[2:] > 0).all() or not (detector[2:] > 0).all():
        raise ValueError('Invalid camera frame/person/bbox identity')
    # Fixed H32 source: body input (256,192), virtual focal (5000,5000).
    expected_focal = bbox[2:] * [5000. / 192., 5000. / 256.]
    expected_center = bbox[:2] + bbox[2:] / 2.
    if not np.allclose(camera['focal'], expected_focal, rtol=1e-6, atol=1e-5) or \
       not np.allclose(camera['princpt'], expected_center, rtol=0, atol=1e-5):
        raise ValueError('Camera differs from pinned crop-to-image convention')
    return camera


def rebase_translation(model, params, camera, reference):
    """Anchor pelvis pixels under a fixed camera; keep all local shape/pose arrays exact."""
    camera, reference = validate_camera(camera), validate_camera(reference)
    scale = reference['focal'] / camera['focal']
    if not np.isclose(scale[0], scale[1], rtol=1e-6, atol=1e-9):
        raise ValueError('Reference camera requires consistent x/y focal scaling')
    joints, tips = model.forward(params)
    points = np.concatenate((joints, tips))
    if points.shape != (65, 3) or not np.isfinite(points).all() or not (points[:, 2] > 1e-5).all():
        raise ValueError('Invalid or behind-camera SMPL-X geometry')
    original_projected = project(points, camera)
    pelvis_depth = points[0, 2] * scale.mean()
    pelvis = np.r_[(original_projected[0] - reference['princpt']) /
                   reference['focal'] * pelvis_depth, pelvis_depth]
    delta = pelvis - points[0]
    proposal = {k: v.copy() for k, v in params.items()}
    proposal['transl'] = params['transl'].astype(np.float64) + delta.reshape(1, 3)
    proposed_points = points + delta
    proposed_projected = project(proposed_points, reference)
    errors = np.linalg.norm(proposed_projected - original_projected, axis=-1)
    return proposal, {
        'pelvis_projection_error_pixels': float(errors[0]),
        'max_projection_error_pixels': float(errors.max()),
        'mean_projection_error_pixels': float(errors.mean()),
        'physical_motion_approved': False,
        'pose_and_shape_exactly_preserved': all(np.array_equal(proposal[k], params[k])
                                              for k in params if k != 'transl'),
    }, {'original': original_projected, 'proposal': proposed_projected, 'errors': errors}


def project(points, camera):
    if not np.isfinite(points).all() or not (points[:, 2] > 1e-5).all():
        raise ValueError('Nonfinite or behind-camera projection')
    return points[:, :2] / points[:, 2:3] * camera['focal'] + camera['princpt']


def verified_report(root, expected):
    manifest = evidence.verify_manifest(root.parent, root.parent / 'SHA256SUMS')
    path = evidence.contained_file(root, 'report.json')
    if evidence.digest(path) != expected or manifest.get('results/report.json') != expected:
        raise ValueError('Fusion report digest mismatch')
    return evidence.load_json(path), manifest


def listed_file(root, relative, manifest):
    path = evidence.contained_file(root, relative)
    if manifest.get(relative) != evidence.digest(path):
        raise ValueError('Unlisted source file or digest mismatch: '+relative)
    return path


def hand_pixels(points, side, helper):
    indices = [helper.WRISTS[side]]
    for i, chain in enumerate(helper.JOINTS[side]):
        indices.extend(chain)
        indices.append(55 + i + (0 if side == 'left' else 5))
    return points[indices]


def comparison_sheet(views, destination, helper):
    from PIL import Image, ImageDraw

    sheet = Image.new('RGB', (len(views) * 260, 680), 'white')
    d = ImageDraw.Draw(sheet)
    d.text((10, 6), 'Camera-coordinate proposal; frozen poses; NOT physical motion/training approval', fill='black')
    for index, (frame, path, points, sides) in enumerate(views):
        with Image.open(path) as image:
            original = image.convert('RGB')
        all_points = np.concatenate([hand_pixels(points['original'], s, helper) for s in sides])
        lo = np.maximum(np.floor(all_points.min(axis=0) - [65, 60]), [0, 0]).astype(int)
        hi = np.minimum(np.ceil(all_points.max(axis=0) + [65, 65]), original.size).astype(int)
        if np.any(hi <= lo):
            raise ValueError('Invalid review hand crop')
        for row, kind in enumerate(('source', 'original', 'proposal')):
            view = original.copy()
            draw = ImageDraw.Draw(view)
            if kind != 'source':
                color = (40, 130, 230) if kind == 'original' else (30, 170, 85)
                for side in sides:
                    hand = hand_pixels(points[kind], side, helper)
                    for a, b in helper.EDGES:
                        draw.line([tuple(hand[a]), tuple(hand[b])], fill=color, width=2)
                    for x, y in hand:
                        draw.ellipse((x-2, y-2, x+2, y+2), outline=color, width=2)
            view = view.crop((lo[0], lo[1], hi[0], hi[1]))
            view.thumbnail((250, 170))
            x, y = index * 260 + 5, 30 + row * 215
            sheet.paste(view, (x, y + 32))
            d.text((x, y), 'f%d %s' % (frame, kind), fill='black')
    sheet.save(destination, quality=95)


def plot_camera(original_z, proposal_z, focal, errors, fps, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    time = np.arange(len(original_z)) / fps
    figure, axes = plt.subplots(2, 2, figsize=(12, 7), constrained_layout=True)
    axes[0, 0].plot(time, original_z, label='Original crop-camera translation')
    axes[0, 0].plot(time, proposal_z, label='Fixed-camera proposal')
    axes[0, 0].set_ylabel('Virtual camera depth (m; NOT world motion)')
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].plot(time, focal)
    axes[0, 1].set_ylabel('Per-frame virtual focal (pixels)')
    axes[1, 0].plot(time[1:], np.abs(np.diff(original_z)), label='Original')
    axes[1, 0].plot(time[1:], np.abs(np.diff(proposal_z)), label='Proposal')
    axes[1, 0].set_ylabel('Absolute adjacent depth step (m)')
    axes[1, 0].legend(fontsize=8)
    axes[1, 1].plot(time, errors.max(axis=1), label='Max joint/tip error')
    axes[1, 1].plot(time, np.quantile(errors, .95, axis=1), label='95th percentile')
    axes[1, 1].set_ylabel('Proposal reprojection difference (pixels)')
    axes[1, 1].legend(fontsize=8)
    for ax in axes.ravel():
        ax.set_xlabel('Clip seconds')
        ax.grid(alpha=.25)
    figure.suptitle('Camera-coordinate experiment: no temporal smoothing; no pose changes')
    try:
        figure.savefig(destination, dpi=130)
    finally:
        plt.close(figure)


def audit(args):
    from PIL import Image

    source, batch, fusion, root, out = [Path(getattr(args, k)).resolve() for k in
                                      ('fit_source', 'batch', 'fusion_results', 'smplerx_root', 'output')]
    if out.exists() or any(p == out or p in out.parents or out in p.parents
                           for p in (source, batch, fusion.parent, root)):
        raise ValueError('Output must be new and separate from inputs')
    source_manifest = evidence.verify_manifest(source, source/'SHA256SUMS')
    batch_manifest = evidence.verify_manifest(batch, batch/'SHA256SUMS')
    run_path = listed_file(source, 'run.json', source_manifest)
    if evidence.digest(run_path) != args.fit_run_sha256:
        raise ValueError('Fit run digest mismatch')
    run = evidence.load_json(run_path)
    capture = evidence.load_json(listed_file(source, 'capture.json', source_manifest))
    if capture.get('schema') != 'signbridge-camera-source-capture-v1' or \
       capture.get('fit_run_sha256') != args.fit_run_sha256 or \
       capture.get('source_files_modified') is not False or capture.get('training_ready') is not False:
        raise ValueError('Unexpected capture contract')
    helper = evidence.load_model_helper()
    if run.get('schema') != 'signbridge-smplerx-run-v1' or run.get('model') != 'smpler_x_h32' or \
       run.get('status') != 'inferred_pending_import_audit' or set(run.get('completed', [])) != set(COUNTS) or \
       run.get('preflight', {}).get('actual_commit') != helper.COMMIT:
        raise ValueError('Unexpected original fitting run')
    report0, fusion_manifest = verified_report(fusion, args.fusion_report_sha256)
    if report0.get('schema') != 'signbridge-mano-smplx-alignment-v1' or \
       report0.get('training_ready') is not False or report0.get('fit_run_sha256') != args.fit_run_sha256:
        raise ValueError('Fusion run linkage differs')
    tasks_path = evidence.contained_file(batch, 'tasks.jsonl')
    if evidence.digest(tasks_path) != run.get('tasks_sha256') or \
       batch_manifest.get('tasks.jsonl') != evidence.digest(tasks_path):
        raise ValueError('Batch/fitting tasks digest mismatch')
    contract = evidence.load_json(listed_file(batch, 'contract.json', batch_manifest))
    if contract.get('schema') != 'signbridge-smplerx-input-v1' or contract.get('model_training_ready') is not False:
        raise ValueError('Unexpected batch contract')
    for name in ('contract.json', 'tasks.jsonl', 'SHA256SUMS'):
        evidence.require_source_digest(report0, 'batch/'+name, evidence.digest(batch/name))
    tasks_list = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]
    tasks = {row['segment_id']: row for row in tasks_list}
    if len(tasks) != len(tasks_list):
        raise ValueError('Duplicate tasks')
    jobs = {row['segment_id']: row for row in run['jobs']}
    if set(jobs) != set(COUNTS) or len(jobs) != len(run['jobs']):
        raise ValueError('Unexpected fitting job scope')
    for remote, sha in report0['source_sha256'].items():
        prefix = capture['remote_fits'] + '/'
        if remote.startswith(prefix):
            path = evidence.contained_file(source, remote[len(prefix):])
            if evidence.digest(path) != sha:
                raise ValueError('Previous fit/meta source digest mismatch')
    model_path = evidence.contained_file(root, helper.MODEL_FILE)
    if evidence.digest(model_path) != helper.MODEL_SHA256:
        raise ValueError('SMPL-X model digest mismatch')
    evidence.require_source_digest(report0, 'SMPLer-X/'+helper.MODEL_FILE, evidence.digest(model_path))
    model = helper.SparseSMPLX(model_path)
    cases = {(row['segment_id'], row['frame_1based']): row for row in report0['cases']}
    if len(cases) != len(report0['cases']) or any(s not in COUNTS or not 1 <= f <= COUNTS[s] for s, f in cases):
        raise ValueError('Unexpected fused frame identities')
    results, artifacts = {}, {}
    for segment, count in COUNTS.items():
        task = tasks[segment]
        if task['frames'] != count or task.get('model_training_ready') is not False or \
           not np.isfinite(task['fps']) or task['fps'] <= 0:
            raise ValueError('Wrong source frame count/FPS/readiness')
        frame_path = listed_file(batch, task['frame_manifest'], batch_manifest)
        frames = [json.loads(line) for line in frame_path.read_text().splitlines() if line.strip()]
        if [x['frame_id'] for x in frames] != list(range(1, count+1)):
            raise ValueError('Frame identity/order differs')
        argv = jobs[segment]['argv']
        image_dir = argv[argv.index('--img_path')+1]
        meta, params, images = [], [], []
        for frame, row in enumerate(frames, 1):
            relative = 'samples/'+segment+'/images/%06d.jpg' % frame
            image = evidence.contained_file(batch, relative)
            if row['image'] != relative or row['sha256'] != evidence.digest(image) or \
               batch_manifest.get(relative) != row['sha256'] or \
               not np.isclose(row['clip_seconds'], (frame-1)/task['fps'], rtol=0, atol=1e-6):
                raise ValueError('Image/frame digest or timestamp mismatch')
            m = evidence.load_json(listed_file(source, segment+'/meta/%05d_0.json' % frame, source_manifest))
            validate_meta(m, image_dir+'/%06d.jpg' % frame)
            meta.append(m)
            params.append(helper.read_native(listed_file(source, segment+'/smplx/%05d_0.npz' % frame, source_manifest)))
            with Image.open(image) as opened:
                images.append((image, opened.size))
        if len({size for _, size in images}) != 1:
            raise ValueError('Image sizes vary within the source clip')
        focal = np.asarray([m['focal'] for m in meta])
        reference = {'focal': np.median(focal, axis=0), 'princpt': np.asarray(images[0][1], dtype=float)/2.}
        proposed, errors, frame_stats, views = [], [], [], []
        for frame, (m, native) in enumerate(zip(meta, params), 1):
            proposal, stats, projected = rebase_translation(model, native, m, reference)
            proposed.append(proposal['transl'].ravel())
            errors.append(projected['errors'])
            stats.update(frame_1based=frame, source_translation=native['transl'].ravel().tolist(),
                         proposal_translation=proposal['transl'].ravel().tolist())
            if (segment, frame) in cases:
                case = cases[(segment, frame)]
                if case['output_relative'] != segment+'/%06d' % frame or case.get('training_ready') is not False:
                    raise ValueError('Fusion frame/output identity differs')
                folder = 'results/'+case['output_relative']
                baseline = helper.read_native(listed_file(fusion.parent, folder+'/baseline.npz', fusion_manifest))
                candidate = helper.read_native(listed_file(fusion.parent, folder+'/candidate.npz', fusion_manifest))
                if any(not np.array_equal(baseline[k], native[k]) for k in native):
                    raise ValueError('Fusion baseline does not match original fitting parameters')
                helper.preserved(native, candidate, case['required_sides'], allow_elbow=True)
                fused_proposal, fused_stats, fused_projected = rebase_translation(model, candidate, m, reference)
                stats['fused_window_projection'] = fused_stats
                stats['fused_window_proposal_translation'] = fused_proposal['transl'].ravel().tolist()
                views.append((frame, images[frame-1][0], fused_projected, case['required_sides']))
            frame_stats.append(stats)
        translations = np.stack([p['transl'].ravel() for p in params]).astype(np.float64)
        proposals = np.asarray(proposed)
        errors = np.asarray(errors)
        z, zp = translations[:, 2], proposals[:, 2]
        dz, dzp = np.abs(np.diff(z)), np.abs(np.diff(zp))
        summary = {'frames': count, 'fps': task['fps'], 'reference_camera': {k:v.tolist() for k,v in reference.items()},
                   'reference_selection': 'Median full-clip virtual focal and image center, no physical calibration',
                   'max_adjacent_depth_step_metres': float(dz.max()),
                   'proposal_max_adjacent_depth_step_metres': float(dzp.max()),
                   'projection_error_p95_pixels': float(np.quantile(errors, .95)),
                   'projection_error_max_pixels': float(errors.max()),
                   'focal_depth_correlation': float(np.corrcoef(focal[:, 0], z)[0, 1])
                       if np.std(focal[:, 0]) > 1e-12 and np.std(z) > 1e-12 else None,
                   'max_pelvis_projection_error_pixels': max(r['pelvis_projection_error_pixels'] for r in frame_stats),
                   'frames_audited': frame_stats, 'training_ready': False, 'physical_motion_approved': False}
        results[segment] = summary
        artifacts[segment] = dict(translations=translations, proposals=proposals, errors=errors,
            focal=focal, reference=reference, fps=task['fps'], views=views)
    for path in (source, batch, fusion.parent):
        evidence.verify_manifest(path, path/'SHA256SUMS')
    out.mkdir(parents=True)
    for segment, a in artifacts.items():
        folder = out/segment; folder.mkdir()
        np.savez_compressed(folder/'camera-proposals.npz', original_translation=a['translations'],
            proposal_translation=a['proposals'], original_focal=a['focal'],
            reference_focal=a['reference']['focal'], reference_principal_point=a['reference']['princpt'],
            frame_ids=np.arange(1, len(a['proposals'])+1), timestamps_seconds=np.arange(len(a['proposals']))/a['fps'],
            projection_errors_pixels=a['errors'], training_ready=np.asarray(False), physical_motion_approved=np.asarray(False))
        plot_camera(a['translations'][:,2], a['proposals'][:,2], a['focal'][:,0], a['errors'],
                    a['fps'], folder/'camera-depth.png')
        if a['views']:
            comparison_sheet(a['views'], folder/'reference-camera-review.jpg', helper)
    report = {'schema':'signbridge-camera-coordinate-audit-v1', 'status':'reference_camera_proposals_pending_review',
              'frames_evaluated':sum(COUNTS.values()), 'sequences':results, 'training_ready':False,
              'physical_motion_approved':False, 'contact_approved':False, 'source_fits_modified':False,
              'temporal_smoothing':False, 'full_sequence_hands_refined':False,
              'source_sha256': {'fit_run':args.fit_run_sha256, 'fusion_report':args.fusion_report_sha256,
                               'fit_manifest':evidence.digest(source/'SHA256SUMS'),
                               'batch_manifest':evidence.digest(batch/'SHA256SUMS'), 'model':evidence.digest(model_path),
                               'audit_tool':evidence.digest(__file__)},
              'limitations':['Reference camera is a virtual coordinate convention, not a calibrated physical camera.',
                  'Only pelvis projection is constrained exactly; non-root depth introduces measurable reprojection differences.',
                  'Root translation reduction is not proof of correct physical depth or sign-language motion.',
                  'Pose, fingers, face and shape are frozen; original hand errors are retained outside the fused windows.',
                  'Unresolved contact/mirror/transition labels and independent quality evaluation still block training.']}
    path = out/'report.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    paths = sorted(p for p in out.rglob('*') if p.is_file())
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+str(p.relative_to(out))+'\n' for p in paths))
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fit-source', type=Path, required=True)
    p.add_argument('--fit-run-sha256', required=True)
    p.add_argument('--batch', type=Path, required=True)
    p.add_argument('--fusion-results', type=Path, required=True)
    p.add_argument('--fusion-report-sha256', required=True)
    p.add_argument('--smplerx-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    print(audit(p.parse_args()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
