"""Extract unapproved caption candidates from evidence-bound sparse Vision OCR."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def normalized(text):
    return re.sub(r'[\W_]+','',text,flags=re.UNICODE)


def parse_line(line):
    text=str(line.get('text','')).strip()
    confidence=line.get('confidence',0.)
    box=line.get('bounding_box')
    if (not isinstance(box,list) or len(box)!=4 or
            not all(isinstance(n,(int,float)) and math.isfinite(n) for n in box)):
        raise ValueError('Invalid OCR bounding box')
    x,y,width,height=box
    if not (isinstance(confidence,(int,float)) and math.isfinite(confidence)):
        raise ValueError('Invalid OCR confidence')
    if confidence<.5 or not re.search('[\u4e00-\u9fff]',text) or height<.016:
        return None
    if .035<=y<=.28 and .05<=x and x+width<=.98:
        rule='bottom_caption_candidate'
    elif .05<=x and .30<=y<=.80 and x+width<=.53 and height>=.025:
        rule='left_panel_caption_candidate'
    elif .55<=x and .40<=y<=.90 and x+width<=1.01:
        rule='right_panel_caption_candidate'
    else:
        return None
    if re.search('国家通用手语|手语学堂|中国手语|手语学校|bilibili|哔哩哔哩|扫码|点赞|投币|关注',text,re.I):
        return None
    marker=re.match(r'^(?:下面(?:一个|的)词|下一个词)[\s:：，,]*(.+)$',text)
    label=(marker.group(1) if marker else text).strip(' ：:，,。')
    if not label or len(label)>50 or not normalized(label):return None
    if not marker and re.search('手背|掌心|伸出|伸开|左手|右手|拇指|小指|食指|手指|手掌|手腕|手形|手型|怎么做|做法|然后|下面一个词',label):
        return None
    return {'label':label,'confidence':float(confidence),'box':box,
            'rule':'lesson_word_marker' if marker else rule,'text_raw':text}


def caption_groups(observations,duration,interval):
    if not math.isfinite(duration) or not duration>0 or not 0<interval<=10:
        raise ValueError('Invalid sparse OCR timeline')
    active,groups,previous={},[],None
    for observation in observations:
        seconds=observation['source_seconds']
        if not (isinstance(seconds,(int,float)) and math.isfinite(seconds) and 0<=seconds<duration) or previous is not None and seconds<=previous:
            raise ValueError('Unordered or out-of-range OCR timeline')
        previous=seconds
        labels={}
        for line in observation.get('lines',[]):
            parsed=parse_line(line)
            if parsed:
                key=normalized(parsed['label'])
                if key not in labels or parsed['confidence']>labels[key]['confidence']:labels[key]=parsed
        active={key:value for key,value in active.items() if key in labels}
        for key,value in labels.items():
            group=active.get(key)
            if not group or seconds-group['evidence'][-1]['source_seconds']>interval*1.01:
                group={'label_candidate':value['label'],'extraction_rule':value['rule'],'evidence':[]}
                groups.append(group);active[key]=group
            group['evidence'].append({'source_seconds':seconds,'image':observation['image'],
                'image_sha256':observation['image_sha256'],'text_raw':value['text_raw'],
                'confidence':value['confidence'],'bounding_box':value['box']})
    return groups


def candidate_record(source,group,number,duration,interval):
    evidence=group['evidence'];times=[r['source_seconds'] for r in evidence]
    return {'schema':'signbridge-caption-candidate-v1',
        'annotation_id':source['source_id']+'-cap-%04d'%number,'source_id':source['source_id'],
        'source_sha256':source['sha256'],'relative_path':source['relative_path'],
        'content_class':source.get('content_class','unconfirmed'),'label_candidate':group['label_candidate'],
        'start_seconds_nominal':max(0.,times[0]-interval/2),
        'end_seconds_nominal':min(duration,times[-1]+interval/2),
        'sampled_seconds_nominal':times,'sample_interval_seconds':interval,
        'extraction_rule':group['extraction_rule'],'sample_count':len(evidence),
        'ocr_confidence_min':min(r['confidence'] for r in evidence),
        'ocr_confidence_mean':sum(r['confidence'] for r in evidence)/len(evidence),
        'evidence':evidence,'raw_ocr_texts':sorted({r['text_raw'] for r in evidence}),
        'text_verified':'','human_approved':False,'training_ready':False,'model_training_ready':False,
        'language':'unconfirmed','mirror_status':'unknown','signer_identity':'unconfirmed','split':'unassigned',
        'semantics_approved':False,'boundaries_approved':False,'boundary_review':'sparse_ocr_window',
        'label_provenance':'spatial/temporal sparse OCR heuristic; not verified signing semantics'}


def build(args):
    manifest_path,screen,output=args.manifest.resolve(),args.screen.resolve(),args.output.resolve()
    if output.exists():raise ValueError('Use a new candidate output directory')
    manifest=json.loads(manifest_path.read_text());report=json.loads((screen/'screen.json').read_text())
    if report.get('status')!='screened_new_sources_pending_candidate_review':raise ValueError('OCR run is incomplete')
    if report.get('source_manifest_sha256')!=sha(manifest_path):raise ValueError('Screen source manifest digest differs')
    interval=1/report['sampling_fps'];sources={r['source_id']:r for r in manifest['sources']}
    rows=[];images_verified=0
    for source_row in report['sources']:
        source=sources[source_row['source_id']]
        if source_row['source_sha256']!=source['sha256']:raise ValueError('Screen source hash differs')
        observations=[json.loads(x) for x in (screen/source['source_id']/'ocr.jsonl').read_text().splitlines() if x.strip()]
        for observation in observations:
            image=(screen/observation['image']).resolve()
            if screen not in image.parents or not image.is_file() or sha(image)!=observation['image_sha256']:
                raise ValueError('OCR image provenance differs')
            images_verified+=1
        groups=caption_groups(observations,source['duration_seconds'],interval)
        rows.extend(candidate_record(source,g,i,source['duration_seconds'],interval) for i,g in enumerate(groups,1))
    eligible=[r for r in rows if r['sample_count']>=4 and r['ocr_confidence_mean']>=.75 and
              4<=r['end_seconds_nominal']-r['start_seconds_nominal']<=20]
    common=re.compile('你好|谢谢|再见|请问|对不起|帮助|医生|今天|明天|工作|学习|学校|多少钱|哪里|可以|怎么|吃|爸爸|妈妈|天气|早上|下雨|需要|朋友')
    eligible.sort(key=lambda r:(not bool(common.search(r['label_candidate'])),-r['sample_count'],-r['ocr_confidence_mean'],r['annotation_id']))
    counts=defaultdict(int);shortlist=[]
    for row in eligible:
        if counts[row['source_id']]>=args.per_source:continue
        if any(r['source_id']==row['source_id'] and normalized(r['label_candidate'])==normalized(row['label_candidate']) for r in shortlist):continue
        shortlist.append(row);counts[row['source_id']]+=1
    output.mkdir(parents=True)
    for name,values in [('caption-candidates.jsonl',rows),('manual-review-shortlist.jsonl',shortlist)]:
        (output/name).write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in values))
    summary={'schema':'signbridge-caption-candidate-summary-v1','sources':len(report['sources']),
             'source_manifest_sha256':sha(manifest_path),'screen_report_sha256':sha(screen/'screen.json'),
             'ocr_images_sha256_verified':images_verified,'candidates':len(rows),
             'repeated_candidates':sum(r['sample_count']>1 for r in rows),'manual_review_shortlist':len(shortlist),
             'candidate_sources':len({r['source_id'] for r in rows}),
             'verified_labels':0,'training_ready':False,'source_files_modified':False,
             'selection_rule':'four consecutive OCR samples, mean confidence >=0.75, 4-20 nominal seconds; limited per source; common text only affects priority'}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (output/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(output.iterdir()) if p.is_file()))
    print(json.dumps(summary,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('manifest','screen','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--per-source',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.per_source<=5:parser.error('per-source must be between 1 and 5')
    build(args)


if __name__=='__main__':main()
