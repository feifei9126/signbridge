"""Stage and seal the extension-hosted model Demo, keeping weights outside the extension."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

PUBLIC_KEY = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqRSxea4oSTOogvPok12mkWDTAUf3qEVSH+SylL0lzdfsPF1VYKVZFQFoMf8+G/2vR/Cu6jAFNd9oJNSJPzrcy9AGAQ91VRpeBkl0OZrZgPNrd9mwAkOFLa8y2vGfQasCxYLyfg0lWKfmIFCDXz6GyIsW/kVJ53z0UEJSOdypW1+3AUIVLXiM/RKZT0txV240jxKWw6SSlsnlBiv1DuEi5yLIGcrxahzTPzUJUAgnCwctnCU8OE0oz9UIkekqqn/aWByzyf2gH2NNHtfm151Q4Vs6uTwdsTceldWJm6OARI0Zztw4aZbpyyNu6uv2n2blNclNhOEQ8dfDMx1lPFDq9QIDAQAB'
CHECKPOINT = 'c6997e70392afac6748999e2e311131e7c2d0928b06da6ee97b184ef13e8af2d'
MEMBERS = ['chrome-extension', 'private-model', 'tools', 'docs', 'README.md', 'model-config.json',
           '启动模型Demo.command', 'provenance.json', 'validation', 'SUMMARY.json']


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()


def member(root, name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or str(path) != name:
        raise ValueError('Unsafe package member')
    target = root / name
    if any(root.joinpath(*path.parts[:i]).is_symlink() for i in range(1, len(path.parts) + 1)):
        raise ValueError('Package symlink rejected')
    return target


def extension_id():
    digest = hashlib.sha256(base64.b64decode(PUBLIC_KEY)).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(n, 16)) for n in digest)


def stage(base, build, output):
    base, build, output = Path(base).resolve(), Path(build).resolve(), Path(output).absolute()
    if output.exists(): raise FileExistsError('Choose a NEW delivery directory')
    for line in (base / 'PACKAGE-SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if sha(member(base, name)) != digest: raise ValueError('Previous delivery changed: ' + name)
    info = json.loads((build / 'BUILD.json').read_text())
    if info['profile'] != 'public-motion-demo' or info['research_asset_manifest_sha256'] != '243e4345dd07d33af6f16b0e2cec300f731e3feae5ed48da779b95c2585ba946':
        raise ValueError('Unexpected public motion build')
    for name, digest in info['files'].items():
        if sha(member(build, name)) != digest: raise ValueError('Build changed: ' + name)
    output.mkdir()
    extension = output / 'chrome-extension'; extension.mkdir()
    for name in [*info['files'], 'BUILD.json']:
        target = member(extension, name); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(member(build, name), target)
    manifest = json.loads((extension / 'manifest.json').read_text())
    manifest.update(key=PUBLIC_KEY, name='SignBridge 模型演示 Demo', version_name='1.0.7 · local model Demo')
    (extension / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    info['files']['manifest.json'] = sha(extension / 'manifest.json')
    info['model_demo_extension_id'] = extension_id()
    info['unmodified_build_sha256'] = sha(build / 'BUILD.json')
    (extension / 'BUILD.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
    shutil.copytree(base / 'private-model', output / 'private-model')
    tools = output / 'tools'; tools.mkdir()
    for source in sorted((base / 'tools').glob('*.py')):
        current = Path(__file__).with_name(source.name)
        if not current.is_file(): raise ValueError('Required tool missing: ' + source.name)
        shutil.copy2(current, tools / source.name)
    config = json.loads((base / 'model-config.json').read_text())
    if config['checkpoint_sha256'] != CHECKPOINT: raise ValueError('Unexpected checkpoint')
    config.update(web='chrome-extension', service_port=8787, extension_origins=['chrome-extension://' + extension_id()])
    (output / 'model-config.json').write_text(json.dumps(config, indent=2) + '\n')
    command = output / '启动模型Demo.command'
    command.write_text('#!/bin/zsh\ncd -- "${0:A:h}" || exit 1\nexec /usr/bin/python3 tools/sign-model-demo-launch.py --no-open "$@"\n')
    command.chmod(0o755)
    (output / 'docs').mkdir(); (output / 'validation').mkdir()
    record = {'schema': 'signbridge-extension-model-demo-v1', 'extension_id': extension_id(),
        'base_delivery': str(base), 'base_manifest_sha256': sha(base / 'PACKAGE-SHA256SUMS'),
        'original_build_sha256': sha(build / 'BUILD.json'), 'packaged_build_sha256': sha(extension / 'BUILD.json'),
        'checkpoint_sha256': CHECKPOINT, 'public_key_only': True, 'runtime_external': config['runtime'],
        'research_only': True, 'human_approved': False, 'semantics_approved': False,
        'training_ready': False, 'model_training_ready': False, 'csl_translation_verified': False}
    (output / 'provenance.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    return record


def seal(root, archive):
    root, archive = Path(root).resolve(), Path(archive).absolute()
    if archive.exists() or archive.is_relative_to(root): raise ValueError('Choose a NEW archive outside the delivery')
    files = []
    for name in MEMBERS:
        path = member(root, name)
        if not path.exists(): raise ValueError('Missing package member: ' + name)
        for file in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if file.is_symlink(): raise ValueError('Package symlink rejected')
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc': files.append(file)
    manifest = ''.join(sha(file) + '  ' + file.relative_to(root).as_posix() + '\n' for file in sorted(files))
    (root / 'PACKAGE-SHA256SUMS').write_text(manifest)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for file in [*sorted(files), root / 'PACKAGE-SHA256SUMS']:
            name = file.relative_to(root).as_posix()
            entry = zipfile.ZipInfo(name, date_time=(2026, 11, 8, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = ((0o100755 if name.endswith('.command') else 0o100644) << 16)
            entry.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(entry, file.read_bytes(), compresslevel=6)
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip(): raise ValueError('ZIP CRC failure')
        for line in manifest.splitlines():
            digest, name = line.split('  ', 1)
            if hashlib.sha256(zipped.read(name)).hexdigest() != digest: raise ValueError('ZIP member differs')
    record = {'archive': str(archive), 'sha256': sha(archive), 'bytes': archive.stat().st_size,
        'verified_internal_files': len(files), 'live_session_state_included': False, 'runtime_external': True}
    Path(str(archive) + '.sha256').write_text(record['sha256'] + '  ' + archive.name + '\n')
    (root / 'package-verification.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('stage')
    for name in ['base', 'build', 'output']: prepare.add_argument('--' + name, type=Path, required=True)
    pack = commands.add_parser('seal'); pack.add_argument('--root', type=Path, required=True); pack.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.base, args.build, args.output) if args.command == 'stage' else seal(args.root, args.archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))
