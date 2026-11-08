"""Build a relocatable Apple-silicon model Demo from locally verified artifacts."""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import subprocess
import sys


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''): h.update(data)
    return h.hexdigest()


def closure(names):
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    selected = {}
    pending = list(names)
    while pending:
        name = canonicalize_name(pending.pop())
        if name in selected: continue
        dist = metadata.distribution(name)
        selected[name] = dist
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker and not req.marker.evaluate({'extra': ''}): continue
            if req.specifier and metadata.version(req.name) not in req.specifier:
                raise ValueError('Dependency version differs: ' + raw)
            pending.append(req.name)
    return selected


def runtime(output):
    base = Path(sys.base_prefix).resolve()
    (output / 'bin').mkdir(parents=True)
    shutil.copy2(base / 'bin/python3.10', output / 'bin/python3.10')
    shutil.copytree(base / 'lib', output / 'lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc', '*.a'))
    for path in base.glob('*LICENSE*'):
        if path.is_file(): shutil.copy2(path, output / path.name)
    packages = output / 'lib/python3.10/site-packages'; packages.mkdir()
    records = []
    for name, dist in sorted(closure(['torch', 'transformers', 'numpy']).items()):
        site = Path(dist.locate_file('')).resolve(); copied = {}
        for file in dist.files or []:
            source = Path(dist.locate_file(file))
            try: relative = source.absolute().relative_to(site)
            except ValueError: continue  # Console scripts are not needed by inference.
            if '..' in relative.parts or source.suffix == '.pyc' or '__pycache__' in relative.parts: continue
            if source.is_symlink() and not source.resolve().is_relative_to(site):
                raise ValueError('External dependency symlink: ' + str(source))
            if not source.is_file(): raise ValueError('Dependency file missing: ' + str(source))
            target = packages / relative; target.parent.mkdir(parents=True, exist_ok=True)
            digest = sha(source)
            if target.exists() and sha(target) != digest: raise ValueError('Conflicting distribution file: ' + str(relative))
            shutil.copy2(source, target)
            if sha(target) != digest: raise ValueError('Dependency copy differs')
            copied[relative.as_posix()] = digest
        records.append({'name': name, 'version': dist.version, 'files': copied})
    # A .pth entry can import code or reintroduce the source virtual environment.
    for path in packages.glob('*.pth'): raise ValueError('Unexpected runtime path hook: ' + path.name)
    return {'python': sys.version, 'python_base_provenance': str(base), 'distributions': records,
        'file_hash_scope': 'copied distribution source files before ad-hoc signing; final signed application hashes are recorded separately'}


def verified_members(root, required=()):
    root = Path(root)
    if root.is_symlink() or (root / 'PACKAGE-SHA256SUMS').is_symlink():
        raise ValueError('Delivery root/manifest symlink rejected')
    files = {}
    for line in (root / 'PACKAGE-SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or '..' in path.parts or str(path) != name
                or chr(92) in name or name in files):
            raise ValueError('Unsafe or duplicate delivery member')
        if any(root.joinpath(*path.parts[:i]).is_symlink() for i in range(1, len(path.parts) + 1)):
            raise ValueError('Delivery member symlink rejected')
        source = root / name
        if sha(source) != digest: raise ValueError('Model delivery differs: ' + name)
        files[name] = source
    if any(name not in files for name in required): raise ValueError("Required model delivery member missing from manifest")
    return files


def build(delivery, output):
    delivery, output = Path(delivery).absolute(), Path(output).absolute()
    if output.exists(): raise FileExistsError('Choose a NEW output directory')
    files = verified_members(delivery, ["model-config.json", "README.md", "provenance.json"])
    output.mkdir()
    app = output / 'payload/SignBridge Demo.app'
    contents = app / 'Contents'; resources = contents / 'Resources'; macos = contents / 'MacOS'
    resources.mkdir(parents=True); macos.mkdir()
    for name, source in sorted(files.items()):
        if PurePosixPath(name).parts[0] not in ['chrome-extension', 'private-model', 'tools']: continue
        target = resources / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(Path(__file__).with_name('sign-native-model-serve.py'), resources / 'tools/sign-native-model-serve.py')
    config = json.loads(files['model-config.json'].read_text())
    config['runtime'] = 'runtime/bin/python3.10'
    (resources / 'model-config.json').write_text(json.dumps(config, indent=2) + '\n')
    source = Path(__file__).resolve().parents[1] / 'i18n/locales.js'
    program = "const {LOCALES}=await import(process.argv[1]);console.log(JSON.stringify(Object.fromEntries(Object.entries(LOCALES['zh-CN'].modelDemo).filter(([k])=>k.startsWith('native')))));"
    labels = subprocess.check_output(['node', '--input-type=module', '-e', program, source.as_uri()], text=True)
    (resources / 'native-locales.json').write_text(labels)
    record = runtime(resources / 'runtime')
    (resources / 'runtime-provenance.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    source = Path(__file__).with_name('mac-demo-launcher.swift')
    subprocess.run(['/usr/bin/swiftc', '-swift-version', '5', '-O', '-target', 'arm64-apple-macosx13.0',
                    str(source), '-o', str(macos / 'SignBridge Demo'), '-framework', 'AppKit'], check=True)
    info = {'CFBundleName': 'SignBridge Demo', 'CFBundleDisplayName': 'SignBridge 演示版',
            'CFBundleIdentifier': 'org.signbridge.model-demo', 'CFBundleExecutable': 'SignBridge Demo',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '1.0.8', 'CFBundleVersion': '20261108.1',
            'LSMinimumSystemVersion': '13.0', 'LSApplicationCategoryType': 'public.app-category.education',
            'NSHighResolutionCapable': True}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copy2(files['README.md'], resources / 'MODEL-DEMO-README.md')
    shutil.copy2(files['provenance.json'], resources / 'model-provenance.json')
    repository = Path(__file__).resolve().parents[3]
    shutil.copy2(repository / 'LICENSE', resources / 'PROJECT-LICENSE.txt')
    shutil.copy2(repository / 'docs/mac-demo-installer-20261108.md', resources / '安装与使用说明.md')
    result = {'app': str(app), 'platform': 'macOS arm64', 'external_runtime_required': False,
              'source_delivery': str(delivery), 'source_delivery_manifest_sha256': sha(delivery / 'PACKAGE-SHA256SUMS'),
              'runtime_distributions': {d['name']: d['version'] for d in record['distributions']},
              'checkpoint_sha256': config['checkpoint_sha256'], 'research_only': True,
              'training_ready': False, 'model_training_ready': False, 'csl_translation_verified': False}
    (output / 'build.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def fixed_components(records):
    for item in records:
        item['BundleIsRelocatable'] = False
        item['BundleHasStrictIdentifier'] = True
        item['BundleIsVersionChecked'] = True
    return records


def package(output, installer):
    output, installer = Path(output).resolve(), Path(installer).absolute()
    if installer.exists(): raise FileExistsError('Choose a NEW installer file')
    app = output / 'payload/SignBridge Demo.app'
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    components = output / 'components.plist'
    subprocess.run(['/usr/bin/pkgbuild', '--analyze', '--root', str(output / 'payload'), str(components)], check=True)
    components.write_bytes(plistlib.dumps(fixed_components(plistlib.loads(components.read_bytes()))))
    subprocess.run(['/usr/bin/pkgbuild', '--root', str(output / 'payload'), '--component-plist', str(components),
                    '--identifier', 'org.signbridge.model-demo', '--version', '1.0.8',
                    '--install-location', '/Applications', '--ownership', 'recommended', str(installer)], check=True)
    digest = sha(installer)
    Path(str(installer) + '.sha256').write_text(digest + '  ' + installer.name + '\n')
    record = {'installer': str(installer), 'sha256': digest, 'bytes': installer.stat().st_size,
              'install_location': '/Applications/SignBridge Demo.app', 'relocatable_install_target': False,
              'architecture': 'arm64', 'developer_signed_or_notarized': False}
    (output / 'installer.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--installer', type=Path)
    args = parser.parse_args()
    if not args.installer and not args.delivery: parser.error('Specify --delivery or --installer')
    result = package(args.output, args.installer) if args.installer else build(args.delivery, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
