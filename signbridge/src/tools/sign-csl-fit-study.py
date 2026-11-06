"""Full train/G fitting measurement and a single matched-budget LR control.

CPU diagnostics never optimize; training requires CUDA. H/test are never read.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import random
import sys


def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),Path(__file__).with_name(name))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


t=load('sign-csl-bert-transfer.py')
u=t.u
SCHEMA='signbridge-fit-lr-study-v1'
GATES={**u.GATES,'holdout_H_read':False,'official_test_read':False,'promoted':False}


def source_hashes(include_study=True):
    paths=[t.__file__,t.c.__file__,t.c.study.__file__,u.__file__,u.base.__file__,t.c.study.err.__file__]
    if include_study:paths.append(__file__)
    return {Path(p).name:u.base.sha(Path(p)) for p in paths}


def enforce_shared_sources(expected):
    if expected!=source_hashes(False):raise ValueError('Shared baseline source hashes differ; not an LR-only comparison')


def control_settings(baseline,train_count):
    if (baseline.get('plan',{}).get('settings')!=t.SETTINGS or baseline.get('epochs_completed')!=15
            or baseline.get('optimizer_steps')!=1035 or train_count!=4368):
        raise ValueError('Unexpected baseline budget/settings; do not silently change experiment')
    return {'epochs':15,'expected_steps':1035,'batch_size':64,'learning_rate':.001,
            'seed':20261105,'label_smoothing':.05,'weight_decay':.01,'clip_grad':1.,
            'freeze_encoder':True,'early_stop':False,'selection':'minimum G raw Gloss GER, earliest tie',
            'budget_note':'Matches actual prior15 epochs/1035 updates. Prior run early-stopped at15; this control fixes15 with no earlier stop.'}


def verify_predictions(rows,predictions):
    if (len(rows)!=len(predictions) or len({p.get('id') for p in predictions})!=len(predictions)
            or any(p.get('id')!=r['id'] or p.get('text')!=r['text'] or p.get('reference')!=r['gloss_sequence']
                   or not isinstance(p.get('predicted'),list) for r,p in zip(rows,predictions))):
        raise ValueError('Saved prediction identities/text/targets differ')


def slices(train,rows):
    freq=Counter(x for r in train for x in r['gloss_sequence'])
    chars={x for word in freq for x in word}
    return {'all':list(range(len(rows))),
        'person':[i for i,r in enumerate(rows) if any(x in ('我','你','他','她','我们','你们','他们') for x in r['gloss_sequence'])],
        'negation':[i for i,r in enumerate(rows) if any(t.c.study.err.variant_surface(x) in ('不','没','没有','不是','不能','不要','不想','不用') for x in r['gloss_sequence'])],
        'unknown_target_character':[i for i,r in enumerate(rows) if any(x not in chars for word in r['gloss_sequence'] for x in word)],
        'rare_train_label':[i for i,r in enumerate(rows) if any(0<freq[x]<=2 for x in r['gloss_sequence'])]}


def forced_counts(logits,target):
    import torch
    ref=target[:,1:];valid=ref.ne(0);correct=logits.argmax(-1).eq(ref)
    nll=torch.nn.functional.cross_entropy(logits.flatten(0,1),ref.reshape(-1),ignore_index=0,reduction='none').reshape(ref.shape)
    return {'tokens':int(valid.sum()),'correct_tokens':int((valid&correct).sum()),
            'samples':ref.size(0),'exact_sequences':int((correct|~valid).all(1).sum()),'nll_sum':float(nll.sum())}


def load_baseline(root,prepared):
    root=u.safe_path(root);data,vocab,plan,inputs=t.read_prepared(prepared)
    manifest,used=u.read_manifest(root)
    report=json.loads(u.checked(root,'report.json',manifest,used))
    predictions=json.loads(u.checked(root,'selection-predictions.json',manifest,used))
    if (report.get('schema')!=t.SCHEMA or report.get('status')!='completed' or report.get('plan')!=plan
            or report.get('inputs')!=inputs or report.get('frozen_encoder_unchanged') is not True
            or any(report.get(k) is not False for k in ['test_read','holdout_H_read','official_test_read','promoted','training_ready','model_training_ready'])):
        raise ValueError('Invalid baseline report/provenance')
    enforce_shared_sources(report.get('tool_sha256'))
    verify_predictions(data['selection'],predictions)
    if t.c.metrics(data['selection'],predictions)!=report['selected_metrics']:raise ValueError('Baseline metric mismatch')
    content=u.checked(root,report['checkpoint'],manifest,used)
    if used[report['checkpoint']]!=report['checkpoint_sha256']:raise ValueError('Baseline checkpoint digest differs')
    return data,vocab,plan,inputs,report,predictions,content,used


def evaluate_fit(model,tokenizer,rows,train,vocab,device='cpu',batch_size=64):
    import torch
    model.eval();predictions=[];forced_rows=[]
    for start in range(0,len(rows),batch_size):
        part=rows[start:start+batch_size];source,target=t.batch(part,vocab,tokenizer,device)
        with torch.no_grad():
            logits=model(source,target[:,:-1])
            for i,row in enumerate(part):
                forced_rows.append({'id':row['id'],**forced_counts(logits[i:i+1],target[i:i+1])})
        predictions.extend(t.generate(model,part,vocab,tokenizer,device,batch_size))
    verify_predictions(rows,predictions)
    by_group={}
    for name,ids in slices(train,rows).items():
        tokens=sum(forced_rows[i]['tokens'] for i in ids);correct=sum(forced_rows[i]['correct_tokens'] for i in ids)
        nll=sum(forced_rows[i]['nll_sum'] for i in ids);exact=sum(forced_rows[i]['exact_sequences'] for i in ids)
        by_group[name]={'samples':len(ids),'teacher_forced':{'tokens':tokens,'correct_tokens':correct,
            'token_accuracy':correct/tokens if tokens else None,'exact_sequences':exact,'nll_sum':nll,'mean_token_nll':nll/tokens if tokens else None},
            'free_generation':u.base.metrics([rows[i]['gloss_sequence'] for i in ids],[predictions[i]['predicted'] for i in ids])}
    return {'groups':by_group,'free_generation':t.c.metrics(rows,predictions)},predictions,forced_rows


def diagnose(prepared,baseline,encoder_root,output):
    import torch
    prepared,baseline,encoder_root,output=map(u.safe_path,[prepared,baseline,encoder_root,output]);u.new_output(output,[prepared,baseline,encoder_root])
    data,vocab,plan,inputs,report,saved,statebytes,baseline_hashes=load_baseline(baseline,prepared)
    torch.set_num_threads(4);encoder,tokenizer,encoder_hashes,info=t.load_encoder(encoder_root)
    if encoder_hashes!=report['encoder_inputs']:raise ValueError('Encoder inputs differ')
    model=t.make_model(encoder,vocab);t.load_trainable(model,torch.load(io.BytesIO(statebytes),map_location='cpu',weights_only=True))
    frozen=u.base.weights_hash(encoder);trainable=t.state_hash(t.trainable_state(model))
    if frozen!=report['frozen_encoder_final_hash'] or trainable!=report['selected_trainable_hash']:raise ValueError('Baseline weights differ')
    output.mkdir(parents=True)
    result={**GATES,'schema':SCHEMA,'status':'running','training_started':False,'device':'cpu_inference_only',
        'baseline_checkpoint_sha256':report['checkpoint_sha256'],'baseline_hashes':baseline_hashes,
        'prepared_inputs':inputs,'encoder_hashes':encoder_hashes,'results':{}}
    for split in ['train','selection']:
        print(json.dumps({'evaluating':split,'samples':len(data[split]),'device':'cpu'}),flush=True)
        scores,predictions,forced=evaluate_fit(model,tokenizer,data[split],data['train'],vocab)
        if split=='selection' and predictions!=saved:raise ValueError('CPU G baseline no longer exactly matches saved predictions')
        result['results'][split]=scores
        u.base.write_json(output/(split+'-predictions.json'),predictions)
        u.base.write_json(output/(split+'-teacher-forcing.json'),forced)
        u.base.write_json(output/'progress.json',{'completed_split':split,'samples':len(predictions)})
    if frozen!=u.base.weights_hash(encoder) or trainable!=t.state_hash(t.trainable_state(model)):raise ValueError('Read-only diagnostic changed parameters')
    result.update(status='completed',finished_at_utc=datetime.now(timezone.utc).isoformat(),all_489_G_predictions_match_saved=True,
        frozen_encoder_unchanged=True,trainable_weights_unchanged=True,optimizer_steps=0,
        limitations=['Train fitting measurements are not validation/generalization scores.','G has been used repeatedly for development; H and official test remain excluded.'])
    u.base.write_json(output/'report.json',result);u.seal(output);return result


def prepare(prepared,baseline,diagnostic,output):
    prepared,baseline,diagnostic,output=map(u.safe_path,[prepared,baseline,diagnostic,output]);u.new_output(output,[prepared,baseline,diagnostic])
    data,vocab,prior,inputs,report,saved,_,baseline_hashes=load_baseline(baseline,prepared)
    settings=control_settings(report,len(data['train']));manifest,used=u.read_manifest(diagnostic)
    fit=json.loads(u.checked(diagnostic,'report.json',manifest,used))
    if (fit.get('status')!='completed' or fit.get('schema')!=SCHEMA or fit.get('baseline_checkpoint_sha256')!=report['checkpoint_sha256']
            or fit.get('prepared_inputs')!=inputs or fit.get('optimizer_steps')!=0 or fit.get('device')!='cpu_inference_only'
            or fit['results']['train']['groups']['all']['samples']!=4368 or fit['results']['selection']['groups']['all']['samples']!=489):
        raise ValueError('Full CPU diagnostic missing or source mismatched')
    if fit['results']['train']['groups']['all']['teacher_forced']['token_accuracy']>=.95:
        raise ValueError('Train teacher-forcing is already high; preregister a different next hypothesis')
    output.mkdir(parents=True);original=output/'original-prepared';original.mkdir()
    t.copy_verified_inputs(prepared/'input',original/'input',inputs['grouped'])
    source_manifest,source_used=u.read_manifest(prepared)
    for name in ['plan.json','vocab.json']:(original/name).write_bytes(u.checked(prepared,name,source_manifest,source_used))
    u.seal(original)
    plan={**GATES,'schema':SCHEMA,'status':'prepared_not_started','training_started':False,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'settings':settings,'baseline_report_sha256':baseline_hashes['report.json'],'baseline_checkpoint_sha256':report['checkpoint_sha256'],
        'baseline_initial_trainable_hash':report['initial_trainable_hash'],'baseline_frozen_encoder_hash':report['frozen_encoder_initial_hash'],
        'original_prepared_hashes':inputs,'baseline_settings':report['plan']['settings'],
        'baseline_metrics':report['selected_metrics'],'baseline_fit':fit['results'],'CPU_diagnostic_sha256':used['report.json'],
        'source_read_scope':'same train/G only; no H/test','controlled_change':'Learning rate0.0002 ->0.001; all other actual update settings/data/initial weights unchanged.',
        'tool_sha256':source_hashes(),
        'independent_test':False,'promotion_constraints':['G overall/person/negation GER no worse than baseline.','G deletion count no worse and no malformed/empty/missing-EOS outputs.','Train fitting gains alone do not justify adopting weights or Demo integration.']}
    u.base.write_json(output/'control-plan.json',plan);u.seal(output);return plan


def read_control(root):
    root=u.safe_path(root);manifest,used=u.read_manifest(root);plan=json.loads(u.checked(root,'control-plan.json',manifest,used))
    data,vocab,prior,inputs=t.read_prepared(root/'original-prepared')
    expected=control_settings({'epochs_completed':15,'optimizer_steps':1035,'plan':{'settings':t.SETTINGS}},len(data['train']))
    if (plan.get('schema')!=SCHEMA or plan.get('settings')!=expected or plan.get('baseline_settings')!=t.SETTINGS
            or plan.get('original_prepared_hashes')!=inputs or plan.get('tool_sha256')!=source_hashes()
            or any(plan.get(k) is not False for k in ['test_read','holdout_H_read','official_test_read','promoted','training_ready','model_training_ready','human_approved','deployment_ready','can_play','independent_test'])):
        raise ValueError('Controlled experiment contract differs')
    return data,vocab,prior,plan,{'control':used,'prepared':inputs}


def adoption_gates(current,baseline):
    gates={'overall_no_regression':current['raw_gloss']['gloss_error_rate']<=baseline['raw_gloss']['gloss_error_rate'],
           'deletions_no_regression':current['raw_gloss']['deletions']<=baseline['raw_gloss']['deletions'],
           'outputs_valid':current['malformed_rows']==current['empty_prediction_rows']==current['missing_eos_rows']==0}
    for family in ['person','negation']:gates[family+'_no_regression']=current['slices'][family]['gloss_error_rate']<=baseline['slices'][family]['gloss_error_rate']
    return gates


def train(control,encoder_root,output):
    import torch
    device=u.cuda_device('cuda');control,encoder_root,output=map(u.safe_path,[control,encoder_root,output]);u.new_output(output,[control,encoder_root])
    data,vocab,prior,plan,inputs=read_control(control);settings=plan['settings']
    torch.set_num_threads(4);torch.manual_seed(settings['seed']);torch.cuda.manual_seed_all(settings['seed']);random.seed(settings['seed'])
    encoder,tokenizer,encoder_inputs,load_info=t.load_encoder(encoder_root)
    if encoder_inputs!=prior['encoder_files_sha256']:raise ValueError('Encoder provenance differs')
    model=t.make_model(encoder,vocab).to(device);frozen=u.base.weights_hash(encoder);initial=t.state_hash(t.trainable_state(model))
    if frozen!=plan['baseline_frozen_encoder_hash'] or initial!=plan['baseline_initial_trainable_hash']:
        raise ValueError('Fresh initialization does not exactly match baseline')
    optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=settings['learning_rate'],weight_decay=settings['weight_decay'])
    output.mkdir(parents=True);(output/'checkpoints').mkdir();u.base.write_json(output/'vocab.json',vocab)
    report={**GATES,'schema':SCHEMA,'status':'running','training_started':True,'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'plan':plan,'inputs':inputs,'encoder_inputs':encoder_inputs,'initial_trainable_hash':initial,'frozen_encoder_initial_hash':frozen,
        'history':[],'optimizer_steps':0,'runtime':{'python':sys.version,'executable':sys.executable,'torch':str(torch.__version__),
            'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(device),'device':str(next(model.parameters()).device)},
        'tool_sha256':{Path(p).name:u.base.sha(Path(p)) for p in [__file__,t.__file__,t.c.__file__,t.c.study.__file__,u.__file__,u.base.__file__,t.c.study.err.__file__]}}
    u.base.write_json(output/'report.json',report);best=float('inf');best_epoch=steps=0;best_metrics=None
    try:
        for epoch in range(1,settings['epochs']+1):
            model.train();order=list(data['train']);random.shuffle(order);losses=[]
            assert not encoder.training
            for start in range(0,len(order),settings['batch_size']):
                source,target=t.batch(order[start:start+settings['batch_size']],vocab,tokenizer,device);optimizer.zero_grad(set_to_none=True)
                logits=model(source,target[:,:-1]);loss=torch.nn.functional.cross_entropy(logits.flatten(0,1),target[:,1:].reshape(-1),ignore_index=0,label_smoothing=settings['label_smoothing'])
                if not torch.isfinite(loss):raise ValueError('Nonfinite controlled loss')
                loss.backward();params=[p for p in model.parameters() if p.requires_grad]
                if any(p.grad is not None for p in encoder.parameters()):raise ValueError('Frozen encoder gradient')
                if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in params):raise ValueError('Nonfinite gradient')
                torch.nn.utils.clip_grad_norm_(params,settings['clip_grad']);optimizer.step();steps+=1;losses.append(float(loss.detach()))
            predictions=t.generate(model,data['selection'],vocab,tokenizer,device,64);evaluated=t.c.metrics(data['selection'],predictions)
            score=evaluated['raw_gloss']['gloss_error_rate']
            if score<best:
                best,best_epoch,best_metrics=score,epoch,evaluated;torch.save(t.trainable_state(model),output/'checkpoints/best.pt')
                u.base.write_json(output/'selection-predictions.json',predictions)
            torch.save({'trainable_model':t.trainable_state(model),'optimizer':optimizer.state_dict(),'epoch':epoch,'steps':steps,
                'python_rng':random.getstate(),'torch_rng':torch.get_rng_state(),'cuda_rng':torch.cuda.get_rng_state_all(),'best_epoch':best_epoch},output/'checkpoints/recovery-last.pt')
            record={'epoch':epoch,'steps':steps,'train_loss':sum(losses)/len(losses),'G_metrics':evaluated,'selected_epoch':best_epoch}
            report['history'].append(record);report.update(epochs_completed=epoch,optimizer_steps=steps,selected_epoch=best_epoch)
            u.base.write_json(output/'report.json',report);print(json.dumps(record),flush=True)
        if steps!=settings['expected_steps']:raise ValueError('Matched baseline update budget differs')
        t.load_trainable(model,torch.load(output/'checkpoints/best.pt',map_location=device,weights_only=True))
        if u.base.weights_hash(encoder)!=frozen:raise ValueError('Frozen encoder changed')
        fit={}
        for split in ['train','selection']:
            scores,predictions,forced=evaluate_fit(model,tokenizer,data[split],data['train'],vocab,device,64);fit[split]=scores
            u.base.write_json(output/(split+'-fit-predictions.json'),predictions)
            u.base.write_json(output/(split+'-teacher-forcing.json'),forced)
        if fit['selection']['free_generation']!=best_metrics:raise ValueError('Selected evaluation changed')
        report.update(status='completed',finished_at_utc=datetime.now(timezone.utc).isoformat(),checkpoint='checkpoints/best.pt',
            checkpoint_sha256=u.base.sha(output/'checkpoints/best.pt'),selected_trainable_hash=t.state_hash(t.trainable_state(model)),
            selected_metrics=best_metrics,fit=fit,development_gates=adoption_gates(best_metrics,plan['baseline_metrics']),
            frozen_encoder_final_hash=u.base.weights_hash(encoder),frozen_encoder_unchanged=True)
        u.base.write_json(output/'report.json',report);u.seal(output)
    except Exception as error:
        report.update(status='failed',error=repr(error),optimizer_steps=steps);u.base.write_json(output/'report.json',report);u.seal(output);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name,fields in [('diagnose',['prepared','baseline','encoder-root','output']),('prepare',['prepared','baseline','diagnostic','output']),('train',['control','encoder-root','output'])]:
        p=sub.add_parser(name)
        for field in fields:p.add_argument('--'+field,type=Path,required=True)
    args=parser.parse_args()
    if args.command=='diagnose':result=diagnose(args.prepared,args.baseline,args.encoder_root,args.output)
    elif args.command=='prepare':result=prepare(args.prepared,args.baseline,args.diagnostic,args.output)
    else:result=train(args.control,args.encoder_root,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='history'},ensure_ascii=False,indent=2))
