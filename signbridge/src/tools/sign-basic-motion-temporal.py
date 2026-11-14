"""Joint source-constrained correction of contiguous observed hand runs, never gap fill."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import time
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation


def load(name):
 s=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


correction=load('sign-basic-motion-correct.py');h=correction.hand;c=correction.compare


def contiguous(mask):
 groups=[]
 for i,valid in enumerate(mask):
  if valid:
   if not groups or i!=groups[-1][-1]+1:groups.append([i])
   else:groups[-1].append(i)
 return groups


def joint_fit(model,originals,targets,cameras,anchor,side='left',max_nfev=100):
 count=len(originals);key=side+'_hand_pose';ei=h.ELBOWS[side]-1;wi=h.WRISTS[side]-1;mean=model.mean[25:40] if side=='left' else model.mean[40:55];anchorrot=h.hand_rotations(anchor,model,side)
 prepared=[model.prepared(p) for p in originals];scales=[h.target_scale(p[:,:2]) for p in targets];weights=np.ones((21,1));weights[[4,8,12,16,20]]=1.5
 centers=[];inits=[]
 for source in originals:
  center=np.r_[source[key].ravel(),[0.,0.,0.],[0.,0.,0.]];initial=center.copy();initial[:45]=anchor[key].ravel();centers.append(center);inits.append(initial)
 centers=np.asarray(centers);bounds=np.r_[np.full(45,np.deg2rad(150)),np.full(3,np.pi),np.full(3,np.deg2rad(55))];inits=np.clip(inits,centers-bounds+1e-7,centers+bounds-1e-7)
 def unpack(values):
  result=[]
  for source,vector in zip(originals,values.reshape(count,51)):
   p={k:v.astype(float).copy() for k,v in source.items()};p[key]=vector[:45].reshape(15,3);p['body_pose'][ei]=h.bounded_elbow_rotation(vector[45:48],source['body_pose'][ei],14.99);p['body_pose'][wi]=h.bounded_elbow_rotation(vector[48:51],source['body_pose'][wi],79.99);result.append(p)
  return result
 # Each frame's source residual; adjacent geometry prior uses two frames and cannot bridge missing indices.
 frame_len=42+42+2+135+9+9
 adjacent_len=135+9
 sparsity=lil_matrix((count*frame_len+(count-1)*adjacent_len,count*51),dtype=int)
 for i in range(count):sparsity[i*frame_len:(i+1)*frame_len,i*51:(i+1)*51]=1
 for i in range(count-1):sparsity[count*frame_len+i*adjacent_len:count*frame_len+(i+1)*adjacent_len,i*51:(i+2)*51]=1
 def residual(values):
  params=unpack(values);parts=[];rotations=[];wrists=[]
  for i,p in enumerate(params):
   xy=h.project(model.hand(p,side,prepared[i]),cameras[i]);local=(xy-xy[0])/scales[i];targetlocal=(targets[i][:,:2]-targets[i][0,:2])/scales[i];rot=h.hand_rotations(p,model,side);wr=Rotation.from_rotvec(p['body_pose'][wi]).as_matrix();er=Rotation.from_rotvec(p['body_pose'][ei]).as_matrix()-Rotation.from_rotvec(originals[i]['body_pose'][ei]).as_matrix()
   parts.extend([(weights*(local-targetlocal)).ravel(),(1.25*weights*(xy-targets[i][:,:2])/scales[i]).ravel(),8*(xy[0]-targets[i][0,:2])/scales[i],.22*(rot-anchorrot).ravel(),.03*er.ravel(),.08*(wr-Rotation.from_rotvec(originals[i]['body_pose'][wi]).as_matrix()).ravel()]);rotations.append(rot);wrists.append(wr)
  for i in range(count-1):parts.extend([3.0*(rotations[i+1]-rotations[i]).ravel(),.50*(wrists[i+1]-wrists[i]).ravel()])
  return np.concatenate(parts)
 result=least_squares(residual,inits.ravel(),jac_sparsity=sparsity.tocsr(),bounds=((centers-bounds).ravel(),(centers+bounds).ravel()),loss='linear',max_nfev=max_nfev,xtol=2e-5,ftol=2e-5,gtol=2e-5)
 proposal=[{k:v.astype(source[k].dtype) for k,v in p.items()} for source,p in zip(originals,unpack(result.x))]
 for before,after in zip(originals,proposal):correction.unchanged(before,after,side)
 return proposal,{'status':int(result.status),'nfev':int(result.nfev),'cost':float(result.cost),'message':str(result.message),'frames':count,'source_specific_anchor_regularization':.22,'adjacent_effective_hand_regularization':3.0,'not_interpolated':True,'semantic_or3D_truth_implied':False}


def verify_bound_inputs(library, independent, sid, model_file):
 action=correction.verify_inputs(library,sid,model_file)
 prior=json.loads((independent/sid/'report.json').read_text())
 for field,old in [('source_sha256','source_sha256'),('clip_sha256','source_clip_sha256'),('action_version_sha256','baseline_action_version'),('annotation_sha256','annotation_sha256')]:
  if action[field]!=prior[old]:raise ValueError('Prior correction source identity changed: '+field)
 for name,digest in prior['source_file_hashes'].items():
  if correction.sha(name)!=digest:raise ValueError('Previously verified source hash differs: '+name)
 if correction.sha(model_file)!=c.MODEL_SHA:raise ValueError('SMPL-X model differs')
 if correction.sha(correction.safe_file(library,action['clip']))!=action['clip_sha256']:raise ValueError('Source clip hash differs')
 comparison=action['native_comparison']
 for field in ['source_sha256','clip_sha256','action_version_sha256']:
  if comparison[field]!=action[field]:raise ValueError('Nested action identity differs')
 if comparison['candidate_id']!=sid or comparison['expected_frames']!=action['frames']:raise ValueError('Frame/ID binding differs')
 return action


def frame_gate(model, source, proposal, target, camera, status):
 before=h.reprojection_metrics(model.hand(source,'left'),target,camera);after=h.reprojection_metrics(model.hand(proposal,'left'),target,camera)
 change=Rotation.from_matrix(h.hand_rotations(proposal,model,'left')@h.hand_rotations(source,model,'left').transpose(0,2,1)).magnitude()
 wrist0=h.project(model.hand(source,'left'),camera)[0];wrist=h.project(model.hand(proposal,'left'),camera)[0];wbefore=float(np.linalg.norm(wrist0-target[0,:2]));wafter=float(np.linalg.norm(wrist-target[0,:2]))
 wrist_pass=wafter<=(.8*wbefore if wbefore>8 else wbefore+1e-5)
 passed=bool(status>0 and h.projection_gate(before,after) and np.rad2deg(change.max())<=155 and wrist_pass)
 return {'passed':passed,'before':before,'after':after,'finger_delta_max_degrees':float(np.rad2deg(change.max())),'wrist_error_before':wbefore,'wrist_error_after':wafter,'wrist_gate':bool(wrist_pass)}


def sequence(job):
 library,independent,model_file,out,sid=job
 library,independent,model_file,out=map(Path,[library,independent,model_file,out]);start=time.monotonic();folder=out/sid;folder.mkdir();model=h.SparseSMPLX(model_file)
 action=verify_bound_inputs(library,independent,sid,model_file);native=library/action['local_native_directory']
 count=action['frames'];first_report=json.loads((independent/sid/'report.json').read_text());width,height=first_report['dimensions_wh']
 with np.load(library/action['observations'],allow_pickle=False) as a:mask=a['left_hand_image_detected'].copy();targets=a['left_hand_image'].astype(float)*[width,height,width]
 originals=[h.read_native(native/'smplx'/f'{i:05d}_0.npz') for i in range(1,count+1)];cameras=[{k:np.asarray(v[k],float) for k in ['focal','princpt']} for v in [json.loads((native/'meta'/f'{i:05d}_0.json').read_text()) for i in range(1,count+1)]]
 anchor_index=26 if sid=='basic-i' else 43;anchor=h.read_native(independent/sid/'independent'/f'{anchor_index+1:05d}_0.npz');final=[{k:v.copy() for k,v in p.items()} for p in originals];runs=[];usable=mask.copy()
 for i in np.flatnonzero(mask):usable[i]=h.target_scale(targets[i,:,:2])>=15
 for ids in contiguous(usable):
  proposed,record=joint_fit(model,[originals[i] for i in ids],[targets[i] for i in ids],[cameras[i] for i in ids],anchor,max_nfev=100)
  record['frame_ids_1based']=[i+1 for i in ids];runs.append(record)
  # Save proposals even on timeout; timeout never becomes an accepted correction.
  for i,proposal in zip(ids,proposed):
   p=folder/'raw-proposals';p.mkdir(exist_ok=True);np.savez_compressed(p/f'{i+1:05d}_0.npz',**proposal)
  record['frame_numeric_gates']=[frame_gate(model,originals[i],proposal,targets[i],cameras[i],record['status']) for i,proposal in zip(ids,proposed)]
  record['all_frame_numeric_gates_passed']=all(x['passed'] for x in record['frame_numeric_gates'])
  # A saved proposal is not an accepted trajectory. Keep all run failures explicit.
  if record['status']>0:
   for i,proposal in zip(ids,proposed):final[i]=proposal
  print(json.dumps({'id':sid,'run':[ids[0]+1,ids[-1]+1],'optimizer_status':record['status'],'nfev':record['nfev']}),flush=True)
 dst=folder/'candidate';dst.mkdir();hashes=[]
 for i,p in enumerate(final):
  correction.unchanged(originals[i],p,'left')
  if not usable[i] and any(not np.array_equal(originals[i][k],p[k]) for k in p):raise ValueError('Missing frame modified')
  np.savez_compressed(dst/f'{i+1:05d}_0.npz',**p);hashes.append(c.sha(dst/f'{i+1:05d}_0.npz'))
 def metrics(series):
  xy=np.stack([h.project(model.hand(p,'left'),cam) for p,cam in zip(series,cameras)]);rot=np.stack([p['left_hand_pose'] for p in series]);angles=c.angular_change(rot,model.mean[25:40]);observedadj=usable[:-1]&usable[1:]
  return {'spatial':c.spatial_errors(xy,targets[:,:,:2],usable),'velocity':c.compare_velocity(xy,targets[:,:,:2],usable),'all_hand_adjacent_degrees':c.summary(angles),'fully_observed_adjacent_degrees':c.summary(angles[observedadj])}
 report={'status':'joint_trajectory_proposal_pending_quality_selection','id':sid,'frames':count,'runs':runs,'all_numeric_frame_gates_passed':bool(runs) and all(x['all_frame_numeric_gates_passed'] for x in runs),'candidate_means_proposal_not_accepted_playback':True,'metrics':{'baseline':metrics(originals),'candidate':metrics(final)},'observed_active_hand_frames':int(mask.sum()),'unobserved_frames_1based':(np.flatnonzero(~mask)+1).tolist(),'no_points_filled':True,'no_gap_interpolation':True,'global_handshape_anchor_is_a_source_specific_prior_not_approval':True,'candidate_version':__import__('hashlib').sha256(json.dumps({'baseline':action['action_version_sha256'],'annotation':action['annotation_sha256'],'native_files':hashes},sort_keys=True).encode()).hexdigest(),'source_action_version':action['action_version_sha256'],'annotation_sha256':action['annotation_sha256'],'source_sha256':action['source_sha256'],'clip_sha256':action['clip_sha256'],'training_ready':False,'model_training_ready':False,'network_training_started':False,'full_action_two_round_passes':0,'elapsed_seconds':time.monotonic()-start}
 if correction.verify_inputs(library,sid,model_file)!=action:raise ValueError('Source identity changed during joint fitting')
 (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');return report


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--independent',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.output.resolve()
 if root.exists() or root.is_relative_to(a.library.resolve()) or a.library.resolve().is_relative_to(root):raise ValueError('NEW separate output required')
 root.mkdir(parents=True);(root/'tool-source.py').write_bytes(Path(__file__).read_bytes())
 import scipy,platform,sys
 toolsdir=root/'tool-sources';toolsdir.mkdir();hashes={}
 for name in ['sign-basic-motion-temporal.py','sign-basic-motion-correct.py','sign-hand-refine.py','sign-csl-foundation-compare.py','sign-csl-foundation.py']:
  source=Path(__file__).with_name(name);hashes[str(source)]=correction.sha(source);(toolsdir/name).write_bytes(source.read_bytes())
 (root/'provenance.json').write_text(json.dumps({'tool_hashes':hashes,'model_sha256':correction.sha(a.model),'python':sys.version,'numpy':np.__version__,'scipy':scipy.__version__,'platform':platform.platform(),'initial_keyframe_prior':str(a.independent),'legacy_prior_helper_runtime_hashes':'not_all_recorded; preserved gap; inputs independently reverified','network_training':False},indent=2)+'\n')
 with ProcessPoolExecutor(max_workers=2) as pool:reports=list(pool.map(sequence,[(str(a.library),str(a.independent),str(a.model),str(root),sid) for sid in ['basic-i','basic-you']]))
 if any(correction.sha(path)!=digest for path,digest in hashes.items()):raise ValueError('Running tools changed')
 (root/'report.json').write_text(json.dumps({'records':reports,'training_started':False,'full_action_two_round_passes':0},ensure_ascii=False,indent=2)+'\n');print('joint sequence correction complete',flush=True)
