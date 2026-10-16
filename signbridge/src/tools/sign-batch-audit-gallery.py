"""Build a local per-item evidence gallery for a six-batch motion audit."""
import argparse
from collections import Counter
import html
import importlib.util
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

spec = importlib.util.spec_from_file_location('batch_gallery_native', Path(__file__).with_name('sign-batch-motion-audit.py'))
native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
write = native.audit.sequence.write_json
FONT = '/System/Library/Fonts/STHeiti Light.ttc'


def label(draw, xy, text, size=17, fill='white'):
    draw.text(xy, str(text), fill=fill, font=ImageFont.truetype(FONT, size))


def tile(image, size=(320, 220)):
    if image is None: return Image.new('RGB', size, '#343d45')
    if isinstance(image, np.ndarray): image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    return ImageOps.pad(image.convert('RGB'), size, color='#151e28')


def sampled_video(path, numbers):
    frames = {}; wanted = set(numbers); cap = cv2.VideoCapture(str(path)); index = 0
    while cap.isOpened() and wanted:
        ok, image = cap.read()
        if not ok: break
        index += 1
        if index in wanted: frames[index] = image; wanted.remove(index)
    cap.release(); return frames


def native_sheet(row, output):
    scores = []
    for key in ['body_pose', 'left_hand_pose', 'right_hand_pose']:
        scores += row.get('metrics', {}).get(key, {}).get('worst_frames', [])
    peak = max(scores, key=lambda r: r['residual_max_deg'])['frame_1based'] if scores else max(1, row['frames'] // 2)
    samples = sorted({1, max(1, peak - 1), peak, min(row['frames'], peak + 1), row['frames']})
    clip = row.get('clip') or str(Path(row['landmarks']).with_name('clip.mp4'))
    frames = sampled_video(clip, samples)
    sheet = Image.new('RGB', (320 * len(samples), 524), '#18232f'); draw = ImageDraw.Draw(sheet)
    label(draw, (10, 5), row['uid'] + '  ' + row['text'], 16)
    missing = []
    for j, number in enumerate(samples):
        sheet.paste(tile(frames.get(number)), (j * 320, 55))
        if row['kind'] == 'native': image = cv2.imread(str(Path(row['fit']) / 'img' / f'{number:06d}.jpg'))
        else:
            overlay = sampled_video(Path(row['landmarks']).with_name('overlay.mp4'), [number]); image = overlay.get(number)
        sheet.paste(tile(image), (j * 320, 300))
        label(draw, (j * 320 + 8, 32), f'原视频 帧 {number} / {row["frames"]}', 15)
        label(draw, (j * 320 + 8, 278), ('SMPL-X渲染' if row['kind'] == 'native' else '二维观测') + f' 帧 {number}', 15)
        if number not in frames: missing.append(number)
    path = output / 'sheets' / (row['uid'] + '.jpg'); sheet.save(path, quality=88)
    return {'uid': row['uid'], 'path': str(path), 'sample_frames': samples, 'source_missing_sample_frames': missing,
            'sha256': native.audit.sha(path), 'selection': 'first/last and consecutive frames around largest raw joint residual'}


def avatar_sheet(row, captures, output):
    sheet = Image.new('RGB', (960, 610), '#18232f'); draw = ImageDraw.Draw(sheet)
    label(draw, (10, 5), row['uid'] + '  ' + row['text'], 16)
    for j, number in enumerate(row['sample_frames']):
        for mode, y in [('raw', 45), ('current_display', 330)]:
            file = next(x for x in row['files'] if x['frame_1based'] == number and x['mode'] == mode)
            with Image.open(captures / file['path']) as image: sheet.paste(tile(image, (320, 255)), (j * 320, y))
            label(draw, (j * 320 + 8, y - 22), ('未平滑' if mode == 'raw' else '当前显示') + f' 帧 {number}', 16)
    path = output / 'sheets' / (row['uid'] + '.jpg'); sheet.save(path, quality=90)
    return {'uid': row['uid'], 'path': str(path), 'sample_frames': row['sample_frames'], 'sha256': native.audit.sha(path)}


def run(args):
    root = args.root.resolve(); output = args.output.resolve()
    if output.exists(): raise ValueError('Choose new output; prior evidence is immutable')
    output.mkdir(parents=True); (output / 'sheets').mkdir()
    evidence_file = root / 'evidence-review-v2/evidence-review.json'; avatar_file = root / 'avatar-audit-v3/avatar-review.json'
    evidence = json.loads(evidence_file.read_text()); avatar = json.loads(avatar_file.read_text())
    am = {r['uid']: r for r in avatar['records']}; records = evidence['records']; sheets = []
    for row in records:
        if row['kind'] == 'reference2d':
            row['risk_flags'] += [side + ':2d_coverage_below_50_percent' for side, value in row['hand_coverage'].items() if value < .5]
    if args.sheets_from:
        previous = json.loads((args.sheets_from / 'report.json').read_text())
        for item in previous['contact_sheets']:
            original = Path(item['path'])
            if native.audit.sha(original) != item['sha256']: raise ValueError('Contact sheet changed')
            target = output / 'sheets' / original.name; shutil.copyfile(original, target)
            sheets.append({**item, 'path': str(target)})
    else:
        for row in records:
            if row['kind'] in ('native', 'reference2d'):
                sheets.append(native_sheet(row, output))
                if len(sheets) % 20 == 0: print(json.dumps({'sheets': len(sheets), 'total_native_reference': 224}), flush=True)
    capture_root = root / 'avatar-captures-v1'; captures = json.loads((capture_root / 'capture-report.json').read_text())
    if not args.sheets_from:
        for row in captures['records']: sheets.append(avatar_sheet(row, capture_root, output))
    sm = {r['uid']: r for r in sheets}; manifest = []
    for row in records:
        if row['uid'] in am: row['avatar'] = am[row['uid']]
        if row['uid'] in sm: row['contact_sheet'] = str(Path(sm[row['uid']]['path']).relative_to(output))
        if row['kind'] == 'native' and row['group'] == 'source4':
            compare = root.parent / 'data-expansion-20261014/source-4/reconstruction-delivery-20261015-69rzrm_g/review-v1' / row['id'] / 'compare.mp4'
            if compare.exists(): row['comparison_video'] = str(compare)
    counts = {}
    for batch in range(1, 7):
        subset = [r for r in records if batch in r.get('batches', [])]
        native_rows = [r for r in subset if r['kind'] == 'native']
        runtime_rows = [r for r in subset if r['kind'] == 'runtime']
        counts[str(batch)] = {'native_tasks': len(native_rows), 'native_complete': sum(not r['errors'] for r in native_rows),
            'native_automatic_risks': sum(bool(r['risk_flags']) and not r['errors'] for r in native_rows), 'native_errors': sum(bool(r['errors']) for r in native_rows),
            'native_frames_expected': sum(r['frames'] for r in native_rows),
            'runtime_clips': len(runtime_rows), 'runtime_automatic_risks': sum(bool(r['avatar']['risk_flags']) for r in runtime_rows),
            'two_dimensional_references': sum(r['kind'] == 'reference2d' for r in subset),
            'independent_smplx_keyframes': sum(r['kind'] == 'independent_keyframe' for r in subset),
            'independent_mano_cases': sum(r['kind'] == 'independent_mano' for r in subset)}
    source_coverage = []
    for source in evidence['sources']:
        matched = [r['uid'] for r in records if r.get('source_sha256') == source['sha256']]
        source_coverage.append({**source, 'matched_result_ids': matched,
            'status': 'existing_results_audited' if matched else 'no_matching_current_result_in_audited_stages'})
    report = {'schema': 'signbridge-six-batch-motion-quality-report-v1', 'counts_by_source_batch': counts,
        'records': records, 'checkpoints': evidence['checkpoints'], 'preserved_manifests': evidence['preserved_manifests'],
        'contact_sheets': sheets, 'source_inventory': source_coverage, 'limitations': evidence['limitations'],
        'input_reports': [{'path': str(p), 'sha256': native.audit.sha(p)} for p in [evidence_file, avatar_file, capture_root / 'capture-report.json']],
        'gallery_tool_sha256': native.audit.sha(__file__),
        'human_approved': False, 'training_ready': False, 'model_training_ready': False, 'source_parameters_changed': False,
        'supersedes': ['evidence-review-v1: missing optional 2D observations incorrectly counted as nonfinite fits; superseded by v2',
            'avatar-audit-v1: unchanged numerical results; v2 binds corrected evidence-review-v2'],
        'visual_scope': 'All-frame automated structural/temporal/bone checks. Every main native/2D item has original/render sampled contacts. All 112 runtime clips have six exact rendered samples. Human semantic and full-video visual approval remains unperformed.'}
    write(output / 'report.json', report)
    esc = lambda value: html.escape(str(value), quote=True)
    status_names = {'technical_error': '确定技术错误', 'high_priority_review': '原始轨迹待复看', 'no_automatic_red_flag': '未触发自动阈值',
                    'sparse_not_temporal': '关键帧：连续性未知', 'not_3d_reconstructed': '二维参考：尚无三维重建'}
    sections = []
    for row in records:
        aa = row.get('avatar'); risk = aa and aa['risk_flags']; kind = row['kind']; group = row['group']
        status = '当前显示仍有风险' if risk and kind == 'runtime' else status_names[row['status']]
        details = [f'<p class="id">{esc(row["uid"])}</p>', f'<p>{esc(status)}</p>']
        if row['errors']: details.append('<p class="bad">' + esc('；'.join(row['errors'])) + '</p>')
        if row['risk_flags']: details.append('<p>' + esc('；'.join(row['risk_flags'])) + '</p>')
        if row.get('boundary_review_flags'): details.append('<p>边界注意：' + esc('；'.join(row['boundary_review_flags'])) + '</p>')
        if aa:
            before, used = aa['before'], aa['used']
            details.append(f'<p>人物角度残差 P95：原始 {before["residualP95Deg"]:.2f}° → 当前设置 {used["residualP95Deg"]:.2f}°；手腕残差 P95：{before["wristResidualP95Cm"]:.2f} → {used["wristResidualP95Cm"]:.2f} cm。'
                           f'帧数 {aa["frames"]}；平均窗口平滑仅用于显示。</p>')
        if row.get('contact_sheet'): details.append(f'<img loading="lazy" src="{esc(row["contact_sheet"])}" alt="{esc(row["text"])} 原始与重建对照图">')
        for key, title in [('comparison_image', '关键帧原始/候选对比'), ('comparison_video', '完整原视频/网格对照视频'), ('clip', '原始片段'), ('candidate_npz', '原生参数'), ('asset', '运行时动作文件')]:
            if row.get(key) and Path(row[key]).is_file(): details.append(f'<a href="{esc(Path(row[key]).as_uri())}">{title}</a> ')
        if row.get('comparison_image') and Path(row['comparison_image']).is_file():
            details.append(f'<img loading="lazy" src="{esc(Path(row["comparison_image"]).as_uri())}" alt="独立关键帧对比">')
        details.append('<details><summary>逐项参数、确切帧号与来源</summary><pre>' + esc(json.dumps(row, ensure_ascii=False, indent=2)) + '</pre></details>')
        search = ' '.join([row['uid'], row['text'], kind, group, status] + list(map(str, row.get('batches', []))))
        sections.append(f'<article data-batches="{esc(",".join(map(str,row.get("batches",[]))))}" data-kind="{esc(kind)}" data-risk="{1 if row["errors"] or row["risk_flags"] or risk else 0}" data-search="{esc(search.lower())}"><h3>{esc(row["text"])} <small>{esc(group)}</small></h3>' + ''.join(details) + '</article>')
    table = ''.join(f'<tr><td>第 {b} 批</td><td>{c["native_complete"]}/{c["native_tasks"]}</td><td>{c["native_errors"]}</td><td>{c["native_automatic_risks"]}</td><td>{c["runtime_automatic_risks"]}/{c["runtime_clips"]}</td><td>{c["two_dimensional_references"]}</td><td>{c["independent_smplx_keyframes"]} / {c["independent_mano_cases"]}</td></tr>' for b,c in counts.items())
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SignBridge 六批动作逐项检查</title>
<style>body{font:16px/1.65 system-ui,sans-serif;background:#eef2f5;color:#182a3a;margin:0}main{max-width:1200px;margin:auto;padding:28px}h1{font-size:30px}article,.note{background:white;border:1px solid #c9d6df;border-radius:10px;padding:20px;margin:18px 0}img{width:100%;height:auto;border-radius:6px}small,.id{color:#526477;overflow-wrap:anywhere}pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:650px;overflow:auto;background:#edf1f5;padding:12px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px;border:1px solid #cad5dc;text-align:left}.bad{color:#a52d2c;font-weight:600}input,select{font:inherit;padding:9px;max-width:100%;margin:4px}nav{position:sticky;top:0;background:#eef2f5;padding:10px 0;z-index:2}a{color:#1a547b}article[hidden]{display:none}label{display:inline-block}button{font:inherit;padding:8px}#count{font-weight:600}</style><main>
<h1>六批动作逐项检查</h1><p>2026-10-16 · 依据原视频 SHA-256 归属目录 1–6 · 保留失败与未完成项</p>
<div class="note"><strong>当前最需要处理：</strong>第 4 批 2 条连续重建缺帧；第 2 批 1 个独立关键帧无人身重建；当前 Demo 第 4 批 2 句平滑后手腕残差仍超过筛查阈值。旧 T03–T07 部分解码有时序风险。所有 10 份权重哈希匹配；8 份历史清单共 171,685 个文件重新校验一致。</div>
<p>“待复看”是量化风险，快速手势也可能触发；不代表手语错误。“未触发阈值”也不表示语义、手型或接触关系正确。全帧执行结构/时序/骨架检查；对照图为采样，未宣称逐段人工观看全部视频。历史批准记录保持原样，本报告不新增批准。</p>
<table><thead><tr><th>来源</th><th>连续完整/任务</th><th>确定错误</th><th>原始时序风险</th><th>当前显示风险/动作</th><th>二维参考</th><th>独立身体关键帧/手部案例</th></tr></thead><tbody>''' + table + '''</tbody></table>
<p>独立身体关键帧与 MANO 案例互有对应，不能相加当作句子数；训练轮次与原视频批次亦不同。第 5 批只有 24 条二维参考，4 条左手检测覆盖低于 50%。第 6 批原生参数完整，10 条触发广义原始尖峰筛查，当前显示 12 条均未触发人物残差阈值，但文本/边界仍待人工确认。</p>
<p>阈值：原始相邻旋转 &gt;90°；某关节中点残差 &gt;30°；关节总体残差 P95 &gt;10°。人物当前显示筛查：角度残差 P95 &gt;10°、手腕残差 P95 &gt;2cm 或相邻旋转 &gt;90°。这些是当前模型尺寸、25FPS 的排查指标，不是语言准确率或网格穿模证明。</p>
<p><a href="report.json">完整机器报告</a> · <a href="REVIEW.md">检查结论与修复顺序</a></p>
<nav><label>查找 <input id="query" placeholder="句子、ID、训练轮次" type="search"></label><label>批次 <select id="batch"><option value="">全部</option>''' + ''.join(f'<option value="{b}">第{b}批</option>' for b in range(1,7)) + '''</select></label><label>阶段 <select id="kind"><option value="">全部</option><option value="runtime">当前 Demo/预览</option><option value="native">原始连续重建</option><option value="decoded">训练解码</option><option value="reference2d">二维参考</option><option value="independent_keyframe">独立身体关键帧</option><option value="independent_mano">独立 MANO</option></select></label><label><input id="risk" type="checkbox">仅风险/缺失</label><span id="count"></span></nav>
''' + ''.join(sections) + '''<script>const items=[...document.querySelectorAll('article')];function filter(){let n=0;const q=document.querySelector('#query').value.trim().toLowerCase(),b=document.querySelector('#batch').value,k=document.querySelector('#kind').value,r=document.querySelector('#risk').checked;for(const item of items){const show=(!q||item.dataset.search.includes(q))&&(!b||item.dataset.batches.split(',').includes(b))&&(!k||item.dataset.kind===k)&&(!r||item.dataset.risk==='1');item.hidden=!show;if(show)n++}document.querySelector('#count').textContent=n+' / '+items.length+' 项'}document.querySelectorAll('input,select').forEach(e=>e.addEventListener('input',filter));filter();</script></main></html>'''
    coverage_summary = '；'.join(f'第{b}批 {sum(s["batch"] == b and bool(s["matched_result_ids"]) for s in source_coverage)}/{sum(s["batch"] == b for s in source_coverage)} 个当前视频文件有对应结果' for b in range(1,7))
    page = page.replace('<nav>', '<p>原视频覆盖：' + coverage_summary + '。其余文件未找到本轮已完成阶段的对应结果，不能视为已训练；完整文件清单见机器报告。</p><nav>')
    page = page.replace('</style>', '@media(max-width:600px){main{padding:14px}table{display:block;overflow-x:auto}article{padding:12px;overflow-wrap:anywhere}input[type=search]{width:190px}}</style>')
    (output / 'index.html').write_text(page)
    runtime_risks = [r for r in records if r['kind'] == 'runtime' and r['avatar']['risk_flags']]
    text = ['# 六批动作质量检查', '', '检查日期：2026-10-16。所有既有参数、权重与审批状态保持原样。', '',
        '## 确定技术错误', '']
    for row in records:
        if row['errors']: text.append(f'- {row["uid"]}：{row["text"]}；{", ".join(row["errors"])}。缺失不得补零或插值。')
    text += ['', '## 当前显示仍需修复', '']
    for row in runtime_risks:
        a = row['avatar']; text.append(f'- {row["text"]}（{row["id"]}）：手腕中点残差 P95 {a["used"]["wristResidualP95Cm"]:.2f} cm；重点帧 {[p["frame_1based"] for p in a["used"]["worstWristFrames"]]}。')
    text += ['', '## 结论与处理顺序', '',
        '- 第4批原始91条完整轨迹均触发广义风险筛查；当前83条使用既有显示平滑，81条未触发当前骨架阈值，2条仍需处理。不能靠更强平滑证明手型正确。',
        '- 第6批12条原生参数完整，当前显示未触发骨架阈值；边界、教学相邻演示、手型及接触仍需人工复看。',
        '- T01–T10权重哈希一致。62条历史保存解码含6条冻结共同参考；T03–T05共6条、T06–T07各1条触发人物时序筛查。这些历史输出没有替换当前T08。较平滑的T09/T10不等于语义更准。',
        '- 第2批685个独立身体关键帧有1个未检出身体，256个关键帧含未通过历史局部门槛的选中手部候选，65个无选中手部候选。665个MANO案例有13个无手部检出；可选二维观测缺失是显式NaN，三维拟合均有限，不能误报为损坏。',
        '- 第5批24条仅二维参考，其中4条左手覆盖不足50%；不能判断三维人物抖动，不能称已经训练。',
        '- 先在新副本定位当前2条残余抖动并与原视频对照；再处理2条连续缺帧、1个独立无人身帧；保留失败证据并在新尝试重建；最后人工确认边界和动作含义。此次仅完成检查，没有自动平滑或重训源参数。',
        '', '## 覆盖范围与限制', '',
        '- 200条连续原生任务、24条二维参考、685个独立身体关键帧、665个独立MANO案例、62条保存的训练解码、112条当前运行时动作。不同阶段互相对应，不可合计为独立句子数。',
        '- 按341个现有视频文件重新计算SHA-256归属批次。第3批实际有61条连续重建；旧目录名不代表原视频批次。',
        '- 原视频结果覆盖：' + coverage_summary + '。未匹配文件不视为已经训练。',
        '- 171,685个历史清单条目重新校验一致；初期遗留溯源限制与第4批原始JPEG哈希缺口明确保留。文件哈希一致只证明未改变，不证明动作正确。',
        '- 原生姿态包含人物演示未使用的下肢/躯干关节，因此原始广义尖峰与实际人物显示风险分开列出。',
        '- 全帧完成结构与数值检查；224张原视频/重建采样表、112张当前人物原始/显示对照表。采样不是逐段人工语义审阅，不证明无穿模或接触错误。',
        '- evidence-review-v1误将缺失二维观测当作拟合NaN，已由v2纠正；两版均保留。avatar-audit-v2绑定纠正后的来源报告。',
        '- training_ready / model_training_ready 保持 false；无新训练、无检查点替换、无新增人工批准。']
    (output / 'REVIEW.md').write_text('\n'.join(text) + '\n')
    for p in sorted(output.rglob('*')):
        if p.is_file(): manifest.append(native.audit.sha(p) + '  ' + str(p.relative_to(output)))
    (output / 'SHA256SUMS').write_text('\n'.join(manifest) + '\n')
    print(json.dumps({'records': len(records), 'contact_sheets': len(sheets), 'counts': counts, 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, required=True); p.add_argument('--output', type=Path, required=True); p.add_argument('--sheets-from', type=Path)
    run(p.parse_args())
