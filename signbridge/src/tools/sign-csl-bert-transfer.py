"""Frozen official Chinese BERT -> trainable character Gloss decoder research.

Only train/G development data. Never reads old H or official test; CUDA training only.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import random
import sys


def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),Path(__file__).with_name(name))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


c=load('sign-csl-character-gloss.py')
u=c.u
MODEL_ID='google-bert/bert-base-chinese'
REVISION='8f23c25b06e129b6c986331a13d8d025a92cf0ea'
MODEL_SHA='3404a1ffd8da507042e8161013ba2a4fc49858b4e3f8fbf5ce5724f94883aec3'
SCHEMA='signbridge-frozen-bert-gloss-v1'
SETTINGS={'epochs':30,'patience':6,'batch_size':64,'learning_rate':.0002,
          'seed':20261105,'label_smoothing':.05,'freeze_encoder':True}
PINNED={'model.safetensors':MODEL_SHA,
        'config.json':'88af762cfb15fa9ce183c84dcbfdc9d635196ba635dfe81f265fdd21d67f4c4c',
        'vocab.txt':'45bbac6b341c319adc98a532532882e91a9cefc0329aa57bac9ae761c27b291c',
        'tokenizer_config.json':'0f6d13e6f4da6f9e24f22ada6bc3be571123d858d7c0c05a8a7cd55a9c23c2e8'}


def check_settings(settings):
    if settings!=SETTINGS:raise ValueError('Frozen transfer settings differ')


def check_encoder(root):
    root=u.safe_path(root);manifest,used=u.read_manifest(root)
    for name,digest in PINNED.items():
        if manifest.get(name)!=digest:raise ValueError('Pinned encoder file differs: '+name)
        path=u.safe_path(root/name)
        if not path.is_file() or u.base.sha(path)!=digest:raise ValueError('Encoder digest differs: '+name)
        used[name]=digest
    meta=json.loads(u.checked(root,'provenance.json',manifest,used))
    if (meta.get('model_id')!=MODEL_ID or meta.get('revision')!=REVISION or meta.get('license')!='apache-2.0'
            or meta.get('weight_sha256')!=MODEL_SHA):raise ValueError('Encoder provenance differs')
    return used


def validate_loading_info(info):
    allowed_pooler={'bert.pooler.dense.weight','bert.pooler.dense.bias'}
    if (info['missing_keys'] or info.get('mismatched_keys') or info.get('error_msgs')
            or any(not (n.startswith('cls.') or n in allowed_pooler) for n in info['unexpected_keys'])):
        raise ValueError('Unexpected encoder loading keys: '+str(info))


def load_encoder(root):
    import transformers
    from transformers import BertModel,BertTokenizer
    if transformers.__version__!='4.40.2':raise ValueError('Pinned Transformers4.40.2 required')
    used=check_encoder(root)
    tokenizer=BertTokenizer.from_pretrained(str(root),local_files_only=True)
    encoder,info=BertModel.from_pretrained(str(root),local_files_only=True,use_safetensors=True,
        trust_remote_code=False,add_pooling_layer=False,output_loading_info=True)
    validate_loading_info(info)
    if encoder.config.hidden_size!=768 or tokenizer.pad_token_id!=0:raise ValueError('Unexpected BERT shape or padding')
    for p in encoder.parameters():p.requires_grad_(False)
    encoder.eval()
    return encoder,tokenizer,used,info


def make_model(encoder,vocab,config=None):
    import torch
    from torch import nn
    config=config or c.CONFIG
    class Transfer(nn.Module):
        def __init__(self):
            super().__init__();self.encoder=encoder
            for param in self.encoder.parameters():param.requires_grad_(False)
            self.encoder.eval()
            # Reuse the exact established decoder architecture and target contract.
            base=u.base.make_model(vocab,config)
            self.target=base.target;self.target_position=base.target_position
            self.decoder=base.transformer.decoder;self.output=base.output
            self.projection=nn.Linear(encoder.config.hidden_size,config['width'])
            self.memory_norm=nn.LayerNorm(config['width'])
        def train(self,mode=True):
            super().train(mode);self.encoder.eval();return self
        def encode(self,source):
            with torch.no_grad():
                hidden=self.encoder(input_ids=source,attention_mask=source.ne(0),return_dict=True).last_hidden_state
            return self.memory_norm(self.projection(hidden))
        def decode(self,target,memory,source_padding):
            embedded=self.target(target)*math.sqrt(config['width'])
            embedded=embedded+self.target_position(torch.arange(target.size(1),device=target.device))[None]
            mask=torch.ones(target.size(1),target.size(1),dtype=torch.bool,device=target.device).triu(1)
            return self.output(self.decoder(embedded,memory,tgt_mask=mask,tgt_key_padding_mask=target.eq(0),memory_key_padding_mask=source_padding))
        def forward(self,source,target):return self.decode(target,self.encode(source),source.eq(0))
    return Transfer()


def batch(rows,vocab,tokenizer,device):
    if tokenizer.pad_token_id!=0:raise ValueError('Padding ID must remain0')
    encoded=tokenizer([r['text'] for r in rows],padding=True,truncation=False,return_tensors='pt')
    source=encoded['input_ids']
    if source.ndim!=2 or source.size(0)!=len(rows) or source.size(1)>c.CONFIG['max_source']:
        raise ValueError('BERT source length or shape exceeds frozen config; no truncation')
    _,target=c.character_batch(rows,vocab,device)
    return source.to(device),target


def generate(model,rows,vocab,tokenizer,device,batch_size=64):
    import torch
    result=[];model.eval()
    with torch.inference_mode():
        for start in range(0,len(rows),batch_size):
            part=rows[start:start+batch_size];source,_=batch(part,vocab,tokenizer,device)
            memory=model.encode(source);target=torch.full((len(part),1),2,dtype=torch.long,device=device)
            done=torch.zeros(len(part),dtype=torch.bool,device=device)
            for _ in range(c.CONFIG['max_target']-1):
                logits=model.decode(target,memory,source.eq(0))[:,-1];logits[:,0]=-torch.inf;logits[:,2]=-torch.inf
                token=logits.argmax(-1);token=torch.where(done,torch.full_like(token,3),token)
                target=torch.cat([target,token[:,None]],dim=1);done=done|token.eq(3)
                if bool(done.all()):break
            for row,ids in zip(part,target[:,1:].cpu().tolist()):
                terminated=3 in ids
                if terminated:ids=ids[:ids.index(3)]
                tokens=[vocab['target'][i] for i in ids];decoded=c.decode_gloss(tokens)
                if not terminated:decoded['errors'].append('missing_eos');decoded['gloss'].append(c.INVALID+'eos')
                result.append({'id':row['id'],'text':row['text'],'reference':row['gloss_sequence'],
                    'predicted':decoded['gloss'],'target_character_tokens':tokens,'terminated':terminated,
                    'representation_errors':sorted(set(decoded['errors']))})
    return result


def trainable_state(model):
    return {k:v.detach().cpu() for k,v in model.state_dict().items() if not k.startswith('encoder.')}


def load_trainable(model,state):
    import torch
    expected={k:v for k,v in model.state_dict().items() if not k.startswith('encoder.')}
    if set(state)!=set(expected) or any(v.shape!=expected[k].shape or v.dtype!=expected[k].dtype or not torch.isfinite(v).all() for k,v in state.items()):
        raise ValueError('Invalid trainable checkpoint keys/shapes/values')
    info=model.load_state_dict(state,strict=False)
    if info.unexpected_keys or set(info.missing_keys)!={k for k in model.state_dict() if k.startswith('encoder.')}:
        raise ValueError('Unexpected trainable state restore')


def state_hash(state):
    import hashlib
    digest=hashlib.sha256()
    for key,value in sorted(state.items()):digest.update(key.encode());digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def copy_verified_inputs(source,output,expected_hashes):
    source=u.safe_path(source);manifest,used=u.read_manifest(source)
    if used['SHA256SUMS']!=expected_hashes.get('SHA256SUMS'):raise ValueError('Input manifest changed before copy')
    output.mkdir()
    for name in ['train.jsonl','selection.jsonl','report.json']:
        content=u.checked(source,name,manifest,used)
        if used[name]!=expected_hashes.get(name):raise ValueError('Input digest changed before copy')
        (output/name).write_bytes(content)
    u.seal(output)


def prepare(character_prepared,character_baseline,encoder_root,output):
    roots=list(map(u.safe_path,[character_prepared,character_baseline,encoder_root]));output=u.safe_path(output);u.new_output(output,roots)
    data,vocab,prior,inputs=c.read_prepared(roots[0]);encoder_hashes=check_encoder(roots[2])
    manifest,used=u.read_manifest(roots[1]);report=json.loads(u.checked(roots[1],'report.json',manifest,used))
    predictions=json.loads(u.checked(roots[1],'selection-predictions.json',manifest,used))
    if (report.get('schema')!=c.SCHEMA or report.get('status')!='completed' or report.get('experiment')!=prior
            or report.get('source_hashes')!=inputs or report.get('holdout_H_read') is not False or report.get('test_read') is not False):
        raise ValueError('Character baseline provenance differs')
    baseline=c.metrics(data['selection'],predictions)
    if baseline!=report['selected_metrics']:raise ValueError('Character baseline metrics differ')
    output.mkdir(parents=True);copy_verified_inputs(roots[0]/'input',output/'input',inputs['grouped'])
    u.base.write_json(output/'vocab.json',vocab)
    plan={**u.GATES,'schema':SCHEMA,'training_started':False,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'settings':SETTINGS,'config':c.CONFIG,'model_id':MODEL_ID,'model_revision':REVISION,'model_weight_sha256':MODEL_SHA,
        'license_metadata':'apache-2.0','source_hashes':inputs,'encoder_files_sha256':encoder_hashes,
        'baseline_hashes':used,'baseline_selection_metrics':baseline,'counts':{k:len(v) for k,v in data.items()},
        'holdout_H_read':False,'official_test_read':False,'independent_test':False,
        'selection_rule':'Minimum reconstructed raw Gloss GER on G, earliest tie',
        'limits':['Frozen general Chinese BERT is not a sign-language pretrained model.',
                  'Architecture/tokenizer/frozen policy/parameter count differ; not an equal-capacity causal ablation.',
                  'G is previously used development data, not an independent test.','No H or official test or motions included.']}
    u.base.write_json(output/'plan.json',plan);u.seal(output);return plan


def read_prepared(root):
    root=u.safe_path(root);manifest,used=u.read_manifest(root);plan=json.loads(u.checked(root,'plan.json',manifest,used));check_settings(plan.get('settings'))
    if (plan.get('schema')!=SCHEMA or plan.get('config')!=c.CONFIG or plan.get('model_id')!=MODEL_ID
            or plan.get('model_revision')!=REVISION or plan.get('model_weight_sha256')!=MODEL_SHA
            or any(plan.get(k) is not False for k in ['test_read','holdout_H_read','official_test_read','independent_test','human_approved','training_ready','model_training_ready','deployment_ready','can_play'])):
        raise ValueError('Transfer plan contract differs')
    data,source=c.load_data(root/'input')
    if source['sha256']!=plan['source_hashes']['grouped']:raise ValueError('Transfer data changed')
    vocab=json.loads(u.checked(root,'vocab.json',manifest,used))
    if vocab!=c.build_vocab(data['train']):raise ValueError('Target vocabulary is not train-only')
    return data,vocab,plan,{'prepared':used,'grouped':source['sha256']}


def train(prepared,encoder_root,output):
    import torch
    device=u.cuda_device('cuda');prepared,encoder_root,output=map(u.safe_path,[prepared,encoder_root,output]);u.new_output(output,[prepared,encoder_root])
    data,vocab,plan,inputs=read_prepared(prepared);settings=plan['settings']
    torch.set_num_threads(4);torch.manual_seed(settings['seed']);torch.cuda.manual_seed_all(settings['seed']);random.seed(settings['seed'])
    encoder,tokenizer,encoder_inputs,load_info=load_encoder(encoder_root)
    if encoder_inputs!=plan['encoder_files_sha256']:raise ValueError('Pinned encoder assets differ from plan')
    model=make_model(encoder,vocab).to(device);frozen_hash=u.base.weights_hash(model.encoder)
    optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=settings['learning_rate'],weight_decay=.01)
    output.mkdir(parents=True);(output/'checkpoints').mkdir();u.base.write_json(output/'vocab.json',vocab)
    report={**u.GATES,'schema':SCHEMA,'status':'running','training_started':True,'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'plan':plan,'inputs':inputs,'encoder_inputs':encoder_inputs,'encoder_loading_info':load_info,
        'frozen_encoder_initial_hash':frozen_hash,'initial_trainable_hash':state_hash(trainable_state(model)),
        'parameters':{'total':sum(p.numel() for p in model.parameters()),'trainable':sum(p.numel() for p in model.parameters() if p.requires_grad)},
        'runtime':{'python':sys.version,'executable':sys.executable,'torch':str(torch.__version__),'cuda':torch.version.cuda,
                   'gpu':torch.cuda.get_device_name(device),'actual_device':str(next(model.parameters()).device),
                   'transformers':importlib.metadata.version('transformers')},
        'tool_sha256':{Path(p).name:u.base.sha(Path(p)) for p in [__file__,c.__file__,c.study.__file__,u.__file__,u.base.__file__,c.study.err.__file__]},
        'history':[],'optimizer_steps':0,'holdout_H_read':False,'official_test_read':False,'promoted':False}
    u.base.write_json(output/'report.json',report);best=float('inf');best_epoch=stale=steps=0;best_metrics=None
    try:
        for epoch in range(1,settings['epochs']+1):
            model.train();order=list(data['train']);random.shuffle(order);losses=[]
            assert not model.encoder.training
            for start in range(0,len(order),settings['batch_size']):
                source,target=batch(order[start:start+settings['batch_size']],vocab,tokenizer,device)
                optimizer.zero_grad(set_to_none=True);logits=model(source,target[:,:-1])
                loss=torch.nn.functional.cross_entropy(logits.flatten(0,1),target[:,1:].reshape(-1),ignore_index=0,label_smoothing=settings['label_smoothing'])
                if not torch.isfinite(loss):raise ValueError('Nonfinite transfer loss')
                loss.backward()
                if any(p.grad is not None for p in model.encoder.parameters()):raise ValueError('Frozen encoder received gradients')
                trainable=[p for p in model.parameters() if p.requires_grad]
                if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in trainable):raise ValueError('Nonfinite gradient')
                torch.nn.utils.clip_grad_norm_(trainable,1.);optimizer.step();steps+=1;losses.append(float(loss.detach()))
            predictions=generate(model,data['selection'],vocab,tokenizer,device,settings['batch_size']);evaluated=c.metrics(data['selection'],predictions)
            score=evaluated['raw_gloss']['gloss_error_rate']
            if score<best:
                best,best_epoch,stale=score,epoch,0;best_metrics=evaluated
                torch.save(trainable_state(model),output/'checkpoints/best.pt');u.base.write_json(output/'selection-predictions.json',predictions)
            else:stale+=1
            torch.save({'trainable_model':trainable_state(model),'optimizer':optimizer.state_dict(),'epoch':epoch,'steps':steps,
                        'python_rng':random.getstate(),'torch_rng':torch.get_rng_state(),'cuda_rng':torch.cuda.get_rng_state_all(),
                        'best_epoch':best_epoch,'best_ger':best,'stale':stale},output/'checkpoints/recovery-last.pt')
            record={'epoch':epoch,'steps':steps,'loss':sum(losses)/len(losses),'selection':evaluated,'selected_epoch':best_epoch}
            report['history'].append(record);report.update(epochs_completed=epoch,optimizer_steps=steps,selected_epoch=best_epoch)
            u.base.write_json(output/'report.json',report);print(json.dumps(record),flush=True)
            if stale>=settings['patience']:break
        load_trainable(model,torch.load(output/'checkpoints/best.pt',map_location=device,weights_only=True))
        frozen_final=u.base.weights_hash(model.encoder)
        if frozen_final!=frozen_hash:raise ValueError('Frozen encoder weights changed')
        baseline=plan['baseline_selection_metrics'];gates={'overall_not_worse':best_metrics['raw_gloss']['gloss_error_rate']<=baseline['raw_gloss']['gloss_error_rate']}
        for family in ['person','negation']:gates[family+'_not_worse']=best_metrics['slices'][family]['gloss_error_rate']<=baseline['slices'][family]['gloss_error_rate']
        gates['no_malformed']=best_metrics['malformed_rows']==0
        report.update(status='completed',finished_at_utc=datetime.now(timezone.utc).isoformat(),checkpoint='checkpoints/best.pt',
            checkpoint_sha256=u.base.sha(output/'checkpoints/best.pt'),selected_trainable_hash=state_hash(trainable_state(model)),
            frozen_encoder_final_hash=frozen_final,frozen_encoder_unchanged=True,selected_metrics=best_metrics,development_gates=gates)
        u.base.write_json(output/'report.json',report);u.seal(output)
    except Exception as error:
        report.update(status='failed',error=repr(error),optimizer_steps=steps);u.base.write_json(output/'report.json',report);u.seal(output);raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    for name in ['character-prepared','character-baseline','encoder-root','output']:p.add_argument('--'+name,type=Path,required=True)
    p=sub.add_parser('train')
    for name in ['prepared','encoder-root','output']:p.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=prepare(args.character_prepared,args.character_baseline,args.encoder_root,args.output) if args.command=='prepare' else train(args.prepared,args.encoder_root,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
