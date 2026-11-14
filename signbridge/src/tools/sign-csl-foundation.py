"""Build a source-grounded basic lexicon with a strict two-round motion gate."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sqlite3

CHECKS=('semantics','handshape','palm_orientation','location','path','nonmanual','boundaries','temporal_stability','collision')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):return json.loads(Path(p).read_text())


def lines(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def jsonl(p,rows):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n' for x in rows))


def text_key(s):
    # Normalize terminal utterance punctuation only. Preserve variant digits, internal tokens and qualifiers.
    return s.strip().rstrip('。！？!?')


def gate(action,rounds):
    reasons=[]
    expected={key:action.get(key) for key in ['source_sha256','clip_sha256','action_version_sha256','annotation_sha256']}
    if any(not v or not re.fullmatch(r'[0-9a-f]{64}',v) for v in expected.values()):reasons.append('missing_bound_source_or_action_version')
    if len(rounds)!=2:reasons.append('two_rounds_required')
    if {row.get('round') for row in rounds}!={1,2}:reasons.append('round_numbers_must_be1and2')
    methods=set()
    for row in rounds:
        methods.add(row.get('method_sha256'))
        if row.get('result')!='passed':reasons.append('round_not_passed:'+str(row.get('round')))
        if any(row.get(k)!=v for k,v in expected.items()):reasons.append('round_source_or_action_version_differs')
        if any(row.get('checks',{}).get(k)!='passed' for k in CHECKS):reasons.append('unverified_or_failed_consistency_dimension')
        if row.get('evidence_scope')!='full_action_all_source_frames':reasons.append('partial_or_non_action_evidence')
    if len(methods)!=2 or None in methods or any(not re.fullmatch(r'[0-9a-f]{64}',str(x)) for x in methods):reasons.append('rounds_not_independent_methods')
    return {'training_allowed':not reasons,'independent_passes':sum(x.get('result')=='passed' for x in rounds),
            'reasons':sorted(set(reasons)),'same_version_required':True,'any_revision_invalidates_rounds':True}


def caption_type(text):
    if text in {'这么久！','她给他','两条鱼','在上海。','很难'}:return 'phrase','按短语或省略的关系示例保留，不按字数拆词。'
    if any(x in text for x in ['？','?']) or text.startswith(('我想','我喜欢','我不','他画','有，这','行，这','给你看看','一直往前走','上课了','知道了','下次上课交','好，明天','服务好','有空儿','你打我')):
        return 'sentence','来源为完整询问、陈述、祈使或带语境的句子标签；词级动作边界仍未知。'
    if text in {'不喜欢','听音乐','发信息','无线上网','招手问好','花儿开了','从远处看','在目前情况下','这个时候','很久以前','暂时保密','举一反三','有的放矢'}:
        return 'phrase','按组合表达、固定成语或上下文短语建候选，不将多个字各自当成动作。'
    return 'word_candidate','来源为词汇候选标签；普通中文词级判读仍需结合具体原课，非手语形式认证。'


def annotation_version(sample,lexical,refined,targets,caption=None):
    label=text_key(caption['clean_text']) if caption and caption.get('clean_text') else text_key(sample['raw']['Chinese Sentences'])
    source_rows=[x for x in lexical if x['source_sha256']==sample['source_sha256'] and text_key(x['canonical_text'])==label]
    source_ids={x['id'] for x in source_rows}
    payload={'sample':sample,'source_lexical_records':source_rows,
             'refined_lexical_records':[x for x in refined if x['original_lexical_id'] in source_ids],
             'foundation_definitions':[x for x in targets if text_key(x['text'])==label],
             'caption_refinement':caption,
             'word_boundary_and_source_mapping':{k:sample.get(k) for k in ['source_window_seconds_nominal','source_pts_seconds','source_frame_ids_0based','candidate_override']}}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def native_tool():
    spec=importlib.util.spec_from_file_location('foundation_native_verifier',Path(__file__).with_name('sign-csl-foundation-compare.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def build(database,root,output,native_comparison=None):
    db,root,out=map(lambda p:Path(p).resolve(),[database,root,output])
    if out.exists() or out.is_relative_to(db) or out.is_relative_to(root):raise ValueError('New output separate from frozen sources required')
    samples=lines(db/'samples.jsonl');by_sample={x['id']:x for x in samples};lexical=lines(db/'tutorial/lexical-evidence.jsonl');captions=lines(db/'additional-candidates/windows.jsonl');terms=lines(db/'lexicon.jsonl')
    refined=load(root/'annotations/tutorial-refinement-main-v2.json')['annotations'];refmap={x['original_lexical_id']:x for x in refined}
    if set(refmap)!={x['id'] for x in lexical} or len(refined)!=573:raise ValueError('Tutorial refinement must cover exact frozen573 IDs')
    targets=load(root/'annotations/foundation-targets-v2.json')['records'];corrections=load(root/'annotations/caption-visual-corrections.json')['records'];fixmap={x['candidate_id']:x for x in corrections}
    obsroot=root/'motion-observations-v2';obsmap={x['id']:x for x in lines(obsroot/'records.jsonl')};compare_root=Path(native_comparison).resolve() if native_comparison else root/'native-comparison-v1';native={x['candidate_id']:x for x in lines(compare_root/'records.jsonl')}
    for x in samples:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}',x['id']):raise ValueError('Unsafe sample ID')
    expected={x['id'] for x in samples if x['dataset_id'] in {'tutorial-basic-candidates','additional-caption-candidates'}}
    if set(obsmap)!=expected or len(expected)!=283 or load(obsroot/'report.json')['failures']:raise ValueError('All283clipobservations must be accounted')
    for x in refined:
        original=next(y for y in lexical if y['id']==x['original_lexical_id'])
        if x['source_sha256']!=original['source_sha256'] or x['source_id']!=original['source_id'] or any(x.get(k) is not False for k in ['human_approved','training_ready','model_training_ready']):raise ValueError('Refinement changed source or raised approval')
    original_input_hashes={str(p):sha(p) for p in [db/'database.sqlite',db/'samples.jsonl',db/'SHA256SUMS',root/'annotations/tutorial-refinement-main-v2.json',root/'annotations/foundation-targets-v2.json',root/'annotations/caption-visual-corrections.json',obsroot/'records.jsonl',compare_root/'records.jsonl']}
    out.mkdir(parents=True);(out/'evidence').mkdir();(out/'clips').mkdir();(out/'observations').mkdir();(out/'source-annotations').mkdir();(out/'validation').mkdir()
    refined_captions=[]
    for row in captions:
        fix=fixmap.get(row['id']);raw=row['label_candidate'];clean=fix['corrected_text'] if fix else raw
        if fix:
            if fix['source_clip_sha256']!=row['local_video_sha256'] or sha(root/fix['evidence_image'])!=fix['evidence_image_sha256']:raise ValueError('Visual correction source image/clip differs')
            kind=fix['refined_unit_type'];reason=fix['reason']
        else:kind,reason=caption_type(raw)
        refined_captions.append({'id':row['id'],'source_sha256':row['source_sha256'],'raw_text':raw,'clean_text':clean,
                                 'refined_unit_type':kind,'reason':reason,'lexicon_eligible':clean is not None and kind not in {'section_title','theory_context','grammar_concept'},
                                 'source_authority':'assistant_actual_midframe_review' if fix else 'stored_caption_label_only',
                                 'visual_correction':fix,'word_boundaries_verified':False,'human_approved':False,'training_ready':False,'model_training_ready':False})
    capmap={x['id']:x for x in refined_captions};le_by_text=defaultdict(list);cap_by_text=defaultdict(list);clip_by_text=defaultdict(list)
    for x in lexical:le_by_text[text_key(x['canonical_text'])].append(x)
    for x in refined_captions:
        if x['lexicon_eligible']:cap_by_text[text_key(x['clean_text'])].append(x)
    for x in samples:
        if x['id'] in obsmap:
            label=capmap[x['id']]['clean_text'] if x['id'] in capmap else x['raw']['Chinese Sentences']
            if label is not None:clip_by_text[text_key(label)].append(x)
    ce_train=[x for x in samples if x['dataset_id']=='CE-CSL' and x['source_split']=='train' and x['status']=='retained'];ce_terms={x['label']:x for x in terms if x['in_ce_csl']}
    units=[];evidence=[];actions=[];native_verifier=native_tool()
    for record in native.values():native_verifier.verify_action(record)
    method1=hashlib.sha256((sha(compare_root/'report.json')+'spatial_native_projection_and_source').encode()).hexdigest()
    method2=hashlib.sha256((sha(Path(__file__))+'temporal_direction_and_rotation_different_checks').encode()).hexdigest()
    for sample_id in sorted(expected):
        row=by_sample[sample_id];ob=obsmap[sample_id];n=native.get(sample_id)
        if sha(obsroot/sample_id/'observations.npz')!=ob['observations_sha256']:raise ValueError('Observed artifact changed')
        shutil.copyfile(db/row['local_video'],out/'clips'/(sample_id+'.mp4'))
        if sha(out/'clips'/(sample_id+'.mp4'))!=row['media_sha256']:raise ValueError('Copied reference clip changed')
        shutil.copyfile(obsroot/sample_id/'observations.npz',out/'observations'/(sample_id+'.npz'));shutil.copyfile(obsroot/sample_id/'source-contact.jpg',out/'evidence'/(sample_id+'.jpg'))
        action={'id':sample_id,'source_sha256':row['source_sha256'],'clip_sha256':row['media_sha256'],'action_version_sha256':n['action_version_sha256'] if n else None,
                'annotation_sha256':annotation_version(row,lexical,refined,targets,capmap.get(sample_id)),
                'clip':'clips/'+sample_id+'.mp4','frames':row['frames'],'fps':row['reference_fps'],'observations':'observations/'+sample_id+'.npz',
                'contact':'evidence/'+sample_id+'.jpg','source_metrics':ob['metrics'],'native_comparison':n,
                'human_review_scope':'current_you_displayed_keyframe_only' if sample_id=='basic-you' else None,
                'full_action_human_approved':False,'native_motion_status':n['round1_status'] if n else 'no_exact_whole_action_mapping',
                'source_clip_word_alignment':'assistant_conservative_revision' if sample_id=='basic-you' else 'coarse_window_not_verified',
                'label_scope':capmap[sample_id]['refined_unit_type'] if sample_id in capmap else 'source_teaching_candidate'}
        if n:
            verified_inventory=native_verifier.verify_action(n)
            native_target=out/'native-actions'/sample_id
            native_target.mkdir(parents=True)
            for frame in verified_inventory:
                for field,sub,name in [('native','smplx',f"{frame['frame']:05d}_0.npz"),('metadata','meta',f"{frame['frame']:05d}_0.json"),('render','img',f"{frame['frame']:06d}.jpg")]:
                    if frame[field] is None:continue
                    source=Path(n['native_directory'])/sub/name;target=native_target/sub/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                    if sha(target)!=frame[field]:raise ValueError('Copied native action differs')
            jsonl(native_target/'asset-inventory.jsonl',verified_inventory)
            action['local_native_directory']=str(native_target.relative_to(out))
            local_record={**n,'native_directory':str(native_target)};native_verifier.verify_action(local_record)
        if n and (n['source_sha256']!=row['source_sha256'] or n['clip_sha256']!=row['media_sha256']):raise ValueError('Native comparison input version differs')
        dimensions={k:'unknown' for k in CHECKS}
        if n and n['missing_native_frames']:dimensions['temporal_stability']='failed_incomplete_action'
        rounds=[]
        for num,method in [(1,method1),(2,method2)]:
            rounds.append({'round':num,'method_sha256':method,**{k:action[k] for k in ['source_sha256','clip_sha256','action_version_sha256','annotation_sha256']},
                           'evidence_scope':'full_source_clip_technical_checks_not_complete_action_acceptance',
                           'result':'not_passed','checks':dict(dimensions),
                           'actual_checks':('spatial_source/native_projection_and_exact_frames' if num==1 else 'wrist_motion_direction_and_effective_rotation_trajectory'),
                           'result_note':('Missing native parameters are explicit' if n and n['missing_native_frames'] else 'Native/source handshape depth, word alignment, nonmanual semantics and mesh penetration are not fully established')})
        action['validation_rounds']=rounds;action['training_gate']=gate(action,rounds);actions.append(action)
    actmap={x['id']:x for x in actions}
    for number,t in enumerate(targets,1):
        key=text_key(t['text']);source_rows=le_by_text.get(key,[]);caption_rows=cap_by_text.get(key,[]);clips=clip_by_text.get(key,[])
        syntax=[refmap[x['id']]['refined_unit_type'] for x in source_rows]
        kind=Counter(syntax).most_common(1)[0][0] if syntax else t['target_unit_type'];tid='basic-'+hashlib.sha256((key+'\0'+kind).encode()).hexdigest()[:20]
        ceterm=ce_terms.get(t['text']);freq=ceterm['ce_occurrences_by_split']['train'] if ceterm else 0
        examples=[]
        for s in ce_train:
            if (ceterm and any(z['kind']=='gloss' and z['label']==t['text'] for z in s['gloss_tokens'])) or text_key(s['raw']['Chinese Sentences'])==key:
                examples.append({'sample_id':s['id'],'chinese':s['raw']['Chinese Sentences'],'gloss_sequence':s['raw']['Gloss'],'source_split':'train','whole_sequence_only_not_word_span':True,'video':s['local_video']})
                if len(examples)==2:break
        uid={'id':tid,'text':t['text'],'unit_type':kind,'target_structure_type':t['target_unit_type'],'category':t['category'],'meaning':t['meaning'],'do_not_equate':t['do_not_equate'],
             'source_lexical_ids':[x['id'] for x in source_rows],'source_caption_ids':[x['id'] for x in caption_rows],'action_ids':[x['id'] for x in clips],
             'source_forms':[{'id':x['id'],'source_id':x['source_id'],'meaning':x['meaning'],'manual_form_note':x.get('manual_form_note'),
                              'nonmanual_note':x.get('nonmanual_note'),'intervals':x['source_intervals'],'uncertainties':x['uncertainties'],'evidence_status':x['evidence_status']} for x in source_rows],
             'ce_train_source_occurrences':freq,'ce_train_examples':examples,
             'meaning_evidence':'audited_source_teaching' if source_rows else 'visually_checked_caption_label_not_full_definition' if any(x['visual_correction'] for x in caption_rows) else 'source_caption_or_CE_sequence_context_only' if caption_rows or examples else 'explicit_missing_motion_evidence',
             'motion_evidence':'actual_reference_clips_with_observations' if clips else 'source_lesson_context_only' if source_rows else 'no_isolated_motion_reference',
             'two_round_pass_actions':[],'training_ready':False,'model_training_ready':False,'word_boundary_verified':False,'full_action_consistency_verified':False}
        units.append(uid)
        evidence.extend({'unit_id':tid,'kind':'tutorial','record_id':x['id'],'sample_id':None,'lexical_id':x['id']} for x in source_rows)
        evidence.extend({'unit_id':tid,'kind':'caption_or_clip','record_id':x['id'],'sample_id':x['id'],'lexical_id':None} for x in clips)
    char_sources=defaultdict(Counter)
    for s in samples:
        for char in s['raw']['Chinese Sentences']:
            if '\u4e00'<=char<='\u9fff':char_sources[char][s['source_split']]+=1
    for t in terms:
        for char in t['label']:
            if '\u4e00'<=char<='\u9fff':char_sources[char]['written_labels']+=1
    chars=[{'character':ch,'kind':'written_character_component','counts_by_source_scope':dict(freq),
            'word_or_morpheme_status':'context_dependent_not_inferred_from_single_character','independent_sign_action_inferred':False,'training_ready':False} for ch,freq in sorted(char_sources.items())]
    # Copy all inherited video paths too, so SQLite media references remain self-contained.
    spec=importlib.util.spec_from_file_location('foundation_media_copy',Path(__file__).with_name('sign-csl-reference-database.py'))
    copier=importlib.util.module_from_spec(spec);spec.loader.exec_module(copier)
    media=copier.MediaCopies(out)
    for entry in lines(db/'media-aliases.jsonl'):media.copy(db/entry['relative_path'],entry['sha256'],entry['relative_path'])
    for name in ['reviews','motions']:
        if (db/name).exists():shutil.copytree(db/name,out/name)
    sentence_coverage=[]
    for s in samples:
        status='source_sequence_label_without_word_frame_alignment' if s['dataset_id']=='CE-CSL' else 'unlabeled_whole_lesson' if s['dataset_id']=='additional-course-sources' else 'clip_motion_evidence_checked_with_unverified_word_boundaries'
        sentence_coverage.append({'id':s['id'],'dataset_id':s['dataset_id'],'source_split':s['source_split'],'chinese':s['raw']['Chinese Sentences'],'gloss':s['raw']['Gloss'],
                                  'annotation_level':status,'word_spans':[],'motion_action_checked':s['id'] in expected,'training_ready':False})
    # New DB copies source records via SQLite backup; source library is opened strictly read-only.
    source=sqlite3.connect(f'file:{db}/database.sqlite?mode=ro',uri=True);c=sqlite3.connect(out/'foundation.sqlite');source.backup(c);source.close()
    try:
        c.executescript('PRAGMA foreign_keys=ON; CREATE TABLE foundation_units(id TEXT PRIMARY KEY,text TEXT NOT NULL,unit_type TEXT NOT NULL,category TEXT NOT NULL,record_json TEXT NOT NULL); CREATE TABLE refined_tutorial(id TEXT PRIMARY KEY REFERENCES lexical_evidence(id),record_json TEXT NOT NULL); CREATE TABLE refined_captions(id TEXT PRIMARY KEY REFERENCES caption_candidates(id),record_json TEXT NOT NULL); CREATE TABLE character_components(character TEXT PRIMARY KEY,record_json TEXT NOT NULL); CREATE TABLE action_checks(id TEXT PRIMARY KEY REFERENCES samples(id),record_json TEXT NOT NULL); CREATE TABLE foundation_evidence(unit_id TEXT REFERENCES foundation_units(id),kind TEXT,record_id TEXT,sample_id TEXT REFERENCES samples(id),lexical_id TEXT REFERENCES lexical_evidence(id)); CREATE VIEW foundation_training_eligible AS SELECT * FROM foundation_units WHERE json_extract(record_json,"$.training_ready")=1;')
        c.executemany('INSERT INTO foundation_units VALUES (?,?,?,?,?)',[(x['id'],x['text'],x['unit_type'],x['category'],json.dumps(x,ensure_ascii=False)) for x in units]);c.executemany('INSERT INTO refined_tutorial VALUES (?,?)',[(x['original_lexical_id'],json.dumps(x,ensure_ascii=False)) for x in refined]);c.executemany('INSERT INTO refined_captions VALUES (?,?)',[(x['id'],json.dumps(x,ensure_ascii=False)) for x in refined_captions]);c.executemany('INSERT INTO character_components VALUES (?,?)',[(x['character'],json.dumps(x,ensure_ascii=False)) for x in chars]);c.executemany('INSERT INTO action_checks VALUES (?,?)',[(x['id'],json.dumps(x,ensure_ascii=False)) for x in actions]);c.executemany('INSERT INTO foundation_evidence VALUES (?,?,?,?,?)',[(x['unit_id'],x['kind'],x['record_id'],x['sample_id'],x['lexical_id']) for x in evidence]);c.commit()
        if c.execute('PRAGMA integrity_check').fetchone()!=('ok',) or c.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Foundation SQLite contract failed')
    finally:c.close()
    for name,data in [('foundation-units.jsonl',units),('characters.jsonl',chars),('refined-tutorial.jsonl',refined),('refined-captions.jsonl',refined_captions),('action-checks.jsonl',actions),('source-sentence-coverage.jsonl',sentence_coverage)]:jsonl(out/name,data)
    with (out/'基础词组库.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','字词/表达','单位类型','类别','中文含义','来源义项数','原片片段数','CEtrain出现','两轮全通过','训练就绪'])
        for x in units:writer.writerow([x['id'],x['text'],x['unit_type'],x['category'],x['meaning'],len(x['source_lexical_ids']),len(x['action_ids']),x['ce_train_source_occurrences'],0,False])
    for name in ['foundation-targets-v2.json','tutorial-refinement-main-v2.json','caption-visual-corrections.json']:shutil.copyfile(root/'annotations'/name,out/'source-annotations'/name)
    shutil.copytree(root/'visual',out/'source-annotations/visual')
    for src,name in [(root/'inputs/training-gate.json','training-gate.json'),(obsroot/'report.json','all-clip-observations.json'),(compare_root/'report.json','native-source-comparison.json'),(root/'reports/prior-motion-evidence-map.json','prior-motion-evidence-map.json')]:shutil.copyfile(src,out/'validation'/name)
    jsonl(out/'validation/native-source-comparison-records.jsonl',list(native.values()))
    report={'schema':'signbridge-csl-foundation-refinement-v1','status':'foundation_library_built_motion_gate_not_passed','created_at':datetime.now(timezone.utc).isoformat(),'base_database':str(db),
            'foundation_units':len(units),'foundation_unit_types':dict(Counter(x['unit_type'] for x in units)),
            'foundation_with_reference_clips':sum(bool(x['action_ids']) for x in units),'foundation_without_isolated_reference':sum(not x['action_ids'] for x in units),
            'tutorial_records_reannotated':len(refined),'tutorial_refined_types':dict(Counter(x['refined_unit_type'] for x in refined)),
            'caption_records_reannotated':len(refined_captions),'caption_source_visual_revisions':len(corrections),'caption_excluded_as_section_or_theory':sum(not x['lexicon_eligible'] for x in refined_captions),
            'written_character_components':len(chars),'characters_with_inferred_independent_sign':0,'source_samples_with_coverage_status':len(sentence_coverage),
            'source_motion_clips_checked':len(actions),'source_motion_frames_checked':sum(x['frames'] for x in actions),
            'prior_native_clips_compared':len(native),'prior_native_complete':sum(x['all_frames_native_complete'] for x in native.values()),'prior_native_incomplete':sum(not x['all_frames_native_complete'] for x in native.values()),
            'full_action_two_round_acceptance_passes':0,'eligible_training_units':0,'weights_training_started':False,'training_ready':False,'model_training_ready':False,
            'original_database_sha256':sha(db/'database.sqlite'),'original_manifest_sha256':sha(db/'SHA256SUMS'),
            'strict_gate_note':'Two independent source/action full-consistency passes on identical source/clip/action version required. Technical spatial/temporal checks are not two complete passes.'}
    for record in native.values():native_verifier.verify_action(record)
    for action in actions:
        if action.get('local_native_directory'):
            native_verifier.verify_action({**action['native_comparison'],'native_directory':str(out/action['local_native_directory'])})
    for name,digest in original_input_hashes.items():
        if sha(name)!=digest:raise ValueError('Frozen source input changed during foundation assembly')
    write(out/'source-input-hashes.json',original_input_hashes)
    write(out/'report.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['database','root','output']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--native-comparison',type=Path)
    a=p.parse_args();print(json.dumps(build(a.database,a.root,a.output,a.native_comparison),ensure_ascii=False))
