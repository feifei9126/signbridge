"""Assemble source-specific lexical audits without inventing sign or standard approval."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
from urllib.parse import quote

GATES={'human_approved':False,'semantics_approved':False,'boundaries_approved':False,'text_verified':'','training_ready':False,'model_training_ready':False,'csl_translation_verified':False}
TYPES={'word','phrase','sentence','fingerspelling','number','grammar_concept','classifier_concept','name_sign_concept'}
BASES={'visible_title','explicit_instruction','sentence_context','theory_explanation'}

def text_key(value):
    return re.sub(r'[\s“”‘’「」『』"\'|]','',value.replace('／','/').replace('（','(').replace('）',')'))

def no_approval(row):
    for key,expected in GATES.items():
        if key in row and (row[key] is not expected if isinstance(expected,bool) else row[key]!=expected):
            raise ValueError('Automatic audit cannot raise '+key)
    if row.get('national_standard_match','not_checked')!='not_checked':raise ValueError('National sign form not independently verified')

def classify_interval(unit_type,text,source_text,basis):
    if basis=='sentence_context':return 'context_only'
    if basis=='explicit_instruction':return 'instruction_subunit_not_certified_boundary'
    if unit_type!='word':return 'source_'+unit_type+'_not_isolated_word'
    return 'source_label_not_motion_approval'

def instruction_matches(lesson,seconds,raw_text):
    key=text_key(raw_text)
    return bool(key) and any(abs(row['seconds']-seconds)<=.51 and key in text_key(''.join(line['text'] for line in row['lines'])) for row in lesson['raw_spatial_ocr'])

def correct_line(text,source_id,seconds,rules):
    matches=[(i,row) for i,row in enumerate(rules) if row['source_id']==source_id and abs(row['seconds']-seconds)<=.51 and row['raw_text']==text and row.get('corrected_text') and row.get('auto_apply',True)]
    values={row['corrected_text'] for _,row in matches}
    if len(values)>1:raise ValueError('Conflicting scoped text corrections')
    return (next(iter(values)),[i for i,_ in matches]) if values else (text,[])

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def safe_file(root,name):
    if not isinstance(name,str) or not name or '\\' in name or '\x00' in name:raise ValueError('Unsafe artifact path')
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or str(path)!=name:raise ValueError('Unsafe artifact path')
    for index in range(1,len(path.parts)+1):
        if root.joinpath(*path.parts[:index]).is_symlink():raise ValueError('Artifact symlink rejected')
    file=root/path
    if not file.is_file() or not file.resolve().is_relative_to(root.resolve()):raise ValueError('Missing/escaping artifact')
    return file

def validate_annotations(lesson,annotation):
    if annotation.get('source_id')!=lesson['source_id'] or annotation.get('number')!=lesson['number']:raise ValueError('Lesson identity differs')
    no_approval(annotation)
    if not annotation.get('course_title') or not annotation.get('lesson_summary') or not isinstance(annotation.get('terms'),list):raise ValueError('Missing lesson audit')
    if annotation.get('course_type') not in {'lexical_teaching','phrase_teaching','grammar','fingerspelling','numbers','test','name_sign_theory','classifier_theory'}:raise ValueError('Invalid/missing course type')
    for field in ['visual_sheets_inspected','text_corrections','excluded_or_context_only','gaps']:
        if not isinstance(annotation.get(field),list):raise ValueError('Missing lesson field: '+field)
    duration=lesson['duration'];warnings=[]
    for term in annotation['terms']:
        no_approval(term)
        if term.get('unit_type') not in TYPES or not term.get('canonical_text','').strip() or not term.get('meaning','').strip():raise ValueError('Missing lexical meaning/type')
        for field in ['raw_aliases','do_not_equate','variants','uncertainties']:
            if not isinstance(term.get(field,[]),list) or any(not isinstance(v,str) for v in term.get(field,[])):raise ValueError('Invalid lexical list field: '+field)
        if term.get('evidence_status') not in {'assistant_source_audited','unresolved'}:raise ValueError('Unknown evidence authority')
        if not isinstance(term.get('source_intervals'),list) or not term['source_intervals']:raise ValueError('Missing source range')
        for interval in term['source_intervals']:
            start,end=interval.get('start'),interval.get('end')
            if type(start) not in (int,float) or type(end) not in (int,float) or not math.isfinite(start+end) or not 0<=start<end<=duration+.05 or interval.get('basis') not in BASES:raise ValueError('Invalid source interval')
        for evidence in term.get('instruction_evidence',[]):
            if type(evidence.get('seconds')) not in (int,float) or not math.isfinite(evidence['seconds']) or not 0<=evidence['seconds']<=duration or not isinstance(evidence.get('raw_text'),str):raise ValueError('Invalid instruction evidence')
            if not instruction_matches(lesson,evidence.get('seconds',-1000),evidence.get('raw_text','')):
                warnings.append({'term':term['canonical_text'],'seconds':evidence.get('seconds'),'raw_text':evidence.get('raw_text'),'issue':'quoted_text_not_exact_timed_OCR; preserve_as_assistant_note_only'})
    return warnings

def raw_role(line):
    text=line['text'];box=line['bounding_box']
    if any(word.lower() in text.lower() for word in ['bilibili','圣杯九','小九_']):return 'watermark_or_channel_text'
    if any(word in text for word in ['点赞','收藏','关注','评论区','我们下期','下期见']):return 'outro_or_engagement'
    if box[1]>=.70:return 'title_or_upper_context'
    if box[1]<=.45:return 'instruction_or_caption'
    return 'other_visible_text'

def validate_index(index,inventory):
    sources=inventory.get('unique_sources',[])
    if len(index)!=48 or len(sources)!=48 or len({x.get('source_id') for x in index})!=48 or len({x.get('sha256') for x in index})!=48:
        raise ValueError('Exactly 48 distinct selected tutorial sources required')
    if {x.get('number') for x in index}!=set(range(1,49)):raise ValueError('Course numbers must cover 1..48 once')
    if inventory.get('counts',{}).get('files')!=62 or sum(len(x.get('aliases',[])) for x in sources)!=62:raise ValueError('All 62 original aliases required')
    bindings={x['source_id']:x['sha256'] for x in sources}
    if any(bindings.get(x['source_id'])!=x['sha256'] for x in index):raise ValueError('Frozen source inventory and course index differ')


def read_snapshot(path):
    raw=Path(path).read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest(),raw


def build(audit_root,annotation_files,output):
    audit_root,output=Path(audit_root).resolve(),Path(output).absolute()
    if output.exists():raise FileExistsError('Choose a NEW output directory')
    if output.resolve().is_relative_to(audit_root):raise ValueError('Keep assembled results outside frozen audit inputs')
    index,index_digest,index_raw=read_snapshot(safe_file(audit_root,'lesson-index.json'));lessons={}
    inventory,inventory_digest,_=read_snapshot(safe_file(audit_root,'inputs/inventory.json'))
    validate_index(index,inventory)
    input_hashes={str(audit_root/'lesson-index.json'):index_digest,str(audit_root/'inputs/inventory.json'):inventory_digest};annotations={};warnings=[];annotation_snapshots=[]
    for item in index:
        path=safe_file(audit_root,item['input']);lesson,digest,_=read_snapshot(path);input_hashes[str(path)]=digest
        if lesson['source_id']!=item['source_id'] or lesson['sha256']!=item['sha256']:raise ValueError('Frozen lesson differs')
        source=Path(lesson['path']).resolve();source_root=Path('/Users/mac/Desktop/手语/2/100').resolve()
        if not source.is_relative_to(source_root) or sha(source)!=lesson['sha256']:raise ValueError('Bounded original video changed')
        lessons[item['source_id']]=lesson
    for path in map(Path,annotation_files):
        value,digest,raw=read_snapshot(path);input_hashes[str(path.resolve())]=digest;annotation_snapshots.append((path.name,raw))
        if value.get('schema')!='signbridge-source-semantic-annotations-v1':raise ValueError('Annotation schema differs')
        for row in value['lessons']:
            sid=row['source_id']
            if sid not in lessons or sid in annotations:raise ValueError('Unknown/duplicate audited lesson')
            warnings.extend({'source_id':sid,**warning} for warning in validate_annotations(lessons[sid],row));annotations[sid]=row
    if set(lessons)!=set(annotations):raise ValueError('Not all selected videos audited')
    output.mkdir(parents=True);(output/'evidence').mkdir();(output/'annotations').mkdir();(output/'annotation-snapshots').mkdir()
    for name,raw in annotation_snapshots:(output/'annotation-snapshots'/name).write_bytes(raw)
    lexical=[];corrections=[];rawlines=[];perlesson=[]
    for sid,lesson in sorted(lessons.items(),key=lambda pair:pair[1]['number']):
        audit=annotations[sid]
        declared=audit.get('visual_sheets_inspected',[])
        if not declared or not set(declared)<=set(lesson['contact_sheets']):raise ValueError('Visual inspection references not bound to lesson')
        sheets=[]
        for name in lesson['contact_sheets']:
            source=safe_file(audit_root,name);destination=output/name;shutil.copy2(source,destination);sheets.append({'path':name,'sha256':sha(source),'assistant_reported_inspected':name in declared})
        for correction in audit.get('text_corrections',[]):
            raw=correction.get('raw_text','');seconds=correction.get('seconds',-1)
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=lesson['duration']:raise ValueError('Invalid correction time')
            bound=instruction_matches(lesson,seconds,raw)
            if not bound:warnings.append({'source_id':sid,'seconds':seconds,'raw_text':raw,'issue':'correction_raw_text_not_timed_source_OCR; not automatically_applied'})
            single_line=any(abs(frame['seconds']-seconds)<=.51 and raw in [line['text'] for line in frame['lines']] for frame in lesson['raw_spatial_ocr'])
            corrections.append({**correction,'correction_id':'correction-'+hashlib.sha256((sid+'\0'+str(seconds)+'\0'+raw+'\0'+str(correction.get('corrected_text'))).encode()).hexdigest()[:20],'source_id':sid,'source_sha256':lesson['sha256'],'raw_source_text_matches':bound,'auto_apply':bound and single_line and correction.get('corrected_text') is not None,'scope':'exact_single_raw_line_at_source_time' if single_line else 'proposed_context_revision_not_automatically_applied'})
        for i,term in enumerate(audit['terms']):
            row={**term,'id':'lexical-'+hashlib.sha256((lesson['sha256']+'\0'+str(i)+'\0'+term['canonical_text']).encode()).hexdigest()[:20],'source_id':sid,'source_sha256':lesson['sha256'],'lesson_number':lesson['number'],'course_title':audit['course_title'],'source_family':'tutorial-series-100','signer_identity':'unconfirmed','mirror_status':'unknown','anatomical_handedness':'unverified','split':'unassigned','training_group':lesson['sha256'],'source_video':lesson['path'],'word_motion_alignment_verified':False,'source_authority':'assistant_source_specific_audit','national_standard_match':'not_checked',**GATES}
            evidence=[]
            for item in row.get('instruction_evidence',[]):evidence.append({**item,'exact_timed_raw_ocr_match':instruction_matches(lesson,item['seconds'],item['raw_text'])})
            row['instruction_evidence']=evidence
            row['context_classifications']=[classify_interval(row['unit_type'],row['canonical_text'],'',interval['basis']) for interval in row['source_intervals']]
            if any(not x['exact_timed_raw_ocr_match'] for x in evidence):row.setdefault('uncertainties',[]).append('Some prose quotes differ from frozen OCR; inspect original image and do not use unmatched quote as training supervision.')
            lexical.append(row)
        perlesson.append({**audit,'source_sha256':lesson['sha256'],'duration_seconds':lesson['duration'],'aliases':lesson['aliases'],'physical_source_path':lesson['path'],'sampled_frames':lesson['sampled_frames'] if 'sampled_frames' in lesson else len(lesson['raw_spatial_ocr']),'evidence_sheets':sheets,'source_binding_verified':True,**GATES})
        (output/'annotations'/f'{lesson["number"]:02d}-{sid}.json').write_text(json.dumps(perlesson[-1],ensure_ascii=False,indent=2)+'\n')
    characters=defaultdict(lambda:{'occurrences':0,'sources':set(),'lexical_entries':set()})
    for sid,lesson in lessons.items():
        for frame in lesson['raw_spatial_ocr']:
            for ordinal,line in enumerate(frame['lines']):
                revised,ruleids=correct_line(line['text'],sid,frame['seconds'],corrections)
                rawlines.append({'source_id':sid,'source_sha256':lesson['sha256'],'seconds_nominal':frame['seconds'],'line_index':ordinal,'raw_text':line['text'],'corrected_text':revised,'correction_indices':ruleids,'correction_ids':[corrections[i]['correction_id'] for i in ruleids],'role':raw_role(line),'bounding_box':line['bounding_box'],'ocr_confidence':line['confidence'],'image_reference':frame['image'],'image_sha256':frame['image_sha256'],'sampled_not_full_video_transcription':True,'linguistic_motion_alignment_verified':False})
                if raw_role(line) not in {'watermark_or_channel_text','outro_or_engagement'}:
                    for char in revised:
                        if '\u4e00'<=char<='\u9fff':characters[char]['occurrences']+=1;characters[char]['sources'].add(sid)
    for row in lexical:
        for char in row['canonical_text']:
            if '\u4e00'<=char<='\u9fff':characters[char]['lexical_entries'].add(row['id'])
    dispositions=[]
    for sid,lesson in lessons.items():
        termrows=[row for row in lexical if row['source_id']==sid]
        for candidate in lesson['title_candidates']:
            middle=(candidate['start']+candidate['end'])/2
            exact=[];overlapping=[]
            for term in termrows:
                overlap=any(interval['start']<=middle<=interval['end'] for interval in term['source_intervals'])
                aliases=[term['canonical_text'],*term.get('raw_aliases',[])]
                if overlap:overlapping.append(term['id'])
                if overlap and text_key(candidate['text_candidate']) in {text_key(alias) for alias in aliases}:exact.append(term['id'])
            dispositions.append({'candidate_id':candidate['id'],'source_id':sid,'raw_title':candidate['text_candidate'],
                'source_window_seconds':[candidate['start'],candidate['end']],
                'disposition':'scoped_label_match_only' if exact else 'time_context_only_not_label_assignment' if overlapping else 'unmapped_raw_OCR_or_context_requires_review',
                'matched_lexical_ids':exact,'overlapping_context_ids':overlapping,'automatically_approved':False,'training_ready':False})
    byconcept=defaultdict(list)
    for row in lexical:byconcept[(row['canonical_text'],row['unit_type'])].append(row)
    concept_records=[]
    for (label,unit),examples in sorted(byconcept.items()):
        concept_records.append({'canonical_text':label,'unit_type':unit,
            'source_occurrences':[{'lexical_id':x['id'],'source_id':x['source_id'],'course_title':x['course_title'],
                                   'source_intervals':x['source_intervals'],'meaning':x['meaning'],
                                   'manual_form_note':x.get('manual_form_note'),'variants':x.get('variants',[]),
                                   'nonmanual_note':x.get('nonmanual_note'),'evidence_status':x['evidence_status']} for x in examples],
            'different_source_forms_not_averaged':True,'same_written_word_does_not_prove_same_motion':True,
            'national_standard_match':'not_checked','independent_word_boundary_verified':False,**GATES})
    (output/'concept-index.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in concept_records))
    (output/'candidate-disposition.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in dispositions))
    transcript=[]
    line_groups=defaultdict(list)
    for row in rawlines:
        if row['role'] not in {'watermark_or_channel_text','outro_or_engagement'}:
            line_groups[(row['source_id'],row['seconds_nominal'])].append(row)
    for lesson in perlesson:
        transcript.append('# '+str(lesson['number'])+' '+lesson['course_title']+'\n')
        transcript.append(lesson['lesson_summary']+'\n')
        transcript.append('原片：'+lesson['physical_source_path']+'\n')
        for frame in lessons[lesson['source_id']]['raw_spatial_ocr']:
            lines=line_groups[(lesson['source_id'],frame['seconds'])]
            if not lines:continue
            raw=' | '.join(x['raw_text'] for x in lines);revised=' | '.join(x['corrected_text'] for x in lines)
            transcript.append(f"{frame['seconds']:.1f}秒　{revised}"+('　〔原OCR：'+raw+'〕' if raw!=revised else '')+'\n')
        transcript.append('\n')
    (output/'逐课可见文字记录.md').write_text(''.join(transcript))
    chars=[{'character':k,'visible_text_occurrences':v['occurrences'],'source_ids':sorted(v['sources']),'lexical_entries':sorted(v['lexical_entries']),'standalone_sign_exists':None,'note':'Written character coverage; never implies a standalone sign or composable unit.'} for k,v in sorted(characters.items())]
    for name,rows in [('lexical-entries.jsonl',lexical),('visible-text-audit.jsonl',rawlines),('character-index.jsonl',chars),('corrections.jsonl',corrections)]:
        (output/name).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
    (output/'lessons.json').write_text(json.dumps(perlesson,ensure_ascii=False,indent=2)+'\n');(output/'evidence-warnings.json').write_text(json.dumps(warnings,ensure_ascii=False,indent=2)+'\n');(output/'input-hashes.json').write_text(json.dumps(input_hashes,ensure_ascii=False,indent=2)+'\n')
    fields=['id','canonical_text','unit_type','category','meaning','do_not_equate','source_id','lesson_number','course_title','source_intervals','manual_form_note','variants','nonmanual_note','evidence_status','uncertainties','national_standard_match','training_ready']
    with (output/'词义审计表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in lexical:writer.writerow({k:json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else row.get(k) for k in fields})
    distinct=Counter((row['canonical_text'],row['unit_type']) for row in lexical)
    report={'schema':'signbridge-source-semantic-audit-v1','status':'source_specific_audit_with_explicit_uncertainties','source_root':'/Users/mac/Desktop/手语/2/100','counts':{'source_videos':len(lessons),'physical_files':sum(len(v['aliases']) for v in lessons.values()),'sampled_frames':sum(len(v['raw_spatial_ocr']) for v in lessons.values()),'visible_ocr_lines':len(rawlines),'written_characters':len(chars),'lexical_entries':len(lexical),'unique_written_label_and_unit_type':len(distinct),'unit_types':dict(Counter(x['unit_type'] for x in lexical)),'unresolved_entries':sum(x['evidence_status']=='unresolved' for x in lexical),'source_specific_text_corrections':len(corrections),'exact_source_bound_corrections':sum(x['auto_apply'] for x in corrections),'raw_title_windows_accounted':len(dispositions),'raw_title_disposition_counts':dict(Counter(x['disposition'] for x in dispositions)),'unmatched_quote_or_correction_warnings':len(warnings),'evidence_sheets':sum(len(x['evidence_sheets']) for x in perlesson)},'not_a_claim_of_complete_semantic_mastery':True,'national_standard_gesture_forms_verified':0,'whole_video_framewise_expert_review':False,'source_text_and_gesture_correctness_separate':True,'new_model_training_started':False,**GATES}
    try:render_review(output,perlesson,lexical,corrections,report)
    except Exception as error:
        (output/'ASSEMBLY-FAILED.json').write_text(json.dumps({'status':'failed','error_type':type(error).__name__,'message':str(error)},ensure_ascii=False,indent=2)+'\n');raise
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def render_review(output,lessons,terms,corrections,report):
    def esc(value):return html.escape(str(value),quote=True)
    type_names={'word':'词','phrase':'短语','sentence':'整句','fingerspelling':'手指字母','number':'数字','grammar_concept':'语法讲解','classifier_concept':'类标记','name_sign_concept':'手语名字'}
    cards=[]
    for lesson in lessons:
        rows=[r for r in terms if r['source_id']==lesson['source_id']]
        entries=[]
        for row in rows:
            source_uri=Path(row['source_video']).as_uri()
            clips=' '.join(f'<a href="{esc(source_uri)}#t={interval["start"]},{interval["end"]}" target="_blank" rel="noopener">原片{interval["start"]:.1f}–{interval["end"]:.1f}秒</a>' for interval in row['source_intervals'])
            intervals='；'.join(f"{x['start']:.1f}–{x['end']:.1f}秒（{x['basis']}）" for x in row['source_intervals'])
            evidence='；'.join(f"{x['seconds']:.1f}秒：{x['raw_text']}" for x in row['instruction_evidence']) or '没有独立讲解引文，按画面或语境保留证据。'
            uncertain='；'.join(row.get('uncertainties',[])) or '仍未核准镜像、手别和精确词动作边界。'
            contrast='、'.join(row.get('do_not_equate',[])) or '不与相近中文词自动合并。'
            variants='；'.join(row.get('variants',[])) or '本次未另列并列变体。'
            status='留疑' if row['evidence_status']=='unresolved' else '教程证据审计'
            entries.append(f'<article class="term" data-type="{esc(row["unit_type"])}" data-status="{esc(row["evidence_status"])}"><h3>{esc(row["canonical_text"])} <small>{esc(type_names[row["unit_type"]])} · {status}</small></h3><p>{clips}</p><p><b>本课词义：</b>{esc(row["meaning"])}</p><p><b>不要混淆：</b>{esc(contrast)}</p><p><b>手型与动作说明：</b>{esc(row.get("manual_form_note","未确认"))}</p><p><b>面部／头部：</b>{esc(row.get("nonmanual_note","未确认"))}</p><details><summary>时间、原文、变体与不确定项</summary><p>{esc(intervals)}</p><p>讲解原文：{esc(evidence)}</p><p>课内变体：{esc(variants)}</p><p class="warning">{esc(uncertain)}</p><p>动作词界未认证；未声称国家通用手语标准动作或人工批准。</p></details></article>')
        sheets=''.join(f'<a href="{esc(x["path"])}"><img loading="lazy" src="{esc(x["path"])}" alt="{esc(lesson["course_title"])}原片采样对照"></a>' for x in lesson['evidence_sheets'])
        changes=[x for x in corrections if x['source_id']==lesson['source_id']]
        change_html=''.join(f'<li>{x["seconds"]:.1f}秒：{esc(x["raw_text"])} → {esc(x.get("corrected_text") or "留疑")}；{esc(x.get("reason",""))}</li>' for x in changes)
        originals=Path(lesson['physical_source_path']).as_uri()
        gaps='；'.join(lesson.get('gaps',[])) or '本课动作词界、镜像和人物身份未核准。'
        cards.append(f'<section class="lesson" id="lesson-{lesson["number"]}" data-number="{lesson["number"]}"><header><span>第{lesson["number"]}份来源 · {esc(lesson["course_type"])}</span><h2>{esc(lesson["course_title"])}</h2><p>{esc(lesson["lesson_summary"])}</p><a href="{esc(originals)}" target="_blank" rel="noopener">打开本机原视频</a><small> 时长{lesson["duration_seconds"]:.1f}秒 · SHA {lesson["source_sha256"][:16]}…</small></header><div class="sheets">{sheets}</div><details><summary>本课误字修订与缺项</summary><ul>{change_html or "<li>未另列具体误字修订；不代表全部字幕无误。</li>"}</ul><p>{esc(gaps)}</p></details><div class="entries">'+(''.join(entries) if entries else '<p>本课没有可据现有字幕确认的独立词义标签；测验或其他未定内容保留在上面的缺项说明中。</p>')+'</div></section>')
    count=report['counts']
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SignBridge 全课程词义审计</title><link rel="stylesheet" href="review.css"><main><h1>逐课把词义说清楚</h1><p>仅限你提供的2/100教程。标准书写、课程义项、手语动作分开核验。</p><div class="metrics">'+f'<b>{count["source_videos"]}份去重视频</b><b>{count["lexical_entries"]}条课程义项</b><b>{count["source_specific_text_corrections"]}项修订／留疑</b><b>{count["visible_ocr_lines"]:,}行OCR可追溯</b>'+'</div><aside>这份审计解释本教程中的词义与说明，不把OCR标题视作已训练动作，也不声称全部示范都是国家通用手语的唯一标准。未核准的词界、手别、镜像和面部语义保留不确定性。本轮没有更新模型权重。</aside><nav><label for="search">查词或讲解</label><input id="search" placeholder="例如：我、我们、早上、上午、食指、疑问"><label for="kind">内容类型</label><select id="kind"><option value="">全部类型</option>'+''.join(f'<option value="{k}">{v}</option>' for k,v in type_names.items())+'</select><label for="state">证据</label><select id="state"><option value="">全部</option><option value="unresolved">只看留疑</option></select><p id="result" role="status"></p></nav><p><a href="词义审计表.csv">下载词义审计表CSV</a> · <a href="report.json">计数口径</a> · <a href="evidence-warnings.json">引文绑定告警</a></p>'+''.join(cards)+'<footer>所有人工批准／训练就绪标志仍为false。一个汉字出现不等于存在单独对应手语；片头、讲解、例句、指拼、数字和普通词分别处理。</footer></main><script src="review.js"></script></html>'
    (output/'index.html').write_text(page)
    (output/'review.css').write_text('body{margin:0;background:#f3f5ef;color:#183c32;font:16px/1.7 system-ui}main{max-width:1240px;margin:36px auto;padding:0 22px}h1{font-size:34px}h2{font-size:25px;margin:6px 0}h3{font-size:21px;margin:0}.metrics{display:flex;gap:14px;flex-wrap:wrap}.metrics b{padding:12px;background:#e2eddf;border-radius:8px}aside{padding:18px;border-left:4px solid #987631;background:#fff1d3;margin:24px 0}nav{position:sticky;top:0;background:#f3f5eff2;padding:16px 0;z-index:2}input,select{padding:10px;font:inherit;max-width:100%;border:1px solid #9eb3a0;border-radius:6px}input{width:330px}label{margin-right:8px}nav label:not(:first-child){margin-left:16px}section{background:white;margin:30px 0;border:1px solid #cedbcb;padding:22px;border-radius:12px}.sheets{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:16px}.sheets img{width:100%}.entries{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:20px}.term{border-top:2px solid #e0eadb;padding:16px 10px;min-width:0}.term p{margin:9px 0}small,header>span,footer{font-size:12px;color:#52685a}.warning{color:#8c4126}a{color:#176450}summary{cursor:pointer}details{font-size:14px;margin-top:16px}p,li{overflow-wrap:anywhere}[hidden]{display:none!important}#result{margin:8px 0 0;font-size:13px}@media(max-width:750px){.entries,.sheets{grid-template-columns:1fr}nav{position:static}nav label{display:block!important;margin:10px 0 4px!important}h1{font-size:28px}section{padding:14px}input,select{width:100%;box-sizing:border-box}}')
    (output/'review.js').write_text("const search=document.querySelector('#search'),kind=document.querySelector('#kind'),state=document.querySelector('#state');function update(){let n=0,lessons=0;const q=search.value.trim();for(const lesson of document.querySelectorAll('.lesson')){let visible=0;for(const card of lesson.querySelectorAll('.term')){const show=(!q||card.textContent.includes(q))&&(!kind.value||card.dataset.type===kind.value)&&(!state.value||card.dataset.status===state.value);card.hidden=!show;if(show){visible++;n++;}}const hasNoTerms=lesson.querySelectorAll('.term').length===0;const showEmpty=hasNoTerms&&!kind.value&&!state.value&&(!q||lesson.textContent.includes(q));lesson.hidden=!visible&&!showEmpty;if(!lesson.hidden)lessons++;}document.querySelector('#result').textContent=`显示 ${n} 条义项，来自 ${lessons} 课。`; }for(const el of [search,kind,state])el.addEventListener('input',update);update();\n")


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--audit-root',type=Path,required=True);parser.add_argument('--annotations',type=Path,nargs='+',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.audit_root,args.annotations,args.output),ensure_ascii=False))
if __name__=='__main__':main()
