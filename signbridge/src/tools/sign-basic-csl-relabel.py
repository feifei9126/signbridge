"""Bounded relabel/annotation helpers for the source-2 tutorial batch."""
import argparse, hashlib, json, math, re
from pathlib import Path
from statistics import median

SCHEMA='signbridge.basic-csl-relabel-v1'
FLAGS={'human_approved':False,'semantics_approved':False,'boundaries_approved':False,'text_verified':'','training_ready':False,'model_training_ready':False,'training_started':False}
BASIC_TARGETS=('我','你','我们','他们','地方','早上','上午','下午','晚上','中午')

def evidence_kind(text, heading, explicit):
    if explicit and text in heading.replace('“','').replace('”',''): return 'explicit_instruction_subunit'
    if text in heading: return 'context_only'
    return 'unresolved'

def validate_proposal(row,duration):
    if not isinstance(row,dict) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',row.get('id','')): raise ValueError('invalid id')
    if not isinstance(row.get('text'),str) or not row['text'].strip(): raise ValueError('invalid text')
    if type(row.get('start')) not in (int,float) or type(row.get('end')) not in (int,float) or not math.isfinite(row['start']) or not math.isfinite(row['end']) or not 0<=row['start']<row['end']<=duration: raise ValueError('invalid window')
    if row.get('human_approved') is not False: raise ValueError('automatic approval forbidden')
    for key,expected in FLAGS.items():
        if key in row and (row[key] is not False if expected is False else row[key]!=expected):raise ValueError('Unverified approval/readiness field: '+key)
    if not re.fullmatch(r'[0-9a-f]{64}',row.get('source_sha256','')) or not row.get('assistant_note'): raise ValueError('missing provenance')

def training_group(source_sha256,start,end):
    return source_sha256

def finite_summary(values):
    finite=sorted(float(x) for x in values if isinstance(x,(int,float)) and math.isfinite(x))
    if not finite:return {'count':0,'missing':len(values),'median':None,'p95':None}
    position=.95*(len(finite)-1);low=math.floor(position);high=math.ceil(position)
    value=finite[low]+(finite[high]-finite[low])*(position-low)
    return {'count':len(finite),'missing':len(values)-len(finite),'median':median(finite),'p95':value}

def is_heading(line):
    text=line.get('text','');box=line.get('bounding_box',[0,0,0,0]);conf=line.get('confidence',0)
    return bool(text and conf>=.3 and box[1]>=.72 and box[0]>=.18 and box[3]<=.16 and not any(x in text for x in ['挑战100天','bilibili','圣杯九','小九']))

def face_fields(face_image, pose_image):
    # Presence is a detection field; no inferred emotion or lip label.
    return {'face_landmarks':face_image,'pose_landmarks':pose_image,'nonmanual_status':'observed_coordinates_only','emotion_label':None,'mouth_label':None,'eyebrow_label':None,'gaze_label':None,'training_ready':False}

def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def verified_proposal_source(row,sources,source_root):
    if row['source_sha256'] not in sources:raise ValueError('Unknown bounded source digest')
    expected=Path(sources[row['source_sha256']]['path']).resolve(strict=True)
    actual=Path(row['source_path']).resolve(strict=True)
    if actual!=expected or not actual.is_relative_to(Path(source_root).resolve()) or file_sha(actual)!=row['source_sha256']:
        raise ValueError('Actual proposal input differs from verified inventory source')
    return actual


def observation_status(completed,failures):
    if failures:return 'failed_no_observations' if completed==0 else 'partial_observations_with_failures'
    return 'observation_extraction_completed' if completed else 'failed_no_observations'


def catalog(inventory,reference_root,proposals,output):
    import html
    from collections import Counter
    inventory,reference_root,output=map(Path,[inventory,reference_root,output])
    if output.exists():raise ValueError('Choose a NEW output directory')
    inv=json.loads(inventory.read_text());scope=Path(inv['scope']).resolve()
    if output.resolve().is_relative_to(scope):raise ValueError('Keep outputs outside original videos')
    old=json.loads((reference_root/'sources.json').read_text())
    old_sources={row['source_id']:row for row in old['sources']}
    source_rows=[];candidate_rows=[];input_hashes={str(inventory.resolve()):file_sha(inventory)}
    for source in inv['unique_sources']:
        path=Path(source['path']).resolve()
        if not path.is_relative_to(scope) or file_sha(path)!=source['sha256']:raise ValueError('Bounded source bytes differ')
        previous=old_sources[source['source_id']]
        if previous['sha256']!=source['sha256']:raise ValueError('Reference source binding differs')
        ocr=reference_root/'screen'/source['source_id']/'ocr.jsonl'
        input_hashes[str(ocr.resolve())]=file_sha(ocr)
        observed=[json.loads(line) for line in ocr.read_text().splitlines()]
        observations=[]
        for row in observed:
            image=reference_root/row['image']
            if not image.resolve().is_relative_to(reference_root.resolve()) or file_sha(image)!=row['image_sha256']:raise ValueError('OCR image evidence differs')
            input_hashes[str(image.resolve())]=row['image_sha256']
            headings=[line for line in row['lines'] if is_heading(line)]
            # Exactly one dominant title. Multi-title and instructions remain evidence only.
            headings.sort(key=lambda x:(x['bounding_box'][1],x['bounding_box'][2]),reverse=True)
            if headings:
                line=headings[0];text=re.sub(r'\s+','',line['text'])
                if len(text)<=18 and not any(w in text for w in ['复习','总结','点赞','关注','day','Day','今天我们','测试']):
                    observations.append({'text':text,'raw_text':line['text'],'time':row['source_seconds_nominal'],'confidence':line['confidence'],'image':str(image.resolve()),'image_sha256':row['image_sha256']})
        groups=[]
        for item in observations:
            if groups and item['text']==groups[-1][0]['text'] and item['time']-groups[-1][-1]['time']<=2.1:groups[-1].append(item)
            else:groups.append([item])
        source_candidates=[]
        for group in groups:
            if len(group)<3:continue
            start=max(0.,group[0]['time']-.5);end=min(source['duration'],group[-1]['time']+.5)
            identity=hashlib.sha256(f"{source['sha256']}:{start:.3f}:{end:.3f}:{group[0]['text']}".encode()).hexdigest()[:20]
            raw=group[0]['text']
            instructions=[{'time':row['source_seconds_nominal'],'lines':[line['text'] for line in row['lines'] if line['bounding_box'][1]<.42]} for row in observed if start<=row['source_seconds_nominal']<=end]
            candidate={'id':'bounded-'+identity,'text_candidate':raw,'source_id':source['source_id'],'source_sha256':source['sha256'],'source_path':str(path),'start':start,'end':end,'label_status':'spatial_title_repeated_automatic_candidate','sample_type':'teaching_window_not_isolated_word','word_boundaries_verified':False,'evidence':group,'instructions_raw':instructions,'contains_compound_alternatives':any(x in raw for x in ['好','/','—','-','篇']),'mirror_status':'unknown','anatomical_handedness':'unverified','source_family':'tutorial-series-100','training_group':training_group(source['sha256'],start,end),'split':'unassigned','nonmanual':face_fields(None,None),**FLAGS}
            candidate_rows.append(candidate);source_candidates.append(candidate['id'])
        source_rows.append({**source,'spatial_title_candidates':len(source_candidates),'candidate_ids':source_candidates,'ocr_snapshot':str(ocr.resolve()),'ocr_sha256':input_hashes[str(ocr.resolve())],'source_bytes_reverified':True})
    basics=json.loads(Path(proposals).read_text());input_hashes[str(Path(proposals).resolve())]=file_sha(proposals)
    allowed={row['sha256']:row for row in inv['unique_sources']}
    for row in basics['rows']:
        validate_proposal(row,allowed[row['source_sha256']]['duration'])
        verified_proposal_source(row,allowed,scope)
        row['training_group']=training_group(row['source_sha256'],row['start'],row['end'])
    output.mkdir(parents=True)
    (output/'lesson-catalog.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in source_rows))
    (output/'title-candidates.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in candidate_rows))
    (output/'basic-proposals.json').write_text(json.dumps(basics,ensure_ascii=False,indent=2)+'\n')
    counts=Counter(row['text_candidate'] for row in candidate_rows)
    report={'schema':SCHEMA,'source_root':str(scope),'counts':{'physical_files':inv['counts']['files'],'unique_sources':len(source_rows),'exact_duplicates':inv['counts']['exact_duplicates'],'minutes':inv['counts']['minutes'],'spatial_title_windows':len(candidate_rows),'unique_raw_titles':len(counts),'basic_windows':len(basics['rows']),'basic_unique_labels':len(set(row['text'] for row in basics['rows']))},'basic_unresolved':basics['unresolved_basic_targets'],'source_scope_reverified':True,'input_hashes':len(input_hashes),'face_future_training_required':True,'nonmanual_speech_vs_lexical_mouthing_unresolved':True,'GPU_status':'connection_refused','weights_training_started':False,**FLAGS}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(output/'input-hashes.json').write_text(json.dumps(input_hashes,ensure_ascii=False,indent=2)+'\n')
    cards=[]
    for row in basics['rows']:
        cards.append('<article><h3>'+html.escape(row['text'])+'</h3><p>'+html.escape(row['assistant_note'])+'</p><p>'+html.escape(f"{row['source_id']} {row['start']}–{row['end']}秒")+'</p></article>')
    page='<!doctype html><meta charset="utf-8"><title>基础词重标注</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;line-height:1.7}article{border:1px solid #ccc;padding:16px;margin:12px 0}small{color:#555}</style><h1>只重做这批教程的基础词</h1><p>原文件62份／去重48份。自动标注候选不代表人工批准；GPU连接被拒绝，尚未更新权重。</p><p>手型、掌向、位置、轨迹、源视频有意交叉和面部证据分别保留。词义候选和“播放正确”分别验收。</p>'+''.join(cards)
    (output/'index.html').write_text(page)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,required=True);parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--proposals',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(catalog(args.inventory,args.reference_root,args.proposals,args.output),ensure_ascii=False))
if __name__=='__main__':main()
