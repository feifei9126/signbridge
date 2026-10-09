"""Fresh leave-source-group-out motion-tokenizer experiments; no text/sign quality claims."""
import argparse
import importlib
import importlib.util
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np


def tool(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


smoke=tool('sign-tokenizer-smoke')
evidence=tool('sign-contact-audit')
GROUP_FIELDS=('source_id','source_sha256','signer_id','split_group')


def group_components(rows):
    ids=[r.get('segment_id') for r in rows]
    if any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids) or \
       any(not isinstance(r.get(k),str) or not r[k] for r in rows for k in GROUP_FIELDS):
        raise ValueError('Missing/duplicate segment or source/person/course identities')
    parent=list(range(len(rows)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    owners={}
    for i,row in enumerate(rows):
        for field in GROUP_FIELDS:
            key=(field,row[field])
            if key in owners:
                a,b=find(i),find(owners[key]);parent[a]=b
            else:owners[key]=i
    groups={}
    for i,row in enumerate(rows):groups.setdefault(find(i),[]).append(i)
    ordered=sorted(groups.values(),key=lambda v:min(v))
    return [{'indices':indices,'segments':[rows[i]['segment_id'] for i in indices],
             'source_ids':sorted({rows[i]['source_id'] for i in indices}),
             'signer_ids':sorted({rows[i]['signer_id'] for i in indices}),
             'split_groups':sorted({rows[i]['split_group'] for i in indices})} for indices in ordered]


def holdout_fold_indices(rows):
    groups=group_components(rows)
    if len(groups)<2:raise ValueError('At least two independent recorded source groups are required')
    return [tuple(g['indices']) for g in groups]


def assert_disjoint(train,evaluation):
    group_components(train+evaluation)
    for field in GROUP_FIELDS:
        if {r[field] for r in train} & {r[field] for r in evaluation}:
            raise ValueError('Recorded split leakage: '+field)


def exposure_audit(rows,exposed_segments):
    group_components(rows)
    known={r['segment_id']:r for r in rows}
    if not set(exposed_segments)<=set(known):raise ValueError('Unknown exposed training segment')
    seen={known[s]['source_id'] for s in exposed_segments}
    remaining=[r for r in rows if r['segment_id'] not in exposed_segments]
    independent=[r['segment_id'] for r in remaining if r['source_id'] not in seen]
    return {'exposed_segments':list(exposed_segments),'exposed_source_ids':sorted(seen),
            'source_independent_remaining_segments':independent,
            'same_source_remaining_segments':[r['segment_id'] for r in remaining if r['source_id'] in seen],
            'current_checkpoint_has_independent_source_test':bool(independent),
            'signer_identity_independently_verified':False}


def comparison_metrics(prediction,truth,valid,mean,std):
    p=np.asarray(prediction);y=np.asarray(truth);mask=np.asarray(valid)
    mean=np.asarray(mean);std=np.asarray(std)
    if p.shape!=y.shape or y.ndim!=2 or y.shape[1]!=133 or mask.shape!=y.shape or mask.dtype.kind!='b' or \
       not np.isfinite(p).all() or not np.isfinite(y).all() or mean.shape!=(133,) or std.shape!=(133,) or \
       not np.isfinite(mean).all() or not np.isfinite(std).all() or not (std>0).all():
        raise ValueError('Invalid reconstruction metrics')
    names={'all':np.arange(133),'body_face':np.r_[np.arange(30),np.arange(120,133)],
           'left_hand':np.arange(30,75),'right_hand':np.arange(75,120)}
    result={}
    for name,idx in names.items():
        m=mask[:,idx];count=int(m.sum())
        if not count:
            result[name]={'valid_values':0,'normalized_mse':None,'raw_rmse':None,'mean_baseline_normalized_mse':None}
            continue
        error=(p[:,idx]-y[:,idx]);normalized=error/std[idx]
        baseline=(mean[idx]-y[:,idx])/std[idx]
        result[name]={'valid_values':count,'normalized_mse':float((normalized**2*m).sum()/count),
                      'raw_rmse':float(np.sqrt((error**2*m).sum()/count)),
                      'mean_baseline_normalized_mse':float((baseline**2*m).sum()/count)}
    result['independent_human_ground_truth']=False
    return result


def prepare_inputs(args):
    motions=Path(args.motions).resolve();batch=Path(args.batch).resolve()
    evidence.verify_manifest(motions,motions/'SHA256SUMS')
    evidence.verify_manifest(batch,batch/'SHA256SUMS')
    rows,arrays,_=smoke.load_inputs(motions,True)
    masks,_=smoke.load_quality_masks(motions,rows,required=True)
    tasks=[json.loads(x) for x in (batch/'tasks.jsonl').read_text().splitlines() if x.strip()]
    task_index={r['segment_id']:r for r in tasks}
    group_components(tasks)
    for row in rows:
        task=task_index[row['segment_id']]
        if any(row.get(k)!=task[k] for k in GROUP_FIELDS) or row['frames']!=task['frames']:
            raise ValueError('Motion/batch source identity differs')
    holdout_fold_indices(rows)
    watched={str(p):evidence.digest(p) for root in (motions,batch) for p in root.rglob('*')
             if p.is_file() and (root==motions or p.name in ('contract.json','tasks.jsonl','SHA256SUMS'))}
    return rows,arrays,masks,tasks,watched


def run(args):
    motions,batch,soke,out=[Path(getattr(args,k)).resolve() for k in ('motions','batch','soke_root','output')]
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (motions,batch,soke)):
        raise ValueError('Output must be new and separate')
    rows,arrays,masks,tasks,watched=prepare_inputs(args)
    if subprocess.check_output(['git','-C',str(soke),'rev-parse','HEAD'],text=True).strip()!=smoke.SOKE_COMMIT:
        raise ValueError('SOKE commit differs')
    for relative in ('mGPT/archs/mgpt_vq.py','mGPT/archs/tools/resnet.py','mGPT/archs/tools/quantize_cnn.py'):
        watched[str(soke/relative)]=evidence.digest(soke/relative)
    out.mkdir(parents=True)
    report={'schema':'signbridge-leave-source-out-tokenizer-v1','status':'running','training_ready':False,
            'deployment_ready':False,'text_to_sign_trained':False,'independent_human_ground_truth':False,
            'source_group_components':group_components(tasks),'processed_components':group_components(rows),
            'previous_mixed_checkpoint_exposure':exposure_audit(tasks,[r['segment_id'] for r in rows]),
            'checkpoint_selection':'Minimum masked reconstruction MSE on training windows ONLY',
            'normalization':'Training-fold masked targets ONLY; no evaluation normalization statistics',
            'fresh_weights_per_fold':True,'steps':args.steps,'folds':[],
            'source_sha256':watched,'soke_commit':smoke.SOKE_COMMIT,
            'limitations':['Only two processed sources; results cannot establish broad sign-language generalization.',
                'Signer IDs are provisional; source-held-out protocol is checked but actual person disjointness is not independently confirmed.',
                'Motion reconstruction is conditioned on the supplied evaluation motion, not on text.',
                'Targets are estimated/curated SMPL-X; no independent contact or sign-semantic ground truth.',
                'Recorded grouping is separate from production dataset split flags, which remain unchanged.']}
    path=out/'report.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    save()
    try:
        import torch
        if not torch.cuda.is_available():raise ValueError('CUDA required for this evaluation training')
        torch.set_num_threads(1);sys.path.insert(0,str(soke))
        module=importlib.import_module('mGPT.archs.mgpt_vq')
        if Path(module.__file__).resolve()!=soke/'mGPT/archs/mgpt_vq.py':raise ValueError('Architecture source differs')
        config={'quantizer':'ema_reset','code_dim':64,'output_emb_width':64,'width':128,
            'down_t':2,'stride_t':2,'depth':2,'dilation_growth_rate':2,'activation':'relu','norm':None}
        configs=[{**config,'nfeats':width,'code_num':n} for width,n in ((43,16),(45,32),(45,32))]
        report['runtime']={'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0)}
        for fold_id,evaluation_indices in enumerate(holdout_fold_indices(rows),1):
            train_indices=[i for i in range(len(rows)) if i not in evaluation_indices]
            assert_disjoint([rows[i] for i in train_indices],[rows[i] for i in evaluation_indices])
            folder=out/('fold-%02d'%fold_id);folder.mkdir()
            seed=20261009+fold_id;torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
            models=torch.nn.ModuleList([module.VQVae(**c).cuda() for c in configs])
            mean,std=smoke.normalization([arrays[i] for i in train_indices],[masks[i] for i in train_indices])
            normalized=[smoke.normalized_model_input(a,mean,std,m) for a,m in zip(arrays,masks)]
            windows=smoke.make_windows([normalized[i] for i in train_indices])
            quality=smoke.make_windows([masks[i] for i in train_indices])
            tensor=torch.from_numpy(windows).cuda();mask=torch.from_numpy(quality).cuda()
            parts=[torch.cat((tensor[...,:30],tensor[...,120:]),dim=-1),tensor[...,30:75],tensor[...,75:120]]
            mask_parts=[torch.cat((mask[...,:30],mask[...,120:]),dim=-1),mask[...,30:75],mask[...,75:120]]
            optimizer=torch.optim.AdamW(models.parameters(),lr=.001,weight_decay=0.)
            def forward(inputs):
                predictions=[];commitments=[]
                for model,part in zip(models,inputs):
                    pred,commit,_=model(part);predictions.append(pred);commitments.append(commit)
                return predictions,commitments
            def training_error():
                models.eval()
                with torch.no_grad():
                    predicted,_=forward(parts)
                    return float((sum(((p-y)**2*m).sum() for p,y,m in zip(predicted,parts,mask_parts)) /
                                  sum(m.sum() for m in mask_parts).clamp(min=1)).item())
            models.train()
            with torch.no_grad():forward([p[:4] for p in parts])
            fold={'fold_id':fold_id,'seed':seed,'train_segments':[rows[i]['segment_id'] for i in train_indices],
                  'evaluation_segments':[rows[i]['segment_id'] for i in evaluation_indices],
                  'train_source_ids':sorted({rows[i]['source_id'] for i in train_indices}),
                  'evaluation_source_ids':sorted({rows[i]['source_id'] for i in evaluation_indices}),
                  'training_windows':len(windows),'initial_train_MSE':training_error(),'history':[],
                  'recorded_split_disjoint':True,'normalization_frame_count':sum(len(arrays[i]) for i in train_indices),
                  'training_ready':False}
            fold['best_train_MSE']=fold['initial_train_MSE'];report['folds'].append(fold);save()
            start=time.monotonic();checkpoint=folder/'tokenizer-heldout.pt'
            for step in range(1,args.steps+1):
                models.train();indices=torch.randint(0,len(windows),(min(8,len(windows)),),device='cuda')
                inputs=[p[indices] for p in parts];predicted,commits=forward(inputs)
                loss=sum((torch.nn.functional.smooth_l1_loss(p,y,reduction='none')*m[indices]).sum()/
                          m[indices].sum().clamp(min=1) for p,y,m in zip(predicted,inputs,mask_parts))+.02*sum(commits)
                if not torch.isfinite(loss):raise ValueError('Training became nonfinite')
                optimizer.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(models.parameters(),1.);optimizer.step()
                if step==1 or step%50==0 or step==args.steps:
                    mse=training_error();fold['history'].append({'step':step,'train_MSE':mse})
                    print(json.dumps({'fold':fold_id,'step':step,'train_MSE':mse}),flush=True)
                    if mse<fold['best_train_MSE']:
                        fold['best_train_MSE']=mse;fold['checkpoint_step']=step
                        torch.save({'schema':'signbridge-heldout-tokenizer-checkpoint-v1','state_dict':models.state_dict(),
                            'model_configs':configs,'mean':mean,'std':std,'train_segments':fold['train_segments'],
                            'evaluation_segments':fold['evaluation_segments'],'soke_commit':smoke.SOKE_COMMIT,
                            'normalization_train_only':True,'research_only':True,'training_ready':False,'step':step},checkpoint)
                    save()
            if not checkpoint.is_file():raise ValueError('No improved training checkpoint')
            loaded=torch.load(checkpoint,map_location='cuda');models.load_state_dict(loaded['state_dict'],strict=True);models.eval()
            reloaded=training_error()
            if not np.isclose(reloaded,fold['best_train_MSE'],rtol=1e-5,atol=1e-6):raise ValueError('Checkpoint reload error differs')
            fold.update(checkpoint_reload_passed=True,checkpoint_sha256=evidence.digest(checkpoint),
                        reloaded_train_MSE=reloaded,elapsed_seconds=time.monotonic()-start)
            sample_metrics=[]
            with torch.no_grad():
                for i in range(len(rows)):
                    padded=np.pad(normalized[i],((0,(-len(normalized[i]))%4),(0,0)),mode='edge')
                    inputs=[torch.from_numpy(p).unsqueeze(0).cuda() for p in smoke.split_parts(padded)]
                    predicted,_=forward(inputs)
                    decoded=smoke.combine_parts([p[0].cpu().numpy() for p in predicted])[:len(arrays[i])]*std+mean
                    if not np.isfinite(decoded).all():raise ValueError('Evaluation decode is nonfinite')
                    sample=folder/rows[i]['segment_id'];sample.mkdir()
                    np.save(sample/'reconstructed-133.npy',decoded.astype(np.float32),allow_pickle=False)
                    for name,model,part in zip(('body','left','right'),models,inputs):
                        ids,_=model.encode(part);np.save(sample/(name+'-tokens.npy'),ids.cpu().numpy(),allow_pickle=False)
                    sample_metrics.append({'segment_id':rows[i]['segment_id'],'role':'evaluation' if i in evaluation_indices else 'train',
                        'frames':len(arrays[i]),'metrics':comparison_metrics(decoded,arrays[i],masks[i],mean,std)})
            fold['sample_metrics']=sample_metrics
            evaluated=[m for m in sample_metrics if m['role']=='evaluation']
            fold['heldout_metrics_computed']=True
            fold['evaluation_used_for_weight_updates']=False
            fold['evaluation_used_for_checkpoint_selection']=False
            fold['improves_heldout_mean_baseline']=all(m['metrics']['all']['normalized_mse']<
                 m['metrics']['all']['mean_baseline_normalized_mse'] for m in evaluated)
            save();del models,optimizer;torch.cuda.empty_cache()
        for p,sha in watched.items():
            if evidence.digest(p)!=sha:raise ValueError('Source changed during independent evaluation')
        report.update(status='leave_source_out_experiments_complete_pending_quality_review',
                      source_files_unchanged=True,evaluation_completed=True,evaluation_tool_sha256=evidence.digest(__file__))
        save()
        (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+str(p.relative_to(out))+'\n'
                                           for p in sorted(out.rglob('*')) if p.is_file()))
        return path
    except Exception as e:
        report.update(status='failed',error=str(e),traceback=traceback.format_exc());save();raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('motions','batch','soke-root','output'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--steps',type=int,choices=range(50,1001),default=1000)
    print(run(p.parse_args()))
if __name__=='__main__':main()
