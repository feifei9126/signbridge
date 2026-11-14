"""Correct observed hand poses across full source clips; preserve unknowns and originals."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def tool(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


hand=tool('sign-hand-refine.py')
compare=tool('sign-csl-foundation-compare.py')


def sha(p):return hand.sha256(Path(p))


def safe_file(root,name):
    path=Path(root)/name
    if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()) or not path.is_file():raise ValueError('Unsafe input artifact')
    if any((Path(root).joinpath(*Path(name).parts[:i])).is_symlink() for i in range(1,len(Path(name).parts)+1)):raise ValueError('Symlink in input artifact path')
    return path


def checksum_manifest(root):
    """Read a SHA256SUMS manifest without accepting aliases or duplicate paths."""
    entries = {}
    for line in safe_file(root, 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
        if not match:
            raise ValueError('Invalid SHA256SUMS entry')
        digest, name = match.groups()
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or
                relative.as_posix() != name or name in entries):
            raise ValueError('Unsafe or duplicate SHA256SUMS path')
        entries[name] = digest
    return entries


def frozen_file(root, checksums, name):
    path = safe_file(root, name)
    if checksums.get(name) != sha(path):
        raise ValueError('Frozen SHA256SUMS mismatch: ' + name)
    return path


def unique_record(path, sid):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    matches = [row for row in rows if row.get('id') == sid]
    if len(matches) != 1:
        raise ValueError('Missing or duplicate action/sample ID: ' + sid)
    return matches[0]


def verify_inputs(library, sid, model_file):
    """Return the unchanged action dict after verifying its frozen identity chain.

    Accepts str/Path library and model paths and a sample ID. Reads only: no
    model loading, fitting, output creation, GPU access or approval changes.
    The library's frozen report/source-input-hashes locate the reference DB;
    its samples and lexical evidence are needed to recompute annotation_version.
    Every source frame ID/PTS must match that frozen sample, including gaps in
    hand detections. Failure raises ValueError; success is not motion acceptance.
    Joint fitting callers should revalidate before publishing their outputs.
    """
    library, model_file = Path(library).resolve(), Path(model_file)
    if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}', sid):
        raise ValueError('Unsafe sample ID')
    checksums = checksum_manifest(library)
    checked = lambda name: frozen_file(library, checksums, name)
    action = unique_record(checked('action-checks.jsonl'), sid)
    required = {'id', 'source_sha256', 'clip_sha256', 'annotation_sha256',
                'action_version_sha256', 'frames', 'fps', 'clip', 'observations',
                'local_native_directory', 'native_comparison'}
    if not required.issubset(action):
        raise ValueError('Incomplete frozen action identity')
    for key in ['source_sha256', 'clip_sha256', 'annotation_sha256', 'action_version_sha256']:
        if not isinstance(action[key], str) or not re.fullmatch(r'[0-9a-f]{64}', action[key]):
            raise ValueError('Invalid action identity digest: ' + key)
    count, fps = action['frames'], action['fps']
    if type(count) is not int or count < 2 or type(fps) not in (int, float) or not np.isfinite(fps) or fps <= 0:
        raise ValueError('A full source sequence with valid frame count/fps is required')
    expected_paths = {'clip': f'clips/{sid}.mp4', 'observations': f'observations/{sid}.npz',
                      'local_native_directory': f'native-actions/{sid}'}
    if any(action[key] != name for key, name in expected_paths.items()):
        raise ValueError('Action artifact paths differ from sample identity')
    clip = checked(action['clip'])
    observation = checked(action['observations'])
    if sha(clip) != action['clip_sha256']:
        raise ValueError('Source clip digest differs from action')
    if not model_file.is_file() or sha(model_file) != compare.MODEL_SHA:
        raise ValueError('SMPL-X model differs')
    native_record = action['native_comparison']
    bindings = {'candidate_id': sid, 'source_sha256': action['source_sha256'],
                'clip_sha256': action['clip_sha256'], 'expected_frames': count,
                'action_version_sha256': action['action_version_sha256']}
    if not isinstance(native_record, dict) or any(native_record.get(k) != v for k, v in bindings.items()):
        raise ValueError('Native/action identity binding differs')

    report = json.loads(checked('report.json').read_text())
    input_hashes = json.loads(checked('source-input-hashes.json').read_text())
    if not isinstance(report.get('base_database'), str) or not isinstance(input_hashes, dict):
        raise ValueError('Missing frozen reference database identity')
    database = Path(report['base_database']).resolve()
    for name in ['SHA256SUMS', 'samples.jsonl']:
        path = safe_file(database, name)
        if input_hashes.get(str(path)) != sha(path):
            raise ValueError('Frozen reference database changed: ' + name)
    database_checksums = checksum_manifest(database)
    sample = unique_record(frozen_file(database, database_checksums, 'samples.jsonl'), sid)
    if (sample.get('source_sha256') != action['source_sha256'] or
            sample.get('media_sha256') != action['clip_sha256'] or
            sample.get('frames') != count or sample.get('reference_fps') != fps):
        raise ValueError('Frozen sample/source/clip/frame identity differs')
    source_id = sample.get('source_id')
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}', source_id):
        raise ValueError('Unsafe original source ID')
    if sha(checked(f'tutorial-sources/video/{source_id}.mp4')) != action['source_sha256']:
        raise ValueError('Original source video differs')
    lexical_path = frozen_file(database, database_checksums, 'tutorial/lexical-evidence.jsonl')
    lexical = [json.loads(line) for line in lexical_path.read_text().splitlines() if line.strip()]
    refined = json.loads(checked('source-annotations/tutorial-refinement-main-v2.json').read_text())['annotations']
    targets = json.loads(checked('source-annotations/foundation-targets-v2.json').read_text())['records']
    captions = [json.loads(line) for line in checked('refined-captions.jsonl').read_text().splitlines() if line.strip()]
    caption_rows = [row for row in captions if row.get('id') == sid]
    if len(caption_rows) > 1:
        raise ValueError('Duplicate caption annotation identity')
    foundation = tool('sign-csl-foundation.py')
    annotation = foundation.annotation_version(sample, lexical, refined, targets, caption_rows[0] if caption_rows else None)
    if annotation != action['annotation_sha256']:
        raise ValueError('Annotation/source/word-boundary binding differs')

    with np.load(observation, allow_pickle=False) as archive:
        fields = {'left_hand_image', 'left_hand_image_detected', 'source_pts_seconds',
                  'source_frame_ids_0based', 'reference_fps'}
        if not fields.issubset(archive.files):
            raise ValueError('Incomplete raw observation identity')
        points, mask = archive['left_hand_image'], archive['left_hand_image_detected']
        pts, ids = archive['source_pts_seconds'], archive['source_frame_ids_0based']
        reference_fps = archive['reference_fps']
        if (points.shape != (count, 21, 3) or points.dtype.kind != 'f' or
                mask.shape != (count,) or mask.dtype.kind != 'b' or
                not np.isfinite(points[mask]).all() or not np.isnan(points[~mask]).all()):
            raise ValueError('Invalid raw observed hand targets or missing mask')
        expected_ids = np.asarray(sample.get('source_frame_ids_0based', []))
        expected_pts = np.asarray(sample.get('source_pts_seconds', []))
        if (ids.shape != (count,) or ids.dtype.kind not in 'iu' or
                expected_ids.shape != (count,) or expected_ids.dtype.kind not in 'iu' or
                (ids < 0).any() or (ids > np.iinfo(np.int64).max).any() or
                not (np.diff(ids.astype(np.int64)) == 1).all() or
                not np.array_equal(ids, expected_ids)):
            raise ValueError('Source frame IDs are not the exact frozen consecutive sequence')
        if (pts.shape != (count,) or pts.dtype.kind != 'f' or
                expected_pts.shape != (count,) or expected_pts.dtype.kind not in 'fi' or
                not np.isfinite(pts).all() or (pts < 0).any() or
                not (np.diff(pts) > 0).all() or not np.array_equal(pts, expected_pts)):
            raise ValueError('Source PTS differ from exact frozen frame mapping')
        if reference_fps.size != 1 or not np.isclose(reference_fps.item(), fps, rtol=0, atol=1e-6):
            raise ValueError('Observation reference fps differs')
    override = sample.get('candidate_override')
    if override and (override.get('clip_sha256') != action['clip_sha256'] or
                     override.get('observations_sha256') != sha(observation) or override.get('frames') != count):
        raise ValueError('Amended source boundary/observation binding differs')

    import cv2
    capture = cv2.VideoCapture(str(clip))
    try:
        if (not capture.isOpened() or capture.get(cv2.CAP_PROP_FRAME_COUNT) != count or
                not np.isclose(capture.get(cv2.CAP_PROP_FPS), fps, rtol=0, atol=1e-4) or
                min(capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) <= 0):
            raise ValueError('Source clip frame count/fps/dimensions differ')
        decoded = 0
        while True:
            ok, image = capture.read()
            if not ok:
                break
            decoded += 1
            if image is None or decoded > count:
                raise ValueError('Invalid source clip frame sequence')
        if decoded != count:
            raise ValueError('Source clip does not decode to all frozen frames')
    finally:
        capture.release()
    native = library / action['local_native_directory']
    for i in range(1, count + 1):
        for folder, name in [('smplx', f'{i:05d}_0.npz'), ('meta', f'{i:05d}_0.json'), ('img', f'{i:06d}.jpg')]:
            checked(f'{action["local_native_directory"]}/{folder}/{name}')
        hand.read_native(native / 'smplx' / f'{i:05d}_0.npz')
        camera = json.loads((native / 'meta' / f'{i:05d}_0.json').read_text())
        for key in ['focal', 'princpt']:
            value = np.asarray(camera.get(key), dtype=float)
            if value.shape != (2,) or not np.isfinite(value).all() or (key == 'focal' and (value <= 0).any()):
                raise ValueError('Invalid frozen native camera: ' + key)
    compare.verify_action({**native_record, 'native_directory': str(native)})
    return action


def observed_neighbors(index,mask,accepted):
    return [i for i in [index-1,index+1] if 0<=i<len(mask) and mask[i] and accepted[i]]


def unchanged(source,candidate,side):
    hand.preserved(source,candidate,(side,),allow_elbow=True)
    if any(source[k].dtype!=candidate[k].dtype for k in source):raise ValueError('Native dtype changed')
    elbow=hand.ELBOWS[side]-1;wrist=hand.WRISTS[side]-1
    error=lambda a,b:float(np.rad2deg((Rotation.from_rotvec(a)*Rotation.from_rotvec(b).inv()).magnitude()))
    if error(candidate['body_pose'][elbow],source['body_pose'][elbow])>15.00002 or error(candidate['body_pose'][wrist],source['body_pose'][wrist])>80.00001:raise ValueError('Protected elbow/wrist angular limit exceeded')


def fit_temporal(model,original,initial,side,target,camera,neighbors,weight=.12,max_nfev=300):
    key=side+'_hand_pose';elbow=hand.ELBOWS[side]-1;wrist=hand.WRISTS[side]-1
    elbow0=original['body_pose'][elbow].astype(float);wrist0=original['body_pose'][wrist].astype(float);hand0=original[key].ravel().astype(float)
    delta=(Rotation.from_rotvec(initial['body_pose'][elbow])*Rotation.from_rotvec(elbow0).inv()).as_rotvec()
    x0=np.r_[initial[key].ravel(),delta,initial['body_pose'][wrist]];center=np.r_[hand0,[0.,0.,0.],wrist0];bounds=np.r_[np.full(45,np.deg2rad(150)),np.full(3,np.pi),np.full(3,np.deg2rad(55))]
    x0=np.clip(x0,center-bounds+1e-8,center+bounds-1e-8);prepared=model.prepared(original);scale=hand.target_scale(target[:,:2]);local_target=(target[:,:2]-target[0,:2])/scale
    native_prior=hand.hand_rotations(original,model,side);wr0=Rotation.from_rotvec(wrist0).as_matrix();weights=np.ones((21,1));weights[[4,8,12,16,20]]=1.5
    references=[(hand.hand_rotations(p,model,side),Rotation.from_rotvec(p['body_pose'][wrist]).as_matrix()) for p in neighbors]
    def unpack(x):
        p={k:v.astype(float).copy() for k,v in original.items()};p[key]=x[:45].reshape(15,3);p['body_pose'][elbow]=hand.bounded_elbow_rotation(x[45:48],elbow0,15.);p['body_pose'][wrist]=x[48:51];return p
    def residual(x):
        p=unpack(x);xy=hand.project(model.hand(p,side,prepared),camera);rot=hand.hand_rotations(p,model,side);wr=Rotation.from_rotvec(p['body_pose'][wrist]).as_matrix();er=Rotation.from_rotvec(p['body_pose'][elbow]).as_matrix()-Rotation.from_rotvec(elbow0).as_matrix()
        parts=[(weights*((xy-xy[0])/scale-local_target)).ravel(),(1.25*weights*(xy-target[:,:2])/scale).ravel(),2.*(xy[0]-target[0,:2])/scale,.03*(rot-native_prior).ravel(),.03*er.ravel(),.10*(wr-wr0).ravel()]
        for rotation,wrotation in references:parts.extend([weight*(rot-rotation).ravel(),weight*(wr-wrotation).ravel()])
        return np.concatenate(parts)
    result=least_squares(residual,x0,bounds=(center-bounds,center+bounds),loss='soft_l1',f_scale=.1,max_nfev=max_nfev,xtol=1e-5,ftol=1e-5,gtol=1e-5)
    p={k:v.astype(original[k].dtype) for k,v in unpack(result.x).items()};unchanged(original,p,side)
    before=hand.reprojection_metrics(model.hand(initial,side),target,camera);after=hand.reprojection_metrics(model.hand(p,side),target,camera)
    baseline=hand.reprojection_metrics(model.hand(original,side),target,camera)
    source_projection_passed=hand.projection_gate(baseline,after)
    finger_change=Rotation.from_matrix(hand.hand_rotations(p,model,side)@native_prior.transpose(0,2,1)).magnitude()
    max_finger_change=float(np.rad2deg(finger_change.max()))
    wrist_before=float(np.linalg.norm(hand.project(model.hand(original,side),camera)[0]-target[0,:2]))
    wrist_after=float(np.linalg.norm(hand.project(model.hand(p,side),camera)[0]-target[0,:2]))
    wrist_gate_passed=bool(wrist_after<=(.8*wrist_before if wrist_before>8 else wrist_before+1e-5))
    fingertip_gate_passed=bool(after['fingertip_local_rmse_pixels']<=before['fingertip_local_rmse_pixels']+1e-5)
    approved=bool(result.status>0 and source_projection_passed and wrist_gate_passed and fingertip_gate_passed and max_finger_change<=155.00001 and after['local_rmse_pixels']<=max(before['local_rmse_pixels']*1.08,before['local_rmse_pixels']+.3) and after['absolute_rmse_pixels']<=before['absolute_rmse_pixels']+1.)
    return p,{'optimizer_status':int(result.status),'nfev':int(result.nfev),'neighbor_count':len(neighbors),'temporal_weight':weight,'baseline':baseline,'before':before,'after':after,'source_projection_gate_passed':bool(source_projection_passed),'fingertip_gate_passed':fingertip_gate_passed,'max_finger_change_degrees':max_finger_change,'wrist_error_before_pixels':wrist_before,'wrist_error_after_pixels':wrist_after,'wrist_gate_passed':wrist_gate_passed,'numeric_candidate_retained':approved,'semantic_approval':False}


def run_sequence(args):
    library,model_file,root,sid=args;library,model_file,root=map(Path,[library,model_file,root]);start=time.monotonic();side='left'
    action=verify_inputs(library,sid,model_file);native=library/action['local_native_directory'];count=action['frames'];out=root/sid;out.mkdir()
    model=hand.SparseSMPLX(model_file)
    source_hashes={str(library/name):sha(library/name) for name in ['SHA256SUMS','action-checks.jsonl','report.json','source-input-hashes.json',action['clip']]};source_hashes[str(model_file)]=sha(model_file)
    observation=safe_file(library,action['observations']);source_hashes[str(observation)]=sha(observation)
    with np.load(observation,allow_pickle=False) as f:
        points=f['left_hand_image'].copy();mask=f['left_hand_image_detected'].copy();source_pts=f['source_pts_seconds'].copy();source_ids=f['source_frame_ids_0based'].copy()
    if points.shape!=(count,21,3) or mask.dtype.kind!='b' or not np.isfinite(points[mask]).all() or not np.isnan(points[~mask]).all():raise ValueError('Invalid raw observed hand targets')
    import cv2
    cap=cv2.VideoCapture(str(library/action['clip']));width,height=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT));cap.release();targets=points.astype(float)*[width,height,width]
    originals=[];cameras=[];metas=[];independent=[];frame_records=[];accepted=np.zeros(count,bool)
    for i in range(count):
        nativefile=native/'smplx'/f'{i+1:05d}_0.npz';metafile=native/'meta'/f'{i+1:05d}_0.json';p=hand.read_native(nativefile);meta=json.loads(metafile.read_text());camera={k:np.asarray(meta[k],float) for k in ['focal','princpt']};originals.append(p);cameras.append(camera);metas.append(meta)
        source_hashes[str(nativefile)]=sha(nativefile);source_hashes[str(metafile)]=sha(metafile)
        base={'frame_1based':i+1,'source_pts_seconds':float(source_pts[i]),'source_frame_id_0based':int(source_ids[i]),'source_hand_observed':bool(mask[i]),'baseline_sha256':sha(nativefile)}
        if not mask[i]:
            selected={k:v.copy() for k,v in p.items()};base.update(independent_status='unobserved_source_hand; original_native_preserved',independent_accepted=False)
        else:
            if hand.target_scale(targets[i,:,:2])<15:
                selected={k:v.copy() for k,v in p.items()};base.update(independent_status='observed_hand_too_small; original_native_preserved',independent_accepted=False)
            else:
                left_error=np.linalg.norm(hand.project(model.hand(p,'left'),camera)[0]-targets[i,0,:2]);right_error=np.linalg.norm(hand.project(model.hand(p,'right'),camera)[0]-targets[i,0,:2])
                if left_error+20>=right_error:raise ValueError('Same-slot anatomical association is ambiguous; no hand swap permitted')
                candidate,metrics=hand.fit_hand(model,p,side,targets[i],camera,250,allow_elbow=True);attempts=[metrics]
                if metrics['optimizer_status']==0:
                    candidate,metrics=hand.fit_hand(model,p,side,targets[i],camera,600,allow_elbow=True);attempts.append(metrics)
                accepted[i]=metrics['candidate_gate_passed'];selected=candidate if accepted[i] else {k:v.copy() for k,v in p.items()};base.update(independent_status='numeric_candidate' if accepted[i] else 'rejected_original_preserved',independent_accepted=bool(accepted[i]),independent_metrics=metrics,optimization_attempts=attempts)
                folder=out/'raw-proposals';folder.mkdir(exist_ok=True);np.savez_compressed(folder/f'{i+1:05d}_0.npz',**candidate)
        unchanged(p,selected,side);independent.append(selected);frame_records.append(base)
        folder=out/'independent';folder.mkdir(exist_ok=True);np.savez_compressed(folder/f'{i+1:05d}_0.npz',**selected)
        if (i+1)%10==0:print(json.dumps({'id':sid,'stage':'independent','frame':i+1,'count':count,'retained':int(accepted[:i+1].sum())}),flush=True)
    final=[]
    for i,p in enumerate(independent):
        neighbors=observed_neighbors(i,mask,accepted)
        if accepted[i] and neighbors:
            candidate,metrics=fit_temporal(model,originals[i],p,side,targets[i],cameras[i],[independent[j] for j in neighbors]);selected=candidate if metrics['numeric_candidate_retained'] else p;frame_records[i]['temporal_metrics']=metrics
        else:selected=p;frame_records[i]['temporal_metrics']={'numeric_candidate_retained':False,'reason':'Noacceptedobservedadjacentframe; nofillorinterpolation'}
        unchanged(originals[i],selected,side);final.append(selected);folder=out/'candidate';folder.mkdir(exist_ok=True);np.savez_compressed(folder/f'{i+1:05d}_0.npz',**selected);frame_records[i]['candidate_sha256']=sha(folder/f'{i+1:05d}_0.npz')
        if not mask[i] and any(not np.array_equal(originals[i][k],selected[k]) for k in selected):raise ValueError('Unobserved source hand was modified')
    def metrics_for(series):
        xy=np.stack([hand.project(model.hand(p,side),cam) for p,cam in zip(series,cameras)]);space=compare.spatial_errors(xy,targets[:,:,:2],mask);velocity=compare.compare_velocity(xy,targets[:,:,:2],mask);angles=compare.angular_change(np.stack([p['left_hand_pose'] for p in series]),model.mean[25:40]);return {'spatial':space,'velocity':velocity,'effective_hand_adjacent_degrees':compare.summary(angles)}
    summary={'baseline':metrics_for(originals),'independent':metrics_for(independent),'candidate':metrics_for(final)}
    for name,digest in source_hashes.items():
        if sha(name)!=digest:raise ValueError('Source changed during corrective fitting')
    if verify_inputs(library,sid,model_file)!=action:raise ValueError('Frozen action changed during corrective fitting')
    version=hashlib.sha256(json.dumps({'source':action['source_sha256'],'clip':action['clip_sha256'],'annotation':action['annotation_sha256'],'frames':[x['candidate_sha256'] for x in frame_records]},sort_keys=True).encode()).hexdigest()
    (out/'frames.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n' for x in frame_records))
    report={'schema':'signbridge-observed-hand-sequence-correction-v1','status':'corrective_pose_candidates_created_not_full_semantic_pass','id':sid,'frames':count,'fps':action['fps'],'dimensions_wh':[width,height],'source_clip_sha256':action['clip_sha256'],'source_sha256':action['source_sha256'],'annotation_sha256':action['annotation_sha256'],'baseline_action_version':action['action_version_sha256'],'candidate_action_version':version,'observed_active_hand_frames':int(mask.sum()),'unobserved_active_hand_frames':np.flatnonzero(~mask).astype(int).__add__(1).tolist(),'numeric_frame_candidates':int(accepted.sum()),'metrics':summary,'protected_native_values_unchanged':True,'missing_observations_filled':False,'source_file_hashes':source_hashes,'elapsed_seconds':time.monotonic()-start,'training_started':False,'training_ready':False,'model_training_ready':False,'human_approved':False,'full_action_two_round_passes':0,'remaining_unknowns':['Unobservedactivehandframesnotcorrected','Otherhandnotobservable','3Ddepth/handedness/mirrorandsign-specificfingeridentitynotfullycertified','Fullmeshandfacialsemanticacceptanceneedindependentverification']}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps({'id':sid,'complete':True,'seconds':report['elapsed_seconds'],'metrics':summary}),flush=True);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--library',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.output.resolve();library=a.library.resolve()
    if root.exists() or root.is_relative_to(library) or library.is_relative_to(root):raise ValueError('NEWoutput separatefromfrozenlibraryrequired')
    root.mkdir(parents=True);(root/'tool-source.py').write_bytes(Path(__file__).read_bytes())
    with ProcessPoolExecutor(max_workers=2) as pool:reports=list(pool.map(run_sequence,[(str(library),str(a.model.resolve()),str(root),sid) for sid in ['basic-i','basic-you']]))
    report={'status':'two_sequence_correction_candidates_completed','sequences':2,'frames':sum(x['frames'] for x in reports),'records':reports,'tool_sha256':sha(__file__),'training_started':False,'training_ready':False,'model_training_ready':False,'full_action_two_round_passes':0,'at_utc':datetime.now(timezone.utc).isoformat()};(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps({'sequences':2,'frames':report['frames'],'training_started':False}),flush=True)


if __name__=='__main__':main()
