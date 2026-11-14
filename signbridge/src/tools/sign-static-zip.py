#!/usr/bin/env python3
"""Package the demo as a self-contained static ZIP for web-app hosting platforms.

Platform requirements this satisfies:
  * a runnable static site produced by a build step (we ship the verified build)
  * package.json at the ZIP root with `name` and `version`
  * index.html at the ZIP root, with every referenced script, style and image
    included; no JSX/TSX sources and no node_modules
  * no build or install is performed by the platform

The demo entry point is the nested demo/index.html, so the root index.html is a
small redirect page. Extension-only pages (ASR settings, coverage, motion review,
pose editor, service worker) are not copied: they call chrome.* APIs and would
be dead links on a plain static host. Verified copies only.
"""
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

NAME = 'signbridge-demo'
VERSION = '2.1.2'

# Directories shipped in the ZIP, copied from the verified build manifest.
INCLUDE_PREFIXES = ('demo/', 'avatar/', 'icons/')
# Extension-only assets inside those directories, excluded from a static host.
EXCLUDE_FILES = {
    'avatar/avatar-frame.html',
    'avatar/iframe-bundle.js',
    'avatar/page-agent.js',
    'avatar/pose-editor.html',
    'avatar/pose-editor-bundle.js',
    'avatar/record-mode.html',
    'avatar/record-bundle.js',
    'avatar/help.html',
    'avatar/help.js',
    'avatar/motion-library.css',
    'avatar/t08-index.json',
}

ROOT_INDEX = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>SignBridge Demo __VERSION__</title>
    <meta http-equiv="refresh" content="0; url=demo/index.html" />
    <style>
      body { font-family: system-ui, sans-serif; margin: 0; min-height: 100vh;
        display: grid; place-items: center; background: #f6f5f0; color: #26363a; }
      a { color: #0b7285; font-size: 18px; }
      p { font-size: 15px; color: #4a5a5a; }
    </style>
  </head>
  <body>
    <main>
      <p>SignBridge 演示版 __VERSION__</p>
      <a href="demo/index.html">进入演示页面 (Open the demo)</a>
    </main>
  </body>
</html>
"""


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verified_site(site):
    site = Path(site).absolute()
    if site.is_symlink() or (site / 'BUILD.json').is_symlink():
        raise ValueError('Site root/manifest symlink rejected')
    manifest = json.loads((site / 'BUILD.json').read_text(encoding='utf-8'))
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Site BUILD.json has no file list')
    for name in sorted(files):
        path = site / name
        if not path.is_file() or sha(path) != files[name]:
            raise ValueError('Site file differs from its manifest: ' + name)
    return files


def strip_extension_links(html, version):
    """Remove the hidden extension-only tool panel and its data-i18n wrapper.

    The panel is hidden outside the extension anyway; dropping it keeps a
    static host free of dead links without touching the workbench itself.
    """
    start = html.find('<div id="extension-tools" hidden>')
    if start >= 0:
        depth = 0
        i = start
        while i < len(html):
            nxt_open = html.find('<div', i + 1)
            nxt_close = html.find('</div>', i + 1)
            if nxt_close < 0:
                break
            if 0 <= nxt_open < nxt_close:
                depth += 1
                i = nxt_open
                continue
            if depth == 0:
                html = html[:start] + html[nxt_close + 6:]
                break
            depth -= 1
            i = nxt_close
    return html


def build(site, output):
    site, output = Path(site).absolute(), Path(output).absolute()
    if output.exists():
        raise FileExistsError('Choose a NEW output directory')
    files = verified_site(site)
    staging = output / NAME
    staging.mkdir(parents=True)
    copied = []
    for name in sorted(files):
        if not name.startswith(INCLUDE_PREFIXES) or name in EXCLUDE_FILES:
            continue
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(site / name, target)
        if sha(target) != files[name]:
            raise ValueError('Copy differs: ' + name)
        copied.append(name)
    entry = staging / 'demo/index.html'
    html = entry.read_text(encoding='utf-8')
    entry.write_text(strip_extension_links(html, VERSION), encoding='utf-8')
    for name in ('demo/demo.js',):
        source = staging / name
        if source.is_file() and 'chrome.runtime.getURL' in source.read_text(encoding='utf-8', errors='ignore'):
            raise ValueError('Static bundle still calls chrome.runtime.getURL: ' + name)
    (staging / 'index.html').write_text(ROOT_INDEX.replace('__VERSION__', VERSION), encoding='utf-8')
    (staging / 'package.json').write_text(json.dumps({
        'name': NAME,
        'version': VERSION,
        'description': 'SignBridge 中国手语 3D 演示（静态站点）',
        'private': True,
        'scripts': {'start': 'npx serve .'},
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    archive = output / f'{NAME}-{VERSION}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                stream.write(path, path.relative_to(staging).as_posix())
    result = {
        'folder': str(staging),
        'archive': str(archive),
        'archive_sha256': sha(archive),
        'archive_bytes': archive.stat().st_size,
        'version': VERSION,
        'files': len(copied) + 2,
        'excluded_extension_files': sorted(EXCLUDE_FILES),
        'root_index': 'index.html',
        'root_package_json': 'package.json',
        'entry': 'demo/index.html',
    }
    (output / 'build.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.site, args.output), ensure_ascii=False, indent=2))
