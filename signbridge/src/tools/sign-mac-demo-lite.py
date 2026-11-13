"""Build the lightweight native SignBridge Demo application from a hash-verified static build."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import subprocess

TOOLS = Path(__file__).resolve().parent
VERSION = '2.0.0'
BUILD_NUMBER = '20261112.1'
REQUIRED_LABELS = ['nativeLiteStartFailed', 'nativeLiteInstallPlugin', 'nativeLiteInstallHelp',
                   'nativeLiteInstallDone', 'nativeLiteOpenExtensions', 'nativeLiteChromeMissing']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''): h.update(data)
    return h.hexdigest()


def verified_site(site):
    site = Path(site).absolute()
    if site.is_symlink() or (site / 'BUILD.json').is_symlink(): raise ValueError('Site root/manifest symlink rejected')
    files = json.loads((site / 'BUILD.json').read_text()).get('files')
    if (not isinstance(files, dict) or not files or 'manifest.json' not in files
            or 'demo/model.html' not in files or 'BUILD.json' in files):
        raise ValueError('Site BUILD.json is not a plugin build')
    for name, digest in files.items():
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or '..' in path.parts or '.' in path.parts
                or chr(92) in name or str(path) != name):
            raise ValueError('Unsafe site member: ' + name)
        if any(site.joinpath(*path.parts[:i]).is_symlink() for i in range(1, len(path.parts) + 1)):
            raise ValueError('Site member symlink rejected: ' + name)
        if sha(site / name) != digest: raise ValueError('Site file differs: ' + name)
    return files


def native_labels():
    source = TOOLS.parent / 'i18n/locales.js'
    program = "const {LOCALES}=await import(process.argv[1]);console.log(JSON.stringify(Object.fromEntries(Object.entries(LOCALES['zh-CN'].modelDemo).filter(([k])=>k.startsWith('native')))));"
    text = subprocess.check_output(['node', '--input-type=module', '-e', program, source.as_uri()], text=True)
    labels = json.loads(text)
    missing = [k for k in REQUIRED_LABELS if not labels.get(k)]
    if missing: raise ValueError('Missing interface labels: ' + ', '.join(missing))
    return text, labels


def build(site, output):
    site, output = Path(site).absolute(), Path(output).absolute()
    if output.exists(): raise FileExistsError('Choose a NEW output directory')
    files = verified_site(site)
    labels_text, labels = native_labels()
    app = output / 'SignBridge Demo.app'
    contents = app / 'Contents'; resources = contents / 'Resources'; macos = contents / 'MacOS'
    output.mkdir()
    macos.mkdir(parents=True); (resources / 'site').mkdir(parents=True)
    # Only manifest-listed files plus BUILD.json are copied, so stray files never ship.
    for name in sorted(files):
        target = resources / 'site' / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(site / name, target)
        if sha(target) != files[name]: raise ValueError('Copy differs: ' + name)
    shutil.copy2(site / 'BUILD.json', resources / 'site/BUILD.json')
    (resources / 'native-locales.json').write_text(labels_text)
    icon = TOOLS / 'assets/AppIcon.icns'
    if not icon.is_file(): raise ValueError('AppIcon.icns is missing')
    shutil.copy2(icon, resources / 'AppIcon.icns')
    subprocess.run(['/usr/bin/swiftc', '-swift-version', '5', '-O', '-parse-as-library', '-target', 'arm64-apple-macosx13.0',
                    str(TOOLS / 'mac-demo-lite.swift'), str(TOOLS / 'mac-plugin-export.swift'),
                    '-o', str(macos / 'SignBridge Demo'), '-framework', 'AppKit', '-framework', 'WebKit'], check=True)
    info = {'CFBundleName': 'SignBridge Demo', 'CFBundleDisplayName': 'SignBridge 演示版',
            'CFBundleIdentifier': 'org.signbridge.demo-lite', 'CFBundleExecutable': 'SignBridge Demo',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': VERSION, 'CFBundleVersion': BUILD_NUMBER,
            'LSMinimumSystemVersion': '13.0', 'LSApplicationCategoryType': 'public.app-category.education',
            'NSHighResolutionCapable': True, 'CFBundleIconFile': 'AppIcon'}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    result = {'app': str(app), 'platform': 'macOS arm64', 'version': VERSION, 'build': BUILD_NUMBER,
              'site_source': str(site), 'site_build_sha256': sha(site / 'BUILD.json'), 'site_files': len(files),
              'executable_sha256': sha(macos / 'SignBridge Demo'), 'native_label_count': len(labels),
              'signature': 'ad-hoc', 'notarized': False, 'model_runtime_included': False,
              'research_only': True, 'training_ready': False, 'csl_translation_verified': False}
    (output / 'build.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + chr(10))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, help='Verified static build directory (contains BUILD.json)')
    parser.add_argument('--output', required=True, help='NEW output directory')
    args = parser.parse_args()
    print(json.dumps(build(args.site, args.output), ensure_ascii=False, indent=2))
