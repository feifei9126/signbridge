"""Full-clip source/baseline/conservative-fusion review videos from real saved overlays."""
import argparse,importlib.util,json,subprocess,tempfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('media_evidence',Path(__file__).with_name('sign-contact-audit.py'))
evidence=importlib.util.module_from_spec(spec);spec.loader.exec_module(evidence)


def overlay_name(row):
    v=row.get('temporal_baseline_selected')
    if type(v) is not bool:raise ValueError('Missing saved temporal selection flag')
    return 'baseline-overlay.jpg' if v else 'candidate-overlay.jpg'


def media_contract(segment,frames,fps,reconstruction=False):
    if not isinstance(frames,int) or frames<1 or not 0<fps<=60:raise ValueError('Invalid media timeline')
    return {'schema':'signbridge-full-sequence-review-media-v1','segment_id':segment,'frames':frames,'fps':fps,
            'training_ready':False,'temporal_interpolation':False,
            'in_sample_reconstruction':reconstruction,'unaccepted_hands_preserved':reconstruction,
            'panels':['Original video frame','Conservative fused input','Tokenizer in-sample reconstruction; masked hands preserved']
                if reconstruction else ['Original video frame','Stable SMPLer-X baseline','Conservative fused candidate; UNREVIEWED']}


def create(args):
    from PIL import Image,ImageDraw,ImageFont
    batch,fusion,motions,out=[Path(getattr(args,k)).resolve() for k in ('batch','fusion_results','motions','output')]
    reconstructed=getattr(args,'reconstructed_results',None)
    reconstructed=Path(reconstructed).resolve() if reconstructed is not None else None
    protected=(batch,fusion.parent,motions)+((reconstructed,) if reconstructed else ())
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in protected):
        raise ValueError('Output must be new and separate')
    checks=evidence.verify_manifest(fusion.parent,fusion.parent/'SHA256SUMS')
    evidence.verify_manifest(motions,motions/'SHA256SUMS')
    reconstruction_checks=None
    if reconstructed:
        reconstruction_checks=evidence.verify_manifest(reconstructed,reconstructed/'SHA256SUMS')
        r=evidence.load_json(reconstructed/'report.json')
        if r.get('status')!='in_sample_native_reconstruction_pending_review' or r.get('training_ready') is not False or \
           r.get('unaccepted_hands_preserved') is not True:
            raise ValueError('Unexpected native reconstruction report')
    tasks=[json.loads(x) for x in (motions/'motions.jsonl').read_text().splitlines() if x.strip()]
    out.mkdir(parents=True)
    for task in tasks:
        segment=task['segment_id'];count=task['frames'];fps=task['fps']
        quality=[json.loads(x) for x in (motions/'samples'/segment/'frame-quality.jsonl').read_text().splitlines() if x.strip()]
        if [r['frame_1based'] for r in quality]!=list(range(1,count+1)):raise ValueError('Media quality/frame scope differs')
        meta=media_contract(segment,count,fps,reconstruction=reconstructed is not None)
        with tempfile.TemporaryDirectory(prefix='signbridge-full-media-') as tmp:
            tmp=Path(tmp)
            for name in ('original','baseline','candidate'):(tmp/name).mkdir()
            sources={}
            for i,row in enumerate(quality,1):
                source=evidence.contained_file(batch,'samples/'+segment+'/images/%06d.jpg'%i)
                selected={kind:evidence.contained_file(fusion.parent,'results/'+segment+'/%06d/'%i+name)
                          for kind,name in (('baseline','baseline-overlay.jpg'),('candidate',overlay_name(row)))}
                for kind,path in selected.items():
                    if checks.get(str(path.relative_to(fusion.parent)))!=evidence.digest(path):raise ValueError('Overlay digest differs')
                if reconstructed:
                    selected['baseline']=selected['candidate']
                    relative=segment+'/%06d.jpg'%i
                    prediction=evidence.contained_file(reconstructed,relative)
                    if reconstruction_checks.get(relative)!=evidence.digest(prediction):raise ValueError('Reconstruction image digest differs')
                    selected['candidate']=prediction
                selected['original']=source
                for kind,path in selected.items():
                    with Image.open(path) as img:
                        frame=img.convert('RGB').resize((640,360),Image.Resampling.LANCZOS)
                    d=ImageDraw.Draw(frame)
                    d.rectangle((0,0,640,30),fill='black')
                    label={'original':'Original','baseline':'Stable baseline',
                           'candidate':'Fused candidate - UNREVIEWED'}[kind]
                    if reconstructed:
                        label={'original':'Original','baseline':'Conservative fused input',
                               'candidate':'Tokenizer reconstruction - IN SAMPLE'}[kind]
                    try:
                        font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',18)
                    except OSError:
                        font=ImageFont.load_default(size=18)
                    d.text((10,5),label,fill='white',font=font)
                    frame.save(tmp/kind/('%06d.jpg'%i),quality=92)
                    sources[str(path)]=evidence.digest(path)
            graph='[0:v][1:v][2:v]hstack=inputs=3[v]'
            command=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n']
            for name in ('original','baseline','candidate'):command+=['-framerate',str(fps),'-start_number','1','-i',str(tmp/name/'%06d.jpg')]
            video=out/(segment+'-compare.mp4')
            command+=['-filter_complex',graph,'-map','[v]','-frames:v',str(count),'-c:v','libx264','-crf','21','-pix_fmt','yuv420p','-movflags','+faststart',str(video)]
            subprocess.run(command,check=True,timeout=180)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames',
                '-show_entries','stream=nb_read_frames,avg_frame_rate,width,height','-of','json',str(video)],text=True))['streams'][0]
            numerator,denominator=map(float,probe['avg_frame_rate'].split('/'))
            if int(probe['nb_read_frames'])!=count or abs(numerator/denominator-fps)>1e-6:raise ValueError('Encoded video frame rate/count differs')
            meta.update(encoded=probe,video_sha256=evidence.digest(video),source_sha256=sources)
            (out/(segment+'-media.json')).write_text(json.dumps(meta,indent=2)+'\n')
    (out/'SHA256SUMS').write_text(''.join(evidence.digest(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file()))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('batch','fusion-results','motions','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--reconstructed-results',type=Path,help='Optional saved native tokenizer reconstructions')
    print(create(p.parse_args()))
if __name__=='__main__':main()
