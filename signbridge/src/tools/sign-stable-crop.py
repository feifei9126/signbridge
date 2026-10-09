"""Isolated short-window/full-clip SMPLer-X crop experiments; source fits stay unchanged."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location('stable_crop_hand', Path(__file__).with_name('sign-hand-refine.py'))
hand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hand)
WINDOWS = {'pilot-greeting-hello-001': tuple(range(88,95)),
           'pilot-hospital-cough-003': tuple(range(156,163))}
INFERENCE_SHA = 'c3e4b018a49432de37275c8b582c01f1fd3209f235950427c227c8f970f0be13'
FIT_SHA = '20f320c5bb3f4082e60d73b9f19ee3972a534785135f9098e34291f030526908'
CHECKPOINT_SHA = '3d40511141fa1ef0d022c095c470b7ad2710e390aea68ce87ac0361911af133b'


def stable_box(boxes):
    a = np.asarray(boxes, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != 4 or not len(a) or not np.isfinite(a).all() or \
       not (a[:,2:] > 0).all() or not np.allclose(a[:,2]/a[:,3], .75, atol=1e-6):
        raise ValueError('Expected finite expanded boxes with fixed H32 aspect ratio')
    size = np.median(a[:,2:], axis=0)
    center = np.median(a[:,:2]+a[:,2:]/2, axis=0)
    return np.r_[center-size/2, size].astype(np.float32)


def scaled_fixed_box(boxes, scale=1.0):
    if not np.isfinite(scale) or not 1. <= scale <= 2.5:
        raise ValueError('Coverage crop scale must be finite and between 1 and 2.5')
    box=stable_box(boxes).astype(np.float64)
    center=box[:2]+box[2:]/2
    size=box[2:]*scale
    return np.r_[center-size/2,size].astype(np.float32)


def validate_crop_points(box, points):
    box, points = np.asarray(box), np.asarray(points)
    if box.shape != (4,) or points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Invalid crop/hand points')
    if np.any(points < box[:2]) or np.any(points > box[:2]+box[2:]):
        raise ValueError('Observed hand points outside fixed crop')


def adapt_inference(source):
    parser = "    parser.add_argument('--bbox_thr', type=int, default=50)"
    bbox = '            bbox = process_bbox(mmdet_box_xywh, original_img_width, original_img_height)'
    # Test fixtures may use a different indentation; production is digest-pinned before adapting.
    line = next((x for x in source.splitlines() if x.strip() == bbox.strip()), None)
    if source.count(parser) != 1 or line is None or source.count(line) != 1:
        raise ValueError('Upstream inference patch anchors differ')
    indentation = line[:len(line)-len(line.lstrip())]
    changed = source.replace(parser, parser+"\n    parser.add_argument('--fixed_bbox_file', required=True)")
    changed = changed.replace(line, indentation+'bbox = np.asarray(json.loads(Path(args.fixed_bbox_file).read_text()), dtype=np.float32)')
    changed = 'from pathlib import Path\n' + changed
    compile(changed, '<stable-crop-inference>', 'exec')
    return changed


def command(python, script, images, first, last, output, box_file):
    if first < 1 or last < first:
        raise ValueError('Invalid frame scope')
    return [str(python), str(script), '--num_gpus', '1', '--pretrained_model', 'smpler_x_h32',
            '--img_path', str(images), '--start', str(first), '--end', str(last-first+1),
            '--output_folder', str(output), '--exp_name', str(output.parent/'runtime'/output.name),
            '--show_bbox', '--fixed_bbox_file', str(box_file)]


def report_contract(full_sequence=False):
    scope={s:tuple(range(1,n+1)) for s,n in hand.FULL_SEQUENCE_COUNTS.items()} if full_sequence else WINDOWS
    return {'schema':'signbridge-stable-crop-pilot-v1','status':'running',
            'scope':{s:list(ids) for s,ids in scope.items()}, 'training_ready':False,
            'full_sequence_inferred':full_sequence,
            'full_sequence_refined':False,'original_fits_overwritten':False,
            'contact_approved':False,'temporal_smoothing':False,
            'new_network_inference':True,'cases':[],'source_sha256':{}}


def run(args):
    from PIL import Image

    root, fits, batch, output, plan_path = [Path(getattr(args,k)).resolve() for k in
        ('smplerx_root','fits','batch','output','plan')]
    if output.exists() or any(output==p or p in output.parents or output in p.parents
                              for p in (root,fits,batch)):
        raise ValueError('Output must be new and separate')
    full_sequence=getattr(args,'full_sequence',False)
    scope={s:tuple(range(1,n+1)) for s,n in hand.FULL_SEQUENCE_COUNTS.items()} if full_sequence else WINDOWS
    report = report_contract(full_sequence)
    watched = {}

    def watch(path, expected=None):
        path=Path(path)
        value=hand.sha256(path)
        if expected is not None and value != expected:
            raise ValueError('Source digest mismatch: '+str(path))
        watched[str(path)] = value
        return value

    watch(plan_path)
    plan = json.loads(plan_path.read_text())
    if plan.get('schema') != 'signbridge-stable-crop-plan-v1' or plan.get('training_ready') is not False or \
       plan.get('fit_run_sha256') != FIT_SHA or set(plan['windows']) != set(scope):
        raise ValueError('Unexpected stable-crop plan')
    watch(fits/'run.json', FIT_SHA)
    previous = json.loads((fits/'run.json').read_text())
    if previous.get('tasks_sha256') != watch(batch/'tasks.jsonl') or \
       previous.get('status') != 'inferred_pending_import_audit':
        raise ValueError('Original fitting run differs')
    watch(batch/'contract.json',plan['batch_sha256']['contract.json'])
    watch(batch/'SHA256SUMS',plan['batch_sha256']['SHA256SUMS'])
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=hand.COMMIT:
        raise ValueError('Wrong SMPLer-X commit')
    inference = root/'main/inference.py'
    watch(inference, INFERENCE_SHA)
    watch(root/'pretrained_models/smpler_x_h32.pth.tar',CHECKPOINT_SHA)
    for relative, sha in plan['assets_sha256'].items():
        watch(hand.inside(root,relative), sha)
    hand.verify_model_assets(root)
    selected = {}
    for segment, ids in scope.items():
        p = plan['windows'][segment]
        if p['frames'] != list(ids):
            raise ValueError('Wrong plan frame scope')
        records = p['sources']
        if len(records)!=len(ids) or [r['frame_1based'] for r in records]!=list(ids):
            raise ValueError('Wrong plan source identities')
        metas=[]
        for row in records:
            frame=row['frame_1based']
            image=hand.inside(batch,'samples/'+segment+'/images/%06d.jpg'%frame)
            meta=hand.inside(fits,segment+'/meta/%05d_0.json'%frame)
            native=hand.inside(fits,segment+'/smplx/%05d_0.npz'%frame)
            watch(image,row['image_sha256']);watch(meta,row['meta_sha256']);watch(native,row['fit_sha256'])
            value=json.loads(meta.read_text())
            if value['img_path'] != str(image) or value['bbox_id'] != 0:
                raise ValueError('Metadata frame/person differs')
            metas.append(value)
        fixed=scaled_fixed_box([m['bbox'] for m in metas],p.get('coverage_scale',1.0))
        if not np.array_equal(fixed,np.asarray(p['fixed_bbox'],dtype=np.float32)):
            raise ValueError('Fixed crop differs from median source boxes')
        selected[segment]=fixed
    output.mkdir(parents=True)
    path=output/'report.json'

    def save():
        report['source_sha256']=dict(watched)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

    save()
    stage='runtime_preflight'
    try:
        os.environ.setdefault('PYOPENGL_PLATFORM','egl')
        os.environ.setdefault('MPLBACKEND','Agg')
        report['renderer_preflight']=hand.renderer_preflight()
        import torch
        if not torch.cuda.is_available():
            raise ValueError('CUDA unavailable')
        report['runtime']={'torch':torch.__version__,'cuda':torch.version.cuda,
                           'gpu':torch.cuda.get_device_name(0)}
        script=output/'stable-inference.py'
        script.write_text(adapt_inference(inference.read_text()))
        report['adapted_inference_sha256']=hand.sha256(script)
        env=dict(os.environ)
        env['PYTHONPATH']=os.pathsep.join(str(root/p) for p in ('main','common','common/utils/smplx'))
        env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONUNBUFFERED']='1'
        for segment, ids in scope.items():
            stage='inference:'+segment
            folder=output/segment
            box_file=output/(segment+'-bbox.json')
            box_file.write_text(json.dumps(selected[segment].tolist())+'\n')
            argv=command(sys.executable,script,batch/'samples'/segment/'images',ids[0],ids[-1],folder,box_file)
            report.setdefault('commands',[]).append(argv)
            save()
            print('Stable crop actual inference:',segment,'frames',list(ids),flush=True)
            with (output/(segment+'.log')).open('w') as log:
                subprocess.run(argv,cwd=root/'main',env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
            expected={'%05d_0.npz'%f for f in ids}
            if {p.name for p in (folder/'smplx').glob('*.npz')} != expected:
                raise ValueError('Stable-crop inference frame count differs')
            fixed64=selected[segment].astype(np.float64)
            camera_focal=np.asarray([5000./192.*fixed64[2],5000./256.*fixed64[3]])
            camera_principal=fixed64[:2]+fixed64[2:]/2
            for frame in ids:
                meta=json.loads((folder/'meta'/('%05d_0.json'%frame)).read_text())
                values=hand.read_native(folder/'smplx'/('%05d_0.npz'%frame))
                if not np.array_equal(np.asarray(meta['bbox'],dtype=np.float32),selected[segment]) or \
                   not np.allclose(meta['focal'],camera_focal,rtol=1e-6) or \
                   not np.allclose(meta['princpt'],camera_principal,atol=1e-5):
                    raise ValueError('Stable crop camera varies')
                with Image.open(folder/'img'/('%06d.jpg'%frame)) as img:
                    size=img.size
                report['cases'].append({'segment_id':segment,'frame_1based':frame,
                    'parameters_file':segment+'/smplx/%05d_0.npz'%frame,
                    'camera_file':segment+'/meta/%05d_0.json'%frame,
                    'image_size':list(size),'depth':float(values['transl'][0,2]),'training_ready':False})
            save()
        stage='saved_parameter_native_parity'
        sparse=hand.SparseSMPLX(root/hand.MODEL_FILE)
        runtime=hand.native_runtime(root)
        for row in report['cases']:
            params=hand.read_native(output/row['parameters_file'])
            row['native_parity_max_metres']=hand.parity(sparse,runtime,params)
        stage='source_revalidation'
        for name,value in watched.items():
            if hand.sha256(name)!=value:
                raise ValueError('Source changed during stable-crop inference: '+name)
        report.update(status='inferred_pending_stable_crop_review',source_files_unchanged=True)
        save()
        print('Stable-crop inference complete; %d saved frames; no training.'%len(report['cases']),flush=True)
    except Exception as error:
        report.update(status='failed',failure_stage=stage,error_type=type(error).__name__,
                      error=str(error),traceback=traceback.format_exc())
        save()
        raise
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('smplerx-root','fits','batch','output','plan'):
        parser.add_argument('--'+k,type=Path,required=True)
    parser.add_argument('--full-sequence',action='store_true',help='Reviewed 166+218 frame scope; no motion approval')
    print(run(parser.parse_args()))


if __name__=='__main__':
    main()
