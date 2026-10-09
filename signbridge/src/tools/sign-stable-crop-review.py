"""Compare original, rebased-original and re-inferred fixed crops; no automatic training approval."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def tool(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


camera=tool('sign-camera-audit')
stable=tool('sign-stable-crop')
evidence=camera.evidence


def depth_summary(raw,common,new,frame_ids):
    ids=np.asarray(frame_ids)
    arrays=[np.asarray(x,dtype=np.float64) for x in (raw,common,new)]
    if ids.ndim!=1 or len(ids)<2 or not (np.diff(ids)==1).all() or \
       any(a.shape!=ids.shape or not np.isfinite(a).all() for a in arrays):
        raise ValueError('Expected finite complete contiguous depth timelines')
    steps=[np.abs(np.diff(a)) for a in arrays]
    names=('original_raw','original_rebased','stable_crop')
    output={name+'_max_adjacent_depth_step':float(step.max()) for name,step in zip(names,steps)}
    output['transitions']=[{'from_frame':int(ids[i]),'to_frame':int(ids[i+1]),
                           **{name+'_depth_step':float(step[i]) for name,step in zip(names,steps)}}
                          for i in range(len(ids)-1)]
    output.update(unit='model_camera_metres_not_world_motion',training_ready=False,
        improved_vs_rebased_max_step=bool(steps[2].max()<steps[1].max()))
    return output


def projection_comparison(original,new,wilor):
    values=[np.asarray(x,dtype=np.float64) for x in (original,new,wilor)]
    if any(a.shape!=(21,2) or not np.isfinite(a).all() for a in values):
        raise ValueError('Expected finite 21x2 same-side hand projections')
    result={'independent_ground_truth':False,'target':'unchanged WiLoR estimated projected joints',
            'training_ready':False}
    for name,x in zip(('original','stable_crop'),values[:2]):
        error=x-values[2];local=error-error[0]
        result[name]={'absolute_rmse_pixels':float(np.sqrt(np.mean(error**2))),
                     'wrist_error_pixels':float(np.linalg.norm(error[0])),
                     'local_rmse_pixels':float(np.sqrt(np.mean(local**2))),
                     'fingertip_rmse_pixels':float(np.sqrt(np.mean(error[[4,8,12,16,20]]**2)))}
    return result


def contract():
    return {'schema':'signbridge-stable-crop-review-v1','status':'stable_crop_comparison_pending_review',
            'training_ready':False,'source_fits_modified':False,'full_sequence_refined':False,
            'contact_approved':False,'temporal_smoothing':False,'windows':{},
            'limitations':['WiLoR 2D is an estimated comparator, not human-labelled truth.',
                           'Short-window results do not establish full-sequence hand quality.',
                           'Model-camera depth is not physical world motion.',
                           'Fixed crop changes all model estimates; hand errors can improve or worsen.',
                           'Contact, occlusion, mirror and sign semantics remain unconfirmed.']}


def global_rotations(model,params):
    pose=np.vstack([params[k].reshape(-1,3) for k in ('global_orient','body_pose','jaw_pose',
        'leye_pose','reye_pose','left_hand_pose','right_hand_pose')])+model.mean
    rotations=Rotation.from_rotvec(pose).as_matrix()
    for i in range(1,55):
        rotations[i]=rotations[model.parents[i]]@rotations[i]
    return rotations


def sequence_rotations(records,model,side):
    result=[]
    for a,b in zip(records,records[1:]):
        old=stable.hand.hand_rotations(a['params'],model,side)
        new=stable.hand.hand_rotations(b['params'],model,side)
        finger=float(np.rad2deg(Rotation.from_matrix(new@old.transpose(0,2,1)).magnitude().max()))
        ra=global_rotations(model,a['params'])[stable.hand.WRISTS[side]]
        rb=global_rotations(model,b['params'])[stable.hand.WRISTS[side]]
        wrist=float(np.rad2deg(Rotation.from_matrix(rb@ra.T).magnitude()))
        result.append({'from_frame':a['frame'],'to_frame':b['frame'],
                       'max_finger_degrees':finger,'wrist_orientation_degrees':wrist,
                       'review_flag':finger>45 or wrist>30})
    return result


def compare_sheet(views,path):
    from PIL import Image,ImageDraw
    sheet=Image.new('RGB',(260*len(views),810),'white')
    draw=ImageDraw.Draw(sheet)
    draw.text((8,6),'Source / original SMPLer-X / stable crop / WiLoR comparator; no automatic pose acceptance',fill='black')
    for i,v in enumerate(views):
        image,points_old,points_new,targets,sides,frame=v
        cloud=np.concatenate([targets[s] for s in sides])
        lo=np.maximum(np.floor(cloud.min(axis=0)-[60,65]),[0,0]).astype(int)
        hi=np.minimum(np.ceil(cloud.max(axis=0)+[60,55]),image.size).astype(int)
        for row,(name,mapping,color) in enumerate((('source',{},'black'),('original',points_old,(40,115,220)),
                  ('stable-crop',points_new,(30,160,75)),('WiLoR (estimate)',targets,(195,60,140)))):
            output=image.copy();painter=ImageDraw.Draw(output)
            for s in mapping:
                points=mapping[s]
                for a,b in stable.hand.EDGES:
                    painter.line([tuple(points[a]),tuple(points[b])],fill=color,width=2)
                for x,y in points:
                    painter.ellipse((x-2,y-2,x+2,y+2),outline=color,width=2)
            output=output.crop((lo[0],lo[1],hi[0],hi[1]));output.thumbnail((250,155))
            x,y=i*260+5,30+row*192
            sheet.paste(output,(x,y+30));draw.text((x,y),'f%d %s'%(frame,name),fill='black')
    sheet.save(path,quality=95)


def curves(raw,common,new,frame_ids,side_errors,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,6),constrained_layout=True)
    for values,name in ((raw,'Original varying crop camera'),(common,'Original rebased to fixed camera'),
                        (new,'Stable-crop new inference')):
        axes[0].plot(frame_ids,values,'o-',label=name)
    axes[0].set_ylabel('Virtual camera depth (m)');axes[0].legend(fontsize=8)
    for side,values in side_errors.items():
        axes[1].plot(frame_ids,[x['original']['absolute_rmse_pixels'] for x in values],label=side+' original')
        axes[1].plot(frame_ids,[x['stable_crop']['absolute_rmse_pixels'] for x in values],label=side+' stable')
    axes[1].set_ylabel('Hand RMSE to WiLoR estimate (px)');axes[1].legend(fontsize=8)
    for ax in axes:
        ax.set_xlabel('1-based clip frame');ax.grid(alpha=.25)
    fig.suptitle('Fixed-crop experiment; same weights; no temporal smoothing')
    try:
        fig.savefig(path,dpi=130)
    finally:
        plt.close(fig)


def verified_file(root,relative,manifest):
    p=evidence.contained_file(root,relative)
    if manifest.get(relative)!=evidence.digest(p):
        raise ValueError('Unlisted input/digest mismatch: '+relative)
    return p


def review(args):
    from PIL import Image
    source,batch,new,wi,root,out=[Path(getattr(args,k)).resolve() for k in
        ('fit_source','batch','stable_results','wilor_results','smplerx_root','output')]
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (source,batch,new.parent,wi.parent,root)):
        raise ValueError('Output must be new and separate')
    manifests={p:evidence.verify_manifest(p,p/'SHA256SUMS') for p in (source,batch,new.parent,wi.parent)}
    new_path=verified_file(new.parent,'results/report.json',manifests[new.parent])
    run=evidence.load_json(new_path)
    if evidence.digest(new_path)!=args.stable_report_sha256 or run.get('schema')!='signbridge-stable-crop-pilot-v1' or \
       run.get('status')!='inferred_pending_stable_crop_review' or run.get('training_ready') is not False or \
       run.get('source_files_unchanged') is not True:
        raise ValueError('Incomplete or unexpected stable-crop run')
    observed={(r['segment_id'],r['frame_1based']):r for r in run['cases']}
    expected={(s,f) for s,ids in stable.WINDOWS.items() for f in ids}
    if set(observed)!=expected or len(observed)!=len(run['cases']):
        raise ValueError('Stable-crop run frame scope differs')
    if run.get('scope')!={s:list(ids) for s,ids in stable.WINDOWS.items()}:
        raise ValueError('Stable-crop report scope differs')
    for row in run['cases']:
        parity=row.get('native_parity_max_metres')
        if not isinstance(parity,(int,float)) or not np.isfinite(parity) or not 0<=parity<=5e-5:
            raise ValueError('Saved stable-crop native parity has not passed')
        segment,frame=row['segment_id'],row['frame_1based']
        if row.get('parameters_file')!=segment+'/smplx/%05d_0.npz'%frame or \
           row.get('camera_file')!=segment+'/meta/%05d_0.json'%frame or row.get('training_ready') is not False:
            raise ValueError('Stable-crop report parameter/frame identity differs')
    plan_path=verified_file(new.parent,'plan.json',manifests[new.parent])
    plan=evidence.load_json(plan_path)
    evidence.require_source_digest(run,'plan.json',evidence.digest(plan_path))
    if plan.get('schema')!='signbridge-stable-crop-plan-v1' or plan.get('training_ready') is not False or \
       set(plan.get('windows',{}))!=set(stable.WINDOWS):
        raise ValueError('Stable-crop plan linkage differs')
    wpath=verified_file(wi.parent,'results/report.json',manifests[wi.parent])
    wr=evidence.load_json(wpath)
    if evidence.digest(wpath)!=args.wilor_report_sha256 or wr.get('training_ready') is not False:
        raise ValueError('WiLoR report linkage differs')
    if wr.get('schema')!='signbridge-wilor-keyframe-pilot-v1':
        raise ValueError('WiLoR report schema differs')
    windex={(r['segment_id'],r['frame_1based']):r for r in wr['cases']}
    if set(windex)!=expected or len(windex)!=len(wr['cases']):
        raise ValueError('WiLoR short-window scope differs')
    if evidence.digest(verified_file(source,'run.json',manifests[source]))!=stable.FIT_SHA:
        raise ValueError('Original run hash differs')
    capture=evidence.load_json(verified_file(source,'capture.json',manifests[source]))
    for name in ('contract.json','tasks.jsonl','SHA256SUMS'):
        evidence.require_source_digest(run,'batch/'+name,evidence.digest(batch/name))
        evidence.require_source_digest(wr,'batch/'+name,evidence.digest(batch/name))
    model_file=evidence.contained_file(root,stable.hand.MODEL_FILE)
    if evidence.digest(model_file)!=stable.hand.MODEL_SHA256:
        raise ValueError('Model digest differs')
    model=stable.hand.SparseSMPLX(model_file)
    result=contract();files={}
    for segment,ids in stable.WINDOWS.items():
        old_records=[];new_records=[];rows=[];raw=[];common=[];depth=[];images=[]
        sides=('left','right') if 'greeting' in segment else ('right',)
        errors={s:[] for s in sides};reference=None
        for frame in ids:
            image_relative='samples/'+segment+'/images/%06d.jpg'%frame
            image_path=verified_file(batch,image_relative,manifests[batch])
            meta_relative=segment+'/meta/%05d_0.json'%frame
            fit_relative=segment+'/smplx/%05d_0.npz'%frame
            old_meta_path=verified_file(source,meta_relative,manifests[source])
            old_fit_path=verified_file(source,fit_relative,manifests[source])
            evidence.require_source_digest(run,meta_relative,evidence.digest(old_meta_path))
            evidence.require_source_digest(run,fit_relative,evidence.digest(old_fit_path))
            evidence.require_source_digest(run,image_relative,evidence.digest(image_path))
            old_meta=evidence.load_json(old_meta_path)
            old_params=stable.hand.read_native(old_fit_path)
            new_meta_path=verified_file(new.parent,'results/'+meta_relative,manifests[new.parent])
            new_fit_path=verified_file(new.parent,'results/'+fit_relative,manifests[new.parent])
            new_meta=evidence.load_json(new_meta_path);new_params=stable.hand.read_native(new_fit_path)
            if not np.array_equal(np.asarray(new_meta['bbox'],dtype=np.float32),
                                  np.asarray(plan['windows'][segment]['fixed_bbox'],dtype=np.float32)):
                raise ValueError('Saved crop differs from the fixed crop plan')
            if new_meta['img_path']!=old_meta['img_path'] or new_meta['bbox_id']!=0:
                raise ValueError('Camera identity differs')
            camera.validate_meta(new_meta,old_meta['img_path']);camera.validate_meta(old_meta,old_meta['img_path'])
            nc=camera.validate_camera(new_meta);oc=camera.validate_camera(old_meta)
            if reference is None:
                reference=nc
            elif any(not np.array_equal(nc[k],reference[k]) for k in nc):
                raise ValueError('Stable-crop camera not constant')
            rebased,_,_=camera.rebase_translation(model,old_params,oc,nc)
            raw.append(float(old_params['transl'][0,2]));common.append(float(rebased['transl'][0,2]));depth.append(float(new_params['transl'][0,2]))
            old_records.append({'frame':frame,'params':old_params});new_records.append({'frame':frame,'params':new_params})
            targets={};old_hand={};new_hand={}
            for s in sides:
                targets0=[h for h in windex[(segment,frame)]['hands'] if h['side']==s]
                if len(targets0)!=1:
                    raise ValueError('Ambiguous or missing WiLoR identity')
                handfile='results/'+windex[(segment,frame)]['output_relative']+'/'+targets0[0]['parameters_file']
                with np.load(verified_file(wi.parent,handfile,manifests[wi.parent]),allow_pickle=False) as a:
                    if bool(a['right'])!=(s=='right'):
                        raise ValueError('WiLoR side differs')
                    targets[s]=a['projected_joints'].copy()
                old_hand[s]=stable.hand.project(model.hand(old_params,s),oc)
                new_hand[s]=stable.hand.project(model.hand(new_params,s),nc)
                errors[s].append(projection_comparison(old_hand[s],new_hand[s],targets[s]))
            with Image.open(image_path) as opened:
                images.append((opened.convert('RGB'),old_hand,new_hand,targets,sides,frame))
            rows.append({'frame_1based':frame,'hand_projection':{s:errors[s][-1] for s in sides},
                'native_parity_max_metres':observed[(segment,frame)]['native_parity_max_metres'],'training_ready':False})
        result['windows'][segment]={'frames':list(ids),'depth':depth_summary(raw,common,depth,list(ids)),
            'projection_mean_rmse_pixels':{s:{kind:float(np.mean([x[kind]['absolute_rmse_pixels'] for x in errors[s]]))
                                             for kind in ('original','stable_crop')} for s in sides},
            'rotations':{s:{'original':sequence_rotations(old_records,model,s),
                            'stable_crop':sequence_rotations(new_records,model,s)} for s in sides},
            'frame_rows':rows,'training_ready':False}
        files[segment]=(images,raw,common,depth,errors)
    for p in manifests:
        evidence.verify_manifest(p,p/'SHA256SUMS')
    out.mkdir(parents=True)
    for s,(images,raw,common,depth,errors) in files.items():
        folder=out/s;folder.mkdir()
        compare_sheet(images,folder/'stable-crop-review.jpg')
        curves(raw,common,depth,list(stable.WINDOWS[s]),errors,folder/'stable-crop-metrics.png')
    result['source_sha256']={'stable_report':args.stable_report_sha256,'wilor_report':args.wilor_report_sha256,
        'fit_run':stable.FIT_SHA,'model':stable.hand.MODEL_SHA256,'review_tool':evidence.digest(__file__)}
    path=out/'report.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+str(p.relative_to(out))+'\n'
                                       for p in sorted(out.rglob('*')) if p.is_file()))
    return path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('fit-source','batch','stable-results','wilor-results','smplerx-root','output'):
        p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--stable-report-sha256',required=True)
    p.add_argument('--wilor-report-sha256',required=True)
    print(review(p.parse_args()))


if __name__=='__main__':
    main()
