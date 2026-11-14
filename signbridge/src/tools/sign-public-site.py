#!/usr/bin/env python3
"""Derive a publication-safe copy of a built demo site.

The repository's release policy keeps source-video frames out of public
downloads. This tool copies a verified build, drops the research reference
images, empties the research index, and rewrites BUILD.json so the result is
still a self-consistent, hash-listed site. Nothing else is altered.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

RESEARCH_PREFIX = 'demo/research/'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main(source, output):
    source, output = Path(source).absolute(), Path(output).absolute()
    if output.exists():
        raise FileExistsError('Choose a NEW output directory')
    manifest_path = source / 'BUILD.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Source BUILD.json has no file list')
    for name in sorted(files):
        path = source / name
        if not path.is_file() or sha(path) != files[name]:
            raise ValueError('Source file differs from its manifest: ' + name)
    shutil.copytree(source, output)
    removed = []
    for name in sorted(files):
        if name.startswith(RESEARCH_PREFIX):
            (output / name).unlink()
            removed.append(name)
    research_dir = output / 'demo/research'
    if research_dir.is_dir() and not any(research_dir.iterdir()):
        research_dir.rmdir()
    index_path = output / 'demo/research.json'
    if index_path.is_file():
        index_path.write_text('[]\n', encoding='utf-8')
        files['demo/research.json'] = sha(index_path)
    for name in removed:
        files.pop(name, None)
    manifest['files'] = dict(sorted(files.items()))
    manifest['publication_redactions'] = {
        'removed_research_images': len(removed),
        'reason': 'source-video frames are excluded from public downloads',
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    (output / 'BUILD.json').write_text(manifest_text, encoding='utf-8')
    # Re-verify the derived site end to end.
    written = json.loads((output / 'BUILD.json').read_text(encoding='utf-8'))['files']
    for name in sorted(written):
        if sha(output / name) != written[name]:
            raise ValueError('Derived file differs from its manifest: ' + name)
    internal = {'BUILD.json', '.signbridge-build.json'}
    leftovers = [p for p in output.rglob('*') if p.is_file() and p.relative_to(output).as_posix() not in written and p.name not in internal]
    if leftovers:
        raise ValueError('Derived site has unlisted files: ' + ', '.join(str(p) for p in leftovers[:3]))
    print(json.dumps({
        'site': str(output),
        'files': len(written),
        'removed_images': len(removed),
        'build_sha256': sha(output / 'BUILD.json'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    main(args.site, args.output)
