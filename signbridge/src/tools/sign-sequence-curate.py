"""Research alternative choosing existing baseline/fusion frames to reduce added large jumps."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

spec=importlib.util.spec_from_file_location('sequence_export',Path(__file__).with_name('sign-sequence-export.py'))
export=importlib.util.module_from_spec(spec);spec.loader.exec_module(export)
align=export.align
evidence=export.evidence


def choose_existing_poses(baseline,candidate,applied):
    if set(baseline)!=set(align.hand.SHAPES) or set(candidate)!=set(baseline):
        raise ValueError('Invalid native parameter fields')
    n=len(baseline['body_pose'])
    mask=np.asarray(applied)
    if not n or mask.shape!=(n,2) or mask.dtype.kind!='b':raise ValueError('Invalid candidate mask')
    for key,shape in align.hand.SHAPES.items():
        for values in (baseline[key],candidate[key]):
            if values.shape!=(n,)+shape or values.dtype.kind!='f' or not np.isfinite(values).all():
                raise ValueError('Invalid native parameter series')
    for i in range(n):
        a={k:v[i] for k,v in baseline.items()};b={k:v[i] for k,v in candidate.items()}
        align.hand.preserved(a,b,('left','right'),allow_elbow=True)
        for j,side in enumerate(('left','right')):
            if not mask[i,j]:
                indices=[align.hand.WRISTS[side]-1,align.hand.ELBOWS[side]-1]
                if not np.array_equal(a[side+'_hand_pose'],b[side+'_hand_pose']) or \
                   not np.array_equal(a['body_pose'][indices],b['body_pose'][indices]):
                    raise ValueError('Unaccepted hand differs from exact baseline')
    angles=[]
    for source in (baseline,candidate):
        sides=[]
        for side in ('left','right'):
            a=np.asarray(source[side+'_hand_pose'],dtype=np.float64)
            if a.shape!=(n,15,3) or not np.isfinite(a).all():raise ValueError('Invalid saved hand rotation')
            sides.append(Rotation.from_rotvec(a.reshape(-1,3)).as_matrix().reshape(n,15,3,3))
        angles.append(sides)
    def step(prev,i,state):
        maxima=[]
        for s in range(2):
            r=angles[state][s][i]@angles[prev][s][i-1].transpose(0,2,1)
            maxima.append(float(np.rad2deg(Rotation.from_matrix(r).magnitude().max())))
        return np.asarray(maxima)
    cost=np.full((n,2),np.inf);parent=np.zeros((n,2),dtype=int)
    # Dropping an applied hand costs one; a newly added >90 degree transition costs more than all drops.
    penalty=2*n+1
    cost[0]=[float(mask[0].sum()),0.]
    for i in range(1,n):
        baseline_step=step(0,i,0)
        for current in (0,1):
            choice=[]
            for previous in (0,1):
                jump=step(previous,i,current)
                introduced=int(np.any((jump>90.) & (jump>baseline_step+1e-6)))
                choice.append(cost[i-1,previous]+penalty*introduced+(float(mask[i].sum()) if current==0 else 0.))
            parent[i,current]=int(np.argmin(choice));cost[i,current]=min(choice)
    state=int(np.argmin(cost[-1]));selected=np.zeros(n,dtype=bool)
    for i in range(n-1,-1,-1):
        selected[i]=bool(state)
        state=parent[i,state]
    return selected


def curate(args):
    source,out=Path(args.motions).resolve(),Path(args.output).resolve()
    if out.exists() or source==out or source in out.parents or out in source.parents:raise ValueError('Output must be new and separate')
    checks=evidence.verify_manifest(source,source/'SHA256SUMS')
    verification=evidence.load_json(source/'verification.json')
    if verification.get('schema')!='signbridge-full-fusion-export-v1' or verification.get('training_ready') is not False:
        raise ValueError('Unexpected source export')
    records=[json.loads(x) for x in (source/'motions.jsonl').read_text().splitlines() if x.strip()]
    if len(records)!=2 or {r['segment_id'] for r in records}!=set(align.hand.FULL_SEQUENCE_COUNTS):
        raise ValueError('Unexpected motion segment scope')
    def listed(relative):
        path=evidence.contained_file(source,relative)
        if checks.get(relative)!=evidence.digest(path):
            raise ValueError('Unlisted source file or digest mismatch')
        return path
    summaries={};artifacts={}
    for row in records:
        if row.get('model_training_ready') is not False or row.get('motion_review_status')!='needs_review' or \
           row.get('dimensions')!=133 or row.get('representation')!='soke-smplx-133-v1':
            raise ValueError('Unexpected source motion readiness/representation')
        segment=row['segment_id'];folder=source/'samples'/segment
        relative='samples/'+segment+'/'
        with np.load(listed(relative+'fused-smplx-series.npz'),allow_pickle=False) as a:
            baseline={k:a['baseline_'+k].copy() for k in align.hand.SHAPES}
            candidate={k:a['candidate_'+k].copy() for k in align.hand.SHAPES}
            values={k:a[k].copy() for k in a.files}
        chosen=choose_existing_poses(baseline,candidate,values['candidate_applied_mask'])
        if len(chosen)!=row['frames'] or values['frame_ids'].shape!=(len(chosen),) or \
           not np.array_equal(values['frame_ids'],np.arange(1,len(chosen)+1)) or \
           values['observed_hand_mask'].shape!=(len(chosen),2) or values['observed_hand_mask'].dtype.kind!='b' or \
           np.any(values['candidate_applied_mask'] & ~values['observed_hand_mask']) or \
           not np.allclose(values['timestamps_seconds'],np.arange(len(chosen))/row['fps'],atol=1e-6,rtol=0):
            raise ValueError('Invalid saved timeline or observation mask')
        poses={k:np.where(chosen.reshape((-1,)+(1,)*(v.ndim-1)),v,baseline[k]) for k,v in candidate.items()}
        masks=values['candidate_applied_mask'] & chosen[:,None]
        previous_quality=evidence.load_json(listed(relative+'quality.json'))
        rows=[json.loads(x) for x in listed(relative+'frame-quality.jsonl').read_text().splitlines() if x.strip()]
        if [r['frame_1based'] for r in rows]!=list(range(1,len(chosen)+1)) or \
           not np.array_equal(np.array([[r['applied'].get(s,False) for s in ('left','right')] for r in rows]),
                              values['candidate_applied_mask']):
            raise ValueError('Saved frame selection masks differ')
        expected_features=export.features_133([{k:v[i] for k,v in candidate.items()} for i in range(len(chosen))])
        if not np.array_equal(np.load(listed(relative+'features-133.npy'),allow_pickle=False),expected_features) or \
           not np.array_equal(np.load(listed(relative+'feature-valid-mask.npy'),allow_pickle=False),export.feature_valid_mask(rows)):
            raise ValueError('Saved model features or valid mask differs')
        for i,quality in enumerate(rows):
            quality['applied']={s:bool(masks[i,j]) for j,s in enumerate(('left','right'))}
            quality['temporal_baseline_selected']=not bool(chosen[i])
        summary=export.observation_summary(rows)
        summary['rotations']={s:export.rotation_audit(poses[s+'_hand_pose']) for s in ('left','right')}
        summary['original_rotations']=previous_quality['rotations']
        summary['selected_baseline_to_frame']=(np.flatnonzero(~chosen & values['candidate_applied_mask'].any(axis=1))+1).tolist()
        summary['dropped_applied_hands']=int(values['candidate_applied_mask'].sum()-masks.sum())
        summary['training_ready']=False
        summaries[segment]=summary
        for k in poses:values['candidate_'+k]=poses[k]
        values['candidate_applied_mask']=masks
        artifacts[segment]=(poses,values,rows,chosen)
    evidence.verify_manifest(source,source/'SHA256SUMS')
    out.mkdir(parents=True)
    for segment,(poses,values,rows,chosen) in artifacts.items():
        folder=out/'samples'/segment;folder.mkdir(parents=True)
        parameters=[{k:v[i] for k,v in poses.items()} for i in range(len(chosen))]
        np.save(folder/'features-133.npy',export.features_133(parameters),allow_pickle=False)
        np.save(folder/'feature-valid-mask.npy',export.feature_valid_mask(rows),allow_pickle=False)
        np.savez_compressed(folder/'fused-smplx-series.npz',**values)
        (folder/'frame-quality.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (folder/'quality.json').write_text(json.dumps(summaries[segment],indent=2)+'\n')
        (folder/'fit-sources.jsonl').write_bytes((source/'samples'/segment/'fit-sources.jsonl').read_bytes())
        export.series_plot(rows,summaries[segment],folder/'full-sequence-quality.png')
    (out/'motions.jsonl').write_bytes((source/'motions.jsonl').read_bytes())
    verification.update(quality=summaries,
        input_quality='Unreviewed research alternative: exact saved poses selected by temporal continuity, no interpolation',
        temporal_selection={'method':'two-state existing-pose dynamic program; drop applied candidates to avoid >90 degree jumps added relative to baseline',
            'root_and_shape_exactly_preserved':True,'human_quality_approved':False,'no_pose_interpolation':True},
        parent_export_sha256=evidence.digest(source/'verification.json'),curation_tool_sha256=evidence.digest(__file__),
        pending=['Contact/occlusion and transition review','Mirror and identity','Independent held-out evaluation'])
    (out/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+str(p.relative_to(out))+'\n' for p in sorted(out.rglob('*')) if p.is_file()))
    return out/'verification.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--motions',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    print(curate(p.parse_args()))


if __name__=='__main__':main()
