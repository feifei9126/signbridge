"""CUDA-only 32-train-sentence character Gloss memorization diagnostic.

Never opens G, H or official test. Passing means train-subset memorization only.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),Path(__file__).with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


c=load('sign-csl-character-gloss.py')
u=c.u
SCHEMA='signbridge-tiny32-gloss-v1'
SETTINGS={'sample_count':32,'seed':20261106,'max_steps':1000,'evaluate_every':25,
          'learning_rate':.001,'batch_size':32,'label_smoothing':.05,'min_exact':31}
GROUPS=['source_embedding','target_embedding','encoder','decoder','output']


def row_hash(row):
    return hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def check_settings(settings):
    if settings!=SETTINGS:raise ValueError('Frozen diagnostic settings differ')


def choose(rows):
    variants=defaultdict(set);ids=set()
    for row in rows:
        if not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:
            raise ValueError('Invalid/duplicate train identity')
        ids.add(row['id']);c.encode_gloss(row['gloss_sequence'])
        variants[u.base.normalize(row['text'])].add(tuple(row['gloss_sequence']))
    conflicts={text for text,values in variants.items() if len(values)>1}
    order=sorted(rows,key=lambda r:hashlib.sha256((str(SETTINGS['seed'])+'|'+r['id']).encode()).hexdigest())
    sample=[];seen=set();duplicate=[]
    for row in order:
        text=u.base.normalize(row['text'])
        if text in conflicts:continue
        if text in seen:duplicate.append(row['id']);continue
        seen.add(text);sample.append(row)
    if len(sample)<32:raise ValueError('Fewer than 32 unique nonconflicting train sentences')
    return sample[:32],{'conflicting_text_ids':sorted(r['id'] for r in rows if u.base.normalize(r['text']) in conflicts),
                       'same_text_duplicate_ids':duplicate,'eligible_unique_rows':len(sample)}


def prepare(source,output):
    source,output=map(u.safe_path,[source,output])
    if output.exists():raise FileExistsError('Choose a NEW diagnostic directory')
    u.new_output(output,[source]);manifest,used=u.read_manifest(source)
    report=json.loads(u.checked(source,'report.json',manifest,used))
    if (report.get('schema')!='signbridge-gloss-source-group-v1'
            or any(report.get(k) is not False for k in ['test_read','training_ready','model_training_ready','human_approved'])):
        raise ValueError('Invalid source provenance/gates')
    content=u.checked(source,'train.jsonl',manifest,used)
    rows=[json.loads(line) for line in content.decode().splitlines() if line.strip()]
    if len(rows)!=report['counts']['train']:raise ValueError('Source train count differs')
    for row in rows:
        if (row.get('source_code') not in list('ABCDEFIJKL') or row.get('task')!='gloss'
                or row.get('label_source')!='ce_csl_dataset' or row.get('human_approved') is not False
                or not isinstance(row.get('text'),str) or not row['text'] or row['text']!=u.base.normalize(row['text'])):
            raise ValueError('Unexpected training row provenance')
        c.encode_gloss(row['gloss_sequence'])
    sample,excluded=choose(rows);vocab=c.build_vocab(rows)
    for row in sample:
        if len(c.encode_gloss(row['gloss_sequence']))+2>c.CONFIG['max_target']:raise ValueError('Target length exceeds config')
        if len(row['text'])+2>c.CONFIG['max_source']:raise ValueError('Source length exceeds config')
    plan={**u.GATES,'schema':SCHEMA,'training_started':False,'created_at_utc':datetime.now(timezone.utc).isoformat(),
          'settings':SETTINGS,'config':c.CONFIG,'source_count':len(rows),'source_hashes':used,
          'source_train_sha256':used['train.jsonl'],'selection_rule':'SHA256(seed|id) order, unique normalized text, conflicting targets excluded',
          'sample_ids':[r['id'] for r in sample],'sample_hashes':{r['id']:row_hash(r) for r in sample},
          'excluded':excluded,'vocabulary_source':'full_original_train_only_not_G_H_test',
          'holdout_H_read':False,'G_selection_read':False,'official_test_read':False,'generalization_evaluated':False,
          'success_definition':'At least31/32 exact raw Gloss, all EOS/boundaries valid, finite nonzero gradients and changed parameters in all five groups.',
          'limitations':['This uses the same samples for training and evaluation and measures memorization only.',
                         'Diagnostic lr differs from full training; passing does not validate the full run optimizer schedule.',
                         'No hand motion, CSL semantic approval, independent recognition or generalization claim.']}
    output.mkdir(parents=True)
    (output/'samples.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in sample))
    u.base.write_json(output/'vocab.json',vocab);u.base.write_json(output/'plan.json',plan);u.seal(output)
    return plan


def read_prepared(root):
    root=u.safe_path(root);manifest,used=u.read_manifest(root)
    plan=json.loads(u.checked(root,'plan.json',manifest,used));check_settings(plan.get('settings'))
    if (plan.get('schema')!=SCHEMA or plan.get('config')!=c.CONFIG
        or any(plan.get(k) is not False for k in ['test_read','holdout_H_read','G_selection_read','official_test_read','human_approved','training_ready','model_training_ready','deployment_ready','can_play','generalization_evaluated'])):
        raise ValueError('Diagnostic plan contract differs')
    rows=[json.loads(line) for line in u.checked(root,'samples.jsonl',manifest,used).decode().splitlines() if line.strip()]
    if len(rows)!=32 or [r['id'] for r in rows]!=plan['sample_ids'] or len({r['text'] for r in rows})!=32:
        raise ValueError('Diagnostic sample identities/count differ')
    if {r['id']:row_hash(r) for r in rows}!=plan['sample_hashes']:raise ValueError('Frozen sample targets differ')
    vocab=json.loads(u.checked(root,'vocab.json',manifest,used));u.validate_vocab(vocab)
    if c.END not in vocab['target']:raise ValueError('Missing Gloss boundary vocabulary')
    for row in rows:
        if row['source_code'] not in list('ABCDEFIJKL'):raise ValueError('Forbidden source split')
        if set(row['text'])-set(vocab['source']) or set(c.encode_gloss(row['gloss_sequence']))-set(vocab['target']):
            raise ValueError('OOV in selected training examples')
    return rows,vocab,plan


def forced_stats(logits,target):
    import torch
    expected=target[:,1:];valid=expected.ne(0);pred=logits.argmax(-1);good=pred.eq(expected)
    tokens=int(valid.sum());correct=int((good&valid).sum())
    return {'tokens':tokens,'correct_tokens':correct,'token_accuracy':correct/tokens,
            'exact_sequences':int((good|~valid).all(dim=1).sum()),'samples':target.size(0),
            'mean_token_nll':float(torch.nn.functional.cross_entropy(logits.flatten(0,1),expected.reshape(-1),ignore_index=0))}


def passed(metrics,gradient_and_parameter_checks):
    return (metrics['raw_gloss']['samples']==32 and metrics['raw_gloss']['exact_matches']>=31
            and metrics['malformed_rows']==0 and metrics['missing_eos_rows']==0
            and metrics['empty_prediction_rows']==0 and gradient_and_parameter_checks)


def checkpoint_key(metrics,gradient_and_parameter_checks):
    return (passed(metrics,gradient_and_parameter_checks),metrics['raw_gloss']['exact_matches'],
            -metrics['malformed_rows'],-metrics['empty_prediction_rows'],-metrics['raw_gloss']['gloss_error_rate'])


def group_name(name):
    if name.startswith(('source.','source_position.')):return 'source_embedding'
    if name.startswith(('target.','target_position.')):return 'target_embedding'
    if name.startswith('transformer.encoder.'):return 'encoder'
    if name.startswith('transformer.decoder.'):return 'decoder'
    if name.startswith('output.'):return 'output'
    raise ValueError('Unclassified parameter: '+name)


def group_hashes(model):
    digests={name:hashlib.sha256() for name in GROUPS}
    for name,tensor in sorted(model.state_dict().items()):
        digest=digests[group_name(name)];digest.update(name.encode());digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return {name:d.hexdigest() for name,d in digests.items()}


def train(prepared,output):
    import torch
    device=u.cuda_device('cuda');prepared,output=map(u.safe_path,[prepared,output]);u.new_output(output,[prepared])
    rows,vocab,plan=read_prepared(prepared);settings=plan['settings']
    torch.set_num_threads(4);torch.manual_seed(settings['seed']);torch.cuda.manual_seed_all(settings['seed'])
    model=u.base.make_model(vocab,c.CONFIG).to(device);initial=u.base.weights_hash(model);initial_groups=group_hashes(model)
    optimizer=torch.optim.AdamW(model.parameters(),lr=settings['learning_rate'],weight_decay=.01)
    source,target=c.character_batch(rows,vocab,device);output.mkdir(parents=True);(output/'checkpoints').mkdir()
    u.base.write_json(output/'vocab.json',vocab)
    report={**u.GATES,'schema':SCHEMA,'status':'running','started_at_utc':datetime.now(timezone.utc).isoformat(),
        'training_started':True,'settings':settings,'config':c.CONFIG,'sample_ids':[r['id'] for r in rows],
        'prepared_manifest_sha256':u.base.sha(prepared/'SHA256SUMS'),'plan_sha256':u.base.sha(prepared/'plan.json'),
        'initial_weights_sha256':initial,'initial_group_hashes':initial_groups,'optimizer_steps':0,'history':[],
        'gradient_groups':{key:{'finite':True,'nonzero_seen':False,'max_abs_sum':0.} for key in GROUPS},
        'runtime':{'python':sys.version,'torch':str(torch.__version__),'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(device),
                   'executable':sys.executable,'actual_model_device':str(next(model.parameters()).device)},
        'holdout_H_read':False,'G_selection_read':False,'official_test_read':False,'generalization_evaluated':False,'promoted':False}
    u.base.write_json(output/'report.json',report)
    best_key=None;best_step=0;best_record=None;checks=False;goal=False;step=0
    try:
        for step in range(settings['max_steps']+1):
            if step:
                model.train();optimizer.zero_grad(set_to_none=True);logits=model(source,target[:,:-1])
                loss=torch.nn.functional.cross_entropy(logits.flatten(0,1),target[:,1:].reshape(-1),ignore_index=0,label_smoothing=settings['label_smoothing'])
                if not torch.isfinite(loss):raise ValueError('Nonfinite diagnostic loss')
                loss.backward();grad={key:0. for key in GROUPS}
                for name,param in model.named_parameters():
                    if param.grad is None:continue
                    if not torch.isfinite(param.grad).all():raise ValueError('Nonfinite gradient: '+name)
                    grad[group_name(name)]+=float(param.grad.detach().abs().sum())
                for key,total in grad.items():
                    slot=report['gradient_groups'][key];slot['nonzero_seen']|=total>0;slot['max_abs_sum']=max(slot['max_abs_sum'],total)
                torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            if step%settings['evaluate_every'] and step!=settings['max_steps']:continue
            model.eval()
            with torch.no_grad():forced=forced_stats(model(source,target[:,:-1]),target)
            predictions=c.generate(model,rows,vocab,device,32);raw=c.metrics(rows,predictions)
            current_groups=group_hashes(model);changed={key:current_groups[key]!=initial_groups[key] for key in GROUPS}
            checks=all(v['finite'] and v['nonzero_seen'] for v in report['gradient_groups'].values()) and all(changed.values())
            goal=passed(raw,checks)
            record={'step':step,'teacher_forced':forced,'free_generation':raw,'parameter_groups_changed':changed,'gradient_and_update_checks':checks,'memorization_gate_passed':goal}
            report['history'].append(record)
            key=checkpoint_key(raw,checks)
            if best_key is None or key>best_key:
                best_key=key;best_step=step;best_record=record;u.save_weights(output/'checkpoints/best.pt',model)
                u.base.write_json(output/'best-predictions.json',predictions)
            u.save_recovery(output/'checkpoints/recovery-last.pt',model,optimizer,step,step,{'best_step':best_step,'goal':goal})
            report.update(optimizer_steps=step,best_step=best_step,latest=record)
            u.base.write_json(output/'report.json',report);print(json.dumps(record),flush=True)
            if goal:break
        u.save_weights(output/'checkpoints/last.pt',model);u.base.write_json(output/'last-predictions.json',predictions)
        report.update(status='completed',finished_at_utc=datetime.now(timezone.utc).isoformat(),optimizer_steps=step,
            diagnostic_passed=goal,best_step=best_step,best_evaluation=best_record,checkpoint='checkpoints/best.pt',
            checkpoint_sha256=u.base.sha(output/'checkpoints/best.pt'),last_checkpoint_sha256=u.base.sha(output/'checkpoints/last.pt'),
            last_weights_sha256=u.base.weights_hash(model),last_group_hashes=group_hashes(model))
        u.base.write_json(output/'report.json',report);u.seal(output)
    except Exception as error:
        report.update(status='failed',error=repr(error),optimizer_steps=step);u.base.write_json(output/'report.json',report);u.seal(output);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('train');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=prepare(args.source,args.output) if args.command=='prepare' else train(args.prepared,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
