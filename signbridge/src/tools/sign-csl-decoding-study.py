"""Frozen-source study: train-only grouped manifest and dev decoding comparison.

CPU inference only. Never opens the official test split or changes weights.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unicodedata


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


u = load('sign-csl-unified.py')
err = load('sign-ce-csl-gloss-errors.py')
GATES = dict(training_started=False, test_read=False, human_approved=False, training_ready=False,
             model_training_ready=False, deployment_ready=False, can_play=False)
CONFIGS = [('greedy', 1, 0.), ('beam2_a0', 2, 0.), ('beam2_a06', 2, .6),
           ('beam4_a0', 4, 0.), ('beam4_a06', 4, .6), ('beam4_a1', 4, 1.)]


def group_partition(rows):
    seen = set(); groups = defaultdict(set); partitions = {}
    for row in rows:
        id, code = row.get('id'), row.get('source_code')
        if not isinstance(id, str) or not id or id in seen or not re.fullmatch('[A-L]', code or ''):
            raise ValueError('Invalid/duplicate identity or source code')
        text, gloss, video = u.base.normalize(row.get('text', '')), row.get('gloss_sequence'), row.get('video_sha256')
        if not text or not isinstance(gloss, list) or not gloss or not isinstance(video, str) or not video:
            raise ValueError('Invalid grouping fields')
        seen.add(id); partition = 'selection' if code == 'G' else 'holdout' if code == 'H' else 'train'
        partitions[id] = partition
        for key in [('text', text), ('gloss', tuple(gloss)), ('video', video)]:
            groups[key].add(partition)
    output = {'train': [], 'selection': [], 'holdout': []}; quarantined = []
    for row in rows:
        keys = [('text', u.base.normalize(row['text'])), ('gloss', tuple(row['gloss_sequence'])), ('video', row['video_sha256'])]
        reasons = [kind for kind, value in keys if len(groups[(kind, value)]) > 1]
        if reasons:
            quarantined.append({'id': row['id'], 'source_code': row['source_code'], 'reasons': reasons})
        else:
            output[partitions[row['id']]].append(row)
    return output, quarantined


def similarity_audit(partitions):
    """Report high text similarity and quarantine every cross-split exact digit-shape match."""
    import difflib
    def shape(text):
        return ''.join('#' if unicodedata.category(c)=='Nd' else c for c in u.base.normalize(text))
    byshape=defaultdict(list); byprefix=defaultdict(list)
    for split,rows in partitions.items():
        for row in rows:
            text=u.base.normalize(row['text']);key=shape(text)
            byshape[key].append((split,row['id']))
            byprefix[text[:3]].append((split,row['id'],text))
    shape_collisions=[{'shape':key,'members':[{'split':s,'id':i} for s,i in items]}
                      for key,items in byshape.items() if len({s for s,i in items})>1]
    similar=[]
    for items in byprefix.values():
        for i,(a,aid,at) in enumerate(items):
            for b,bid,bt in items[i+1:]:
                if a==b or abs(len(at)-len(bt))>max(len(at),len(bt))*.15:continue
                score=difflib.SequenceMatcher(None,at,bt,autojunk=False).ratio()
                if score>=.88:
                    similar.append({'first_id':aid,'first_split':a,'second_id':bid,'second_split':b,
                                    'similarity':round(score,4)})
    return {'same_digit_shape_cross_split_groups':shape_collisions,'prefix3_similarity_ge_088_pairs':similar,
            'limits':['Heuristic prefix and edit similarity only; cannot prove no semantic/template overlap.',
                      'Digit-shape collisions are excluded; similarity pairs are reported for analysis.']}


def beam_candidates(model, source, vocab, width=4, max_length=62):
    import torch
    if width not in (1, 2, 4) or not 1 <= max_length <= 62:
        raise ValueError('Invalid beam configuration')
    model.eval(); batch, size = source.size(0), len(vocab['target'])
    with torch.inference_mode():
        memory = model.encode(source).repeat_interleave(width, dim=0)
        padding = source.eq(0).repeat_interleave(width, dim=0)
        tokens = torch.full((batch, width, 1), 2, dtype=torch.long, device=source.device)
        scores = torch.full((batch, width), -torch.inf, device=source.device); scores[:, 0] = 0.
        lengths = torch.zeros((batch, width), dtype=torch.long, device=source.device)
        ended = torch.zeros((batch, width), dtype=torch.bool, device=source.device)
        for _ in range(max_length):
            logits = model.decode(tokens.reshape(batch * width, -1), memory, padding)[:, -1]
            logits[:, 0] = -torch.inf; logits[:, 2] = -torch.inf
            logp = torch.log_softmax(logits, dim=-1).reshape(batch, width, size)
            logp = logp.masked_fill(ended.unsqueeze(-1), -torch.inf)
            logp[:, :, 3] = torch.where(ended, torch.zeros_like(scores), logp[:, :, 3])
            scores, indices = (scores.unsqueeze(-1) + logp).reshape(batch, -1).topk(width, dim=-1)
            parent, token = indices // size, indices % size
            tokens = torch.cat([tokens.gather(1, parent.unsqueeze(-1).expand(-1, -1, tokens.size(-1))), token.unsqueeze(-1)], dim=-1)
            prior_ended = ended.gather(1, parent)
            lengths = lengths.gather(1, parent) + (~prior_ended).long()
            ended = prior_ended | token.eq(3)
            if bool(ended.all()):
                break
    result = []
    for batch_tokens, batch_scores, batch_lengths in zip(tokens[:, :, 1:].cpu().tolist(), scores.cpu().tolist(), lengths.cpu().tolist()):
        result.append([{'tokens': t, 'score': s, 'length': n} for t, s, n in zip(batch_tokens, batch_scores, batch_lengths)])
    return result


def select_beams(candidates, vocab, alpha):
    if alpha not in (0., .6, 1.):
        raise ValueError('Unregistered length exponent')
    output = []
    for row in candidates:
        winner = max(row, key=lambda c: c['score'] / (((5 + max(c['length'], 1)) / 6) ** alpha))
        ids = winner['tokens']
        if 3 in ids:
            ids = ids[:ids.index(3)]
        output.append([vocab['target'][i] for i in ids])
    return output


def write_sealed(output):
    u.seal(output)


def read_grouped_training(root):
    root = u.safe_path(root); manifest, consumed = u.read_manifest(root)
    report = json.loads(u.checked(root, 'report.json', manifest, consumed))
    if (report.get('schema') != 'signbridge-gloss-source-group-v1'
            or any(report.get(k) is not False for k in ['test_read', 'training_ready', 'model_training_ready', 'human_approved'])):
        raise ValueError('Invalid grouping provenance/gates')
    data, ids = {}, set()
    for split in ['train','selection']:
        content = u.checked(root, split+'.jsonl', manifest, consumed).decode('utf-8')
        rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        if len(rows) != report['counts'][split] or not rows:
            raise ValueError('Grouped split count differs')
        for row in rows:
            code, identity = row.get('source_code'), row.get('id')
            if (not isinstance(identity,str) or not identity or identity in ids or
                (code != 'G' if split == 'selection' else code not in 'ABCDEF IJKL'.replace(' ','')) or
                not row.get('text') or not isinstance(row.get('gloss_sequence'),list) or not row['gloss_sequence']):
                raise ValueError('Malformed grouped training row')
            ids.add(identity)
        data[split] = rows
    for field in ['text','video_sha256']:
        if {r[field] for r in data['train']} & {r[field] for r in data['selection']}:
            raise ValueError('Grouped train/selection overlap')
    if {tuple(r['gloss_sequence']) for r in data['train']} & {tuple(r['gloss_sequence']) for r in data['selection']}:
        raise ValueError('Grouped Gloss overlap')
    return data, {'sha256':consumed, 'report':report}


def train_grouped(grouped, output, epochs=30, patience=6, batch_size=64, seed=20261105):
    import torch
    import random
    from datetime import datetime
    grouped,output=map(u.safe_path,[grouped,output]);u.new_output(output,[grouped])
    data,provenance=read_grouped_training(grouped)
    device=u.cuda_device('cuda');torch.set_num_threads(4);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed);random.seed(seed)
    vocab=u.base.build_vocab([dict(r,proposed_text=r['text']) for r in data['train']])
    config={'width':128,'heads':4,'layers':2,'feedforward':384,'dropout':.15,'max_source':128,'max_target':64}
    model=u.base.make_model(vocab,config).to(device);initial_hash=u.base.weights_hash(model)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0002,weight_decay=.01)
    output.mkdir(parents=True);(output/'checkpoints').mkdir();u.base.write_json(output/'vocab.json',vocab)
    start=datetime.now(timezone.utc).isoformat();best=float('inf');best_epoch=0;stale=0;steps=0;history=[]
    for epoch in range(1,epochs+1):
        model.train();order=list(data['train']);random.shuffle(order);losses=[]
        for index in range(0,len(order),batch_size):
            rows=order[index:index+batch_size]
            source,target=u.task_batch(rows,'gloss',vocab,device);optimizer.zero_grad(set_to_none=True)
            loss=u.task_loss(model,source,target,'gloss')
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step();steps+=1;losses.append(float(loss.detach()))
        model.eval();predictions=[]
        for index in range(0,len(data['selection']),batch_size):
            rows=data['selection'][index:index+batch_size];source,_=u.task_batch(rows,'gloss',vocab,device)
            predictions.extend(u.base.greedy_decode(model,source,vocab,62))
        metrics=u.base.metrics([r['gloss_sequence'] for r in data['selection']],predictions)
        if metrics['gloss_error_rate']<best:
            best=metrics['gloss_error_rate'];best_epoch=epoch;stale=0
            u.save_weights(output/'checkpoints/best.pt',model)
            u.base.write_json(output/'selected-predictions.json',[{'id':r['id'],'reference':r['gloss_sequence'],'predicted':p} for r,p in zip(data['selection'],predictions)])
        else:stale+=1
        record={'epoch':epoch,'optimizer_steps':steps,'loss':sum(losses)/len(losses),'selection':metrics,'selected_epoch':best_epoch}
        history.append(record);u.base.write_json(output/'progress.json',{'status':'running',**record});print(json.dumps(record),flush=True)
        if stale>=patience:break
    checkpoint=output/'checkpoints/best.pt';checkpoint_sha=u.base.sha(checkpoint)
    report={**GATES,'schema':'signbridge-gloss-grouped-scratch-v1','status':'completed','training_started':True,
            'start_utc':start,'finished_utc':datetime.now(timezone.utc).isoformat(),'device':str(device),'gpu':torch.cuda.get_device_name(device),
            'torch':str(torch.__version__),'cuda_runtime':torch.version.cuda,'seed':seed,'initialization':'fresh_random_no_prior_checkpoint',
            'initial_weights_sha256':initial_hash,'optimizer':'AdamW','learning_rate':.0002,'epochs_completed':len(history),
            'selected_epoch':best_epoch,'optimizer_steps':steps,'checkpoint':'checkpoints/best.pt','checkpoint_sha256':checkpoint_sha,
            'vocab_source':'grouped_train_only','vocab_sizes':{k:len(v) for k,v in vocab.items()},'history':history,
            'source':provenance,'config':config,'holdout_read':False,'test_read':False,'selected_on':'G source-code selection only',
            'limitations':['Source code is not a verified signer identity.','Near duplicate isolation is not proven.',
                           'No previous checkpoint loaded; no actions, video, CSL certification or model promotion.']}
    u.base.write_json(output/'report.json',report);write_sealed(output);return report


def grouped_manifest(package, library, output):
    package, library, output = map(u.safe_path, [package, library, output])
    u.new_output(output, [package, library]); data, _, provenance = u.read_package(package)
    manifest, consumed = u.read_manifest(library)
    raw = u.checked(library, 'splits/train/samples.jsonl', manifest, consumed)
    metadata = {r['id']: r for r in (json.loads(line) for line in raw.decode().splitlines() if line.strip())}
    rows = []
    for row in data['gloss']['train']:
        source = metadata.get(row['id'])
        if (not source or source.get('source_split') != 'train' or source.get('source_translator_scope') != 'dataset_code_only_not_cross_dataset_identity'
                or u.base.normalize(source.get('proposed_text', '')) != row['text']
                or source.get('gloss_sequence') != row['gloss_sequence'] or source.get('video', {}).get('sha256') != row['video_sha256']):
            raise ValueError('Train row differs from source metadata: ' + row['id'])
        rows.append({**row, 'source_code': source['source_translator']})
    partitions, quarantine = group_partition(rows)
    original_similarity=similarity_audit(partitions)
    shape_excluded={member['id'] for item in original_similarity['same_digit_shape_cross_split_groups'] for member in item['members']}
    for split in partitions:
        quarantine.extend({'id':r['id'],'source_code':r['source_code'],'reasons':['same_digit_shape_cross_split']}
                          for r in partitions[split] if r['id'] in shape_excluded)
        partitions[split]=[r for r in partitions[split] if r['id'] not in shape_excluded]
    residual_similarity=similarity_audit(partitions)
    if any(not group for group in partitions.values()):
        raise ValueError('Empty grouped partition')
    for field in ['text', 'video_sha256']:
        sets = [{r[field] for r in group} for group in partitions.values()]
        if any(sets[i] & sets[j] for i in range(3) for j in range(i)):
            raise ValueError('Cross-group ' + field)
    sequences = [{tuple(r['gloss_sequence']) for r in group} for group in partitions.values()]
    if any(sequences[i] & sequences[j] for i in range(3) for j in range(i)):
        raise ValueError('Cross-group Gloss sequence')
    output.mkdir(parents=True)
    for name, group in partitions.items():
        (output / (name + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in group))
    u.base.write_json(output/'quarantine.json', quarantine)
    u.base.write_json(output/'similarity-audit.json',{'initial':original_similarity,'remaining':residual_similarity})
    report = {**GATES, 'schema':'signbridge-gloss-source-group-v1', 'created_at_utc':datetime.now(timezone.utc).isoformat(),
              'source_counts':dict(sorted(Counter(r['source_code'] for r in rows).items())),
              'counts':{k:len(v) for k,v in partitions.items()}, 'quarantined':len(quarantine),
              'source_codes':{'selection':['G'],'holdout':['H'],'train':sorted(set(r['source_code'] for r in partitions['train']))},
              'quarantine_policy':'Exclude every record whose exact normalized text, raw Gloss sequence or video digest crosses partitions.',
              'corpus_provenance':provenance['sha256'], 'source_metadata_sha256':consumed,
              'signer_identity_verified':False, 'future_fresh_train_only':True, 'old_checkpoints_saw_train_split':True,
              'holdout_independent_for_old_checkpoint':False, 'near_duplicates_proven_absent':False,
              'digit_shape_quarantined':len(shape_excluded),'remaining_near_duplicate_pairs':len(residual_similarity['prefix3_similarity_ge_088_pairs']),
              'limitations':['Source code is not verified signer identity.', 'Only exact collisions are isolated; near duplicates are not proven absent.',
                             'Old checkpoints trained on this pool; this holdout is valid only for a future independently initialized experiment.',
                             'No official test samples read; no new human sign-label approval.']}
    u.base.write_json(output/'report.json', report); write_sealed(output); return report


def freeze_dev(package, output):
    package, output = map(u.safe_path, [package, output]); u.new_output(output, [package])
    data, _, provenance = u.read_package(package); rows = data['gloss']['dev']
    # Connected components prevent exact duplicate text, Gloss or video crossing the two slices.
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    keys = {}
    for i, row in enumerate(rows):
        for k in [('text', u.base.normalize(row['text'])), ('gloss', tuple(row['gloss_sequence']))] + ([('video', row['video_sha256'])] if row.get('video_sha256') else []):
            if k in keys: parent[find(i)] = find(keys[k])
            else: keys[k] = i
    groups = defaultdict(list)
    for i, row in enumerate(rows): groups[find(i)].append(row['id'])
    parts = {'selection': [], 'comparison': []}
    for ids in groups.values():
        key = '\n'.join(sorted(ids)).encode(); bucket = int(hashlib.sha256(key).hexdigest()[:8], 16) % 2
        parts['selection' if bucket == 0 else 'comparison'].extend(sorted(ids))
    if any(not x for x in parts.values()): raise ValueError('Empty dev split')
    for k in parts: parts[k].sort()
    output.mkdir(parents=True)
    result = {**GATES, 'schema':'signbridge-decode-dev-freeze-v1', 'split':parts, 'configs':CONFIGS,
              'selection_rule':'minimum selection Gloss error rate, ties favor earliest registered config',
              'prior_model_has_seen_dev':True, 'independent_test':False, 'package_sha256':provenance['sha256'],
              'limitations':['Old checkpoint and dev have historical overlap; comparison is development-only.',
                             'The later comparison slice is not an independent test.', 'Raw Gloss labels are never merged.']}
    u.base.write_json(output/'split.json',result);write_sealed(output);return {k:len(v) for k,v in parts.items()}


def decode_evaluate(package, model_root, frozen, output, batch_size=32):
    package, model_root, frozen, output = map(u.safe_path,[package,model_root,frozen,output])
    u.new_output(output,[package,model_root,frozen]); data, _, provenance = u.read_package(package)
    manifest, used = u.read_manifest(frozen)
    split = json.loads(u.checked(frozen,'split.json',manifest,used))
    if split.get('schema') != 'signbridge-decode-dev-freeze-v1' or split.get('configs') != [list(c) for c in CONFIGS] or split.get('package_sha256') != provenance['sha256']:
        raise ValueError('Frozen plan, configs or package mismatched')
    rows = data['gloss']['dev']; ids = {r['id'] for r in rows}
    selection, comparison = set(split['split']['selection']), set(split['split']['comparison'])
    if selection & comparison or selection | comparison != ids: raise ValueError('Dev split identity mismatch')
    meta, vocab, labels, model, model_hashes = u.load_predictor(model_root)
    source_manifest, consumed = u.read_manifest(model_root)
    saved = json.loads(u.checked(model_root, 'selected-dev-predictions.json', source_manifest, consumed))['gloss']
    if len(saved) != len(rows) or any(x['id'] != r['id'] or x['reference'] != r['gloss_sequence'] or x['text'] != r['text'] for x,r in zip(saved,rows)):
        raise ValueError('Saved baseline dev prediction alignment differs')
    def run(part, all_configs):
        subset = [r for r in rows if r['id'] in part]; preds = {name:[] for name,_,_ in all_configs}
        for start in range(0,len(subset),batch_size):
            batch = subset[start:start+batch_size]; source,_ = u.task_batch(batch,'gloss',vocab,'cpu')
            bywidth = {}
            for name,width,alpha in all_configs:
                if width not in bywidth: bywidth[width] = beam_candidates(model,source,vocab,width,62)
                preds[name].extend(select_beams(bywidth[width],vocab,alpha))
        references = [r['gloss_sequence'] for r in subset]
        results = {name:u.base.metrics(references,prediction) for name,prediction in preds.items()}
        saved_by_id = {p['id']:p['predicted'] for p in saved}
        if 'greedy' in preds and preds['greedy'] != [saved_by_id[r['id']] for r in subset]:
            raise ValueError('Greedy baseline differs from previously saved GPU predictions')
        for name,predictions in preds.items():
            for row,p in zip(subset,predictions):
                yield name,row,p,results[name]
    sel_records = list(run(selection,CONFIGS)); metrics = {name:score for name,_,_,score in sel_records}
    winner = min(CONFIGS, key=lambda c:(metrics[c[0]]['gloss_error_rate'], [x[0] for x in CONFIGS].index(c[0])))
    comp_configs = [CONFIGS[0]] if winner[0]=='greedy' else [CONFIGS[0],winner]
    comp_records = list(run(comparison,comp_configs)); comp_metrics = {name:score for name,_,_,score in comp_records}
    from collections import Counter as Counts
    frequencies = Counts(t for r in data['gloss']['train'] for t in r['gloss_sequence'])
    slices = {}
    for name in [x[0] for x in comp_configs]:
        selected = [(r,p) for n,r,p,_ in comp_records if n==name]
        groups = {'all':selected, 'negation':[(r,p) for r,p in selected if any(t in ('不','没','没有','不是','不能','不想') for t in r['gloss_sequence'])],
                  'rare_label_le2':[(r,p) for r,p in selected if any(0<frequencies[t]<=2 for t in r['gloss_sequence'])],
                  'person':[(r,p) for r,p in selected if any(t in ('我','你','他','她','我们','你们','他们') for t in r['gloss_sequence'])]}
        slices[name] = {k:u.base.metrics([r['gloss_sequence'] for r,p in items],[p for r,p in items]) for k,items in groups.items()}
    output.mkdir(parents=True)
    report = {**GATES, 'schema':'signbridge-decode-study-v1', 'status':'completed', 'device':'cpu_inference_only',
              'frozen_split_sha256':u.base.sha(frozen/'split.json'), 'model_sha256':model_hashes, 'package_sha256':provenance['sha256'],
              'selection':metrics, 'selected_config':winner, 'comparison':comp_metrics, 'comparison_slices':slices,
              'comparison_independent_test':False, 'official_test_opened':False,
              'limitations':['Selection and comparison derive from historically used dev; no independent generalization claim.',
                             'Beam pruning uses cumulative log probability; length normalization is final hypothesis reranking.',
                             'Unknown characters map to <unk> in batch metrics while public research inference abstains.']}
    u.base.write_json(output/'report.json',report)
    (output/'predictions.jsonl').write_text(''.join(json.dumps({'partition':'selection' if row['id'] in selection else 'comparison',
        'id':row['id'],'config':name,'reference':row['gloss_sequence'],'predicted':prediction},ensure_ascii=False)+'\n'
        for name,row,prediction,_ in sel_records+comp_records))
    write_sealed(output);return {'selected_config':winner,'selection':metrics,'comparison':comp_metrics}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    for name,fields in [('grouped',['package','library','output']),('freeze-dev',['package','output']),('decode',['package','model-root','frozen','output']),('train-grouped',['grouped','output'])]:
        p=sub.add_parser(name)
        for field in fields: p.add_argument('--'+field,type=Path,required=True)
    args=parser.parse_args()
    if args.command=='grouped': result=grouped_manifest(args.package,args.library,args.output)
    elif args.command=='freeze-dev': result=freeze_dev(args.package,args.output)
    elif args.command=='decode': result=decode_evaluate(args.package,args.model_root,args.frozen,args.output)
    else: result=train_grouped(args.grouped,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
