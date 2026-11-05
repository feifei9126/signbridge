"""Character Gloss research with explicit boundaries; raw label identities stay exact.

Train is CUDA-only. CPU may prepare data or reproduce inference, never optimize.
The previously used H holdout and official test are never opened by this tool.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


study = load('sign-csl-decoding-study.py')
u = study.u
END = '<gloss_end>'
INVALID = '<invalid_gloss>:'
SCHEMA = 'signbridge-character-gloss-v1'
CONFIG = {'width':128, 'heads':4, 'layers':2, 'feedforward':384,
          'dropout':.15, 'max_source':128, 'max_target':64}


def encode_gloss(labels):
    if (not isinstance(labels,list) or not labels or any(not isinstance(t,str) or not t
            or t in u.base.SPECIALS + [END] or t.startswith(INVALID) for t in labels)):
        raise ValueError('Invalid raw Gloss label list')
    return [token for label in labels for token in [*label, END]]


def decode_gloss(tokens):
    labels, errors, buffer, bad = [], [], [], False
    for token in tokens:
        if token == END:
            if not buffer:
                errors.append('empty_gloss'); labels.append(INVALID+'empty')
            else:
                text = ''.join(buffer)
                labels.append(INVALID+text if bad else text)
            buffer, bad = [], False
        elif not isinstance(token,str) or len(token) != 1:
            errors.append('invalid_character_token'); buffer.append(str(token)); bad = True
        else:
            buffer.append(token)
    if buffer:
        labels.append(INVALID+''.join(buffer)); errors.append('missing_word_boundary')
    return {'gloss':labels, 'errors':sorted(set(errors))}


def build_vocab(train):
    for row in train:
        encode_gloss(row['gloss_sequence'])
    return {'source':u.base.SPECIALS + sorted({c for r in train for c in u.base.normalize(r['text'])}),
            'target':u.base.SPECIALS + [END] + sorted({c for r in train for t in r['gloss_sequence'] for c in t})}


def representation_stats(train, selection):
    labels = {t for r in train for t in r['gloss_sequence']}
    chars = {c for t in labels for c in t}
    sources = {c for r in train for c in u.base.normalize(r['text'])}
    target = [t for r in selection for t in r['gloss_sequence']]
    unseen = set(target)-labels
    lengths = lambda rows: [len(encode_gloss(r['gloss_sequence']))+2 for r in rows]
    unknown = sorted({c for t in target for c in t}-chars)
    return {'train_samples':len(train), 'selection_samples':len(selection), 'train_whole_gloss_types':len(labels),
            'train_target_character_types':len(chars), 'unseen_whole_gloss_types':len(unseen),
            'unseen_whole_gloss_occurrences':sum(t not in labels for t in target),
            'unseen_whole_gloss_types_composable_from_train_characters':sum(set(t)<=chars for t in unseen),
            'unseen_target_character_types':len(unknown), 'unseen_target_characters':unknown,
            'selection_rows_with_unknown_target_character':sum(any(c not in chars for t in r['gloss_sequence'] for c in t) for r in selection),
            'selection_rows_with_unknown_source_character':sum(any(c not in sources for c in u.base.normalize(r['text'])) for r in selection),
            'max_train_encoded_target_length_with_bos_eos':max(lengths(train)),
            'max_selection_encoded_target_length_with_bos_eos':max(lengths(selection)),
            'note':'Composable labels are representable, not demonstrated correct predictions.'}


def load_data(root):
    data, provenance = study.read_grouped_training(root)
    for rows in data.values():
        for row in rows:
            encode_gloss(row['gloss_sequence'])
            if row['text'] != u.base.normalize(row['text']):
                raise ValueError('Unexpected source normalization')
    return data, provenance


def character_batch(rows, vocab, device, max_target=64):
    mapped = []
    for row in rows:
        encoded = encode_gloss(row['gloss_sequence'])
        if len(encoded)+2 > max_target or len(u.base.normalize(row['text']))+2 > CONFIG['max_source']:
            raise ValueError('Encoded length exceeds fixed config; no truncation')
        mapped.append(dict(row, proposed_text=row['text'], gloss_sequence=encoded))
    return u.base.batch_tensors(mapped,vocab,device)


def generate(model, rows, vocab, device, batch_size=64):
    import torch
    predictions = []; model.eval()
    with torch.inference_mode():
        for start in range(0,len(rows),batch_size):
            batch=rows[start:start+batch_size]
            source,_=character_batch(batch,vocab,device)
            memory=model.encode(source)
            target=torch.full((len(batch),1),2,dtype=torch.long,device=device)
            done=torch.zeros(len(batch),dtype=torch.bool,device=device)
            # A maximum accepted target is BOS + 62 content tokens + EOS.
            # The 63rd generation step must remain available for EOS.
            for _ in range(CONFIG['max_target']-1):
                logits=model.decode(target,memory,source.eq(0))[:,-1]
                logits[:,0]=-torch.inf;logits[:,2]=-torch.inf
                token=logits.argmax(-1);token=torch.where(done,torch.full_like(token,3),token)
                target=torch.cat([target,token[:,None]],dim=1);done=done|token.eq(3)
                if bool(done.all()): break
            for row,ids in zip(batch,target[:,1:].cpu().tolist()):
                terminated=3 in ids
                if terminated: ids=ids[:ids.index(3)]
                tokens=[vocab['target'][i] for i in ids];decoded=decode_gloss(tokens)
                if not terminated:
                    decoded['errors'].append('missing_eos');decoded['gloss'].append(INVALID+'eos')
                predictions.append({'id':row['id'],'text':row['text'],'reference':row['gloss_sequence'],
                    'predicted':decoded['gloss'],'target_character_tokens':tokens,'terminated':terminated,
                    'representation_errors':sorted(set(decoded['errors']))})
    return predictions


def metrics(rows, predictions):
    if len(rows)!=len(predictions) or any(r['id']!=p['id'] or r['gloss_sequence']!=p['reference'] for r,p in zip(rows,predictions)):
        raise ValueError('Prediction IDs or reference labels differ')
    def score(indices):
        return u.base.metrics([rows[i]['gloss_sequence'] for i in indices],[predictions[i]['predicted'] for i in indices])
    indices=list(range(len(rows)))
    families={'all':indices,'negation':[i for i,r in enumerate(rows) if any(study.err.variant_surface(t) in ('不','没','没有','不是','不能','不要','不想','不用') for t in r['gloss_sequence'])],
              'person':[i for i,r in enumerate(rows) if any(t in ('我','你','他','她','我们','你们','他们') for t in r['gloss_sequence'])]}
    return {'raw_gloss':score(indices), 'slices':{name:score(ids) for name,ids in families.items()},
            'malformed_rows':sum(bool(p.get('representation_errors')) for p in predictions),
            'empty_prediction_rows':sum(not p['predicted'] for p in predictions),
            'missing_eos_rows':sum(not p.get('terminated',True) for p in predictions)}


def checked_baseline(root, data, grouped_provenance):
    root=u.safe_path(root);manifest,used=u.read_manifest(root)
    report=json.loads(u.checked(root,'report.json',manifest,used))
    saved=json.loads(u.checked(root,'selected-predictions.json',manifest,used))
    if report.get('schema')!='signbridge-gloss-grouped-scratch-v1' or report.get('status')!='completed' or report.get('initialization')!='fresh_random_no_prior_checkpoint':
        raise ValueError('Expected completed grouped whole-Gloss baseline')
    if (report.get('config')!=CONFIG or report.get('seed')!=20261105 or report.get('optimizer')!='AdamW'
            or report.get('learning_rate')!=.0002):
        raise ValueError('Baseline ablation configuration differs')
    # Older report omitted max epochs, patience and batch. Bind those settings
    # to its sealed input plan and actual CLI invocation, not guessed defaults.
    run=root.parent;seal_path=u.safe_path(run/'EVIDENCE-SHA256SUMS')
    run_manifest={}
    for line in seal_path.read_text().splitlines():
        digest,name=line.split('  ',1)
        if name in run_manifest:raise ValueError('Duplicate run evidence entry')
        run_manifest[name]=digest
    if run_manifest.get((root.relative_to(run)/'report.json').as_posix())!=used['report.json']:
        raise ValueError('Baseline report not bound to sealed run')
    plan_name='gpu-prepared-v2/launch-config.json'
    launch_plan=json.loads(u.checked(run,plan_name,run_manifest,used))
    launch=json.loads(u.checked(run,'launch.json',run_manifest,used))
    if ((launch_plan.get('epochs'),launch_plan.get('patience'),launch_plan.get('batch_size'),
         launch_plan.get('seed'),launch_plan.get('learning_rate'))!=(30,6,64,20261105,.0002)
            or launch_plan.get('initialization')!='fresh_random_no_prior_checkpoint'):
        raise ValueError('Baseline schedule differs from planned character ablation')
    command=launch.get('command',[])
    if (len(command)!=7 or Path(command[1]).name!='sign-csl-decoding-study.py'
            or command[2:4]!=['train-grouped','--grouped'] or command[5]!='--output'):
        raise ValueError('Baseline schedule CLI override or different trainer')
    used['EVIDENCE-SHA256SUMS']=u.base.sha(seal_path)
    for name in ['train.jsonl','selection.jsonl']:
        if report['source']['sha256'][name]!=grouped_provenance['sha256'][name]:
            raise ValueError('Baseline and character experiment data differ')
    computed=metrics(data['selection'],saved)
    if computed['raw_gloss']!=report['history'][report['selected_epoch']-1]['selection']:
        raise ValueError('Baseline metrics differ')
    return report,saved,used,computed


def prepare(grouped,baseline,output):
    grouped,baseline,output=map(u.safe_path,[grouped,baseline,output]);u.new_output(output,[grouped,baseline])
    data,provenance=load_data(grouped)
    report,saved,baseline_hashes,baseline_metrics=checked_baseline(baseline,data,provenance)
    stats=representation_stats(data['train'],data['selection']);vocab=build_vocab(data['train'])
    for rows in data.values():
        for start in range(0,len(rows),64):
            # Validate lengths without importing a training runtime or creating tensors.
            if any(len(encode_gloss(r['gloss_sequence']))+2>CONFIG['max_target'] for r in rows[start:start+64]):
                raise ValueError('Fixed character target length exceeded')
    output.mkdir(parents=True);inputs=output/'input';inputs.mkdir()
    for name in ['train.jsonl','selection.jsonl','report.json']:
        shutil.copyfile(grouped/name,inputs/name)
    u.seal(inputs)
    experiment={**u.GATES,'schema':SCHEMA,'status':'prepared_not_started','training_started':False,
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'representation':'Unicode characters, one separate gloss_end token after each raw label',
        'raw_label_normalization':'none; number/variant/punctuation identities preserved','vocab_source':'train_only',
        'config':CONFIG,'seed':20261105,'epochs':30,'patience':6,'batch_size':64,'learning_rate':.0002,
        'initialization':'fresh_random_no_checkpoint','selection':'minimum raw reconstructed Gloss GER on G, earliest tie',
        'only_intended_model_change':'character target and boundary representation; vocabulary/parameter count consequently differ',
        'data_hashes':provenance['sha256'],'baseline_hashes':baseline_hashes,'statistics':stats,
        'baseline_selection_metrics':baseline_metrics,'holdout_H_included':False,'holdout_H_may_be_reused':False,
        'promotion_constraints':['Overall raw Gloss GER must not regress vs same G baseline.',
                                'Person and negation slices must not regress; malformed outputs must be exposed.',
                                'G has been used for development, no independent generalization claim and no automatic Demo integration.'],
        'limitations':['This fills the previously unimplemented character experiment; old whole-label run is only its baseline.',
                       'Character composition improves representability only; unseen characters remain OOV.',
                       'H was evaluated previously; neither its samples nor predictions are used here.',
                       'Malformed segments score as explicit invalid Gloss labels; empty outputs count deletions.']}
    u.base.write_json(output/'experiment.json',experiment);u.base.write_json(output/'vocab.json',vocab)
    u.base.write_json(output/'baseline-selection-predictions.json',saved);u.seal(output)
    return experiment


def read_prepared(root):
    root=u.safe_path(root);manifest,used=u.read_manifest(root)
    plan=json.loads(u.checked(root,'experiment.json',manifest,used))
    if (plan.get('schema')!=SCHEMA or plan.get('config')!=CONFIG or plan.get('seed')!=20261105
            or plan.get('holdout_H_included') is not False or plan.get('holdout_H_may_be_reused') is not False
            or any(plan.get(k) is not False for k in ['test_read','human_approved','training_ready','model_training_ready','deployment_ready','can_play'])
            or (plan.get('epochs'),plan.get('patience'),plan.get('batch_size'),plan.get('learning_rate'))!=(30,6,64,.0002)
            or plan.get('initialization')!='fresh_random_no_checkpoint'):
        raise ValueError('Prepared experiment contract differs')
    data,provenance=load_data(root/'input')
    for name in ['train.jsonl','selection.jsonl']:
        if provenance['sha256'][name]!=plan['data_hashes'][name]:raise ValueError('Prepared data changed')
    vocab=json.loads(u.checked(root,'vocab.json',manifest,used))
    if vocab!=build_vocab(data['train']):raise ValueError('Vocabulary not train-only')
    saved=json.loads(u.checked(root,'baseline-selection-predictions.json',manifest,used))
    if metrics(data['selection'],saved)!=plan['baseline_selection_metrics']:
        raise ValueError('Baseline targets or metrics differ')
    return data,vocab,plan,{'prepared':used,'grouped':provenance['sha256']}


def train(prepared,output):
    import torch
    device=u.cuda_device('cuda')
    prepared,output=map(u.safe_path,[prepared,output]);u.new_output(output,[prepared])
    data,vocab,plan,provenance=read_prepared(prepared)
    torch.set_num_threads(4);torch.manual_seed(plan['seed']);torch.cuda.manual_seed_all(plan['seed']);random.seed(plan['seed'])
    model=u.base.make_model(vocab,CONFIG).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=plan['learning_rate'],weight_decay=.01)
    output.mkdir(parents=True);(output/'checkpoints').mkdir()
    u.base.write_json(output/'vocab.json',vocab)
    report={**u.GATES,'schema':SCHEMA,'status':'running','training_started':True,
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'config':CONFIG,'experiment':plan,
        'source_hashes':provenance,'initial_weights_sha256':u.base.weights_hash(model),
        'runtime':{'python':sys.version,'executable':sys.executable,'torch':str(torch.__version__),
            'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(device),'actual_model_device':str(next(model.parameters()).device)},
        'tool_sha256':{Path(p).name:u.base.sha(Path(p)) for p in [__file__,study.__file__,u.__file__,u.base.__file__,study.err.__file__]},
        'parameters':sum(p.numel() for p in model.parameters()),'optimizer_steps':0,'history':[],
        'holdout_H_read':False,'test_read':False,'promoted':False}
    u.base.write_json(output/'report.json',report)
    best=float('inf');best_epoch=stale=steps=0;best_metrics=None
    try:
        for epoch in range(1,plan['epochs']+1):
            model.train();order=list(data['train']);random.shuffle(order);losses=[]
            for start in range(0,len(order),plan['batch_size']):
                source,target=character_batch(order[start:start+plan['batch_size']],vocab,device)
                optimizer.zero_grad(set_to_none=True)
                logits=model(source,target[:,:-1])
                loss=torch.nn.functional.cross_entropy(logits.flatten(0,1),target[:,1:].reshape(-1),ignore_index=0,label_smoothing=.05)
                if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
                loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step();steps+=1;losses.append(float(loss.detach()))
            predictions=generate(model,data['selection'],vocab,device,plan['batch_size'])
            evaluated=metrics(data['selection'],predictions);score=evaluated['raw_gloss']['gloss_error_rate']
            if score<best:
                best,best_epoch,stale=score,epoch,0;best_metrics=evaluated
                u.save_weights(output/'checkpoints/best.pt',model)
                u.base.write_json(output/'selection-predictions.json',predictions)
            else:stale+=1
            u.save_recovery(output/'checkpoints/recovery-last.pt',model,optimizer,epoch,steps,{'best_epoch':best_epoch,'best_ger':best,'stale':stale})
            record={'epoch':epoch,'optimizer_steps':steps,'loss':sum(losses)/len(losses),'selection':evaluated,'selected_epoch':best_epoch}
            report['history'].append(record);report.update(epochs_completed=epoch,optimizer_steps=steps,selected_epoch=best_epoch)
            u.base.write_json(output/'report.json',report);print(json.dumps(record),flush=True)
            if stale>=plan['patience']:break
        model.load_state_dict(torch.load(output/'checkpoints/best.pt',map_location=device,weights_only=True),strict=True)
        baseline=plan['baseline_selection_metrics']
        gates={'overall_ger_not_worse':best_metrics['raw_gloss']['gloss_error_rate']<=baseline['raw_gloss']['gloss_error_rate']}
        for family in ['person','negation']:
            before=baseline['slices'][family]['gloss_error_rate'];after=best_metrics['slices'][family]['gloss_error_rate']
            gates[family+'_ger_not_worse']=before is not None and after is not None and after<=before
        gates['no_malformed_output']=best_metrics['malformed_rows']==0
        report.update(status='completed',finished_at_utc=datetime.now(timezone.utc).isoformat(),
            checkpoint='checkpoints/best.pt',checkpoint_sha256=u.base.sha(output/'checkpoints/best.pt'),
            selected_weights_sha256=u.base.weights_hash(model),selected_metrics=best_metrics,development_gates=gates)
        u.base.write_json(output/'report.json',report);u.seal(output)
    except Exception as error:
        report.update(status='failed',error=repr(error),optimizer_steps=steps)
        u.base.write_json(output/'report.json',report);u.seal(output);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    for name in ['grouped','baseline','output']:p.add_argument('--'+name,type=Path,required=True)
    p=sub.add_parser('train');p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=prepare(args.grouped,args.baseline,args.output) if args.command=='prepare' else train(args.prepared,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
