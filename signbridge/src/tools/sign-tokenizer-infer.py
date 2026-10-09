"""Load a hash-verified research tokenizer and encode/reconstruct 133D motion on CPU/CUDA."""
import argparse,importlib,importlib.util,json,subprocess,sys
from pathlib import Path
import numpy as np

spec=importlib.util.spec_from_file_location('inference_smoke',Path(__file__).with_name('sign-tokenizer-smoke.py'))
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)


def prepare_sequence(values,mask):
    values=np.asarray(values);mask=np.asarray(mask)
    if values.ndim!=2 or values.shape[1]!=133 or len(values)<4 or values.dtype!=np.float32 or not np.isfinite(values).all() or \
       mask.shape!=values.shape or mask.dtype.kind!='b':
        raise ValueError('Invalid 133D motion/mask arrays')
    count=len(values);pad=(-count)%4
    return np.pad(values,((0,pad),(0,0)),mode='edge'),np.pad(mask,((0,pad),(0,0)),mode='edge'),count


def verify_checkpoint(path,expected):
    if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected) or smoke.digest(path)!=expected:
        raise ValueError('Checkpoint digest differs; refusing model loading')


def contract(count):
    return {'schema':'signbridge-tokenizer-inference-v1','research_only':True,'training_ready':False,
            'deployment_ready':False,'text_to_sign_generated':False,'frames':count,
            'quality_approved':False,'limitations':['Encodes/reconstructs motion; no text generation.',
                'Quality masks mark model input/target availability, not independent sign correctness.']}


def infer(args):
    checkpoint,features,soke,out=[Path(getattr(args,k)).resolve() for k in ('checkpoint','features','soke_root','output')]
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (checkpoint.parent,features.parent,soke)):
        raise ValueError('Output must be new and separate')
    verify_checkpoint(checkpoint,args.checkpoint_sha256)
    if subprocess.check_output(['git','-C',str(soke),'rev-parse','HEAD'],text=True).strip()!=smoke.SOKE_COMMIT:
        raise ValueError('SOKE source commit differs')
    values=np.load(features,allow_pickle=False)
    mask=np.load(args.mask,allow_pickle=False) if args.mask else np.ones_like(values,dtype=bool)
    padded,valid,count=prepare_sequence(values,mask)
    import torch
    torch.set_num_threads(2)
    device=torch.device(args.device)
    if args.device=='cuda' and not torch.cuda.is_available():raise ValueError('CUDA unavailable')
    # Only a digest-verified own training artifact is loaded. Its NumPy normalization arrays require full loading.
    saved=torch.load(checkpoint,map_location='cpu',weights_only=False) if tuple(map(int,torch.__version__.split('+')[0].split('.')[:2])) >= (2,0) \
          else torch.load(checkpoint,map_location='cpu')
    if saved.get('schema')!='signbridge-tokenizer-smoke-checkpoint-v1' or saved.get('training_ready') is not False or \
       saved.get('research_only') is not True or saved.get('soke_commit')!=smoke.SOKE_COMMIT:
        raise ValueError('Unexpected model checkpoint contract')
    configs=saved['model_configs']
    if len(configs)!=3 or [x['nfeats'] for x in configs]!=[43,45,45]:raise ValueError('Model part dimensions differ')
    sys.path.insert(0,str(soke))
    module=importlib.import_module('mGPT.archs.mgpt_vq')
    if Path(module.__file__).resolve()!=soke/'mGPT/archs/mgpt_vq.py':raise ValueError('Wrong architecture import')
    models=torch.nn.ModuleList([module.VQVae(**c) for c in configs])
    models.load_state_dict(saved['state_dict'],strict=True);models.to(device).eval()
    normalized=smoke.normalized_model_input(padded,saved['mean'],saved['std'],valid)
    parts=[torch.from_numpy(p).unsqueeze(0).to(device) for p in smoke.split_parts(normalized)]
    predictions=[];tokens=[]
    with torch.inference_mode():
        for model,part in zip(models,parts):
            prediction,_,_=model(part);predictions.append(prediction[0].cpu().numpy())
            ids,_=model.encode(part);tokens.append(ids.cpu().numpy())
    reconstruction=smoke.combine_parts(predictions)[:count]*saved['std']+saved['mean']
    if reconstruction.shape!=(count,133) or not np.isfinite(reconstruction).all():raise ValueError('Invalid decoded output')
    out.mkdir(parents=True)
    np.save(out/'reconstructed-133.npy',reconstruction.astype(np.float32),allow_pickle=False)
    np.save(out/'feature-valid-mask.npy',mask,allow_pickle=False)
    for name,ids in zip(('body','left','right'),tokens):np.save(out/(name+'-tokens.npy'),ids,allow_pickle=False)
    r=contract(count)
    r.update(status='motion_encoded_and_reconstructed',device=str(device),torch=torch.__version__,
        checkpoint_step=saved['step'],checkpoint_sha256=args.checkpoint_sha256,
        input_features_sha256=smoke.digest(features),mask_sha256=smoke.digest(args.mask) if args.mask else None,
        token_shapes={name:list(ids.shape) for name,ids in zip(('body','left','right'),tokens)},
        inference_tool_sha256=smoke.digest(__file__),normalization_tool_sha256=smoke.digest(smoke.__file__))
    (out/'report.json').write_text(json.dumps(r,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(smoke.digest(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file()))
    return out/'report.json'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('checkpoint','features','soke-root','output'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--checkpoint-sha256',required=True);p.add_argument('--mask',type=Path)
    p.add_argument('--device',choices=('cpu','cuda'),default='cpu')
    print(infer(p.parse_args()))
if __name__=='__main__':main()
