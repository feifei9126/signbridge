"""Seal the tested local Demo into a new ZIP; never include live session files."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

MEMBERS = ['web', 'private-model', 'tools', 'docs', 'README.md', 'model-config.json', '启动模型Demo.command',
           'qa-v2', 'qa-final', 'motion-quality-v1.json', 'catalog-v1.json', 'verification-final-v2.json']


def package(root, archive):
    root, archive = Path(root).resolve(), Path(archive).absolute()
    if archive.exists() or archive.is_relative_to(root): raise ValueError('Choose a NEW archive outside the delivery folder')
    files = []
    for name in MEMBERS:
        path = root / name
        if path.is_symlink() or not path.exists(): raise ValueError('Missing or unsafe package member: ' + name)
        for file in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if file.is_symlink(): raise ValueError('Package symlink rejected')
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc': files.append(file)
    if len(set(files)) != len(files): raise ValueError('Duplicate package paths')
    manifest = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(root).as_posix() + '\n' for p in sorted(files))
    (root / 'PACKAGE-SHA256SUMS').write_text(manifest)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for p in sorted(files): zipped.write(p, p.relative_to(root).as_posix())
        zipped.write(root / 'PACKAGE-SHA256SUMS', 'PACKAGE-SHA256SUMS')
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None: raise ValueError('ZIP CRC failure')
        for line in manifest.splitlines():
            digest, name = line.split('  ', 1)
            if hashlib.sha256(zipped.read(name)).hexdigest() != digest: raise ValueError('ZIP internal digest differs')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + '.sha256').write_text(digest + '  ' + archive.name + '\n')
    record = {'archive': str(archive), 'sha256': digest, 'bytes': archive.stat().st_size, 'verified_internal_files': len(files),
              'live_tokens_or_service_state_included': False, 'local_mac_runtime_external_dependency': True}
    (root / 'package-verification.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(package(args.root, args.archive), ensure_ascii=False, indent=2))
