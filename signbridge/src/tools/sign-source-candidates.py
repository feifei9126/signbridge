"""Local new-source screening and OCR candidate discovery; never approves sign labels or splits."""

import argparse
import csv
import html
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path

spec=importlib.util.spec_from_file_location('candidate_data',Path(__file__).with_name('sign-data.py'))
data=importlib.util.module_from_spec(spec);spec.loader.exec_module(data)


def safe_id(value):
    if not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value) is None:
        raise ValueError('Unsafe source or candidate ID')
    return value


def normalized_text(text):
    return re.sub(r'[\W_]+','',str(text),flags=re.UNICODE)


def section_and_text(lines):
    texts=[str(x.get('text','')).strip() for x in lines if str(x.get('text','')).strip()]
    combined=' '.join(texts)
    if re.search(r'单[人入]演示',combined):
        section='single_person_demo'
    elif any(x in combined for x in ('词学习','词汇学习','句型学习','跟我做')):
        section='vocabulary_or_instruction'
    else:
        section='dialogue_or_other'
    candidates=[]
    for row in lines:
        text=str(row.get('text','')).strip()
        compact=normalized_text(text)
        if not compact or not re.search(r'[\u4e00-\u9fff]',text):continue
        if re.search(r'单[人入]演示|对话示范|词学习|词汇学习|句型学习|跟我做|中国手语|复旦音像|bilibili|倪兰|第.{0,3}课',text,re.I):continue
        box=row.get('bounding_box')
        if section=='single_person_demo' and box is not None and box[1]>.30:
            continue
        if len(compact)>120:continue
        candidates.append((row,text))
    # Vision boxes have bottom-left origin; preserve multiline captions in visual top-to-bottom order.
    candidates.sort(key=lambda x:-float(x[0].get('bounding_box',[0,0,0,0])[1]))
    text=''.join(x[1] for x in candidates)
    return section,text


def caption_spans(rows,source_duration,sampling_interval):
    if not math.isfinite(source_duration) or not math.isfinite(sampling_interval) or \
       not 0<sampling_interval<=10 or not source_duration>0:raise ValueError('Invalid sample timeline')
    result=[];current=None;previous_time=None
    for row in rows:
        t=float(row['source_seconds'])
        if not 0<=t<source_duration or previous_time is not None and t<=previous_time:
            raise ValueError('Unordered/out-of-range OCR sample times')
        section,text=section_and_text(row.get('lines',[]))
        key=(section,normalized_text(text))
        if not text:
            current=None;previous_time=t;continue
        if current is None or current['_key']!=key or t-current['observed_times'][-1]>sampling_interval*1.01:
            current={'_key':key,'section':section,'text_candidate':text,'observed_times':[t],
                'start_seconds':max(0.,t-sampling_interval/2),
                'end_seconds':min(source_duration,t+sampling_interval/2),
                'semantics_approved':False,'boundaries_approved':False,'interpolated':False,
                'sampling_interval_seconds':sampling_interval}
            result.append(current)
        else:
            current['observed_times'].append(t);current['end_seconds']=min(source_duration,t+sampling_interval/2)
        previous_time=t
    for span in result:span.pop('_key')
    return result


def conservative_group(source):
    return 'unverified-textbook-family' if source['relative_path'].startswith('1/') else 'unverified-tutorial-family-'+source['source_id']


def candidate_record(source,segment,span):
    safe_id(segment);safe_id(source['source_id'])
    return {**span,'segment_id':segment,'source_id':source['source_id'],'source_sha256':source.get('sha256'),
        'language':'zh-CSL','text_verified':'','signer_id':'unconfirmed-'+source['source_id'],
        'split_group':conservative_group(source),'split':'unassigned','mirror_status':'unknown',
        'sample_type':'sentence_candidate' if span['section']=='single_person_demo' else 'word_or_instruction_unconfirmed',
        'semantics_status':'needs_review','boundaries_status':'needs_review','motion_review_status':'not_prepared',
        'independent_source_approved':False,'model_training_ready':False,'reviewer':'',
        'label_provenance':'sampled macOS Vision OCR; not verified signing meaning',
        'authorization_status':source.get('authorization_status')}


def text_overlap_links(rows):
    groups={}
    for row in rows:
        key=normalized_text(row['text_candidate'])
        if key:groups.setdefault(key,[]).append(row)
    return [{'text_normalized':key,'segments':[r['segment_id'] for r in values],
             'source_ids':sorted({r['source_id'] for r in values}),
             'signing_content_duplicate_confirmed':False,'status':'needs_content_review'}
             for key,values in groups.items() if len({r['source_id'] for r in values})>1]


def select_initial_candidates(rows,per_source=2):
    if not isinstance(per_source,int) or not 1<=per_source<=10:
        raise ValueError('Initial clip limit must be between 1 and 10 per source')
    by_source={}
    for row in rows:
        text=normalized_text(row['text_candidate'])
        duration=float(row['end_seconds'])-float(row['start_seconds'])
        if row.get('section')!='single_person_demo' or len(row.get('observed_times',[]))<2 or \
           not 4<=duration<=12 or not 4<=len(text)<=50:
            continue
        if row['text_candidate'].rstrip().endswith(('，',',','、','：',':','…','...')):
            continue
        if any(row.get(field)=='approved' for field in ('semantics_status','boundaries_status')) or \
           row.get('text_verified') or row.get('split')!='unassigned' or row.get('model_training_ready') is not False:
            raise ValueError('Screen candidates must retain unverified semantics and splits')
        by_source.setdefault(row['source_id'],[]).append(row)
    selected=[]
    for source,candidates in by_source.items():
        ordered=sorted(candidates,key=lambda r:(-len(r['observed_times']),r['start_seconds'],r['segment_id']))
        chosen=[];seen=set()
        for row in ordered:
            key=normalized_text(row['text_candidate'])
            if key in seen or any(row['start_seconds']<r['end_seconds'] and r['start_seconds']<row['end_seconds'] for r in chosen):
                continue
            chosen.append(row);seen.add(key)
            if len(chosen)>=per_source:break
        selected.extend(sorted(chosen,key=lambda r:r['start_seconds']))
    return selected


def quality_review_row(row,quality):
    if row.get('text_verified') or row.get('model_training_ready') is not False or row.get('label_ready') is not False or \
       row.get('semantics_status')!='needs_review' or row.get('boundaries_status')!='needs_review' or \
       row.get('mirror_status')!='unknown' or row.get('split')!='unassigned':
        raise ValueError('New candidates must preserve unverified labels, mirror and splits')
    frames=row['frames']
    if not isinstance(frames,int) or frames<=0:raise ValueError('Invalid prepared frame count')
    counts=row['hand_detection_frames']
    flags=[]
    coverage={}
    for side in ('left','right'):
        count=counts[side+'_hand_image']
        if not isinstance(count,int) or not 0<=count<=frames:raise ValueError('Invalid hand detection count')
        coverage[side]=count/frames
        if count/frames<.2:flags.append(side+'_hand_low_observation_coverage')
    if quality['detections']['pose_image']['detected_frames']/frames<.9:
        flags.append('body_observation_missing')
    if quality['detections']['face_image']['detected_frames']/frames<.9:
        flags.append('face_observation_missing')
    return {'hand_presence_fractions':coverage,'review_flags':flags,'frames':frames,
            'sign_accuracy_evaluated':False,'training_ready':False,
            'presence_note':'Missing points may be caused by out-of-frame hands, occlusion or detector errors; presence is not accuracy'}


def group_proposal(sources,existing_tasks):
    groups={}
    for source in sources:
        groups.setdefault(conservative_group(source),[]).append(source['source_id'])
    return {'schema':'signbridge-conservative-source-family-proposal-v1',
        'proposed_groups':[{'group_id':group,'source_ids':ids,'actual_person_identity_confirmed':False,
                           'holdout_approved':False} for group,ids in groups.items()],
        'existing_assignments':[{k:r.get(k) for k in ('segment_id','source_id','split_group','signer_id','split')}
                                 for r in existing_tasks],
        'production_splits_modified':False,'actual_person_disjointness_verified':False,
        'basis':'Local collection path and course-family provenance; no facial matching or inferred person identity',
        'limitations':['Same collection courses conservatively stay together until independent person/content annotations exist.',
                       'Tutorial files are possible additional groups, not automatically independent tests.']}


def sha(path):return data.sha256_file(path)


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def source_file(manifest,record):
    root=Path(manifest['source_root']).resolve();relative=Path(record['relative_path']);path=(root/relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or root not in path.parents or not path.is_file():
        raise ValueError('Missing/unsafe original video path')
    if record.get('authorization_status')!='user_reported':raise ValueError('No existing user authorization record')
    if sha(path)!=record['sha256']:raise ValueError('Original video digest differs from scanned inventory')
    return path


def extract(args):
    manifest_path=Path(args.manifest).resolve();tasks_path=Path(args.exposed_tasks).resolve();out=Path(args.output).resolve()
    manifest=json.loads(manifest_path.read_text());root=Path(manifest['source_root']).resolve()
    if out.exists() or out==root or root in out.parents or out in root.parents:
        raise ValueError('Output must be new and separate from original videos')
    if not 0<args.fps<=1:raise ValueError('Screening FPS must be between 0 and 1')
    tasks=[json.loads(x) for x in tasks_path.read_text().splitlines() if x.strip()]
    exposed={r['source_id'] for r in tasks};exposed_hashes={r['source_sha256'] for r in tasks}
    sources=[s for s in manifest['sources'] if s['source_id'] not in exposed and s['sha256'] not in exposed_hashes]
    for source in sources:safe_id(source['source_id'])
    if len({s['source_id'] for s in sources})!=len(sources):raise ValueError('Duplicate source IDs')
    checked={s['source_id']:source_file(manifest,s) for s in sources}
    swift=Path(__file__).with_name('sign-text-ocr.swift')
    out.mkdir(parents=True)
    report={'schema':'signbridge-new-source-screen-v1','status':'running','training_ready':False,
            'sources':[],'source_manifest_sha256':sha(manifest_path),'exposed_tasks_sha256':sha(tasks_path),
            'ocr_tool_sha256':sha(swift),'sampling_fps':args.fps,'source_files_modified':False,
            'actual_person_disjointness_verified':False,'production_splits_modified':False}
    write_json(out/'screen.json',report)
    for source in sources:
        folder=out/source['source_id'];frames=folder/'frames';frames.mkdir(parents=True)
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(checked[source['source_id']]),
            '-vf','fps=%s,scale=960:-2'%args.fps,'-q:v','3','-threads','2',str(frames/'%06d.jpg')],check=True,timeout=300)
        images=sorted(frames.glob('*.jpg'))
        if not images:raise ValueError('No sampled image frames')
        rows=[]
        for start in range(0,len(images),100):
            batch=images[start:start+100]
            result=subprocess.run(['swift',str(swift),*map(str,batch)],capture_output=True,check=True,timeout=180)
            values=[json.loads(line) for line in result.stdout.decode().splitlines() if line.strip()]
            if len(values)!=len(batch):raise ValueError('OCR output frame count differs')
            for i,value in enumerate(values,start):
                timestamp=i/args.fps
                if timestamp>=source['duration_seconds']:continue
                rows.append({'source_seconds':timestamp,'source_time_approx_seconds':timestamp,
                             'sampling_interval_seconds':1/args.fps,'image':str(images[i].relative_to(out)),
                             'image_sha256':sha(images[i]),'lines':value['lines'],'semantics_approved':False})
        spans=caption_spans(rows,source['duration_seconds'],1/args.fps)
        (folder/'ocr.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        write_json(folder/'caption-spans.json',spans)
        row={'source_id':source['source_id'],'source_sha256':source['sha256'],
             'relative_path':source['relative_path'],'duration_seconds':source['duration_seconds'],
             'screening_images':len(rows),'caption_spans':len(spans),
             'single_person_demo_caption_spans':sum(s['section']=='single_person_demo' for s in spans),
             'authorization_status':source['authorization_status'],'split_group':conservative_group(source),
             'training_ready':False}
        report['sources'].append(row);write_json(out/'screen.json',report)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    for s in sources:
        if sha(checked[s['source_id']])!=s['sha256']:raise ValueError('Video changed during screening')
    report.update(status='screened_new_sources_pending_candidate_review',
        limitations=['Sparse OCR samples are nominal timestamps, not labelled signing boundaries.',
                     'Single-person marker is video text, not automatic person identity/count proof.',
                     'Caption and word instruction are not automatically verified sign semantics.',
                     'Textbook-family groups are conservative; actual person/content independence needs separate evidence.'])
    write_json(out/'screen.json',report)
    summarize(argparse.Namespace(manifest=manifest_path,screen=out,output=out/'candidate-index'))
    make_manifest(out)
    return out/'screen.json'


def summarize(args):
    manifest=json.loads(Path(args.manifest).read_text());screen=Path(args.screen).resolve();out=Path(args.output).resolve()
    if out.exists() or out==screen or out in screen.parents:raise ValueError('Candidate index output must be new')
    sources={s['source_id']:s for s in manifest['sources']}
    if len(sources)!=len(manifest['sources']):raise ValueError('Duplicate source IDs')
    screened=json.loads((screen/'screen.json').read_text())
    candidates=[]
    for row in screened['sources']:
        safe_id(row['source_id'])
        if row['source_id'] not in sources:raise ValueError('Unknown screening source')
        source=sources[row['source_id']]
        spans=json.loads((screen/row['source_id']/'caption-spans.json').read_text())
        for i,span in enumerate(spans,1):
            segment='new-'+row['source_id'].removeprefix('source-')+'-%04d'%i
            candidates.append(candidate_record(source,segment,span))
    out.mkdir(parents=True)
    (out/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in candidates))
    write_json(out/'text-overlap-review.json',text_overlap_links(candidates))
    columns=['segment_id','source_id','start_seconds','end_seconds','text_candidate','text_verified','sample_type',
             'language','signer_id','split_group','split','semantics_status','boundaries_status','mirror_status','reviewer']
    with (out/'annotation-template.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        writer.writerows({k:r.get(k,'') for k in columns} for r in candidates)
    write_json(out/'summary.json',{'schema':'signbridge-ocr-candidate-index-v1',
        'candidates':len(candidates),'sentence_candidate_spans':sum(r['section']=='single_person_demo' for r in candidates),
        'training_ready':False,'human_verified_labels':0,'source_screen_sha256':sha(screen/'screen.json')})
    return out/'summary.json'


def prepare_candidates(args):
    manifest_path=Path(args.manifest).resolve();index=Path(args.candidate_index).resolve();out=Path(args.output).resolve()
    manifest=json.loads(manifest_path.read_text());root=Path(manifest['source_root']).resolve()
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (root,index)):
        raise ValueError('Prepared candidate output must be new and separate')
    candidate_path=index/'candidates.jsonl'
    rows=[json.loads(x) for x in candidate_path.read_text().splitlines() if x.strip()]
    source_index={s['source_id']:s for s in manifest['sources']}
    chosen=select_initial_candidates(rows,args.per_source)
    if not chosen:raise ValueError('No suitable single-demo caption candidates; no labels invented')
    for row in chosen:
        source=source_index[row['source_id']]
        if source['sha256']!=row['source_sha256'] or not 0<=row['start_seconds']<row['end_seconds']<=source['duration_seconds']:
            raise ValueError('Candidate source digest or nominal boundaries differ')
        source_file(manifest,source)
    # Plan files are adjacent to the dataset, so the existing preparer can require a fresh output root.
    plan=out.parent/(out.name+'-plan')
    if plan.exists():raise ValueError('Preparation plan already exists; choose a new output path')
    plan.mkdir(parents=True)
    csv_path=plan/'segments.csv'
    segments=[]
    for row in chosen:
        converted={k:row.get(k,'') for k in data.SEGMENT_FIELDS}
        converted.update(sample_type='sentence',text_verified='',semantics_status='needs_review',
            boundaries_status='needs_review',mirror_status='unknown',split='unassigned',reviewer='',
            notes='Automatic caption-screen candidate only. Sparse nominal bounds require full-video verification; no person identity or sign meaning approved.')
        segments.append(converted)
    with csv_path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=data.SEGMENT_FIELDS);writer.writeheader();writer.writerows(segments)
    write_json(plan/'selection.json',{'schema':'signbridge-initial-new-source-selection-v1',
        'candidate_index_sha256':sha(candidate_path),'source_manifest_sha256':sha(manifest_path),
        'selected_ids':[r['segment_id'] for r in chosen],'selected_source_ids':sorted({r['source_id'] for r in chosen}),
        'selection':'at least two consecutive OCR samples, 4-12 nominal seconds, <=%d/source, no caption continuation suffix'%args.per_source,
        'training_ready':False,'semantics_approved':False,'boundaries_approved':False,'fps':25,'max_side':args.max_side})
    data.prepare(argparse.Namespace(manifest=manifest_path,segments=csv_path,output=out,fps=25,max_side=args.max_side))
    prepared=[json.loads(x) for x in (out/'prepared.jsonl').read_text().splitlines() if x.strip()]
    if [r['segment_id'] for r in prepared]!=[r['segment_id'] for r in chosen] or \
       any(r.get('label_ready') is not False or r.get('model_training_ready') is not False for r in prepared):
        raise ValueError('Prepared candidates gained approval or changed frame scope')
    write_json(out/'candidate-provenance.json',{'schema':'signbridge-new-source-prepared-v1',
        'samples':len(prepared),'frames':sum(r['frames'] for r in prepared),'sources':len({r['source_id'] for r in prepared}),
        'selection_plan_sha256':sha(plan/'selection.json'),'candidate_index_sha256':sha(candidate_path),
        'source_manifest_sha256':sha(manifest_path),'preparation_tool_sha256':sha(Path(__file__)),
        'training_ready':False,'production_splits_modified':False,'source_files_modified':False,
        'person_identity_verified':False,'new_verified_sign_labels':0})
    make_manifest(out);make_manifest(plan)
    return out/'candidate-provenance.json'


def make_manifest(root):
    paths=sorted(p for p in Path(root).rglob('*') if p.is_file() and p.name!='SHA256SUMS')
    (Path(root)/'SHA256SUMS').write_text(''.join(sha(p)+'  '+str(p.relative_to(root))+'\n' for p in paths))


def build_review(args):
    manifest_path=Path(args.manifest).resolve();screen=Path(args.screen).resolve();out=Path(args.output).resolve()
    prepared=Path(args.prepared).resolve();tutorials=Path(args.tutorials).resolve();exposed_tasks=Path(args.exposed_tasks).resolve()
    manifest=json.loads(manifest_path.read_text());original_root=Path(manifest['source_root']).resolve()
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (original_root,screen,prepared,tutorials)):
        raise ValueError('Review output must be new and separate')
    sources={s['source_id']:s for s in manifest['sources']}
    if len(sources)!=len(manifest['sources']):raise ValueError('Duplicate source IDs')
    tasks=[json.loads(x) for x in exposed_tasks.read_text().splitlines() if x.strip()]
    screening=json.loads((screen/'screen.json').read_text())
    if screening.get('status')!='screened_new_sources_pending_candidate_review' or \
       screening.get('source_manifest_sha256')!=sha(manifest_path) or screening.get('exposed_tasks_sha256')!=sha(exposed_tasks):
        raise ValueError('Screening inventory/exposure linkage differs')
    if screening['ocr_tool_sha256']!=sha(Path(__file__).with_name('sign-text-ocr.swift')):
        raise ValueError('OCR tool differs from screened provenance')
    exposed={r['source_id'] for r in tasks}
    checked={}
    if len({r['source_id'] for r in screening['sources']})!=len(screening['sources']):
        raise ValueError('Duplicate screened source IDs')
    for record in screening['sources']:
        sid=safe_id(record['source_id'])
        if sid in exposed or record['source_sha256']!=sources[sid]['sha256']:
            raise ValueError('Selected new source is exposed or changed')
        checked[sid]=source_file(manifest,sources[sid])
        observations=[json.loads(x) for x in (screen/sid/'ocr.jsonl').read_text().splitlines() if x.strip()]
        if len(observations)!=record['screening_images']:
            raise ValueError('Screening image count differs')
        for observation in observations:
            relative=Path(observation['image']);path=(screen/relative).resolve()
            if relative.is_absolute() or screen not in path.parents or sha(path)!=observation['image_sha256']:
                raise ValueError('Screening image path/digest differs')
    records=[]
    for kind,root in (('sentence',prepared),('word_or_instruction',tutorials)):
        verification=json.loads((root/'verification.json').read_text())
        rows=[json.loads(x) for x in (root/'prepared.jsonl').read_text().splitlines() if x.strip()]
        if len(rows)!=verification['checked_samples'] or sum(r['frames'] for r in rows)!=verification['total_frames']:
            raise ValueError('Prepared dataset incomplete')
        verify_by_id={r['segment_id']:r for r in verification['results']}
        if len(verify_by_id)!=len(rows) or set(verify_by_id)!={r['segment_id'] for r in rows}:
            raise ValueError('Prepared verification frame identities differ')
        for row in rows:
            safe_id(row['segment_id'])
            if row['source_id'] not in checked or row['source_sha256']!=sources[row['source_id']]['sha256']:
                raise ValueError('Prepared source identity/digest differs')
            artifacts={}
            for name,relative in row['artifacts'].items():
                relative=Path(relative);path=(root/relative).resolve()
                if relative.is_absolute() or root not in path.parents or not path.is_file():
                    raise ValueError('Prepared media/array path unsafe')
                artifacts[name]={'file':str(path),'sha256':sha(path)}
            quality=json.loads(Path(artifacts['quality.json']['file']).read_text())
            audited=verify_by_id[row['segment_id']]
            if audited.get('decode_shape_and_mask')!='passed' or audited.get('model_training_ready') is not False or \
               audited.get('frames')!=row['frames'] or quality.get('frames')!=row['frames']:
                raise ValueError('Prepared video/array verification not passed')
            review=quality_review_row(row,quality)
            import numpy as np
            with np.load(artifacts['landmarks.npz']['file'],allow_pickle=False) as arrays:
                data.validate_landmark_arrays(arrays,row['frames'])
                for side in ('left','right'):
                    count=int(arrays[side+'_hand_image_detected'].sum())
                    if count!=row['hand_detection_frames'][side+'_hand_image'] or \
                       count!=verify_by_id[row['segment_id']]['hand_detected_frames'][side+'_hand_image']:
                        raise ValueError('NPZ mask and reported hand coverage differ')
            records.append({'segment_id':row['segment_id'],'source_id':row['source_id'],'kind':kind,
                'start_seconds':row['start_seconds'],'end_seconds':row['end_seconds'],'text_candidate':row['text_candidate'],
                'text_verified':'','signer_id':row['signer_id'],'split_group':row['split_group'],'split':'unassigned',
                'mirror_status':'unknown','semantics_status':'needs_review','boundaries_status':'needs_review',
                'sample_type':row['sample_type'],'language':row['language'],'reviewer':'',
                'authorization_status':row['authorization_status'],'model_training_ready':False,
                'label_ready':False,'artifacts':artifacts,**review})
    if len({r['segment_id'] for r in records})!=len(records):raise ValueError('Duplicate review sample IDs')
    out.mkdir(parents=True)
    write_json(out/'source-group-proposal.json',group_proposal(manifest['sources'],tasks))
    write_json(out/'text-overlap-review.json',text_overlap_links(records+[
        {'segment_id':r['segment_id'],'source_id':r['source_id'],'text_candidate':r.get('text_verified','')} for r in tasks]))
    (out/'samples.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    columns=[k for k in data.SEGMENT_FIELDS if k!='notes']+['review_flags']
    with (out/'annotation-review.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        writer.writerows({k:(';'.join(r['review_flags']) if k=='review_flags' else r.get(k,'')) for k in columns} for r in records)
    cards=[]
    for row in records:
        e=html.escape
        source=sources[row['source_id']]
        clip=Path(row['artifacts']['clip.mp4']['file'])
        overlay=Path(row['artifacts']['overlay.mp4']['file'])
        import os
        clip_link=e(os.path.relpath(clip,out),quote=True);overlay_link=e(os.path.relpath(overlay,out),quote=True)
        fractions=row['hand_presence_fractions']
        cards.append('<section data-source="'+e(row['source_id'])+'" data-kind="'+e(row['kind'])+'"><h2>'+e(row['text_candidate'])+'</h2>'+
            '<p>'+e(row['segment_id'])+' · '+e(source['relative_path'])+'</p><p>原视频候选区间 '+str(row['start_seconds'])+'–'+str(row['end_seconds'])+
            ' 秒 · '+str(row['frames'])+' 帧 · '+('整句示范候选' if row['kind']=='sentence' else '词汇／分步教学候选')+'</p>'+
            '<p>手部观测返回：左 '+format(fractions['left'],'.0%')+'，右 '+format(fractions['right'],'.0%')+
            '；检测率不是准确率。'+e(' / '.join(row['review_flags']))+'</p><div class="pair"><div><h3>原片段</h3><video controls preload="none" src="'+clip_link+
            '"></video></div><div><h3>关键点与缺失复核</h3><video controls preload="none" src="'+overlay_link+
            '"></video></div></div><button type="button">同步播放／暂停</button><p>请核对完整表达、字幕错字、边界、镜像及遮挡；未填写的核验字段不会自动变为通过。</p></section>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SignBridge 新来源候选复核</title>
<style>body{font-family:system-ui,sans-serif;margin:30px auto;max-width:1280px;padding:0 24px;background:#f4f7fa;color:#193040;line-height:1.75}section,.summary{background:white;padding:22px;border:1px solid #dce5ec;border-radius:12px;margin:22px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}video{width:100%;background:#111}button,select{padding:9px 14px;margin:8px 0}a{color:#135d99}@media(max-width:700px){.pair{grid-template-columns:1fr}}h2{font-size:20px}</style>
<h1>新来源候选复核</h1><div class="summary"><p>候选释义、人物、镜像及完整边界待核对；素材授权沿用用户已有确认。没有新模型训练或自动质量批准。</p><p><a href="annotation-review.csv">下载核对表</a> · <a href="samples.jsonl">候选与来源摘要</a> · <a href="source-group-proposal.json">保守来源分组提案</a></p><label>筛选类别 <select id="kind"><option value="all">全部候选</option><option value="sentence">整句示范候选</option><option value="word_or_instruction">词汇／分步教学候选</option></select></label></div>'''+''.join(cards)+'''
<script>document.getElementById('kind').addEventListener('change',e=>{for(const s of document.querySelectorAll('section'))s.hidden=e.target.value!=='all'&&s.dataset.kind!==e.target.value;});for(const section of document.querySelectorAll('section')){const[a,b]=section.querySelectorAll('video');section.querySelector('button').addEventListener('click',async()=>{if(!a.paused||!b.paused){a.pause();b.pause();return;}b.currentTime=a.currentTime;await Promise.allSettled([a.play(),b.play()]);});}</script></html>'''
    (out/'review.html').write_text(page)
    summary={'schema':'signbridge-new-source-expansion-review-v1','status':'prepared_candidates_pending_human_review',
        'screened_sources':len(screening['sources']),'screening_images':sum(r['screening_images'] for r in screening['sources']),
        'raw_ocr_caption_spans':sum(r['caption_spans'] for r in screening['sources']),
        'single_demo_marker_spans':sum(r['single_person_demo_caption_spans'] for r in screening['sources']),
        'prepared_sentence_candidates':sum(r['kind']=='sentence' for r in records),
        'prepared_instruction_candidates':sum(r['kind']=='word_or_instruction' for r in records),
        'prepared_frames':sum(r['frames'] for r in records),'prepared_sources':len({r['source_id'] for r in records}),
        'low_hand_presence_samples':sum(bool(r['review_flags']) for r in records),
        'new_verified_sign_labels':0,'training_ready':False,'production_splits_modified':False,
        'original_source_files_modified':False,'gpu_inference_or_training_started':False,
        'source_manifest_sha256':sha(manifest_path),'exposed_tasks_sha256':sha(exposed_tasks),
        'source_screen_sha256':sha(screen/'screen.json'),'review_tool_sha256':sha(__file__),
        'prior_14_segments':'Already content-reviewed same-source examples remain separate; no new motion approval or reprocessing.',
        'pending':['Full signing boundaries and subtitle meaning','Mirror and actual signer metadata',
                   'Occluded/low-presence hands and nonmanual expression','Independent holdout qualification and duplicate signing content']}
    write_json(out/'summary.json',summary)
    make_manifest(out)
    return out/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);cmd=p.add_subparsers(dest='command',required=True)
    a=cmd.add_parser('screen');a.add_argument('--manifest',type=Path,required=True);a.add_argument('--exposed-tasks',type=Path,required=True)
    a.add_argument('--fps',type=float,default=.5);a.add_argument('--output',type=Path,required=True)
    a=cmd.add_parser('index');a.add_argument('--manifest',type=Path,required=True);a.add_argument('--screen',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a=cmd.add_parser('prepare-candidates');a.add_argument('--manifest',type=Path,required=True);a.add_argument('--candidate-index',type=Path,required=True)
    a.add_argument('--output',type=Path,required=True);a.add_argument('--per-source',type=int,default=3);a.add_argument('--max-side',type=int,default=960)
    a=cmd.add_parser('review')
    for key in ('manifest','screen','prepared','tutorials','exposed-tasks','output'):a.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args();action={'screen':extract,'index':summarize,'prepare-candidates':prepare_candidates,'review':build_review}[args.command];print(action(args))
if __name__=='__main__':main()
