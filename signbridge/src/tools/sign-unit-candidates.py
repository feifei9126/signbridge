"""Repackage existing tutorial windows as unapproved 2D evidence, not aligned 3D words."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np

FOCUS = ['你好','谢谢','不客气','没关系','再见','明天见','来','去','吃','喝','听','说','现在','今天','昨天','明天','早上好','晚上好','我很好','你好吗']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def activity_windows(xy, eligible, fps):
    xy=np.asarray(xy);eligible=np.asarray(eligible)
    if xy.ndim!=3 or xy.shape[1:]!=(21,2) or eligible.shape!=(len(xy),) or eligible.dtype!=bool or not np.isfinite(fps) or fps<=0:
        raise ValueError('Invalid observation shapes or timebase')
    if not np.isfinite(xy[eligible]).all():raise ValueError('Eligible observation contains nonfinite values')
    runs=[];start=None
    for i,ok in enumerate(list(eligible)+[False]):
        if ok and start is None:start=i
        elif not ok and start is not None:
            if i-start>=3:runs.append((start,i))
            start=None
    candidates=[]
    for start,end in runs:
        speed=np.median(np.linalg.norm(np.diff(xy[start:end],axis=0),axis=-1),axis=1)*fps
        if not len(speed) or float(speed.max())<1e-6:continue
        peak=int(speed.argmax())+start+1
        lo=max(start,peak-round(fps*.35));hi=min(end,peak+round(fps*.35)+1)
        candidates.append({'start_frame_1based':lo+1,'end_frame_1based':hi,
                           'peak_frame_1based':peak+1,'peak_normalized_speed_per_second':float(speed.max()),
                           'boundary_status':'observation_activity_only_not_word_boundary'})
    return sorted(candidates,key=lambda x:-x['peak_normalized_speed_per_second'])[:3]


def candidate_record(row, frames, fps, windows, missing):
    return {'schema':'signbridge-motion-unit-candidate-v1','id':row['annotation_id'],
            'proposed_text':row['label'],'category':row['category'],'sample_type':row['sample_type'],
            'source_id':row['source_id'],'source_sha256':row['source_sha256'],
            'source_window_seconds':row['source_window_seconds'],'source_absolute_path':row['source_absolute_path'],
            'reference_frames':frames,'reference_fps':fps,'activity_window_proposals':windows,
            'missing_or_excluded_observation_frames':missing,'hand_shape_note':row.get('hand_shape_note',''),
            'time_contract':row.get('time_contract','nominal reference time, original PTS not measured'),
            'word_spans':[],'text_verified':'','word_boundaries_verified':False,
            'native_3d_available':False,'anatomical_handedness':'unverified','mirror_status':'unknown',
            'signer_id':None,'split':'unassigned','human_approved':False,'training_ready':False,'model_training_ready':False,
            'limitations':['Tutorial statement and coarse window retained; not independent CSL approval.',
                           'Activity peaks can be instructional transitions; never treat them as verified word phases.',
                           'Extractor left/right are slots, not verified anatomical sides. Missing/excluded observations remain missing.']}


def contained(root,path):
    full=(root/path).resolve()
    if not full.is_relative_to(root) or not full.is_file() or full.is_symlink():raise ValueError('Artifact escapes reference root')
    return full


def run(tutorial, output):
    if output.exists():raise FileExistsError('Choose a new candidate output directory')
    tutorial=tutorial.resolve();index=tutorial/'fitting-reference-index.jsonl'
    rows=[json.loads(x) for x in index.read_text().splitlines() if x.strip()]
    selected=[next(r for r in rows if r['label']==text and r['category']=='word') for text in FOCUS]
    inputs={str(index):sha(index),str(Path(__file__).resolve()):sha(Path(__file__))};prepared=[]
    ffmpeg=shutil.which('ffmpeg')
    for row in selected:
        artifacts={}
        for name in ['clip.mp4','keyframes.jpg','observations-2d.npz','annotation.json','quality.json']:
            info=row['artifacts'][name];path=contained(tutorial,info['relative_path'])
            if sha(path)!=info['sha256']:raise ValueError('Artifact digest mismatch: '+str(path))
            inputs[str(path)]=info['sha256'];artifacts[name]=path
        original=Path(row['source_absolute_path'])
        if not original.is_file() or sha(original)!=row['source_sha256']:raise ValueError('Original video missing or digest differs')
        inputs[str(original)]=row['source_sha256']
        with np.load(artifacts['observations-2d.npz'],allow_pickle=False) as archive:
            frames=len(archive['frame_1based']);fps=float(row['reference_fps'])
            if not np.array_equal(archive['frame_1based'],np.arange(1,frames+1)):raise ValueError('Observation frame identity differs')
            windows={};missing={}
            for side in ('left','right'):
                mask=archive[side+'_eligible_for_2d_fit'];xy=archive[side+'_xy_normalized']
                windows[side]=activity_windows(xy,mask,fps)
                missing[side]=(np.flatnonzero(~mask)+1).tolist()
        if frames!=row['frames']:raise ValueError('Frame count differs')
        decoded=0;capture=cv2.VideoCapture(str(artifacts['clip.mp4']))
        try:
            while True:
                ok,frame=capture.read()
                if not ok:break
                if frame is None or not frame.size:raise ValueError('Empty decoded frame')
                decoded+=1
        finally:capture.release()
        if decoded!=frames:raise ValueError('Full clip decode count differs')
        if ffmpeg:
            proc=subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(artifacts['clip.mp4']),'-f','null','-'],capture_output=True,timeout=90)
            if proc.returncode or proc.stderr:raise ValueError('ffmpeg full decode failed')
        record=candidate_record(row,frames,fps,windows,missing)
        record['decode']={'frames':decoded,'opencv_passed':True,'ffmpeg_passed':bool(ffmpeg)}
        record['original_source_video_rehashed']=True
        start, end = row['source_window_seconds']
        for side in ('left', 'right'):
            for window in windows[side]:
                window['source_start_seconds_nominal'] = start + (window['start_frame_1based'] - 1) / fps
                window['source_end_seconds_nominal'] = start + window['end_frame_1based'] / fps
                window['source_pts_measured'] = False
        record['source_split_group']=row.get('split_group')
        record['artifacts']={name:f'assets/{row["annotation_id"]}/{name}' for name in artifacts}
        prepared.append((record,artifacts))
    output.mkdir();records=[];cards=[]
    for record,artifacts in prepared:
        target=output/'assets'/record['id'];target.mkdir(parents=True)
        for name,path in artifacts.items():shutil.copyfile(path,target/name)
        records.append(record)
        escaped=html.escape(record['proposed_text'])
        suggestions=html.escape(json.dumps(record['activity_window_proposals'],ensure_ascii=False))
        cards.append(f'<article><h2>{escaped}</h2><p>原片粗窗口 {record["source_window_seconds"]} 秒；手型／方向／边界待核验。当前仅2D观测，无可播放3D词单元。</p><video controls preload="metadata" src="{record["artifacts"]["clip.mp4"]}"></video><img loading="lazy" src="{record["artifacts"]["keyframes.jpg"]}" alt="{escaped}原有采样联系表"><p>{html.escape(record["hand_shape_note"])}</p><details><summary>观测活动建议（不是词界）与缺失</summary><pre>{suggestions}</pre><p>左槽缺失／排除 {len(record["missing_or_excluded_observation_frames"]["left"])} 帧；右槽 {len(record["missing_or_excluded_observation_frames"]["right"])} 帧</p></details></article>')
    report={'schema':'signbridge-unit-candidate-review-v1','created_at':datetime.now(timezone.utc).isoformat(),'candidates':records,'count':len(records),'inputs':inputs,
            'verified_word_units':0,'model_training_ready':False,'training_started':False,'original_parameters_changed':False}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (output/'candidates.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    (output/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>旧素材单元候选</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:30px auto;padding:0 18px;background:#f6f5f0;color:#17332d}article{background:white;padding:20px;border:1px solid #c9d5ce;margin:20px 0}video{max-width:360px;width:100%;max-height:430px}img{display:block;width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>20个旧教学词／短语候选</h1><p>可复用的候选证据包。所有词界、含义、镜像、手别、手语者与非手部表达仍待人工核验；不进入正式词库或训练。完整视频已解码，原片摘要重新验证。活动区间是观测线索，不是准确词界。</p>'+''.join(cards)+'</html>')
    for path,digest in inputs.items():
        if sha(path)!=digest:raise ValueError('Input changed during candidate extraction')
    (output/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(output)}\n' for p in sorted(output.rglob('*')) if p.is_file()))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tutorial',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=run(args.tutorial,args.output);print(json.dumps({'candidates':out['count'],'verified_word_units':0,'output':str(args.output)}))
