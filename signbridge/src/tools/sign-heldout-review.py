"""Independent recomputation of fresh source-held-out tokenizer metrics and CPU/GPU parity."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('heldout_source_eval',Path(__file__).with_name('sign-heldout-eval.py'))
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
evidence=evaluation.evidence
smoke=evaluation.smoke
PARTS=('all','body_face','left_hand','right_hand')


def validate_finished_report(report,rows):
    if report.get('schema')!='signbridge-leave-source-out-tokenizer-v1' or \
       report.get('status')!='leave_source_out_experiments_complete_pending_quality_review' or \
       report.get('evaluation_completed') is not True or report.get('training_ready') is not False or \
       report.get('source_files_unchanged') is not True or report.get('fresh_weights_per_fold') is not True:
        raise ValueError('Incomplete or unexpected independent evaluation report')
    expected=evaluation.holdout_fold_indices(rows)
    index={r['segment_id']:r for r in rows}
    folds=report.get('folds',[])
    if len(folds)!=len(expected) or [f.get('fold_id') for f in folds]!=list(range(1,len(folds)+1)):
        raise ValueError('Fold scope differs')
    for fold,ids in zip(folds,expected):
        eval_ids=[rows[i]['segment_id'] for i in ids]
        train_ids=[r['segment_id'] for i,r in enumerate(rows) if i not in ids]
        if fold.get('train_segments')!=train_ids or fold.get('evaluation_segments')!=eval_ids:
            raise ValueError('Train/evaluation fold scope differs')
        train=[index[s] for s in train_ids];test=[index[s] for s in eval_ids]
        evaluation.assert_disjoint(train,test)
        if fold.get('train_source_ids')!=sorted({r['source_id'] for r in train}) or \
           fold.get('evaluation_source_ids')!=sorted({r['source_id'] for r in test}):
            raise ValueError('Fold source identities differ')
        if fold.get('checkpoint_reload_passed') is not True or fold.get('heldout_metrics_computed') is not True or \
           fold.get('recorded_split_disjoint') is not True or \
           fold.get('evaluation_used_for_weight_updates') is not False or \
           fold.get('evaluation_used_for_checkpoint_selection') is not False or \
           fold.get('normalization_frame_count')!=sum(r['frames'] for r in train):
            raise ValueError('Fold leaks evaluation statistics/selection or has incomplete reload')


def relative_improvement(model,baseline):
    if model is None or baseline is None or baseline<=0:return None
    return float(100.*(baseline-model)/baseline)


def compare_saved_metrics(actual,saved):
    for part in PARTS:
        if saved[part]['valid_values']!=actual[part]['valid_values']:
            raise ValueError('Saved valid target count differs')
        for key in ('normalized_mse','raw_rmse','mean_baseline_normalized_mse'):
            a,b=actual[part][key],saved[part][key]
            if (a is None)!=(b is None) or (a is not None and not np.isclose(a,b,rtol=1e-5,atol=1e-7)):
                raise ValueError('Saved evaluation metric differs: '+part+'/'+key)


def load_fold_checkpoint(path):
    """Called only after comparing the trusted report and checkpoint file digests."""
    import torch
    version=tuple(map(int,torch.__version__.split('+')[0].split('.')[:2]))
    return torch.load(path,map_location='cpu',weights_only=False) if version>=(2,0) else torch.load(path,map_location='cpu')


def plot_summary(folds,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for row,fold in enumerate(folds):
        train=next(s for s in fold['samples'] if s['role']=='train')['metrics']
        test=next(s for s in fold['samples'] if s['role']=='evaluation')['metrics']
        ax=axes[row,0]
        ax.bar(['Seen training motion','Unseen-source motion'],[train['all']['raw_rmse'],test['all']['raw_rmse']],
               color=['#207d68','#c35739'])
        ax.set_ylabel('Masked reconstruction RMSE\n(raw pose/expression units)',fontsize=9)
        ax.set_title('Fold %d: %s training source'%(fold['fold_id'],'Hospital' if row==0 else 'Greeting'))
        ax=axes[row,1];x=np.arange(len(PARTS));w=.36
        model=[test[p]['normalized_mse'] or 0. for p in PARTS]
        baseline=[test[p]['mean_baseline_normalized_mse'] or 0. for p in PARTS]
        ax.bar(x-w/2,model,width=w,label='Held-out reconstruction',color='#3274a1')
        ax.bar(x+w/2,baseline,width=w,label='Training-mean baseline',color='#a3a5a7')
        ax.set_xticks(x,['All','Body/face','Left hand','Right hand']);ax.legend(fontsize=8)
        ax.set_ylabel('Normalized MSE\n(training statistics of this fold)',fontsize=9)
        ax.set_title('Unseen source; no evaluation-driven checkpoint selection')
    for ax in axes.ravel():ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('Source-held-out reconstruction experiment; not text generation or sign-language accuracy')
    try:fig.savefig(path,dpi=140)
    finally:plt.close(fig)


def review(args):
    results,motions,batch,cpu,out=[Path(getattr(args,k)).resolve() for k in
                                 ('results','motions','batch','cpu_inference','output')]
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (results.parent,motions,batch,cpu)):
        raise ValueError('Output must be new and separate')
    checks=evidence.verify_manifest(results,results/'SHA256SUMS')
    source_report=evidence.contained_file(results,'report.json')
    if evidence.digest(source_report)!=args.report_sha256 or checks.get('report.json')!=args.report_sha256:
        raise ValueError('Evaluation report digest differs')
    r=evidence.load_json(source_report)
    inputs=argparse.Namespace(motions=motions,batch=batch)
    rows,arrays,masks,tasks,watched=evaluation.prepare_inputs(inputs)
    validate_finished_report(r,rows)
    exposure=evaluation.exposure_audit(tasks,[x['segment_id'] for x in rows])
    if exposure!=r['previous_mixed_checkpoint_exposure'] or evaluation.group_components(tasks)!=r['source_group_components']:
        raise ValueError('Evaluation batch/exposure groups differ')
    for name,sha in r.get('source_sha256',{}).items():
        # Remote paths are provenance data only; resolve selected source surfaces via suffixes.
        for folder,marker in ((motions,'/curated-motions/'),(batch,'/batch/')):
            if marker in name:
                relative=name.rsplit(marker,1)[1]
                p=evidence.contained_file(folder,relative)
                if evidence.digest(p)!=sha:raise ValueError('Evaluation input/source digest differs')
    by_id={row['segment_id']:i for i,row in enumerate(rows)}
    folds=[]
    for fold in r['folds']:
        folder=results/('fold-%02d'%fold['fold_id'])
        checkpoint=evidence.contained_file(folder,'tokenizer-heldout.pt')
        relative=str(checkpoint.relative_to(results))
        if checks.get(relative)!=fold['checkpoint_sha256'] or evidence.digest(checkpoint)!=fold['checkpoint_sha256']:
            raise ValueError('Fold checkpoint hash differs')
        saved=load_fold_checkpoint(checkpoint)
        if saved.get('schema')!='signbridge-heldout-tokenizer-checkpoint-v1' or saved.get('training_ready') is not False or \
           saved.get('research_only') is not True or saved.get('soke_commit')!=smoke.SOKE_COMMIT or \
           saved.get('normalization_train_only') is not True or saved.get('train_segments')!=fold['train_segments'] or \
           saved.get('evaluation_segments')!=fold['evaluation_segments'] or saved.get('step')!=fold['checkpoint_step']:
            raise ValueError('Fold checkpoint source/normalization contract differs')
        train_ids=[by_id[s] for s in fold['train_segments']]
        mean,std=smoke.normalization([arrays[i] for i in train_ids],[masks[i] for i in train_ids])
        if not np.allclose(mean,saved['mean'],rtol=1e-6,atol=1e-7) or not np.allclose(std,saved['std'],rtol=1e-6,atol=1e-7):
            raise ValueError('Checkpoint normalization not fitted from training fold only')
        samples=[];parity=[]
        for metric in fold['sample_metrics']:
            segment=metric['segment_id'];i=by_id[segment]
            prediction_path=evidence.contained_file(folder,segment+'/reconstructed-133.npy')
            if checks.get(str(prediction_path.relative_to(results)))!=evidence.digest(prediction_path):
                raise ValueError('Unlisted reconstruction output')
            prediction=np.load(prediction_path,allow_pickle=False)
            actual=evaluation.comparison_metrics(prediction,arrays[i],masks[i],mean,std)
            compare_saved_metrics(actual,metric['metrics'])
            role='evaluation' if segment in fold['evaluation_segments'] else 'train'
            if role!=metric['role']:raise ValueError('Recorded sample evaluation role differs')
            samples.append({'segment_id':segment,'role':role,'frames':len(prediction),'metrics':actual})
            if role=='evaluation':
                cfolder=cpu/('fold-%02d'%fold['fold_id'])/segment
                cchecks=evidence.verify_manifest(cfolder,cfolder/'SHA256SUMS')
                cr=evidence.load_json(cfolder/'report.json')
                if cr.get('checkpoint_sha256')!=fold['checkpoint_sha256'] or cr.get('checkpoint_role')!='fresh_source_holdout_fold' or \
                   cr.get('train_segments')!=fold['train_segments'] or cr.get('evaluation_segments')!=fold['evaluation_segments'] or \
                   cr.get('input_features_sha256')!=evidence.digest(motions/rows[i]['features']) or \
                   cr.get('mask_sha256')!=evidence.digest((motions/rows[i]['features']).with_name('feature-valid-mask.npy')):
                    raise ValueError('CPU inference source/checkpoint differs')
                cpu_prediction=np.load(cfolder/'reconstructed-133.npy',allow_pickle=False)
                if cpu_prediction.shape!=prediction.shape or not np.isfinite(cpu_prediction).all():
                    raise ValueError('CPU reconstruction shape/values differ')
                error=float(np.abs(cpu_prediction-prediction).max())
                if error>1e-5:raise ValueError('CPU/GPU reconstruction parity failed')
                for token in ('body','left','right'):
                    if not np.array_equal(np.load(cfolder/(token+'-tokens.npy'),allow_pickle=False),
                                          np.load(folder/segment/(token+'-tokens.npy'),allow_pickle=False)):
                        raise ValueError('CPU/GPU token arrays differ')
                parity.append({'segment_id':segment,'max_cpu_gpu_difference':error,'token_arrays_identical':True})
        if len(samples)!=len(rows) or {m['segment_id'] for m in samples}!=set(by_id):
            raise ValueError('Metric sample scope differs')
        test=[m for m in samples if m['role']=='evaluation']
        fold_result={'fold_id':fold['fold_id'],'train_segments':fold['train_segments'],
                     'evaluation_segments':fold['evaluation_segments'],'checkpoint_step':fold['checkpoint_step'],
                     'checkpoint_sha256':fold['checkpoint_sha256'],'samples':samples,
                     'normalization_train_only_verified':True,'source_disjoint_verified':True,
                     'normalization_training_frames':sum(rows[i]['frames'] for i in train_ids),
                     'normalization_valid_values_per_feature':np.concatenate([masks[i] for i in train_ids]).sum(axis=0).tolist(),
                     'evaluation_used_for_training_or_selection':False,'cpu_gpu_parity':parity,
                     'relative_mean_baseline_improvement_percent':{p:relative_improvement(test[0]['metrics'][p]['normalized_mse'],
                                         test[0]['metrics'][p]['mean_baseline_normalized_mse']) for p in PARTS}}
        folds.append(fold_result)
    for path,sha in watched.items():
        if evidence.digest(path)!=sha:raise ValueError('Input changed during review')
    evidence.verify_manifest(results,results/'SHA256SUMS')
    out.mkdir(parents=True);plot_summary(folds,out/'heldout-comparison.png')
    summary={'schema':'signbridge-source-heldout-review-v1','status':'source_holdout_evidence_independently_recomputed',
             'training_ready':False,'deployment_ready':False,'text_to_sign_trained':False,
             'sign_semantics_or_contact_approved':False,'recorded_source_holdout_completed':True,
             'actual_signer_disjointness_verified':False,'source_report_sha256':args.report_sha256,
             'review_tool_sha256':evidence.digest(__file__),'folds':folds,'previous_checkpoint_exposure':exposure,
             'recorded_training_tool_sha256':r.get('evaluation_tool_sha256'),
             'evaluation_verification_tool_sha256':evidence.digest(evaluation.__file__),
             'conclusion':'Both source-held-out models are only modestly better overall than the training-mean baseline; seen-source accuracy does not establish unseen-source reconstruction quality.',
             'limitations':r['limitations']+['Each fold has different training mean/std; normalized fold MSE must be interpreted against its own baseline.']}
    path=out/'report.json';path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file()))
    return path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('results','motions','batch','cpu-inference','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--report-sha256',required=True)
    print(review(p.parse_args()))
if __name__=='__main__':main()
