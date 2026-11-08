"""Measure raw source-observation risks without modifying points or approving signs."""
import argparse
from pathlib import Path
import json,concurrent.futures,subprocess,hashlib


def main(args):
    import numpy as np
    import cv2
    r=args.output;root=args.observations;
    if r.exists():raise ValueError("Choose a NEW quality audit output")
    r.mkdir(parents=True)
    def sha(path):
     digest=hashlib.sha256()
     with Path(path).open('rb') as stream:
      for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
     return digest.hexdigest()
    def checked(name,digest):
     path=root/name
     if not path.resolve(strict=True).is_relative_to(root.resolve()) or path.is_symlink() or sha(path)!=digest:raise ValueError('Observation artifact path/hash differs')
     return path
    records=[json.loads(l) for l in (root/'observations-records.jsonl').read_text().splitlines()]
    def summary(a):
     a=np.asarray(a,float);valid=np.isfinite(a);v=a[valid]
     return {'measured':int(valid.sum()),'missing':int((~valid).sum()),'median':float(np.median(v)) if len(v) else None,'p95':float(np.quantile(v,.95)) if len(v) else None,'max':float(v.max()) if len(v) else None}
    def cross(a,b,c,d):
     def orient(x,y,z):return (y[:,0]-x[:,0])*(z[:,1]-x[:,1])-(y[:,1]-x[:,1])*(z[:,0]-x[:,0])
     return (orient(a,b,c)*orient(a,b,d)<0)&(orient(c,d,a)*orient(c,d,b)<0)
    reports=[]
    for row in records:
     checked(row['observations'],row['observations_sha256']);checked(row['reference_clip'],row['reference_sha256'])
     cap=cv2.VideoCapture(str(root/row['reference_clip']));geometry=np.asarray([cap.get(cv2.CAP_PROP_FRAME_WIDTH),cap.get(cv2.CAP_PROP_FRAME_HEIGHT)]);cap.release()
     if not np.isfinite(geometry).all() or (geometry<=0).any():raise ValueError('Invalid reference dimensions')
     with np.load(root/row['observations'],allow_pickle=False) as f:
      pose=f['pose_image'];p=pose[:,:,:2]*geometry;scale=np.linalg.norm(p[:,11]-p[:,12],axis=1);valid=f['pose_image_detected']&(np.min(pose[:,[11,12,13,14,15,16],3],axis=1)>.5)&(scale>20)
      norm=scale.copy();norm[~valid]=np.nan;arms={}
      for slot in ['left','right']:
       xy=f[slot+'_hand_image'][:,:,:2]*geometry;mask=f[slot+'_hand_image_detected'];res=np.full(len(xy),np.nan)
       active=mask.copy();active[1:-1]&=mask[:-2]&mask[2:];active[0]=active[-1]=False
       distance=np.linalg.norm(xy[1:-1,0]-(xy[:-2,0]+xy[2:,0])/2,axis=1)/norm[1:-1];res[1:-1]=distance;res[~active]=np.nan
       fingers={}
       for name,j in zip(['index','middle','ring','little'],[6,10,14,18]):
        a=xy[:,j-1]-xy[:,j];b=xy[:,j+1]-xy[:,j]
        with np.errstate(invalid='ignore',divide='ignore'):angles=np.degrees(np.arccos(np.clip(np.sum(a*b,axis=1)/(np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1)),-1,1)))
        angles[~mask]=np.nan;fingers[name]=summary(angles)
       arms[slot]={'slot_anatomy':'unverified_mediapipe_slot','detected_frames':int(mask.sum()),'frames':len(mask),'missing_detection_frames':int((~mask).sum()),'observed_screen_x_pixels':summary(xy[:,0,0]),'wrist_midpoint_residual_in_shoulder_widths':summary(res),'finger_PIP_projected_interior_degrees':fingers,'foreshortening_caveat':'2D interior angle is not anatomical flexion; never substitutes for 3D handshape verification'}
      crossed=cross(p[:,13],p[:,15],p[:,14],p[:,16])&valid
      contact=np.linalg.norm(p[:,15]-p[:,16],axis=1)/norm
      face=f['face_image'][:,:,:2]*geometry;faceMask=f['face_image_detected'];eye=np.linalg.norm(face[:,33]-face[:,263],axis=1);eye[~faceMask]=np.nan
      with np.errstate(invalid='ignore',divide='ignore'):
       mouth=np.linalg.norm(face[:,13]-face[:,14],axis=1)/eye
       leftEye=np.linalg.norm(face[:,159]-face[:,145],axis=1)/eye
       rightEye=np.linalg.norm(face[:,386]-face[:,374],axis=1)/eye
       leftBrow=np.linalg.norm(face[:,105]-face[:,159],axis=1)/eye
       rightBrow=np.linalg.norm(face[:,334]-face[:,386],axis=1)/eye
      intended=row['id'] in ['basic-left','basic-right','basic-inside','basic-outside','basic-home','basic-school','basic-hospital']
      report={'id':row['id'],'text':row['text'],'frames':len(pose),'hands':arms,'body':{'observed_valid_frames':int(valid.sum()),'forearms_intersect_in_2d_frames':int(crossed.sum()),'wrist_separation_shoulder_units':summary(contact),'source_contact_or_crossing_may_be_intended':intended,'actual_3d_collision_test':'not_available_from_2D_observations','corrective_policy':'preserve demonstrated intentional crossing; reject unverified avatar intersections, never force hands apart based only on 2D overlap'},'nonmanual':{'face_detected_frames':int(faceMask.sum()),'mouth_opening_interocular_units':summary(mouth),'left_eye_opening_interocular_units':summary(leftEye),'right_eye_opening_interocular_units':summary(rightEye),'left_brow_eye_distance_interocular_units':summary(leftBrow),'right_brow_eye_distance_interocular_units':summary(rightBrow),'observations_only':True,'emotion_label':None,'mouth_linguistic_label':None,'head_and_gaze_linguistic_labels':None,'explainer_speech_mouthing_not_resolved':True},'decoded_dimensions_wh':geometry.astype(int).tolist(),'source_sha256':row['source_sha256'],'source_pts_measured':True,'training_ready':False,'model_training_ready':False,'human_approved':False}
      reports.append(report)
    (r/'quality-metrics.json').write_text(json.dumps({'schema':'signbridge-basic-observation-quality-v1','sequences':reports,'notes':['No smoothing, interpolation or missing-point fill.','Metrics are 2D projection proxies and cannot certify finger anatomy, no jitter, no 3D mesh penetration or CSL correctness.','The left/right slots are MediaPipe outputs; source image-side/anatomical mirror not assumed.']},ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    inv=json.loads(args.inventory.read_text())
    def decode(s):
     if sha(s['path'])!=s['sha256']:raise ValueError('Original source changed before full decode')
     cmd=['ffmpeg','-v','error','-nostdin','-threads','1','-i',s['path'],'-map','0:v:0','-an','-f','null','-']
     v=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
     return {'source_sha256':s['sha256'],'source_path':s['path'],'argv':cmd,'exit_code':v.returncode,'stdout':v.stdout,'stderr':v.stderr,'full_video_decoding_passed':v.returncode==0 and not v.stderr.strip()}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:decodes=list(pool.map(decode,inv['unique_sources']))
    (r/'full-folder-decode.json').write_text(json.dumps({'status':'passed' if all(x['full_video_decoding_passed'] for x in decodes) else 'failed','records':decodes},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'quality_sequences':len(reports),'full_source_decode':len(decodes),'decode_failures':sum(not x['full_video_decoding_passed'] for x in decodes)},ensure_ascii=False))

    return 0 if all(x['full_video_decoding_passed'] for x in decodes) else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--observations',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(parser.parse_args()))
