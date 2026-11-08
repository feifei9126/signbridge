"""Extract source-PTS bound basic vocabulary windows with raw hands/body/face observations."""
import argparse
import importlib.util
from pathlib import Path
import json,hashlib,subprocess,time


def main(args):
    import cv2
    import mediapipe as mp
    import numpy as np
    out=args.output.parent;inv=json.loads(args.inventory.read_text());proposals=json.loads(args.proposals.read_text());by={s['source_sha256'] if 'source_sha256'in s else s['sha256']:s for s in inv['unique_sources']}
    root=args.output.resolve();source_root=Path(inv['scope']).resolve()
    if root.exists() or root.is_relative_to(source_root):raise ValueError('Choose a NEW output outside original videos')
    helper_spec=importlib.util.spec_from_file_location('relabel_helpers',Path(__file__).with_name('sign-basic-csl-relabel.py'));helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
    for row in proposals['rows']:
     helper.validate_proposal(row,by[row['source_sha256']]['duration'])
     helper.verified_proposal_source(row,by,source_root)
    root.mkdir(parents=True);(root/'clips').mkdir();(root/'observations').mkdir();(root/'contact').mkdir()
    def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    def command(args,timeout=180):
     r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
     logs.append({'argv':args,'exit_code':r.returncode,'stdout':r.stdout if len(r.stdout)<30000 else 'omitted frame JSON; parsed into source-frame-map.json','stderr':r.stderr})
     if r.returncode:raise RuntimeError(r.stderr)
     return r.stdout
    logs=[];sourceframes={}
    for digest in sorted(set(x['source_sha256'] for x in proposals['rows'])):
     s=by[digest];assert sha(s['path'])==digest
     info=json.loads(command(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',s['path']]))
     pts=[float(x['best_effort_timestamp_time']) for x in info['frames']];assert all(b>a for a,b in zip(pts,pts[1:]));sourceframes[digest]=pts
    (root/'source-frame-map.json').write_text(json.dumps(sourceframes))
    records=[];failures=[]
    for row in proposals['rows']:
     try:
      pts=sourceframes[row['source_sha256']];ids=[i for i,t in enumerate(pts) if row['start']<=t<row['end']];assert len(ids)>3
      assert ids==list(range(ids[0],ids[-1]+1))
      target=root/'clips'/f"{row['id']}.mp4"
      command(['ffmpeg','-v','error','-nostdin','-n','-i',row['source_path'],'-vf',f"trim=start_frame={ids[0]}:end_frame={ids[-1]+1},setpts=PTS-STARTPTS,scale=720:960:force_original_aspect_ratio=decrease:force_divisible_by=2",'-an','-fps_mode','passthrough','-c:v','libx264','-crf','18','-preset','veryfast','-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(target)])
      records.append({**row,'reference_clip':str(target.relative_to(root)),'reference_sha256':sha(target),'source_frame_ids_0based':ids,'source_pts_seconds':[pts[i] for i in ids],'frames_expected':len(ids),'source_pts_measured':True})
     except Exception as e:failures.append({'id':row['id'],'error':repr(e)})
    (root/'extraction-commands.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2));(root/'extract-failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2))
    (root/'extract-records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    print('Reference clips',len(records),'failures',len(failures),flush=True)
    shapes={'pose_image':(33,4),'left_hand_image':(21,3),'right_hand_image':(21,3),'face_image':(468,3)}
    fields={'pose_image':'pose_landmarks','left_hand_image':'left_hand_landmarks','right_hand_image':'right_hand_landmarks','face_image':'face_landmarks'}
    cv2.setNumThreads(1);reports=[]
    for row in records:
     start=time.monotonic();cap=cv2.VideoCapture(str(root/row['reference_clip']));arrays={key:[] for key in shapes};images=[];fps=cap.get(cv2.CAP_PROP_FPS);n=0
     with mp.solutions.holistic.Holistic(static_image_mode=False,model_complexity=1,smooth_landmarks=False,enable_segmentation=False,refine_face_landmarks=False,min_detection_confidence=.5,min_tracking_confidence=.5) as detector:
      while True:
       ok,image=cap.read()
       if not ok:break
       output=detector.process(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
       for key,shape in shapes.items():
        data=np.full(shape,np.nan,dtype=np.float32);landmarks=getattr(output,fields[key])
        if landmarks is not None:
         assert len(landmarks.landmark)==shape[0]
         data[:,:3]=[[p.x,p.y,p.z] for p in landmarks.landmark]
         if shape[1]==4:data[:,3]=[p.visibility for p in landmarks.landmark]
        arrays[key].append(data)
       if n in set(round(i*(row['frames_expected']-1)/5) for i in range(6)):images.append((n,image.copy()))
       n+=1
     cap.release();assert n==row['frames_expected'],(row['id'],n,row['frames_expected'])
     result={key:np.stack(value) for key,value in arrays.items()};result['source_pts_seconds']=np.asarray(row['source_pts_seconds'],dtype=np.float64);result['source_frame_ids_0based']=np.asarray(row['source_frame_ids_0based'],dtype=np.int64)
     for key in shapes:result[key+'_detected']=np.isfinite(result[key][:,:,:3]).all((1,2))
     result['reference_fps']=np.asarray(fps)
     file=root/'observations'/f"{row['id']}.npz";np.savez_compressed(file,**result)
     # Original contact frames include the full face and both arms. No model overlay hides source hands.
     sheet=np.full((2*460,3*320,3),255,dtype=np.uint8)
     for slot,(frame,image) in enumerate(images):
      h,w=image.shape[:2];scale=min(320/w,420/h);small=cv2.resize(image,(round(w*scale),round(h*scale)));x=(slot%3)*320;y=(slot//3)*460
      sheet[y+30:y+30+small.shape[0],x:x+small.shape[1]]=small;cv2.putText(sheet,f"frame {frame} / {row['source_pts_seconds'][frame]:.3f}s",(x+4,y+20),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),1)
     imagefile=root/'contact'/f"{row['id']}.jpg";cv2.imwrite(str(imagefile),sheet)
     report={**row,'observations':str(file.relative_to(root)),'observations_sha256':sha(file),'contact_sheet':str(imagefile.relative_to(root)),'contact_sheet_sha256':sha(imagefile),'decoded_frames':n,'reference_fps':fps,'detected_frames':{key:int(result[key+'_detected'].sum()) for key in shapes},'extractor':'mediapipe-holistic','extractor_version':mp.__version__,'smoothing':False,'missing':'NaN and detection masks; no zero fill or interpolation','face_training_started':False,'time_seconds':round(time.monotonic()-start,2)}
     reports.append(report);(root/'observations-records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in reports));print(json.dumps({'id':row['id'],'text':row['text'],'frames':n,'detected':report['detected_frames'],'seconds':report['time_seconds']},ensure_ascii=False),flush=True)
    (root/'report.json').write_text(json.dumps({'status':helper.observation_status(len(reports),failures),'sequences':len(reports),'frames':sum(x['decoded_frames'] for x in reports),'failures':failures,'model_training_started':False,'training_ready':False,'human_approved':False,'face_landmarks_preserved':True,'mirror_status':'unknown','notes':['Source PTS are measured on original files; frame selection is exact at decoded source frame granularity.','Reference videos reencoded without FPS filter; frame count checked.','MediaPipe z is relative and not metric shared 3D.','Teaching mouth motion is not a verified lexical nonmanual annotation.','Source video may contain correct arm crossing/contact; observed proximity is not an error label.']},ensure_ascii=False,indent=2)+'\n')

    return 1 if failures or not reports else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--proposals',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(parser.parse_args()))
