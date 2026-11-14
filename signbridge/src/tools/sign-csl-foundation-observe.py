"""Audit every supplied clip with raw, missing-preserving body/hand/face tracks."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

SHAPES={'pose_image':(33,4),'left_hand_image':(21,3),'right_hand_image':(21,3),'face_image':(468,3)}
FIELDS={'pose_image':'pose_landmarks','left_hand_image':'left_hand_landmarks','right_hand_image':'right_hand_landmarks','face_image':'face_landmarks'}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def summary(values):
    import numpy as np
    a=np.asarray(values,float);v=a[np.isfinite(a)]
    return {'measured':int(len(v)),'missing':int(a.size-len(v)),'median':float(np.median(v)) if len(v) else None,
            'p95':float(np.percentile(v,95)) if len(v) else None,'max':float(v.max()) if len(v) else None}


def validate_arrays(a,n):
    import numpy as np
    for name,shape in SHAPES.items():
        v,mask=a[name],a[name+'_detected']
        if v.shape!=(n,*shape) or mask.shape!=(n,) or mask.dtype.kind!='b' or v.dtype!=np.float32:
            raise ValueError('Invalid observation arrays '+name)
        if not np.array_equal(np.isfinite(v[:,:,:3]).all((1,2)),mask) or not np.isnan(v[~mask]).all():
            raise ValueError('Missing detections must remain entirely NaN, with exact masks')


def motion_metrics(a,width,height):
    import numpy as np
    pose=a['pose_image'];body=pose[:,:,:2]*[width,height];valid=a['pose_image_detected']&(pose[:,11,3]>.5)&(pose[:,12,3]>.5)
    scale=np.linalg.norm(body[:,11]-body[:,12],axis=1);valid&=np.isfinite(scale)&(scale>20);scale[~valid]=np.nan;center=(body[:,11]+body[:,12])/2
    hands={}
    for side in ['left','right']:
        name=side+'_hand_image';mask=a[name+'_detected'];xy=a[name][:,:,:2]*[width,height];local=(xy[:,0]-center)/scale[:,None]
        local[~(mask&valid)]=np.nan;res=np.linalg.norm(local[1:-1]-(local[:-2]+local[2:])/2,axis=1)
        palm=np.median(np.linalg.norm(xy[:,[5,9,13,17]]-xy[:,None,0],axis=-1),axis=1);palm[~mask]=np.nan
        hands[side]={'detected_frames':int(mask.sum()),'total_frames':len(mask),'missing_frames':int((~mask).sum()),
                     'wrist_midpoint_residual_shoulder_units':summary(res),'median_palm_scale_pixels':summary(palm),
                     'slot_anatomy':'unverified_mediapipe_slot','presence_is_not_accuracy':True}
    def orient(a,b,c):return (b[:,0]-a[:,0])*(c[:,1]-a[:,1])-(b[:,1]-a[:,1])*(c[:,0]-a[:,0])
    armvalid=valid&np.all(pose[:,[13,14,15,16],3]>.5,axis=1)
    p,q,r,s=(body[:,i] for i in [13,15,14,16]);cross=(orient(p,q,r)*orient(p,q,s)<0)&(orient(r,s,p)*orient(r,s,q)<0)&armvalid
    pair=np.linalg.norm(body[:,15]-body[:,16],axis=1)/scale;pair[~armvalid]=np.nan
    flags=[]
    if not valid.any():flags.append('body_geometry_unavailable')
    if not any(h['detected_frames'] for h in hands.values()):flags.append('no_hand_observations')
    for side,h in hands.items():
        if h['missing_frames']:flags.append(side+'_hand_incomplete_or_not_visible')
        x=h['wrist_midpoint_residual_shoulder_units']['p95']
        if x is not None and x>.08:flags.append(side+'_wrist_projection_instability_candidate')
    if cross.any():flags.append('2d_forearm_crossing_needs_context_not_automatic_error')
    return {'hands':hands,'body':{'valid_geometry_frames':int(valid.sum()),'forearm_2d_crossing_frames':int(cross.sum()),
                               'wrist_separation_shoulder_units':summary(pair),'crossing_is_not_3d_penetration':True},
            'face':{'detected_frames':int(a['face_image_detected'].sum()),'total_frames':len(pose),
                    'linguistic_expression_label':None,'speech_mouthing_separated':False},
            'risk_flags':flags,'actual_3d_collision':'not_tested_from_2d','semantic_sign_correctness':'not_certified',
            'no_jitter_guarantee':False,'thresholds_are_triage_not_label_truth':{'wrist_residual_p95':.08}}


def inspect_one(job):
    os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
    import cv2
    import numpy as np
    from PIL import Image,ImageDraw
    row,db,out=job;started=time.monotonic();root=Path(out);folder=root/row['id'];folder.mkdir();clip=Path(db)/row['local_video']
    if clip.is_symlink() or not clip.resolve().is_relative_to(Path(db).resolve()) or sha(clip)!=row['media_sha256']:
        raise ValueError('Input clip path/hash differs')
    cap=cv2.VideoCapture(str(clip));fps=cap.get(cv2.CAP_PROP_FPS);width,height=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT));expected=row['frames'];images=[];frame_count=0
    reuse=Path(db)/row['observations'] if row.get('observations') else None
    if reuse and (reuse.is_symlink() or not reuse.resolve().is_relative_to(Path(db).resolve()) or sha(reuse)!=row.get('_observation_sha256')):
        raise ValueError('Reused observation path/hash differs from frozen database manifest')
    decoded_times=[]
    if reuse:
        with np.load(reuse,allow_pickle=False) as f:a={name:f[name].copy() for name in f.files}
        validate_arrays(a,expected)
        if not np.array_equal(a['source_frame_ids_0based'],row['source_frame_ids_0based']) or not np.array_equal(a['source_pts_seconds'],row['source_pts_seconds']):
            raise ValueError('Reused basic observations source frame mapping differs')
        extractor={'reused':True,'original_sha256':sha(reuse),'smoothing':False,'source_pts_verified':True}
    else:
        import mediapipe as mp
        arrays={k:[] for k in SHAPES};detector=mp.solutions.holistic.Holistic(static_image_mode=False,model_complexity=1,smooth_landmarks=False,enable_segmentation=False,refine_face_landmarks=False,min_detection_confidence=.5,min_tracking_confidence=.5)
        extractor={'reused':False,'name':'mediapipe-holistic','version':mp.__version__,'smoothing':False,'source_pts_verified':False,'original_source_time':'nominal teaching window only'}
    selected=set(round(i*(expected-1)/5) for i in range(6))
    cv2.setNumThreads(1)
    try:
        while True:
            ok,image=cap.read()
            if not ok:break
            decoded_times.append(float(cap.get(cv2.CAP_PROP_POS_MSEC)/1000))
            if not reuse:
                result=detector.process(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
                for name,shape in SHAPES.items():
                    v=np.full(shape,np.nan,np.float32);found=getattr(result,FIELDS[name])
                    if found is not None:
                        if len(found.landmark)!=shape[0]:raise ValueError('Unexpected point count')
                        v[:,:3]=[[x.x,x.y,x.z] for x in found.landmark]
                        if shape[1]==4:v[:,3]=[x.visibility for x in found.landmark]
                    arrays[name].append(v)
            if frame_count in selected:images.append((frame_count,image.copy()))
            frame_count+=1
    finally:
        cap.release()
        if not reuse:detector.close()
    if frame_count!=expected or abs(fps-row['reference_fps'])>.01:raise ValueError('Decoded clip frame/FPS differs')
    if not reuse:
        a={k:np.stack(v) for k,v in arrays.items()}
        for k in SHAPES:a[k+'_detected']=np.isfinite(a[k][:,:,:3]).all((1,2))
        a['clip_timestamps_seconds']=np.array(decoded_times,np.float64)
        a['clip_frame_ids_0based']=np.arange(frame_count,dtype=np.int64)
    validate_arrays(a,frame_count);np.savez_compressed(folder/'observations.npz',**a)
    sheet=Image.new('RGB',(960,2*300),'white');draw=ImageDraw.Draw(sheet)
    for slot,(n,image) in enumerate(images):
        im=Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB));im.thumbnail((320,270));x=slot%3*320;y=slot//3*300;sheet.paste(im,(x+(320-im.width)//2,y+24));draw.text((x+4,y+4),f'f{n+1} / clip {n/fps:.3f}s',fill='black')
    sheet.save(folder/'source-contact.jpg',quality=94)
    metrics=motion_metrics(a,width,height)
    report={'id':row['id'],'text':row['raw']['Chinese Sentences'],'dataset':row['dataset_id'],'clip_relative_path':row['local_video'],'clip_sha256':row['media_sha256'],
            'source_id':row['source_id'],'source_sha256':row['source_sha256'],'frames':frame_count,'fps':fps,'dimensions_wh':[width,height],
            'status':'technical_observations_with_risks' if metrics['risk_flags'] else 'technical_observations_no_flag_not_semantic_approval',
            'metrics':metrics,'extractor':extractor,'observations':'observations.npz','observations_sha256':sha(folder/'observations.npz'),
            'contact_sheet':'source-contact.jpg','contact_sheet_sha256':sha(folder/'source-contact.jpg'),'elapsed_seconds':round(time.monotonic()-started,2),
            'human_approved':False,'training_ready':False,'model_training_ready':False,'missing_values_filled':False,'full_avatar_motion_verified':False}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');return report


def run(database,output,workers=3,limit=None,reuse_roots=()):
    db=Path(database).resolve();out=Path(output).resolve()
    if out.exists() or out.is_relative_to(db) or db.is_relative_to(out):raise ValueError('NEW output separate from database required')
    raw=(db/'samples.jsonl').read_bytes();rows=[json.loads(x) for x in raw.decode().splitlines()];selected=[r for r in rows if r['dataset_id'] in {'tutorial-basic-candidates','additional-caption-candidates'}]
    expected_hashes={line.split('  ',1)[1]:line.split('  ',1)[0] for line in (db/'SHA256SUMS').read_text().splitlines()}
    for row in selected:
        if row.get('observations'):
            row['_observation_sha256']=expected_hashes[row['observations']]
    if limit is not None:selected=selected[:limit]
    import re
    if len({r['id'] for r in selected})!=len(selected) or any(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}',r['id']) is None for r in selected):raise ValueError('Unsafe/duplicate IDs')
    if not 1<=workers<=4:raise ValueError('Use1to4localobservationworkers')
    out.mkdir(parents=True);reports=[];failures=[];pending=[]
    for row in selected:
        adopted=False
        for previous in map(Path,reuse_roots):
            file=previous/row['id']/'report.json'
            if not file.is_file():continue
            record=json.loads(file.read_text());folder=file.parent
            if record.get('id')!=row['id'] or record.get('clip_sha256')!=row['media_sha256'] or record.get('source_sha256')!=row['source_sha256'] or record.get('frames')!=row['frames']:
                raise ValueError('Prior observation report differs from current input')
            for name,key in [('observations.npz','observations_sha256'),('source-contact.jpg','contact_sheet_sha256')]:
                if sha(folder/name)!=record.get(key):raise ValueError('Prior observation artifact changed')
            import numpy as np
            with np.load(folder/'observations.npz',allow_pickle=False) as arrays:validate_arrays(arrays,row['frames'])
            if sha(db/row['local_video'])!=row['media_sha256']:raise ValueError('Current clip differs from prior run')
            target=out/row['id'];shutil.copytree(folder,target)
            record['adopted_from_interrupted_attempt']={'path':str(folder),'report_sha256':sha(file)}
            (target/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
            reports.append(record);adopted=True;break
        if not adopted:pending.append(row)
    print(json.dumps({'adopted_verified':len(reports),'remaining':len(pending),'expected':len(selected)}),flush=True)
    (out/'tool-source.py').write_bytes(Path(__file__).read_bytes())
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[(r,pool.submit(inspect_one,(r,str(db),str(out)))) for r in pending]
        for row,f in futures:
            try:record=f.result();reports.append(record);print(json.dumps({'checked':len(reports),'id':row['id'],'frames':record['frames'],'seconds':record['elapsed_seconds']}),flush=True)
            except Exception as error:failures.append({'id':row['id'],'error':repr(error)})
            (out/'progress.json').write_text(json.dumps({'checked':len(reports),'expected':len(selected),'failures':failures})+'\n')
    if hashlib.sha256((db/'samples.jsonl').read_bytes()).hexdigest()!=hashlib.sha256(raw).hexdigest():raise ValueError('Input index changed')
    (out/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in reports))
    report={'schema':'signbridge-csl-foundation-motion-observations-v1','status':'complete_technical_audit' if not failures else 'completed_with_explicit_failures','at_utc':datetime.now(timezone.utc).isoformat(),'sequences':len(reports),'expected':len(selected),'frames':sum(r['frames'] for r in reports),'failures':failures,'source_index_sha256':hashlib.sha256(raw).hexdigest(),'tool_sha256':sha(__file__),'weights_training_started':False,'human_approved':False,'training_ready':False,'model_training_ready':False,'scope':'All clip frames processed, raw detection metrics only. Not proof of correct CSL semantics, no jitter or3D collision.'}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=3);p.add_argument('--limit',type=int);p.add_argument('--reuse-root',type=Path,action='append',default=[]);a=p.parse_args();r=run(a.database,a.output,a.workers,a.limit,a.reuse_root);raise SystemExit(2 if r['failures'] else 0)
