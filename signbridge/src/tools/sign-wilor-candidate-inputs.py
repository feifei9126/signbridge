"""Validate unapproved source-image plans without granting content approval."""

import hashlib
import json
import math
import re
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def inside(root, name):
    relative = Path(name)
    path = (root / relative).resolve()
    require(not relative.is_absolute() and '..' not in relative.parts and root in path.parents
            and path.is_file(), 'Unsafe or missing source file')
    return path


def read_candidate_plan(batch, path, expected_sha):
    batch = Path(batch).resolve()
    require(sha(path) == expected_sha, 'Candidate plan digest differs')
    plan = json.loads(Path(path).read_text())
    require(plan.get('schema') == 'signbridge-wilor-candidate-source-plan-v1', 'Candidate schema differs')
    for flag in ('training_ready', 'model_training_ready', 'human_approved'):
        require(plan.get(flag) is False, 'Candidate approval gate must remain false')
    checksums = {}
    for line in (batch / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        require(re.fullmatch('[0-9a-f]{64}', digest) and name not in checksums, 'Invalid manifest')
        require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Unsafe manifest path')
        checksums[name] = digest
    for name, field in [('SHA256SUMS', 'batch_manifest_sha256'), ('tasks.jsonl', 'batch_tasks_sha256'),
                        ('contract.json', 'batch_contract_sha256')]:
        actual = sha(inside(batch, name))
        require(actual == plan.get(field), 'Candidate batch identity differs: ' + name)
        if name != 'SHA256SUMS':
            require(checksums.get(name) == actual, 'Batch file changed: ' + name)
    contract = json.loads((batch / 'contract.json').read_text())
    require(contract.get('schema') == 'signbridge-smplerx-input-v1'
            and contract.get('smplerx_commit') == '064baef0e4ab5277a3297691bc1d46ea5412586f'
            and all(contract.get(flag) is False for flag in ('training_ready', 'model_training_ready', 'human_approved')),
            'Candidate batch contract differs')
    tasks = [json.loads(x) for x in (batch / 'tasks.jsonl').read_text().splitlines() if x.strip()]
    require(len({t['segment_id'] for t in tasks}) == len(tasks), 'Duplicate source tasks')
    index = {t['segment_id']: t for t in tasks}
    sequences = plan.get('sequences')
    require(isinstance(sequences, list) and 1 <= len(sequences) <= 30, 'Bounded sequence scope required')
    selected, seen = [], set()
    for sequence in sequences:
        sid, count = sequence.get('segment_id'), sequence.get('frames')
        require(isinstance(sid, str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', sid)
                and sid in index and sid not in seen, 'Invalid or duplicate source identity')
        seen.add(sid)
        task = index[sid]
        require(task.get('training_ready') is False, 'Candidate training gate must remain false')
        require(type(count) is int and 1 <= count <= task['frames'] and task.get('model_training_ready') is False,
                'Invalid candidate frame count or training gate')
        require(task.get('human_approved') is False and task.get('semantics_approved') is False
                and task.get('boundaries_approved') is False, 'Unapproved input scope must be explicit')
        require(task.get('image_transform', 'none') == 'none' and contract.get('mirroring') is False
                and contract.get('resampling') is False, 'Candidate images must be unchanged')
        require(isinstance(task.get('fps'), (float, int)) and math.isfinite(task['fps']) and task['fps'] > 0,
                'Invalid source fps')
        for field in ('source_sha256', 'clip_sha256'):
            require(sequence.get(field) == task.get(field) and re.fullmatch('[0-9a-f]{64}', task[field]),
                    'Candidate source or package clip identity differs')
        def checked(name):
            file = inside(batch, name)
            require(checksums.get(name) == sha(file), 'Candidate input changed: ' + name)
            return file
        clip = checked(task['clip'])
        require(sha(clip) == task['clip_sha256'], 'Package clip digest differs')
        observation = checked(task['observation_artifact'])
        require(sha(observation) == task['observation_sha256'], 'Observation identity differs')
        frames = [json.loads(x) for x in checked(task['frame_manifest']).read_text().splitlines() if x.strip()]
        require(len(frames) == task['frames'], 'Source frame manifest count differs')
        for number in range(1, count + 1):
            frame = frames[number - 1]
            image = checked(frame['image'])
            require(frame['frame_id'] == number and image.name == '%06d.jpg' % number
                    and image.parent == (batch / task['images']).resolve()
                    and sha(image) == frame['sha256'], 'Candidate image/frame mapping differs')
            require(math.isclose(frame['clip_seconds'], (number - 1) / task['fps'], abs_tol=1e-6, rel_tol=0),
                    'Candidate frame time differs')
            selected.append((task, number, ('left', 'right'), image, observation))
    require(len(selected) <= 384, 'Candidate inference exceeds bounded scope')
    return selected
