"""Export full observed/fallback fusion arrays for research; never approve training labels."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


align=load('sign-mano-align')
evidence=load('sign-contact-audit')
SOKE_COMMIT='5cbc55d84b5a7cbf05a9cf020c468052e8d94d00'


def features_133(parameters):
    if not parameters:raise ValueError('Empty parameter sequence')
    arrays=[]
    for p in parameters:
        if set(p)!=set(align.hand.SHAPES) or any(np.shape(p[k])!=s or not np.isfinite(p[k]).all()
                                              for k,s in align.hand.SHAPES.items()):
            raise ValueError('Invalid native parameters')
        arrays.append(np.r_[p['body_pose'].ravel()[33:],p['left_hand_pose'].ravel(),
                            p['right_hand_pose'].ravel(),p['jaw_pose'].ravel(),p['expression'].ravel()])
    result=np.stack(arrays).astype(np.float32)
    if result.shape!=(len(parameters),133) or not np.isfinite(result).all():raise ValueError('Invalid feature sequence')
    return result


def rotation_audit(poses):
    a=np.asarray(poses,dtype=np.float64)
    if a.ndim!=3 or a.shape[2]!=3 or not np.isfinite(a).all():raise ValueError('Invalid pose series')
    r=Rotation.from_rotvec(a.reshape(-1,3)).as_matrix().reshape(len(a),a.shape[1],3,3)
    if len(a)<2:return {'max_adjacent_degrees':0.,'over_90_to_frame':[]}
    delta=r[1:]@r[:-1].swapaxes(-1,-2)
    angle=np.rad2deg(Rotation.from_matrix(delta.reshape(-1,3,3)).magnitude()).reshape(len(a)-1,-1)
    return {'max_adjacent_degrees':float(angle.max()),
            'over_90_to_frame':(np.flatnonzero((angle>90).any(axis=1))+2).tolist()}


def observation_summary(rows):
    result={'training_ready':False}
    for side in ('left','right'):
        def ids(condition):return [r['frame_1based'] for r in rows if condition(r)]
        result[side]={'missing_frames':ids(lambda r:r['detection_counts'][side]==0),
          'ambiguous_frames':ids(lambda r:r['detection_counts'][side]>1),
          'rejected_observed_frames':ids(lambda r:r['detection_counts'][side]==1 and not r['applied'].get(side,False)),
          'applied_frames':ids(lambda r:r['applied'].get(side,False))}
    return result


def feature_valid_mask(rows):
    mask=np.ones((len(rows),133),dtype=bool)
    mask[:,30:75]=np.asarray([r['applied'].get('left',False) for r in rows])[:,None]
    mask[:,75:120]=np.asarray([r['applied'].get('right',False) for r in rows])[:,None]
    return mask


def series_plot(rows,quality,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ids=[r['frame_1based'] for r in rows]
    fig,axes=plt.subplots(3,1,figsize=(12,7),constrained_layout=True)
    for j,side in enumerate(('left','right')):
        axes[j].plot(ids,[r['detection_counts'][side] for r in rows],label='Detected count')
        axes[j].plot(ids,[int(r['applied'].get(side,False)) for r in rows],label='Fusion applied',alpha=.8)
        axes[j].set_ylabel(side+' hand');axes[j].legend(fontsize=8)
    axes[2].plot(ids,[r['depth'] for r in rows]);axes[2].set_ylabel('Virtual depth (m)')
    for ax in axes:ax.set_xlabel('Clip frame');ax.grid(alpha=.25)
    fig.suptitle('Full sequence detection and candidate masks; NOT a motion quality approval')
    try:fig.savefig(path,dpi=120)
    finally:plt.close(fig)


def audit(args):
    batch,stable,wi,fusion,out=[Path(getattr(args,k)).resolve() for k in ('batch','stable_results','wilor_results','fusion_results','output')]
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (batch,stable.parent,wi.parent,fusion.parent)):
        raise ValueError('Output must be new and separate')
    checks={p:evidence.verify_manifest(p,p/'SHA256SUMS') for p in (batch,stable.parent,wi.parent,fusion.parent)}
    def report(root,sha):
        p=evidence.contained_file(root,'report.json')
        if evidence.digest(p)!=sha or checks[root.parent].get('results/report.json')!=sha:raise ValueError('Report digest differs')
        r=evidence.load_json(p)
        if r.get('training_ready') is not False or r.get('source_files_unchanged') is not True:
            raise ValueError('Incomplete/unexpected source report')
        return r
    sr=report(stable,args.stable_report_sha256);wr=report(wi,args.wilor_report_sha256);fr=report(fusion,args.fusion_report_sha256)
    if sr.get('schema')!='signbridge-stable-crop-pilot-v1' or sr.get('status')!='inferred_pending_stable_crop_review' or \
       wr.get('schema')!='signbridge-wilor-keyframe-pilot-v1' or wr.get('status') not in ('inferred_pending_visual_review','missing_required_hand') or \
       fr.get('schema')!='signbridge-mano-smplx-alignment-v1' or fr.get('status') not in ('alignment_candidates_pending_visual_review','alignment_candidate_gate_failed'):
        raise ValueError('Unexpected source report schema/status')
    if fr.get('stable_report_sha256')!=args.stable_report_sha256 or fr.get('wilor_report_sha256')!=args.wilor_report_sha256 or \
       fr.get('fit_source_kind')!='stable_crop' or fr.get('full_sequence_inferred') is not True:
        raise ValueError('Full fusion provenance differs')
    expected={(s,n) for s,n,_ in align.hand.full_sequence_cases()}
    def index(r):
        v={(c['segment_id'],c['frame_1based']):c for c in r['cases']}
        if set(v)!=expected or len(v)!=len(r['cases']):raise ValueError('Full sequence scope differs')
        return v
    si,wi_index,fi=map(index,(sr,wr,fr))
    tasks={r['segment_id']:r for r in (json.loads(x) for x in (batch/'tasks.jsonl').read_text().splitlines() if x.strip())}
    for name in ('contract.json','tasks.jsonl','SHA256SUMS'):
        evidence.require_source_digest(fr,'batch/'+name,evidence.digest(batch/name))
    def file(root,rel):
        p=evidence.contained_file(root,rel)
        if checks[root].get(rel)!=evidence.digest(p):raise ValueError('Unlisted parameter source')
        return p
    motion_rows=[];summaries={};arrays={}
    for segment,count in align.hand.FULL_SEQUENCE_COUNTS.items():
        if tasks[segment].get('frames')!=count or tasks[segment].get('model_training_ready') is not False or \
           not np.isfinite(tasks[segment]['fps']) or tasks[segment]['fps']<=0:
            raise ValueError('Batch task timeline/readiness differs')
        records=[];rows=[];params=[];sources=[]
        for number in range(1,count+1):
            identity=(segment,number);case=fi[identity];wcase=wi_index[identity]
            if case.get('segment_id')!=segment or case.get('output_relative')!=segment+'/%06d'%number or \
               wcase.get('output_relative')!=segment+'/%06d'%number or case.get('training_ready') is not False:
                raise ValueError('Saved frame/output identity differs')
            unique=align.unique_observed_sides(wcase)
            if case['required_sides']!=list(unique):raise ValueError('Saved fusion observed side identity differs')
            rel='results/'+segment+'/%06d'%number
            baseline_path=file(fusion.parent,rel+'/baseline.npz');candidate_path=file(fusion.parent,rel+'/candidate.npz')
            baseline=align.hand.read_native(baseline_path);candidate=align.hand.read_native(candidate_path)
            stable_path=file(stable.parent,'results/'+segment+'/smplx/%05d_0.npz'%number)
            original=align.hand.read_native(stable_path)
            if any(not np.array_equal(baseline[k],original[k]) for k in original):raise ValueError('Baseline source differs')
            align.hand.preserved(baseline,candidate,unique,allow_elbow=True)
            decisions={}
            for side in unique:
                matches=[h for h in case['hands'] if h['side']==side]
                if len(matches)!=1:raise ValueError('Missing saved candidate decision')
                decision=matches[0]['candidate_gate_passed']
                if type(decision) is not bool or matches[0]['applied_to_candidate']!=decision:raise ValueError('Decision mismatch')
                decisions[side]=decision
            if len(case['hands'])!=len(unique):raise ValueError('Unobserved hand candidate')
            for key in ('baseline_native_parity_max_metres','candidate_native_parity_max_metres'):
                if not isinstance(case[key],(int,float)) or not np.isfinite(case[key]) or not 0<=case[key]<=5e-5:
                    raise ValueError('Saved native parity failed')
            record={'frame_1based':number,'fps':tasks[segment]['fps'],'sides':unique,
                    'baseline':baseline,'candidate':candidate,'decisions':decisions}
            records.append(record);params.append(candidate)
            rows.append({'frame_1based':number,'detection_counts':{s:sum(h['side']==s for h in wcase['hands']) for s in ('left','right')},
                         'applied':{s:decisions.get(s,False) for s in ('left','right')},'depth':float(candidate['transl'][0,2])})
            sources.append({'frame_id':number,'source_candidate_sha256':evidence.digest(candidate_path),
                            'source_baseline_sha256':evidence.digest(baseline_path)})
        packed=align.pack_series(records,allow_variable_sides=True)
        saved=file(fusion.parent,'results/'+segment+'/baseline-candidate-series.npz')
        with np.load(saved,allow_pickle=False) as a:
            if set(a.files)!=set(packed) or any(not np.array_equal(a[k],packed[k]) for k in packed):raise ValueError('Series array/mask differs')
        features=features_133(params)
        quality=observation_summary(rows)
        quality['rotations']={side:rotation_audit(np.stack([p[side+'_hand_pose'] for p in params])) for side in ('left','right')}
        quality['selection_switch_frames']={s:[i+1 for i in range(1,len(rows)) if rows[i]['applied'][s]!=rows[i-1]['applied'][s]] for s in ('left','right')}
        quality['max_adjacent_virtual_depth_step_metres']=float(np.abs(np.diff([r['depth'] for r in rows])).max())
        quality['all_motion_frames_approved']=False
        summaries[segment]=quality;arrays[segment]=(features,packed,rows,sources)
        motion_rows.append({**tasks[segment],'representation':'soke-smplx-133-v1','dimensions':133,
            'features':'samples/'+segment+'/features-133.npy','motion_review_status':'needs_review','model_training_ready':False})
    out.mkdir(parents=True)
    for s,(features,packed,rows,sources) in arrays.items():
        folder=out/'samples'/s;folder.mkdir(parents=True)
        np.save(folder/'features-133.npy',features,allow_pickle=False)
        np.save(folder/'feature-valid-mask.npy',feature_valid_mask(rows),allow_pickle=False)
        np.savez_compressed(folder/'fused-smplx-series.npz',**packed)
        (folder/'frame-quality.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (folder/'fit-sources.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in sources))
        (folder/'quality.json').write_text(json.dumps(summaries[s],indent=2)+'\n')
        series_plot(rows,summaries[s],folder/'full-sequence-quality.png')
    (out/'motions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in motion_rows))
    verification={'schema':'signbridge-full-fusion-export-v1','soke_commit':SOKE_COMMIT,'converted':2,'rejected':[],
        'training_ready':False,'input_quality':'Unreviewed full stable-crop fusion; missing/ambiguous/rejected hands retain baseline',
        'source_sha256':{'stable_report':args.stable_report_sha256,'wilor_report':args.wilor_report_sha256,
                        'fusion_report':args.fusion_report_sha256,'export_tool':evidence.digest(__file__)},
        'quality':summaries,'pending':['Hand contact/occlusion review','Mirror orientation','Grouped held-out split','Independent sign-language quality evaluation']}
    (out/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+str(p.relative_to(out))+'\n' for p in sorted(out.rglob('*')) if p.is_file()))
    return out/'verification.json'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('batch','stable-results','wilor-results','fusion-results','output'):p.add_argument('--'+k,type=Path,required=True)
    for k in ('stable-report-sha256','wilor-report-sha256','fusion-report-sha256'):p.add_argument('--'+k,required=True)
    print(audit(p.parse_args()))


if __name__=='__main__':main()
