"""Compare preserved native SMPL-X clips against current raw source observations."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

SHAPES={'global_orient':(1,3),'body_pose':(21,3),'left_hand_pose':(15,3),'right_hand_pose':(15,3),'jaw_pose':(1,3),'leye_pose':(1,3),'reye_pose':(1,3),'betas':(1,10),'expression':(1,10),'transl':(1,3)}
MODEL_SHA='376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def summary(x):
    v=np.asarray(x,float);a=v[np.isfinite(v)]
    return {'measured':int(a.size),'missing':int(v.size-a.size),'median':float(np.median(a)) if a.size else None,'p95':float(np.percentile(a,95)) if a.size else None,'max':float(a.max()) if a.size else None}


def angular_change(aa,mean=None):
    """Angles compare effective local joint rotations including the native hand mean."""
    aa=np.asarray(aa,float)
    if mean is not None:aa=aa+mean
    n,j,_=aa.shape;mat=Rotation.from_rotvec(aa.reshape(-1,3)).as_matrix().reshape(n,j,3,3)
    rel=mat[:-1].transpose(0,1,3,2)@mat[1:]
    return np.rad2deg(Rotation.from_matrix(rel.reshape(-1,3,3)).magnitude()).reshape(n-1,j)


def spatial_errors(native_xy,source_xy,mask):
    n=np.asarray(native_xy,float);s=np.asarray(source_xy,float);mask=np.asarray(mask,bool)
    if n.shape!=s.shape or n.shape[1:]!=(21,2) or mask.shape!=(len(n),):raise ValueError('Hand comparison shape differs')
    absolute=np.sqrt(np.mean(np.square(n-s),axis=(1,2)));local=np.sqrt(np.mean(np.square((n-n[:,0:1])-(s-s[:,0:1])),axis=(1,2)))
    wrist=np.linalg.norm(n[:,0]-s[:,0],axis=1)
    for x in [absolute,local,wrist]:x[~mask]=np.nan
    return {'absolute_rmse_pixels':summary(absolute),'local_hand_rmse_pixels':summary(local),'wrist_error_pixels':summary(wrist),'source_valid_frames':int(mask.sum())}


def compare_velocity(native_xy,source_xy,mask):
    n=np.asarray(native_xy,float);s=np.asarray(source_xy,float);valid=np.asarray(mask,bool)
    a=np.diff(n[:,0],axis=0);b=np.diff(s[:,0],axis=0);adj=valid[:-1]&valid[1:];an=np.linalg.norm(a,axis=1);bn=np.linalg.norm(b,axis=1)
    moving=adj&(bn>1)&(an>1);cos=np.full(len(a),np.nan)
    cos[moving]=np.clip(np.sum(a[moving]*b[moving],axis=1)/(an[moving]*bn[moving]),-1,1)
    error=np.linalg.norm(a-b,axis=1);error[~adj]=np.nan
    return {'wrist_velocity_error_pixels_per_frame':summary(error),'direction_cosine_on_observed_motion':summary(cos),
            'observed_motion_transitions':int(moving.sum()),'opposite_direction_transitions':int(np.sum(cos<0))}


def parameters(path):
    with np.load(path,allow_pickle=False) as f:
        if set(f.files)!=set(SHAPES):raise ValueError('Unexpected native parameter keys')
        a={k:f[k].copy() for k in f.files}
    if any(a[k].shape!=shape or a[k].dtype.kind!='f' or not np.isfinite(a[k]).all() for k,shape in SHAPES.items()):raise ValueError('Invalid native array shape/dtype/value')
    return a


def asset_inventory(folder,count):
    folder=Path(folder).resolve()
    actual={p.name for p in (folder/'smplx').glob('*.npz')}
    expected={f'{i:05d}_0.npz' for i in range(1,count+1)}
    if actual-expected:raise ValueError('Native extra frame/person files present')
    meta_actual={p.name for p in (folder/'meta').glob('*.json')}
    if meta_actual!={name.removesuffix('.npz')+'.json' for name in actual}:raise ValueError('Native metadata set differs')
    renders={p.name for p in (folder/'img').glob('*.jpg')}
    if renders!={f'{i:06d}.jpg' for i in range(1,count+1)}:raise ValueError('Native render frame set differs')
    hashes=[]
    for i in range(1,count+1):
        native=folder/'smplx'/f'{i:05d}_0.npz';meta=folder/'meta'/f'{i:05d}_0.json';render=folder/'img'/f'{i:06d}.jpg'
        hashes.append({'frame':i,'native':sha(native) if native.exists() else None,'metadata':sha(meta) if meta.exists() else None,'render':sha(render)})
    return hashes


def version_digest(source,clip,hashes):
    return hashlib.sha256(json.dumps({'source':source,'clip':clip,'frames':hashes},sort_keys=True).encode()).hexdigest()


def verify_action(record):
    folder=Path(record['native_directory']);current=asset_inventory(folder,record['expected_frames'])
    actual=version_digest(record['source_sha256'],record['clip_sha256'],current)
    if actual!=record['action_version_sha256']:raise ValueError('Current native/meta/render files differ from verified action version')
    return current


def identity_chain(item,sample,aliases,sequences):
    sid=sample['id'];alias=aliases.get(sid)
    if not alias or alias['source_sha256']!=sample['source_sha256'] or alias['candidate_clip_sha256']!=sample['media_sha256']:
        raise ValueError('Candidate alias source/clip binding differs')
    fit=alias['fit_sequence_id'];sequence=sequences.get(fit)
    if not sequence or sequence['source_sha256']!=sample['source_sha256'] or sequence['clip_sha256']!=sample['media_sha256'] or sequence['frames']!=sample['frames']:
        raise ValueError('Native sequence source/clip/frame binding differs')
    if item['fit_sequence_id']!=fit or item['source_sha256']!=sample['source_sha256'] or item['clip_sha256']!=sample['media_sha256']:
        raise ValueError('Native mapping differs from frozen alias identity')
    report_path=Path(item['proof_path']).resolve()
    if sha(report_path)!=item['proof_sha256']:raise ValueError('Native run report changed')
    report=json.loads(report_path.read_text());found=[r for r in report.get('candidate_records',[]) if r['annotation_id']==fit]
    if len(found)!=1:raise ValueError('Native fit identity absent/duplicated in actual runner report')
    record=found[0]
    if record['source_sha256']!=sample['source_sha256'] or record['frames_expected']!=sample['frames']:raise ValueError('Native runner report source/frame binding differs')
    folder=report_path.parent/'fits'/fit
    for key,sub in [('smplx_directory','smplx'),('metadata_directory','meta'),('render_directory','img')]:
        if record.get(key)!=f'fits/{fit}/{sub}':raise ValueError('Runner report native output path differs')
    if Path(item['native_sample_proof']['path']).resolve().parent.parent!=folder.resolve():raise ValueError('Mapped native directory does not belong to actual run report')
    if not folder.is_dir() or folder.is_symlink():raise ValueError('Missing/unsafe actual native directory')
    if sha(Path(item['clip_proof']['path']))!=sample['media_sha256']:raise ValueError('Proven source clip changed')
    return folder,fit


def run(database,observations,mapping,model_file,output):
    db,obs,out=map(lambda p:Path(p).resolve(),[database,observations,output]);mapping=Path(mapping).resolve();model_file=Path(model_file).resolve()
    if out.exists() or out.is_relative_to(db) or out.is_relative_to(obs):raise ValueError('New separate output required')
    if sha(model_file)!=MODEL_SHA:raise ValueError('Native model asset differs')
    spec=importlib.util.spec_from_file_location('foundation_hand_model',Path(__file__).with_name('sign-hand-refine.py'));h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h);model=h.SparseSMPLX(model_file)
    samples={x['id']:x for x in [json.loads(l) for l in (db/'samples.jsonl').read_text().splitlines()]}
    previous=json.loads(mapping.read_text());proofs=previous['identity_evidence_files'];identity_indexes={}
    for key in ['aliases','sequences']:
        p=Path(proofs[key]['path']);raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=proofs[key]['sha256']:raise ValueError('Native identity index changed')
        identity_indexes[key]=[json.loads(x) for x in raw.decode().splitlines()]
    aliases={x['candidate_id']:x for x in identity_indexes['aliases']};sequences={x['annotation_id']:x for x in identity_indexes['sequences']}
    lookup={x['candidate_id']:x for x in previous['items']};records=[];out.mkdir(parents=True)
    for k,sid in enumerate(lookup,1):
        item=lookup[sid];sample=samples[sid];folder,fit_id=identity_chain(item,sample,aliases,sequences);expected=sample['frames'];person0={p.name for p in (folder/'smplx').glob('*_0.npz')};missing=sorted(set(range(1,expected+1))-{int(p.split('_')[0]) for p in person0})
        evidence={'candidate_id':sid,'source_sha256':sample['source_sha256'],'clip_sha256':sample['media_sha256'],'expected_frames':expected,
                  'native_frame_count':len(person0),'missing_native_frames':missing,'native_directory':str(folder),
                  'human_approved':False,'training_ready':False,'model_training_ready':False,'video_semantic_match':'unverified','actual_3d_collisions':'not_independently_tested'}
        if item['clip_sha256']!=sample['media_sha256'] or sha(Path(item['clip_proof']['path']))!=sample['media_sha256'] or sha(item['proof_path'])!=item['proof_sha256']:
            raise ValueError('Prior native identity proof changed')
        observation_report=json.loads((obs/sid/'report.json').read_text());observation_file=obs/sid/'observations.npz'
        if sha(observation_file)!=observation_report['observations_sha256'] or observation_report['clip_sha256']!=sample['media_sha256']:raise ValueError('Source observation binding differs')
        hashes=asset_inventory(folder,expected);params=[];frame_ids=[];errors=[];meta_list=[]
        for n in range(1,expected+1):
            p=folder/'smplx'/f'{n:05d}_0.npz';meta=folder/'meta'/f'{n:05d}_0.json'
            if not p.exists():continue
            a=parameters(p);m=json.loads(meta.read_text());path=Path(m.get('img_path',''))
            if path.name!=f'{n:06d}.jpg' or path.parent.name!=item['fit_sequence_id'] or m.get('bbox_id')!=0:
                raise ValueError('Native metadata frame/person/sequence mapping differs')
            params.append(a);meta_list.append(m);frame_ids.append(n)
        version=version_digest(sample['source_sha256'],sample['media_sha256'],hashes);evidence['action_version_sha256']=version
        evidence['validated_run_identity']={'report':item['proof_path'],'report_sha256':item['proof_sha256'],'sequence_id':fit_id}
        evidence['asset_inventory_sha256']=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
        (out/(sid+'-native-frame-hashes.json')).write_text(json.dumps(hashes,indent=2)+'\n')
        if missing:
            evidence.update(round1_status='failed_incomplete_native_action',round2_status='blocked_incomplete_native_action',all_frames_native_complete=False,
                            independent_passes=0,spatial_round1=None,temporal_round2=None)
        else:
            with np.load(observation_file,allow_pickle=False) as z:source={key:z[key] for key in ['left_hand_image','right_hand_image','left_hand_image_detected','right_hand_image_detected']}
            width,height=observation_report['dimensions_wh'];predicted={side:[] for side in ['left','right']}
            for a,m in zip(params,meta_list):
                camera={name:np.asarray(m[name],float) for name in ['focal','princpt']}
                if any(v.shape!=(2,) or not np.isfinite(v).all() for v in camera.values()) or not (camera['focal']>0).all():raise ValueError('Invalid frame camera')
                prepared=model.prepared(a)
                for side in predicted:predicted[side].append(h.project(model.hand(a,side,prepared),camera))
            spatial={};temporal={};issues=[]
            for side in predicted:
                xy=np.asarray(predicted[side]);target=source[side+'_hand_image'][:,:,:2]*[width,height];mask=source[side+'_hand_image_detected']
                spatial[side]=spatial_errors(xy,target,mask);temporal[side]=compare_velocity(xy,target,mask)
                pose=np.stack([a[side+'_hand_pose'] for a in params]);mean=model.mean[25:40] if side=='left' else model.mean[40:55];angles=angular_change(pose,mean)
                temporal[side]['effective_joint_adjacent_degrees']=summary(angles)
                if not mask.all():issues.append(side+'_source_hand_not_observed_in_all_frames')
                for name,tolerance in [('local_hand_rmse_pixels',8.),('wrist_error_pixels',20.)]:
                    val=spatial[side][name]['p95']
                    if val is not None and val>tolerance:issues.append(side+'_'+name+'_exceeds_triage_tolerance')
                if angles.max()>60:issues.append(side+'_adjacent_rotation_over60deg')
            evidence.update(round1_status='needs_correction_or_more_evidence' if issues else 'spatial_technical_checks_only_not_full_semantic_pass',
                            round2_status='not_passed_unverified_handshape_depth_face_and_continuity',all_frames_native_complete=True,
                            independent_passes=0,spatial_round1=spatial,temporal_round2=temporal,issues=issues,
                            source_hand_slot_to_native_hand='fixed_same_label_no_swap; anatomical/mirror_unconfirmed')
            np.savez_compressed(out/(sid+'-native-projection.npz'),left=np.asarray(predicted['left'],np.float32),right=np.asarray(predicted['right'],np.float32))
        records.append(evidence);(out/'progress.json').write_text(json.dumps({'checked':k,'expected':len(lookup)})+'\n')
        if k%10==0:print(json.dumps({'native_compared':k,'total':len(lookup)}),flush=True)
    for record in records:verify_action(record)
    for key in ['aliases','sequences']:
        if sha(Path(proofs[key]['path']))!=proofs[key]['sha256']:raise ValueError('Identity index changed during comparison')
    (out/'records.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n' for x in records))
    report={'schema':'signbridge-csl-native-source-comparison-v1','status':'completed_checks_no_full_consistency_pass','clips':len(records),'complete_native':sum(x['all_frames_native_complete'] for x in records),'incomplete_native':sum(not x['all_frames_native_complete'] for x in records),
            'native_frames_rehashed':sum(x['native_frame_count'] for x in records),'two_round_complete_consistency_passes':0,'training_allowed':False,'weights_training_started':False,
            'model_sha256':MODEL_SHA,'mapping_sha256':sha(mapping),'source_observations_report_sha256':sha(obs/'report.json'),'tool_sha256':sha(__file__),
            'round1_scope':'Native arrays/frame/meta identity and per-frame spatial projection compared to un-smoothed source observations.',
            'round2_scope':'Different temporal and velocity/mean-offset rotation checks; neither substitutes for full source/3D handshape/nonmanual semantics validation.',
            'not_evidence_that_source_videos_are_wrong':True,'no_source_point_fill_or_hand_swap':True}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['database','observations','mapping','model-file','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.database,a.observations,a.mapping,a.model_file,a.output)),flush=True)
