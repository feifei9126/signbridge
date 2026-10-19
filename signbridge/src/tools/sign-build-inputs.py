#!/usr/bin/env python3
"""Create a NEW manifest of explicitly chosen local Demo asset bytes.

This snapshot is a build input contract; it is not reconstructed historical
provenance or a human sign-language approval.
"""
import argparse
import hashlib
import json
from pathlib import Path


def snapshot(demo, experimental, output):
    demo, experimental, output = Path(demo).resolve(), Path(experimental).resolve(), Path(output)
    if output.exists():
        raise FileExistsError('Preserve the previous manifest; use a new output')
    groups = {'demo': {}, 'experimental': {}}
    names = ['t08-motion.json', 't08-candidates.json', 'research.json']
    research = json.loads((demo / 'research.json').read_text())
    index = json.loads((experimental / 'experimental-index.json').read_text())
    paths = {'demo': names + [item['image'] for item in research],
             'experimental': ['experimental-index.json'] + [entry['asset'] for entry in index['clips']]}
    for group, files in paths.items():
        root = demo if group == 'demo' else experimental
        for name in files:
            path = root / name
            if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name or path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Unsafe asset path')
            if name in groups[group]:
                raise ValueError('Duplicate asset path')
            groups[group][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = {'schema': 'signbridge-research-build-inputs-v1', **groups,
             'scope': 'Current byte snapshot only; no inferred approval or missing legacy hashes',
             'human_approved': False, 'training_ready': False}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', type=Path, required=True)
    parser.add_argument('--experimental', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = snapshot(args.demo, args.experimental, args.output)
    print(json.dumps({'demo_files': len(value['demo']), 'experimental_files': len(value['experimental']), 'training_ready': False}))
