"""Independent saved-parameter review of stable-crop hand fusion; no training promotion."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np


def load(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


align=load('sign-mano-align')
crop=load('sign-stable-crop-review')
evidence=crop.evidence
WINDOWS={s:tuple(n for segment,n,_ in align.wilor.short_window_cases() if segment==s)
         for s in ('pilot-greeting-hello-001','pilot-hospital-cough-003')}
KINDS=('previous_baseline','previous_fusion','stable_baseline','stable_fusion')


def assert_frozen(baseline,candidate,sides):
    align.hand.preserved(baseline,candidate,sides,allow_elbow=True)


def read_report(results,expected_sha):
    results=Path(results).resolve()
    checks=evidence.verify_manifest(results.parent,results.parent/'SHA256SUMS')
    path=crop.verified_file(results.parent,'results/report.json',checks)
    if evidence.digest(path)!=expected_sha:
        raise ValueError('Source report digest mismatch')
    value=evidence.load_json(path)
    if value.get('training_ready') is not False:
        raise ValueError('Unexpected training-ready source')
    return value,checks


def index_cases(report,expected):
    rows=report.get('cases',[])
    values={(r['segment_id'],r['frame_1based']):r for r in rows}
    if set(values)!=expected or len(rows)!=len(values):
        raise ValueError('Source frame scope differs')
    return values


def sheet(views,path):
    from PIL import Image,ImageDraw
    output=Image.new('RGB',(len(views)*260,980),'white')
    draw=ImageDraw.Draw(output)
    draw.text((10,5),'Saved parameters: old fusion / stable baseline / stable fusion; no contact or sign approval',fill='black')
    rows=(('Source',None,None),('Old fusion','previous_fusion',(45,105,220)),
          ('Stable baseline','stable_baseline',(210,135,35)),('Stable fusion','stable_fusion',(30,160,75)),
          ('WiLoR estimated target','target',(190,55,140)))
    for i,(frame,image,mappings,sides) in enumerate(views):
        cloud=np.concatenate([mappings['target'][s] for s in sides])
        lo=np.maximum(np.floor(cloud.min(axis=0)-[65,60]),[0,0]).astype(int)
        hi=np.minimum(np.ceil(cloud.max(axis=0)+[65,60]),image.size).astype(int)
        for row,(label,key,color) in enumerate(rows):
            rendered=image.copy();d=ImageDraw.Draw(rendered)
            if key:
                for side in sides:
                    points=mappings[key][side]
                    for a,b in align.hand.EDGES:
                        d.line([tuple(points[a]),tuple(points[b])],fill=color,width=2)
                    for x,y in points:
                        d.ellipse((x-2,y-2,x+2,y+2),outline=color,width=2)
            rendered=rendered.crop((lo[0],lo[1],hi[0],hi[1]));rendered.thumbnail((250,155))
            x,y=i*260+5,30+row*185
            output.paste(rendered,(x,y+27));draw.text((x,y),'f%d %s'%(frame,label),fill='black')
    output.save(path,quality=95)


def plot(window,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=window['frame_rows'];ids=window['frames']
    fig,axes=plt.subplots(2,1,figsize=(11,7),constrained_layout=True)
    axes[0].plot(ids,[r['stable_depth_before'] for r in rows],'o-',label='Stable baseline')
    axes[0].plot(ids,[r['stable_depth_after'] for r in rows],'x--',label='Stable fusion (exactly unchanged)')
    axes[0].set_ylabel('Stable virtual-camera depth (m)');axes[0].legend(fontsize=8)
    for side in window['required_sides']:
        for kind in KINDS:
            axes[1].plot(ids,[r['hand_metrics'][side][kind]['absolute_rmse_pixels'] for r in rows],
                         label=side+' '+kind.replace('_',' '))
    axes[1].set_ylabel('RMSE to WiLoR estimated joints (pixels)');axes[1].legend(fontsize=7,ncol=2)
    for ax in axes:
        ax.set_xlabel('1-based clip frame');ax.grid(alpha=.25)
    fig.suptitle('Camera stability and hand fusion reviewed separately; no training approval')
    try:
        fig.savefig(path,dpi=130)
    finally:
        plt.close(fig)


def review(args):
    from PIL import Image
    batch,source,stable,new,old,wi,root,out=[Path(getattr(args,k)).resolve() for k in
        ('batch','fit_source','stable_results','fusion_results','previous_fusion_results','wilor_results','smplerx_root','output')]
    protected=(batch,source,stable.parent,new.parent,old.parent,wi.parent,root)
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in protected):
        raise ValueError('Output must be new and separate')
    nr,nchecks=read_report(new,args.fusion_report_sha256)
    sr,schecks=read_report(stable,args.stable_report_sha256)
    pr,pchecks=read_report(old,args.previous_fusion_report_sha256)
    wr,wchecks=read_report(wi,args.wilor_report_sha256)
    expected={(s,n) for s,ids in WINDOWS.items() for n in ids}
    reports=(nr,pr)
    for r in reports:
        if r.get('schema')!='signbridge-mano-smplx-alignment-v1' or r.get('source_files_unchanged') is not True or \
           r.get('wilor_report_sha256')!=args.wilor_report_sha256:
            raise ValueError('Fusion/WiLoR source linkage mismatch')
    if nr.get('fit_source_kind')!='stable_crop' or nr.get('stable_report_sha256')!=args.stable_report_sha256 or \
       nr.get('status') not in ('alignment_candidates_pending_visual_review','alignment_candidate_gate_failed'):
        raise ValueError('Stable fusion source contract differs')
    if sr.get('schema')!='signbridge-stable-crop-pilot-v1' or sr.get('source_files_unchanged') is not True or \
       sr.get('status')!='inferred_pending_stable_crop_review' or wr.get('schema')!='signbridge-wilor-keyframe-pilot-v1':
        raise ValueError('Unexpected baseline or WiLoR contract')
    ni,pi,si,wi_index=[index_cases(r,expected) for r in (nr,pr,sr,wr)]
    bchecks=evidence.verify_manifest(batch,batch/'SHA256SUMS')
    ochecks=evidence.verify_manifest(source,source/'SHA256SUMS')
    for name in ('contract.json','tasks.jsonl','SHA256SUMS'):
        evidence.require_source_digest(nr,'batch/'+name,evidence.digest(batch/name))
    tasks={r['segment_id']:r for r in (json.loads(x) for x in (batch/'tasks.jsonl').read_text().splitlines() if x.strip())}
    model_path=evidence.contained_file(root,align.hand.MODEL_FILE)
    if evidence.digest(model_path)!=align.hand.MODEL_SHA256:
        raise ValueError('SMPL-X model digest mismatch')
    model=align.hand.SparseSMPLX(model_path)
    result={'schema':'signbridge-stable-fusion-review-v1','status':'stable_fusion_saved_parameters_pending_review',
            'training_ready':False,'contact_approved':False,'full_sequence_refined':False,
            'root_translation_exactly_preserved':True,'source_fits_modified':False,'windows':{},
            'accepted_hands':0,'evaluated_hands':0,
            'limitations':['WiLoR is a model estimate, not independent human ground truth.',
                'Contact/occlusion/mirror and sign semantics remain unconfirmed.',
                'Fixed virtual camera does not establish physical depth or world motion.',
                'Short windows and per-frame candidate gates do not establish full-sequence quality.']}
    images={}
    for segment,ids in WINDOWS.items():
        sides=('left','right') if 'greeting' in segment else ('right',)
        rows=[];records=[];views=[];temporal={'baseline':[],'candidate':[]}
        reference=None
        for frame in ids:
            rel=segment+'/%06d'%frame
            c=ni[(segment,frame)]
            if c.get('output_relative')!=rel or c.get('required_sides')!=list(sides) or c.get('training_ready') is not False:
                raise ValueError('Fusion frame identity differs')
            if len(c.get('hands',[]))!=len(sides) or {h.get('side') for h in c['hands']}!=set(sides):
                raise ValueError('Ambiguous or unobserved saved hand identity')
            for key in ('baseline_native_parity_max_metres','candidate_native_parity_max_metres'):
                x=c.get(key)
                if not isinstance(x,(int,float)) or not np.isfinite(x) or not 0<=x<=5e-5:
                    raise ValueError('Saved fusion native parity failed')
            def values(results,checks,name):
                return align.hand.read_native(crop.verified_file(results.parent,'results/'+rel+'/'+name+'.npz',checks))
            baseline=values(new,nchecks,'baseline');candidate=values(new,nchecks,'candidate')
            old_baseline=values(old,pchecks,'baseline');old_candidate=values(old,pchecks,'candidate')
            fit_rel=segment+'/smplx/%05d_0.npz'%frame
            st_path=crop.verified_file(stable.parent,'results/'+fit_rel,schecks)
            original_path=crop.verified_file(source,fit_rel,ochecks)
            st_native=align.hand.read_native(st_path);orig_native=align.hand.read_native(original_path)
            if any(not np.array_equal(st_native[k],baseline[k]) or not np.array_equal(orig_native[k],old_baseline[k]) for k in baseline):
                raise ValueError('Stored baseline differs from linked inference source')
            assert_frozen(baseline,candidate,sides)
            meta_rel=segment+'/meta/%05d_0.json'%frame
            meta_path=crop.verified_file(stable.parent,'results/'+meta_rel,schecks)
            old_meta_path=crop.verified_file(source,meta_rel,ochecks)
            evidence.require_source_digest(nr,meta_rel,evidence.digest(meta_path))
            evidence.require_source_digest(nr,fit_rel,evidence.digest(st_path))
            meta=evidence.load_json(meta_path);old_meta=evidence.load_json(old_meta_path)
            camera=crop.camera.validate_meta(meta,old_meta['img_path'])
            old_camera=crop.camera.validate_meta(old_meta,old_meta['img_path'])
            if reference is None:
                reference=camera
            elif any(not np.array_equal(reference[k],camera[k]) for k in camera):
                raise ValueError('Stable baseline camera varies')
            projections={k:{} for k in KINDS};projections['target']={};metrics={};decisions={}
            for side in sides:
                hs=[h for h in c['hands'] if h['side']==side]
                targets=[h for h in wi_index[(segment,frame)]['hands'] if h['side']==side]
                if len(hs)!=1 or len(targets)!=1:
                    raise ValueError('Ambiguous hand identity')
                h=hs[0]
                if type(h.get('candidate_gate_passed')) is not bool or h.get('applied_to_candidate')!=h['candidate_gate_passed']:
                    raise ValueError('Saved candidate decision differs')
                decisions[side]=h['candidate_gate_passed']
                name='results/'+wi_index[(segment,frame)]['output_relative']+'/'+targets[0]['parameters_file']
                with np.load(crop.verified_file(wi.parent,name,wchecks),allow_pickle=False) as a:
                    if bool(a['right'])!=(side=='right'):
                        raise ValueError('WiLoR side identity differs')
                    target=a['projected_joints'].copy()
                if target.shape!=(21,2) or not np.isfinite(target).all():
                    raise ValueError('Invalid hand projection target')
                projections['target'][side]=target
                target3=np.c_[target,np.zeros(21)]
                metrics[side]={}
                for kind,p,cam in (('previous_baseline',old_baseline,old_camera),('previous_fusion',old_candidate,old_camera),
                                    ('stable_baseline',baseline,camera),('stable_fusion',candidate,camera)):
                    hand=model.hand(p,side)
                    metrics[side][kind]=align.hand.reprojection_metrics(hand,target3,cam)
                    projections[kind][side]=align.hand.project(hand,cam)
                actual=metrics[side]['stable_fusion'];reported=h['saved_candidate_after']
                if any(k not in reported or not np.isclose(actual[k],reported[k],rtol=1e-4,atol=1e-3) for k in actual):
                    raise ValueError('Saved candidate metric differs from recomputed parameters')
                result['accepted_hands']+=int(decisions[side]);result['evaluated_hands']+=1
            if c.get('all_candidate_gates_passed')!=all(decisions.values()):
                raise ValueError('Combined saved gate state differs')
            record={'frame_1based':frame,'fps':tasks[segment]['fps'],'sides':sides,
                    'baseline':baseline,'candidate':candidate,'decisions':decisions}
            records.append(record)
            row={'frame_1based':frame,'hand_metrics':metrics,'applied_mask':decisions,
                'stable_depth_before':float(baseline['transl'][0,2]),'stable_depth_after':float(candidate['transl'][0,2]),
                'protected_parameters_exact':True,'training_ready':False}
            if len(sides)==2:
                row['contact_diagnostic']={name:align.fingertip_contact_diagnostic(model,p,camera)
                                           for name,p in (('baseline',baseline),('candidate',candidate))}
            rows.append(row)
            for name,p in (('baseline',baseline),('candidate',candidate)):
                world=align.global_rotations(model,p)
                temporal[name].append({'frame_1based':frame,'hands':[{'side':s,
                    'hand_pose':align.hand.hand_rotations(p,model,s),'global_orient':world[align.hand.WRISTS[s]][None],
                    'projected_joints':align.hand.project(model.hand(p,s),camera)} for s in sides]})
            image_relative='samples/'+segment+'/images/%06d.jpg'%frame
            image_path=crop.verified_file(batch,image_relative,bchecks)
            with Image.open(image_path) as image:
                views.append((frame,image.convert('RGB'),projections,sides))
        packed=align.pack_series(records)
        series_path=crop.verified_file(new.parent,'results/'+segment+'/baseline-candidate-series.npz',nchecks)
        with np.load(series_path,allow_pickle=False) as a:
            if set(a.files)!=set(packed) or any(not np.array_equal(a[k],packed[k]) for k in packed):
                raise ValueError('Saved series/masks differ from individual saved parameters')
        z=np.asarray([r['stable_depth_before'] for r in rows])
        result['windows'][segment]={'frames':list(ids),'required_sides':list(sides),'frame_rows':rows,
            'mean_hand_rmse_pixels':{s:{k:float(np.mean([r['hand_metrics'][s][k]['absolute_rmse_pixels'] for r in rows]))
                                          for k in KINDS} for s in sides},
            'max_adjacent_depth_step_metres':float(np.abs(np.diff(z)).max()),
            'series_verified':True,'camera_fixed':True,'training_ready':False,
            'temporal':{k:align.wilor.temporal_summary(v,sides) for k,v in temporal.items()}}
        images[segment]=views
    for p in (batch,source,stable.parent,new.parent,old.parent,wi.parent):
        evidence.verify_manifest(p,p/'SHA256SUMS')
    out.mkdir(parents=True)
    for s,views in images.items():
        folder=out/s;folder.mkdir()
        sheet(views,folder/'fusion-comparison.jpg');plot(result['windows'][s],folder/'fusion-metrics.png')
    result['source_sha256']={'stable_report':args.stable_report_sha256,'fusion_report':args.fusion_report_sha256,
        'previous_fusion_report':args.previous_fusion_report_sha256,'wilor_report':args.wilor_report_sha256,
        'model':align.hand.MODEL_SHA256,'review_tool':evidence.digest(__file__),
        'alignment_tool':evidence.digest(align.__file__),'projection_helper':evidence.digest(align.hand.__file__)}
    p=out/'report.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+str(p.relative_to(out))+'\n'
                                       for p in sorted(out.rglob('*')) if p.is_file()))
    return p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('batch','fit-source','stable-results','fusion-results','previous-fusion-results','wilor-results','smplerx-root','output'):
        parser.add_argument('--'+k,type=Path,required=True)
    for k in ('stable-report-sha256','fusion-report-sha256','previous-fusion-report-sha256','wilor-report-sha256'):
        parser.add_argument('--'+k,required=True)
    print(review(parser.parse_args()))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
