"""Compare historical tokenizer rounds and store exact duplicate artifacts once.

This creates a new content-addressed archive. It never deletes or edits source
training runs and never marks a dataset or checkpoint ready for deployment.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('dedup_smoke',HERE/'sign-tokenizer-smoke.py')
smoke=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def validate_sequence_scope(report,rows):
    expected=[{'segment_id':r['segment_id'],'frames':r['frames']} for r in rows]
    if report.get('sequences')!=expected:
        raise ValueError('Training report/motion sequence scope differs')
    if len({r['segment_id'] for r in rows})!=len(rows):
        raise ValueError('Motion sequence IDs are not unique')


def validate_round(round_id,run_root,motion_root,expected_checkpoint_sha=None):
    run_root=Path(run_root).resolve();motion_root=Path(motion_root).resolve()
    report_path=run_root/'report.json';checkpoint=run_root/'tokenizer-smoke.pt'
    if not report_path.is_file() or not checkpoint.is_file():
        raise ValueError(f'{round_id} report/checkpoint is incomplete')
    report=json.loads(report_path.read_text())
    if (report.get('schema')!='signbridge-tokenizer-smoke-v1' or
        report.get('status')!='research_smoke_trained_not_deployable' or
        report.get('research_only') is not True or report.get('training_ready') is not False or
        report.get('deployment_ready') is not False or report.get('text_to_sign_trained') is not False or
        report.get('checkpoint_reload_passed') is not True):
        raise ValueError(f'{round_id} training report is not a complete research-only run')
    checkpoint_sha=sha(checkpoint)
    if report.get('checkpoint_sha256')!=checkpoint_sha:
        raise ValueError(f'{round_id} checkpoint digest differs from report')
    if expected_checkpoint_sha and checkpoint_sha!=expected_checkpoint_sha:
        raise ValueError(f'{round_id} checkpoint digest differs from the registered digest')
    verification=json.loads((motion_root/'verification.json').read_text())
    rows=read_jsonl(motion_root/'motions.jsonl')
    ids=[r['segment_id'] for r in report.get('sequences',[])]
    if verification.get('training_ready') is not False or verification.get('soke_commit')!=smoke.SOKE_COMMIT:
        raise ValueError(f'{round_id} motion verification contract differs')
    validate_sequence_scope(report,rows)
    observed_rows,arrays,input_hashes=smoke.load_inputs(motion_root,True,ids)
    required=smoke.quality_masks_required(verification)
    masks,mask_hashes=smoke.load_quality_masks(motion_root,observed_rows,required=required)
    input_hashes+=mask_hashes
    if input_hashes!=report.get('input_sha256'):
        raise ValueError(f'{round_id} ordered training input hashes cannot be reproduced')
    feature_hashes={};mask_hashes_by_id={}
    for row in rows:
        feature=(motion_root/row['features']).resolve()
        if motion_root not in feature.parents:
            raise ValueError(f'{round_id} feature path escaped the motion root')
        feature_hashes[row['segment_id']]=sha(feature)
        mask=feature.with_name('feature-valid-mask.npy')
        mask_hashes_by_id[row['segment_id']]=sha(mask) if mask.is_file() else None
    return {'id':round_id,'run_root':str(run_root),'motion_root':str(motion_root),
            'report_sha256':sha(report_path),'checkpoint_sha256':checkpoint_sha,
            'checkpoint_bytes':checkpoint.stat().st_size,'steps':report.get('steps'),
            'checkpoint_step':report.get('checkpoint_step'),'seed':report.get('seed'),
            'best_training_mse_normalized':report.get('best_training_mse_normalized'),
            'reloaded_training_mse_normalized':report.get('reloaded_training_mse_normalized'),
            'frames':sum(r['frames'] for r in rows),'sequences':len(rows),
            'segments':ids,'quality_masked_hand_targets':required,
            'input_hash_count':len(input_hashes),'input_sha256':input_hashes,
            'motions_manifest_sha256':sha(motion_root/'motions.jsonl'),
            'verification_sha256':sha(motion_root/'verification.json'),
            'feature_hashes':feature_hashes,'mask_hashes':mask_hashes_by_id,
            'source_or_person_independence_verified':report.get('source_or_person_independence_verified',False),
            'evaluation_completed':report.get('evaluation_completed',False),
            'training_ready':False,'deployment_ready':False}


def safe_files(root):
    root=Path(root).resolve()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink is not allowed in dedup source: {path}')
        if path.is_file():
            resolved=path.resolve()
            if root not in resolved.parents:
                raise ValueError(f'File escapes dedup source root: {path}')
            yield path.relative_to(root),path


def inventory_files(round_roots,output):
    output=Path(output)
    object_root=output/'objects/sha256'
    records=[];objects={}
    for round_id,root in round_roots.items():
        root=Path(root).resolve()
        for relative,path in safe_files(root):
            digest=sha(path);obj=object_root/digest[:2]/digest
            if digest not in objects:
                obj.parent.mkdir(parents=True,exist_ok=True)
                with path.open('rb') as src,obj.open('xb') as dst:
                    shutil.copyfileobj(src,dst,1024*1024)
                if sha(obj)!=digest:
                    raise ValueError(f'Object verification failed: {relative}')
                objects[digest]={'sha256':digest,'bytes':path.stat().st_size,
                                 'object_path':str(obj.relative_to(output))}
            elif objects[digest]['bytes']!=path.stat().st_size:
                raise ValueError('Digest collision with differing lengths')
            records.append({'round':round_id,'source_root':str(root),'source_path':str(relative),
                            'sha256':digest,'bytes':path.stat().st_size,
                            'object_path':objects[digest]['object_path']})
    return records,objects


def build(args):
    output=args.output.resolve()
    if output.exists():
        raise ValueError('Dedup output must be a new versioned directory')
    runs={};motion_roots={};registered={}
    for entry in args.round:
        round_id,run_path,motion_path,expected=entry.split('|',3)
        if round_id in runs:
            raise ValueError(f'Duplicate round ID: {round_id}')
        runs[round_id]=Path(run_path).resolve()
        motion_roots[round_id]=Path(motion_path).resolve()
        registered[round_id]=expected or None
    if not {'T08','T09','T10'}.issubset(runs):
        raise ValueError('This comparison expects T08, T09 and T10')
    round_records={key:validate_round(key,runs[key],motion_roots[key],registered[key]) for key in runs}
    segment_sets={tuple(record['segments']) for record in round_records.values()}
    if len(segment_sets)!=1:
        raise ValueError('The three rounds do not have the same ordered segment scope')
    output.mkdir(parents=True)
    all_roots={f'{key}:run':runs[key] for key in runs}
    all_roots.update({f'{key}:motion':motion_roots[key] for key in motion_roots})
    records,objects=inventory_files(all_roots,output)
    records_by_digest={}
    for row in records:records_by_digest.setdefault(row['sha256'],[]).append(row)
    exact_duplicates=[]
    for digest,items in records_by_digest.items():
        if len(items)>1:
            exact_duplicates.append({'sha256':digest,'occurrences':len(items),
                                     'bytes_per_copy':objects[digest]['bytes'],
                                     'occurrences_detail':[{'round':x['round'],'path':x['source_path']} for x in items]})
    first=round_records['T08'];first_ids=first['segments']
    features_deduped=all(round_records[key]['feature_hashes']==first['feature_hashes'] for key in runs)
    feature_mapping=[];mask_mapping=[]
    for segment in first_ids:
        feature_variants={round_id:round_records[round_id]['feature_hashes'][segment] for round_id in runs}
        if len(set(feature_variants.values()))!=1:
            raise ValueError(f'Feature content differs across rounds for {segment}')
        feature_mapping.append({'segment_id':segment,'sha256':next(iter(feature_variants.values())),
                                'round_copies':sorted(runs)})
        mask_variants={round_id:round_records[round_id]['mask_hashes'][segment] for round_id in runs}
        unique_masks=sorted({h for h in mask_variants.values() if h is not None})
        mask_mapping.append({'segment_id':segment,'round_mask_sha256':mask_variants,
                             'unique_mask_count':len(unique_masks),'unique_mask_sha256':unique_masks})
    if not features_deduped:
        raise ValueError('Feature files differ; refusing to merge training inputs')
    checkpoints={key:round_records[key]['checkpoint_sha256'] for key in runs}
    if len(set(checkpoints.values()))!=len(checkpoints):
        raise ValueError('Checkpoints unexpectedly identical; investigate training round identity')
    write_json(output/'rounds.json',{'schema':'signbridge-training-round-comparison-v1',
        'created_at':datetime.now(timezone.utc).isoformat(),'rounds':round_records,
        'checkpoint_hashes_are_distinct':True,'feature_content_identical_across_rounds':True,
        'feature_sample_count':len(first_ids),'feature_frames':sum(
                row['frames'] for row in read_jsonl(motion_roots['T08']/'motions.jsonl')),
        'unique_feature_files':len(feature_mapping),'t08_t09_t10_scope_identical':True,
        'quality_approved':False,'training_ready':False,'deployment_ready':False})
    (output/'files.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records))
    write_json(output/'exact-duplicates.json',{'schema':'signbridge-training-file-duplicates-v1',
        'duplicate_groups':len(exact_duplicates),'duplicate_occurrences':sum(x['occurrences']-1 for x in exact_duplicates),
        'bytes_reused':sum(x['bytes_per_copy']*(x['occurrences']-1) for x in exact_duplicates),
        'groups':exact_duplicates})
    write_json(output/'canonical-training-inputs.json',{'schema':'signbridge-canonical-training-inputs-v1',
        'round_scope':['T08','T09','T10'],'unique_samples':len(feature_mapping),
        'frame_count':sum(r['frames'] for r in read_jsonl(motion_roots['T08']/'motions.jsonl')),
        'unique_feature_files':feature_mapping,'quality_mask_variants':mask_mapping,
        'feature_deduplication':'Exact SHA-256 match: same feature arrays stored as one canonical blob in objects/.',
        'mask_policy':'Masks stay versioned and are not merged; T09 and T10 must retain their differing supervision masks.',
        'checkpoints':'All three checkpoint digests differ and are retained as separate experiments.',
        'training_ready':False,'human_motion_quality_approved':False})
    summary={'schema':'signbridge-training-dedup-bundle-v1','created_at':datetime.now(timezone.utc).isoformat(),
        'rounds':sorted(runs),'source_files':len(records),'unique_content_objects':len(objects),
        'exact_duplicate_occurrences_removed_from_bundle':sum(x['occurrences']-1 for x in exact_duplicates),
        'unique_feature_sequences':len(feature_mapping),'quality_mask_variants':sum(x['unique_mask_count'] for x in mask_mapping),
        'distinct_checkpoints':len(checkpoints),'training_started':False,'training_ready':False,
        'next_step':'Run one frozen T10 evaluation against the same paired reference used for T08/T09; do not train a redundant fourth smoke model.',
        'sources_unchanged':True}
    write_json(output/'summary.json',summary)
    checks=[]
    for path in sorted(output.rglob('*')):
        if path.is_file() and path.name!='SHA256SUMS':checks.append(f'{smoke.digest(path)}  {path.relative_to(output)}\n')
    (output/'SHA256SUMS').write_text(''.join(checks))
    print(json.dumps(summary,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round',action='append',required=True,
        help='ROUND|RUN_DIR|MOTION_DIR|EXPECTED_CHECKPOINT_SHA256; blank expected hash allowed only as trailing empty field')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,IndexError) as error:
        raise SystemExit(f'error: {error}')
