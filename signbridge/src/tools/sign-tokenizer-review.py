"""Render in-sample tokenizer reconstruction; masks keep unaccepted hand estimates unchanged."""
import argparse,importlib.util,json,os
from pathlib import Path
import numpy as np

s=importlib.util.spec_from_file_location('tokenizer_review_hand',Path(__file__).with_name('sign-hand-refine.py'))
hand=importlib.util.module_from_spec(s);s.loader.exec_module(hand)


def decode_features(source,features,mask):
    a=np.asarray(features);valid=np.asarray(mask)
    if a.shape!=(133,) or not np.isfinite(a).all() or valid.shape!=(133,) or valid.dtype.kind!='b':
        raise ValueError('Invalid feature reconstruction/mask')
    if any(np.shape(source[k])!=shape or not np.isfinite(source[k]).all() for k,shape in hand.SHAPES.items()):
        raise ValueError('Invalid source native pose')
    p={k:v.copy() for k,v in source.items()}
    p['body_pose'][11:]=a[:30].reshape(10,3)
    for key,start,end in (('left_hand_pose',30,75),('right_hand_pose',75,120)):
        if valid[start:end].all():p[key]=a[start:end].reshape(15,3).astype(p[key].dtype)
        elif valid[start:end].any():raise ValueError('Hand quality mask must cover a whole hand')
    p['jaw_pose']=a[120:123].reshape(1,3).astype(p['jaw_pose'].dtype)
    p['expression']=a[123:].reshape(1,10).astype(p['expression'].dtype)
    return p


def render(args):
    from PIL import Image
    motions,training,stable,batch,root,out=[Path(getattr(args,k)).resolve() for k in
       ('motions','training_results','stable_results','batch','smplerx_root','output')]
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (motions,training.parent,stable.parent,batch,root)):
        raise ValueError('Output must be new and separate')
    report=json.loads((training/'report.json').read_text())
    if report.get('status')!='research_smoke_trained_not_deployable' or report.get('checkpoint_reload_passed') is not True or \
       report.get('training_ready') is not False or report.get('quality_masked_hand_targets') is not True:
        raise ValueError('Unexpected or incomplete training report')
    if hand.sha256(training/'tokenizer-smoke.pt')!=report['checkpoint_sha256']:raise ValueError('Checkpoint digest differs')
    tasks=[json.loads(x) for x in (motions/'motions.jsonl').read_text().splitlines() if x.strip()]
    os.environ.setdefault('PYOPENGL_PLATFORM','egl');os.environ.setdefault('MPLBACKEND','Agg')
    import torch,smplx
    if not torch.cuda.is_available():raise ValueError('CUDA required for saved native rendering')
    modelpath=hand.verify_model_assets(root)
    native=smplx.create(str(modelpath),model_type='smplx',gender='neutral',use_pca=False,
                         flat_hand_mean=False,use_face_contour=False).cuda().eval()
    hand.renderer_preflight()
    out.mkdir(parents=True)
    summary={'schema':'signbridge-tokenizer-native-review-v1','training_ready':False,
      'in_sample_reconstruction':True,'text_to_sign_generated':False,'unaccepted_hands_preserved':True,
      'checkpoint_sha256':report['checkpoint_sha256'],'frames_rendered':0,'samples':[]}
    for task in tasks:
        segment=task['segment_id'];count=task['frames']
        features=np.load(training/segment/'reconstructed-133.npy',allow_pickle=False)
        masks=np.load(motions/'samples'/segment/'feature-valid-mask.npy',allow_pickle=False)
        if features.shape!=(count,133) or not np.isfinite(features).all() or masks.shape!=features.shape or masks.dtype.kind!='b':
            raise ValueError('Reconstructed timeline/mask differs')
        with np.load(motions/'samples'/segment/'fused-smplx-series.npz',allow_pickle=False) as a:
            sources={k:a['candidate_'+k].copy() for k in hand.SHAPES}
        folder=out/segment;folder.mkdir();poses=[]
        for index in range(count):
            source={k:v[index] for k,v in sources.items()}
            p=decode_features(source,features[index],masks[index]);poses.append(p)
            kwargs={k:torch.tensor(v.reshape(1,-1),dtype=torch.float32,device='cuda') for k,v in p.items()}
            with torch.inference_mode():mesh=native(**kwargs).vertices[0].cpu().numpy()
            meta=json.loads((stable/segment/'meta'/('%05d_0.json'%(index+1))).read_text())
            image_path=batch/'samples'/segment/'images'/('%06d.jpg'%(index+1))
            camera=hand.native_camera(meta,image_path)
            with Image.open(image_path) as image:
                pixels=np.asarray(image.convert('RGB'))
            output=hand.render_overlay(pixels,mesh,native.faces,camera,diagnostic=True)
            Image.fromarray(output).save(folder/('%06d.jpg'%(index+1)),quality=92)
            summary['frames_rendered']+=1
        np.savez_compressed(folder/'reconstructed-native.npz',**{k:np.stack([p[k] for p in poses]) for k in hand.SHAPES},
                            frame_ids=np.arange(1,count+1),training_ready=np.asarray(False))
        summary['samples'].append({'segment_id':segment,'frames':count,'fps':task['fps']})
    summary.update(status='in_sample_native_reconstruction_pending_review',
                   limitations=['This reconstructs model-estimated training inputs; no independent or text-conditioned evaluation.',
                                'Masked hands retain saved estimates and are not credited as learned reconstruction.'])
    (out/'report.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(hand.sha256(p)+'  '+str(p.relative_to(out))+'\n' for p in sorted(out.rglob('*')) if p.is_file()))
    return out/'report.json'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('motions','training-results','stable-results','batch','smplerx-root','output'):p.add_argument('--'+k,type=Path,required=True)
    print(render(p.parse_args()))
if __name__=='__main__':main()
