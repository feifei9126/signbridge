"""Evidence-bound tutorial hand-reference clips; no inferred human approval or 3D truth."""
import argparse
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

SPEC = importlib.util.spec_from_file_location('tutorial_data',Path(__file__).with_name('sign-data.py'))
data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(data)
KINDS = {'step_instruction','complete_demonstration','continuous_narrative','theory','word_candidate'}


def validate_annotation(value, duration):
    row = dict(value)
    for key in ('annotation_id','source_id'):
        if not isinstance(row.get(key),str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',row[key]) is None:
            raise ValueError('Invalid annotation or source ID')
    start,end = float(row['start_seconds']),float(row['end_seconds'])
    if not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end<=duration:
        raise ValueError('Invalid annotation boundaries')
    if row.get('sample_type') not in KINDS or any(
            not isinstance(row.get(key), str) or not row[key].strip()
            for key in ('label', 'label_evidence')):
        raise ValueError('Annotation kind, nonempty label and text evidence required')
    if row.get('human_approved') is not False or row.get('mirror_status')!='unknown':
        raise ValueError('Do not infer human approval or mirror direction')
    reviewers = {'sparse_ocr_window': 'automatic_caption_index',
                 'assistant_visual': 'assistant_visual_review',
                 'assistant_visual_coarse': 'assistant_visual_review'}
    if row.get('boundary_review') not in reviewers:
        raise ValueError('Explicit boundary review provenance required')
    annotator = reviewers[row['boundary_review']]
    row.update(start_seconds=start,end_seconds=end,annotator=annotator,
               human_approved=False,training_ready=False,smplx_parameters_created=False)
    return row


def title_spans(rows,duration,interval):
    if not 0<interval<=4 or not math.isfinite(duration) or duration<=0:
        raise ValueError('Invalid sampled-caption timeline')
    groups=[];active=None
    for row in rows:
        t=row['source_seconds_nominal']
        if not math.isfinite(t) or not 0<=t<duration:
            raise ValueError('Caption outside original video')
        labels=[]
        for line in row['lines']:
            x,y,w,h=line['bounding_box'];text=line['text'].strip()
            if not (.62<y<.925 and .12<x and x+w/2<.86 and w<.8 and h>=.025):continue
            if not 1<=len(text)<=20 or re.search(r'挑战|day|Day|评论|总结|bili|圣杯|完整演示|逐个解析',text):continue
            if re.fullmatch(r'[\u4e00-\u9fffA-Za-z0-9~～/（）() 、]+',text) is None:continue
            labels.append((h,line['confidence'],text))
        label=max(labels)[2] if labels else None
        if label is None:continue
        if active and active['label_candidate']==label and t-active['observed_times'][-1]<=1.6*interval:
            active['observed_times'].append(t)
            active['evidence'].append({'source_seconds':t,'image':row['image'],'image_sha256':row['image_sha256']})
        else:
            active={'label_candidate':label,'observed_times':[t],
                    'evidence':[{'source_seconds':t,'image':row['image'],'image_sha256':row['image_sha256']}],
                    'human_approved':False,'training_ready':False,'boundary_status':'sparse_caption_window'}
            groups.append(active)
    result=[]
    for group in groups:
        if len(group['observed_times'])<2:continue
        group.update(start_seconds=max(0,group['observed_times'][0]-interval/2),
                     end_seconds=min(duration,group['observed_times'][-1]+interval/2))
        result.append(group)
    return result


def reference_hand_flags(left,right,left_detected,right_detected,width,height):
    arrays=[np.asarray(left),np.asarray(right)]
    if any(a.shape!=(21,3) for a in arrays) or any(type(v) not in (bool,np.bool_) for v in (left_detected,right_detected)) or width<=0 or height<=0:
        raise ValueError('Invalid reference hand contract')
    result={'reason':'observation_screen_only','handedness_verified':False,'training_ready':False}
    for side,points,detected in zip(('left','right'),arrays,(left_detected,right_detected)):
        eligible=False;palm=None;reason='missing_observation'
        if detected:
            if np.isfinite(points).all() and (points[:,:2]>=0).all() and (points[:,:2]<=1).all():
                xy=points[:,:2]*[width,height];palm=float(np.median(np.linalg.norm(xy[[5,9,13,17]]-xy[0],axis=1)))
                eligible=palm>=15.;reason='estimated_observation_candidate' if eligible else 'small_hand'
            else:reason='invalid_observation'
        result[side]={'detected':bool(detected),'eligible_for_2d_fit':eligible,'palm_pixels':palm,'reason':reason,'not_metric_3d':True}
    if all(result[s]['eligible_for_2d_fit'] for s in ('left','right')):
        a,b=(p[:,:2]*[width,height] for p in arrays);palm=min(result[s]['palm_pixels'] for s in ('left','right'))
        distances=np.linalg.norm(a-b,axis=1)
        if distances.mean()<=.25*palm and distances[0]<=.35*palm:
            result['reason']='overlapping_hand_observations'
            for side in ('left','right'):result[side].update(eligible_for_2d_fit=False,reason='overlapping_hand_observations')
    return result


def build(args):
    manifest=json.loads(args.manifest.read_text());root=Path(manifest['source_root']).resolve();sources={r['source_id']:r for r in manifest['sources']}
    rows=[json.loads(x) for x in args.annotations.read_text().splitlines() if x.strip()]
    if not rows:
        raise ValueError('Reference plan must contain annotations')
    out=args.output.resolve()
    if out.exists() or out==root or root in out.parents or out in root.parents:
        raise ValueError('Choose a new output separate from original sources')
    ids=set();checked=set();clean=[]
    for row in rows:
        if row['source_id'] not in sources:raise ValueError('Unknown tutorial source')
        source=sources[row['source_id']];value=validate_annotation(row,source['duration_seconds'])
        if value['annotation_id'] in ids:raise ValueError('Duplicate annotation ID')
        ids.add(value['annotation_id'])
        path=(root/source['relative_path']).resolve()
        if root not in path.parents or not path.is_file() or source.get('authorization_status')!='user_reported':
            raise ValueError('Missing/unauthorized tutorial source')
        if value['source_id'] not in checked:
            if data.sha256_file(path)!=source['sha256']:raise ValueError('Original source hash changed')
            checked.add(value['source_id'])
        clean.append((value,source,path))
    out.mkdir(parents=True);prepared=[]
    for row,source,path in clean:
        folder=out/'samples'/row['annotation_id'];folder.mkdir(parents=True)
        duration=row['end_seconds']-row['start_seconds']
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n','-ss',str(row['start_seconds']),'-i',str(path),'-t',str(duration),'-an','-vf','fps=25,scale=960:960:force_original_aspect_ratio=decrease','-c:v','libx264','-crf','20','-preset','veryfast','-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(folder/'clip.mp4')],check=True,timeout=180)
        quality=data.landmarks(folder/'clip.mp4',folder,row['start_seconds'])
        frames=quality['frames'];width=quality['width'];height=quality['height']
        with np.load(folder/'landmarks.npz',allow_pickle=False) as a:
            data.validate_landmark_arrays(a,frames)
            flags=[reference_hand_flags(a['left_hand_image'][i],a['right_hand_image'][i],a['left_hand_image_detected'][i],a['right_hand_image_detected'][i],width,height) for i in range(frames)]
            # All stored points and masks remain the actual extractor output, including NaN.
        (folder/'reference-flags.jsonl').write_text(''.join(json.dumps({'frame_1based':i+1,**r})+'\n' for i,r in enumerate(flags)))
        row.update(source_sha256=source['sha256'],frames=frames,fps=25.,width=width,height=height,
                   artifacts={name:str((folder/name).relative_to(out)) for name in ('clip.mp4','overlay.mp4','landmarks.npz','quality.json','reference-flags.jsonl')},
                   reference_purpose='2D estimated hand-point/crop reference for later independent fitting; not SMPL-X/MANO targets',
                   usable_hand_observation_frames={s:sum(r[s]['eligible_for_2d_fit'] for r in flags) for s in ('left','right')})
        data.write_json(folder/'annotation.json',row);prepared.append(row)
        print(json.dumps({'annotation_id':row['annotation_id'],'label':row.get('label'),'frames':frames,'usable_2d_observation_frames':row['usable_hand_observation_frames']},ensure_ascii=False),flush=True)
    (out/'references.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in prepared))
    report={'schema':'signbridge-tutorial-hand-reference-pack-v1','samples':len(prepared),'frames':sum(r['frames'] for r in prepared),
            'manifest_sha256':data.sha256_file(args.manifest),'annotation_input_sha256':data.sha256_file(args.annotations),'tool_sha256':data.sha256_file(__file__),
            'training_ready':False,'human_approved':False,'smplx_parameters_created':False,'source_files_modified':False,
            'limitations':['Assistant annotations describe the visible tutorial, not expert-certified sign-language labels.','Mirror and anatomical hand identity remain unknown.','MediaPipe 2D points are estimates, not metric 3D or hand rotation parameters.','Low-confidence/missing/overlapping hand observations are excluded; no zero filling or interpolation.']}
    data.write_json(out/'report.json',report)
    (out/'SHA256SUMS').write_text(''.join(data.sha256_file(p)+'  '+str(p.relative_to(out))+'\n' for p in sorted(out.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
    return out/'report.json'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('manifest','annotations','output'):p.add_argument('--'+key,type=Path,required=True)
    print(build(p.parse_args()))


if __name__=='__main__':main()
