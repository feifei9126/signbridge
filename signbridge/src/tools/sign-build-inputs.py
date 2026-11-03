#!/usr/bin/env python3
"""Create a NEW manifest of explicitly chosen local Demo asset bytes.

This snapshot is a build input contract; it is not reconstructed historical
provenance or a human sign-language approval.
"""
import argparse
import hashlib
import json
from pathlib import Path


def snapshot(demo, experimental, output, native=None):
    demo, experimental, output = Path(demo).resolve(), Path(experimental).resolve(), Path(output)
    if output.exists():
        raise FileExistsError('Preserve the previous manifest; use a new output')
    groups = {'demo': {}, 'experimental': {}}
    names = ['t08-motion.json', 't08-candidates.json', 'research.json']
    research = json.loads((demo / 'research.json').read_text())
    index = json.loads((experimental / 'experimental-index.json').read_text())
    experimental_paths = ['experimental-index.json'] + [entry['asset'] for entry in index['clips']]
    if index.get('motion_approval'):
        experimental_paths.append(index['motion_approval']['asset'])
    paths = {'demo': names + [item['image'] for item in research],
             'experimental': experimental_paths}
    if native is not None:
        native = Path(native).resolve()
        native_index = json.loads((native / 'native-index.json').read_text())
        groups['native'] = {}
        paths['native'] = ['native-index.json', *[c['asset'] for c in native_index['clips']]]
    for group, files in paths.items():
        root = demo if group == 'demo' else native if group == 'native' else experimental
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
    parser.add_argument('--native', type=Path)
    args = parser.parse_args()
    value = snapshot(args.demo, args.experimental, args.output, args.native)
    print(json.dumps({'demo_files': len(value['demo']), 'experimental_files': len(value['experimental']), 'training_ready': False}))
