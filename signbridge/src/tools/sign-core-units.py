#!/usr/bin/env python3
"""Create source-bound lexical candidates by exact slices of repaired tracks.

Caption evidence and assistant frame comparison are not linguistic approval.
No raw parameters, old libraries or manual review sets are modified.
"""
import argparse
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess

import cv2
from PIL import Image, ImageDraw, ImageOps


FLAGS = {'human_approved': False, 'semantics_approved': False,
         'boundaries_approved': False, 'text_verified': '', 'training_ready': False,
         'model_training_ready': False, 'training_started': False}
PROPOSALS = [
    ('speaker', '我', 'c0f7cda04ec861eebccc5955ce187a05', 1, 43, 'person', '指胸自指；去掉尾部淡出。'),
    ('addressee', '你', 'fddc127ab18d9215c5c550fc4ec76517', 1, 50, 'person', '你好教学中的你子示范；保留伸食指至前指，不能当作整句你好。'),
    ('home', '家', '7946012cbd55f1a8ee72f01fa90d7324', 151, 200, 'noun', '保留末次连续屋顶示范；排除开头里外及讲解。'),
    ('hospital', '医院', '76655d4510a00693bdfc78bfdb2cf105', 21, 76, 'noun', '选首轮额头十字接屋顶；不从讲解的分步动作拼造新帧。'),
    ('work', '工作', 'f036c254f7fb30d3a30196d937637b22', 11, 55, 'predicate', '选首轮连贯工字加握拳动作；排除学习结尾和随后分解教学。'),
    ('healthy', '健康', 'b4a69d0a29f5020fceeb87f9ea0f3af2', 11, 55, 'predicate', '选首轮双手向下再好手势；排除舒服结尾和随后分解。'),
    ('relax', '放松', '8d8a3b234f050511bb24d962880d3115', 56, 100, 'predicate', '排除害怕标题与静止等待，保留双拳到放开。'),
    ('clothes', '衣服', 'c67faf574ec46cc0d4ae79b15e4cbc6b', 16, 50, 'noun', '排除买的结束，保留衣服示范。'),
    ('trousers', '裤子', '9c077a1e368741c3952b09ca071ea0ac', 1, 49, 'noun', '完整穿裤子教学动作；不使用先前另一变体。'),
    ('shoes', '鞋', '61168c56cc2098ede2ef2960814d3e2d', 35, 74, 'noun', '保留双手鞋的实际示范，排除开头静止等待。'),
    ('body', '身体', 'b13b41d3117d0164965ab847000ae604', 57, 100, 'noun', '选复习中的完整胸至腹示范；排除上个词和静止段。'),
    ('nose', '鼻子', '3dd0a0a76b7a0f93e0806a69ade801da', 1, 62, 'noun', '保留第一轮鼻部指示到归位；第二轮不重复。'),
    ('drink', '饮料', '26971523b204dbe3ca23b7a97200e34b', 26, 100, 'noun', '排除文创商店在那边，保留饮料喝水模拟完整示范。'),
    ('absence', '没有', 'a51d1487c6381d31a3bc2e9989eaf89f', 41, 100, 'absence', '排除前面的这里有没有盖章的地方；只作缺少/没有，不能冒充不或不想。'),
    ('banana', '香蕉', '8134d586899050351e198ff5aac8b2a4', 41, 100, 'noun', '选第二轮完整剥香蕉示范及归位。'),
    ('pear', '梨', 'ce573f4632482f0643cf6f683b4472c3', 14, 49, 'noun', '排除苹果结尾，保留梨的抬手头侧示范；标题证据仍属候选。'),
    ('drive', '开车', '7ff3645c3eefbf3b13038e410fb1f154', 61, 100, 'predicate', '排除打车及静止讲解，保留末次双手方向盘动作。'),
]
EXCLUDED = {
    '谢谢': 'whole_phrase_contains_other_signs',
    '帮助': 'directional_recipient_not_verified',
    '眼睛': 'source_window_may_cut_gesture_before_completion',
    '草莓': 'word_internal_step_may_be_incomplete',
    '时间': 'lecture_window_not_isolated_lexical_demonstration',
    '手': 'lexical_boundary_not_established',
    '没关系': 'multi_step_phrase_retained_as_research_reference',
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def label_support(label, lines):
    for line in lines:
        line = re.sub(r'\s+', '', line)
        line = re.sub(r'^手语[：:]', '', line)
        if line == label or line == label + '（房子）':
            return True
    return False


def slice_clip(clip, proposal, source_sha):
    for field, expected in FLAGS.items():
        if clip.get(field) != expected:
            raise ValueError('Candidate flags differ: ' + field)
    start, end = proposal['start'], proposal['end']
    if (type(start) is not int or type(end) is not int or
            not 1 <= start <= end <= clip['frames'] or end - start + 1 < 4):
        raise ValueError('Exact one-based source frame interval required')
    if proposal['source_id'] != clip['id'] or proposal['text'] != clip['text']:
        raise ValueError('Core proposal identity differs')
    result = copy.deepcopy(clip)
    result.update(id='native_core_' + proposal['key'] + '_v1', frames=end - start + 1,
                  text=proposal['text'], aliases=[proposal['text']],
                  source_frame_range_1based=[start, end],
                  source_frame_ids_1based=list(range(start, end + 1)),
                  parent_native_id=clip['id'], parent_asset_sha256=source_sha,
                  core_unit_key=proposal['key'], lexical_role=proposal['role'],
                  boundary_status='assistant_proposed_frame_interval',
                  semantics_status='source_caption_and_assistant_observation_only',
                  source_parameters_modified=False, temporal_interpolation=False,
                  quaternions=clip['quaternions'][start - 1:end], **FLAGS)
    result.pop('asset', None)
    result.pop('sha256', None)
    return result


def build(repaired, technical, evidence, output):
    repaired, technical, evidence = (Path(p).resolve() for p in (repaired, technical, evidence))
    output = Path(output).absolute()
    if output.exists() or any(output.resolve().is_relative_to(p) for p in (repaired, technical, evidence)):
        raise ValueError('Choose a new nonoverlapping output')
    index = json.loads((repaired / 'native-index.json').read_text())
    tech = json.loads((technical / 'index.json').read_text())
    originals = {r['uid']: r for r in tech['records']}
    entries = {c['id']: c for c in index['clips']}
    inventory = json.loads((evidence / 'inventory.json').read_text())
    evidence_by_id = {r['id']: r for r in inventory['records']}
    ocr = {r['image']: r for r in (json.loads(line) for line in (evidence / 'ocr.jsonl').read_text().splitlines())}
    output.mkdir(parents=True)
    (output / 'native').mkdir()
    (output / 'core-evidence').mkdir()
    clips, units, pages = [], [], []
    for key, text, identity, start, end, role, note in PROPOSALS:
        source_id = 'native_fit_' + identity
        entry = entries[source_id]
        source_asset = repaired / entry['asset']
        if sha(source_asset) != entry['sha256']:
            raise ValueError('Repaired source asset digest differs')
        original = originals[entry['source_uid']]
        clip_path = Path(original['clip_path'])
        clip_sha = sha(clip_path)
        if any(a['candidate_clip_sha256'] != clip_sha for a in original['aliases']):
            raise ValueError('Original clip alias digest differs')
        proposal = dict(key=key, text=text, source_id=source_id, start=start, end=end, role=role, note=note)
        clip = slice_clip(json.loads(source_asset.read_text()), proposal, entry['sha256'])
        relative = 'native/' + clip['id'] + '.json'
        write_json(output / relative, clip)
        folder = output / 'core-evidence' / key
        folder.mkdir()
        # Decoding by frame number avoids keyframe-seek drift. No fps/fill filter.
        video = folder / 'original.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1', '-filter_threads', '1',
                        '-i', str(clip_path), '-vf', f'trim=start_frame={start-1}:end_frame={end},setpts=PTS-STARTPTS',
                        '-an', '-c:v', 'libx264', '-threads', '1', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-fps_mode', 'passthrough', str(video)], check=True)
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
                          '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(video)]))
        if int(probe['streams'][0]['nb_read_frames']) != clip['frames']:
            raise ValueError('Trimmed source exact frame count differs')
        selected = set(round(k * (clip['frames'] - 1) / 5) for k in range(6))
        cap = cv2.VideoCapture(str(video))
        sheet = Image.new('RGB', (960, 440), 'white')
        draw = ImageDraw.Draw(sheet)
        i, slot = 0, 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i in selected:
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                image = ImageOps.contain(image, (320, 195))
                x, y = (slot % 3) * 320, (slot // 3) * 220
                sheet.paste(image, (x, y + 20))
                draw.text((x + 5, y + 3), f'source frame {start+i}', fill='black')
                slot += 1
            i += 1
        cap.release()
        if i != clip['frames']:
            raise ValueError('Cut source decode differs')
        sheet.save(folder / 'source-contact.jpg', quality=90)
        evidence_row = evidence_by_id[source_id]
        supports, observed = [], []
        for image in evidence_row['images']:
            if start <= image['frame_1based'] <= end:
                item = ocr[image['path']]
                observed.append({'source_frame_1based': image['frame_1based'], 'lines': item['lines']})
                if label_support(text, [line['text'] for line in item['lines']]):
                    supports.append(image['frame_1based'])
        source = original['aliases'][0]
        window = source['source_window_seconds_nominal']
        provenance = {'source_file': source['source_absolute_path'], 'source_sha256': original['source_sha256'],
                      'source_file_bytes_reverified': False, 'source_video_pts_measured': False,
                      'parent_clip_sha256': clip_sha, 'parent_clip_frames': entry['frames'],
                      'source_window_seconds_nominal': window,
                      'selected_source_seconds_nominal': [window[0] + (start-1)/entry['fps'], window[0] + end/entry['fps']],
                      'frame_time_contract': 'nominal source window + exact decoded parent-clip frame / fps, not original-source PTS certification'}
        unit = {**proposal, 'id': clip['id'], 'asset': relative, 'sha256': sha(output / relative),
                'frames': clip['frames'], 'fps': clip['fps'], 'source_frame_range_1based': [start, end],
                'parent_native_id': source_id, 'parent_asset_sha256': entry['sha256'],
                'source_uid': entry['source_uid'], 'provenance': provenance,
                'evidence': {'original_video': f'core-evidence/{key}/original.mp4', 'original_video_sha256': sha(video),
                             'source_contact': f'core-evidence/{key}/source-contact.jpg',
                             'caption_support_frames': supports, 'ocr_observations': observed,
                             'inspection_basis': 'assistant_comparison_of_actual_source_frame_grids_and_OCR',
                             'limitations': ['Caption/title is contextual evidence, not proof of exact lexical boundaries.',
                                            'Frame interval is an assistant proposal, not a human sign-language decision.']},
                'meaning_scope': 'Chinese source label candidate only', **FLAGS}
        write_json(folder / 'alignment.json', unit)
        metadata = {k: v for k, v in clip.items() if k not in ('quaternions', 'bones')}
        clips.append({**metadata, 'asset': relative, 'sha256': sha(output / relative)})
        units.append(unit)
        pages.append(f'<article><h2>{html.escape(text)}</h2><p>{html.escape(note)}</p>'
                     f'<p>原片帧 {start}–{end}；词义和词界仍未批准。</p><video controls preload="none" src="core-evidence/{key}/original.mp4"></video>'
                     f'<img loading="lazy" src="core-evidence/{key}/source-contact.jpg" alt="{html.escape(text,quote=True)} 原片帧"><a href="core-evidence/{key}/alignment.json">来源与边界记录</a></article>')
    native_index = {**index, 'clips': clips, 'core_version': 'core-motion-v1', 'full_candidate_count': len(index['clips']),
                    'parent_index_sha256': sha(repaired / 'native-index.json'), 'source_index_sha256': sha(repaired / 'native-index.json'),
                    'core_alignment_file': 'core-alignment.json', **FLAGS}
    # Keep the complete 151-clip repaired library as an explicitly separate
    # research catalog. The default planner receives only the core unit IDs.
    for entry in index['clips']:
        original_file = repaired / entry['asset']
        if sha(original_file) != entry['sha256']:
            raise ValueError('Research asset digest differs')
        shutil.copyfile(original_file, output / entry['asset'])
    native_index['clips'] = clips + index['clips']
    write_json(output / 'native-index.json', native_index)
    alignment = {'schema': 'signbridge-core-alignment-v1', 'units': units, 'scope': 'assistant_source_bound_candidates',
                 'parent_index_sha256': sha(repaired / 'native-index.json'), 'human_review_required_for_language_approval': True, **FLAGS}
    write_json(output / 'core-alignment.json', alignment)
    core_manifest = {'schema': 'signbridge-core-motion-v1', 'native_index_sha256': sha(output / 'native-index.json'),
                     'alignment_sha256': sha(output / 'core-alignment.json'),
                     'units': [{key: unit[key] for key in ('id', 'key', 'text', 'role', 'frames', 'fps', 'source_uid',
                                                         'source_frame_range_1based', 'parent_native_id', 'parent_asset_sha256')}
                               for unit in units], **FLAGS}
    write_json(output / 'core-manifest.json', core_manifest)
    ledger = [{'id': c['id'], 'label_candidate': c['text'],
               'status': 'selected_exact_frame_derived_unit' if c['id'] in {u['parent_native_id'] for u in units} else 'research_only',
               'reason': 'selected_by_source_frame_comparison' if c['id'] in {u['parent_native_id'] for u in units}
                         else EXCLUDED.get(c['text'], 'outside_initial_core_scope'),
               'human_approved': False, 'training_ready': False} for c in index['clips']]
    write_json(output / 'coverage-ledger.json', {'records': ledger, 'total': len(ledger),
               'selected': len(units), 'research_only': len(ledger)-len(units), 'excluded_label_reasons': EXCLUDED, **FLAGS})
    (output / 'alignment.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>核心候选原片对齐</title><style>body{font:16px system-ui;margin:28px;background:#f6f5ef}article{background:white;padding:20px;margin:24px 0;border:1px solid #cdd8d4}img{max-width:100%}video{width:320px;max-width:100%}</style><h1>17个核心候选：原片、帧区间和骨骼来源</h1><p>这是助手核对后的候选对齐记录；未授予人工语义批准，没有模型训练。</p>'+''.join(pages)+'</html>', encoding='utf-8')
    core_manifest['evidence_files'] = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob('*'))
                                       if p.is_file() and (p.is_relative_to(output / 'core-evidence') or p.name in
                                                           ('core-alignment.json', 'coverage-ledger.json', 'alignment.html'))}
    write_json(output / 'core-manifest.json', core_manifest)
    files = sorted(p for p in output.rglob('*') if p.is_file())
    (output / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(output).as_posix()}\n' for p in files))
    print(json.dumps({'units': len(units), 'frames': sum(u['frames'] for u in units), 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repaired', required=True)
    parser.add_argument('--technical', required=True)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    build(args.repaired, args.technical, args.evidence, args.output)
