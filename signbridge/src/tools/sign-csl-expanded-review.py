"""Build a local-only explorer for expanded CSL evidence; never a motion approval UI."""
import argparse
import json
from pathlib import Path
import shutil


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build(database, output):
    database, output = database.resolve(), output.resolve()
    report = json.loads((database / 'report.json').read_text())
    reference = Path(report['reference'])
    base = Path(report['base'])
    inputs = [database, base.resolve(), reference.resolve()]
    if output.exists() or any(output.is_relative_to(root) or root.is_relative_to(output) for root in inputs):
        raise ValueError('New review output separate from source roots required')
    output.mkdir(parents=True)
    inventory = rows(database / 'media-inventory.jsonl')
    media = {x['sha256']: reference / x['relative_path'] for x in inventory}
    samples = {x['id']: x for x in rows(database / 'source-samples.jsonl')}
    actions = {x['id']: x for x in rows(database / 'actions.jsonl')}
    view = []
    for unit in rows(database / 'units.jsonl'):
        item = {k: unit[k] for k in ['id', 'text', 'unit_type', 'category', 'base_foundation_ids', 'remaining_issues']}
        item.update(group='中文分层条目', source_senses=[], action_links=[], status='未通过完整动作双轮验证')
        for sense in unit['source_senses']:
            source = media.get(sense.get('clip_sha256')) or media.get(sense.get('source_sha256'))
            item['source_senses'].append({**sense, 'video_url': source.as_uri() if source and source.is_file() else None})
        for sid in unit['action_ids']:
            action = actions[sid]
            clip = base / action['clip']
            comparison = base / 'comparisons' / (sid + '.mp4')
            item['action_links'].append({'id': sid, 'video_url': clip.as_uri(),
                                         'comparison_url': comparison.as_uri() if comparison.exists() else None,
                                         'native_complete': bool(action.get('native_comparison') and action['native_comparison']['all_frames_native_complete'])})
        view.append(item)
    for row in rows(database / 'gloss-index.jsonl'):
        item = {'id': row['id'], 'text': row['text'], 'unit_type': 'dataset_gloss', 'group': 'CE原始Gloss标签',
                'category': '序列级标签，无独立词界', 'base_foundation_ids': [], 'status': '未验证词级动作',
                'source_senses': [], 'action_links': [], 'related_units': row['exact_written_label_matches'],
                'remaining_issues': ['仅原句级标注，不能直接切成词动作'],
                'occurrences': row['occurrences_retained_by_split']}
        for sid in row.get('retained_sample_ids', row['sample_ids'])[:3]:
            sample = samples[sid]
            item['source_senses'].append({'id': sid, 'kind': 'CE-CSL原句', 'meaning': sample['raw']['Chinese Sentences'],
                                          'raw_gloss': sample['raw']['Gloss'], 'source_split': sample['source_split'],
                                          'video_url': (reference / sample['local_video']).as_uri()})
        view.append(item)
    for row in rows(database / 'sentences.jsonl'):
        view.append({'id': row['id'], 'text': row['chinese'], 'unit_type': 'source_sentence', 'group': 'CE原句样本',
                     'category': row['source_split'], 'base_foundation_ids': [],
                     'status': '冲突隔离' if row['status'] != 'retained' else '原句已入库，动作未双轮认证',
                     'source_senses': [{'id': row['id'], 'kind': 'CE-CSL原句', 'meaning': row['chinese'],
                                         'raw_gloss': row['raw_gloss'], 'video_url': (reference / row['local_video']).as_uri(),
                                         'source_split': row['source_split']}], 'action_links': [],
                     'remaining_issues': ['无词级时间对齐', '无此原句完整骨骼认证']})
    (output / 'data.js').write_text('window.EXPANDED=' + json.dumps({'report': report, 'records': view}, ensure_ascii=False).replace('</', '<\\/') + ';\n')
    (output / 'index.html').write_text('''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>中国手语扩展数据库 · 待双轮验证</title>
<style>body{font:16px/1.65 system-ui,sans-serif;color:#192630;background:#f4f6f8;margin:0}main{max-width:1320px;margin:auto;padding:26px}h1{font-size:29px;margin-bottom:8px}.warning{border-left:5px solid #b32828;background:#fff0ee;padding:14px 18px}nav{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0}label{display:flex;gap:7px;align-items:center}input,select,button{font:inherit;padding:8px;border:1px solid #9da9b2;border-radius:5px}input{min-width:240px}a{color:#075ea8}.layout{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);gap:22px}.list{height:72vh;overflow:auto;background:white;border:1px solid #d6dde1}.list button{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #e0e6e9;background:white;border-radius:0}.list button[aria-pressed=true]{background:#dceaf5}.muted{color:#5b6b76;font-size:14px}article{background:white;padding:22px;min-width:0}video{max-width:100%;width:680px;display:block;background:#17212b;margin:15px 0}details{border-top:1px solid #d9e1e6;padding:12px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui}h2{margin-top:0}@media(max-width:750px){main{padding:14px}.layout{grid-template-columns:1fr}.list{height:280px}input{min-width:150px;max-width:90%}article{padding:14px}}</style>
<main><h1>中国手语扩展数据库</h1><p id="stats"></p><div class="warning"><strong>只有同一来源、同一动作、同一标注版本通过两次完整验证，才算通过。</strong><p>当前所有扩展内容均为候选或来源证据。文字入库、视频可解码、参数结构正常，均不等于动作正确。没有训练或替换Demo。</p></div>
<nav aria-label="检索与筛选"><label>搜索<input id="search" type="search" placeholder="字词、词组、句子或原始Gloss" aria-label="搜索内容"></label><label>内容层<select id="group"><option value="中文分层条目">中文分层条目</option><option value="CE原始Gloss标签">CE原始Gloss标签</option><option value="CE原句样本">CE原句样本</option></select></label><label>范围<select id="scope"><option value="all">全部</option><option value="new">本轮新增</option><option value="base">原基础库</option></select></label><label>类别<select id="type"><option value="">全部类别</option></select></label></nav><p id="count" role="status" aria-live="polite"></p><div class="layout"><div class="list" id="list" aria-label="检索结果"></div><article id="detail" aria-label="来源与动作证据"></article></div><p>这是本机证据检索包，视频链接依赖原参照库和基础库目录。没有将13GB原视频重复装入元数据ZIP。<a href="../README.md">阅读说明</a> · <a href="../report.json">机器统计</a></p></main><script src="data.js"></script><script src="review.js"></script></html>''')
    (output / 'review.js').write_text('''const {report,records}=window.EXPANDED;const q=s=>document.querySelector(s);const types={word:"词",phrase:"词组",sentence:"句子",dataset_gloss:"原始Gloss标签",source_sentence:"原句样本",classifier_concept:"类标记概念",grammar_concept:"语法概念",fingerspelling:"指拼",number:"数字",name_sign_concept:"手语名概念"};
q('#stats').textContent=`中文分层条目 ${report.typed_written_entries} 项（本轮新增 ${report.new_typed_entries_beyond_foundation} 项），原始Gloss ${report.ce_gloss_labels} 项，CE原句 ${report.ce_samples_all} 条；完整双轮通过 0。`;
function el(tag,text,parent){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(parent)parent.append(x);return x}
function sourceLink(label,url,parent){if(!url)return;const a=el('a',label,parent);a.href=url;a.target='_blank';a.rel='noopener';el('span','　',parent)}
function show(row,button){q('#list').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));const d=q('#detail');d.replaceChildren();el('h2',row.text,d);el('p',`${types[row.unit_type]||row.unit_type} · ${row.category} · ${row.status}`,d);el('p','同名文字只作为检索分组；各来源义项、变体和动作分别保留。',d).className='muted';el('pre',row.remaining_issues.join('；'),d);for(const x of row.action_links){const section=el('details',undefined,d);el('summary',`动作候选 ${x.id} · 原生参数${x.native_complete?'帧集完整':'不完整或未拟合'}`,section);sourceLink('原片片段',x.video_url,section);sourceLink('原片／拟合对照',x.comparison_url,section);el('p','未通过完整双轮验收；不可按“播放正常”升级为批准。',section)}for(const s of row.source_senses){const section=el('details',undefined,d);section.open=row.source_senses.length===1;el('summary',`${s.kind} · ${s.id}`,section);sourceLink('打开冻结来源视频',s.video_url,section);if(s.video_url){const b=el('button','在本页查看视频',section);b.addEventListener('click',()=>{let v=section.querySelector('video');if(!v){v=el('video',undefined,section);v.controls=true;v.preload='metadata';v.src=s.video_url;const interval=s.source_intervals?.[0];if(interval&&Number.isFinite(interval.start))v.addEventListener('loadedmetadata',()=>{v.currentTime=Math.min(interval.start,Math.max(0,v.duration-.1))},{once:true})}v.scrollIntoView({block:'nearest'})})}const copy={...s};delete copy.video_url;el('pre',JSON.stringify(copy,null,2),section)}}
function refresh(){const term=q('#search').value.trim();const group=q('#group').value;const scope=q('#scope').value;const type=q('#type').value;const selected=records.filter(r=>r.group===group&&(!type||r.unit_type===type)&&(scope==='all'||(scope==='base'?r.base_foundation_ids.length>0:r.base_foundation_ids.length===0))&&(!term||r.text.includes(term)||r.source_senses.some(s=>String(s.meaning||'').includes(term))));q('#count').textContent=`匹配 ${selected.length} 条，显示前200条；请进一步搜索定位。`;const list=q('#list');list.replaceChildren();for(const row of selected.slice(0,200)){const b=el('button',`${row.text} · ${types[row.unit_type]||row.unit_type}${row.base_foundation_ids.length?' · 原基础':' · 待验证'}`,list);b.setAttribute('aria-pressed','false');b.onclick=()=>show(row,b)}if(selected.length){show(selected[0],list.firstChild)}else{q('#detail').replaceChildren(el('p','没有匹配内容。'))}}
function groupChanged(){q('#type').replaceChildren(new Option('全部类别',''));const keys=[...new Set(records.filter(r=>r.group===q('#group').value).map(r=>r.unit_type))];for(const k of keys)q('#type').append(new Option(types[k]||k,k));refresh()}
q('#search').addEventListener('input',refresh);q('#scope').addEventListener('change',refresh);q('#type').addEventListener('change',refresh);q('#group').addEventListener('change',groupChanged);groupChanged();
''')
    shutil.copy2(Path(__file__), output / 'review-tool-source.py')
    return {'records': len(view), 'output': str(output), 'training_ready': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.database.resolve(), args.output.resolve()), ensure_ascii=False))
