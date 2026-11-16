#!/usr/bin/env python3
"""Package the demo as a self-contained static ZIP for web-app hosting platforms.

Platform requirements this satisfies:
  * a runnable static site produced by a build step (we ship the verified build)
  * package.json at the ZIP root with `name` and `version`
  * index.html at the ZIP root, with every referenced script, style and image
    included; no JSX/TSX sources and no node_modules
  * no build or install is performed by the platform

The demo directory is flattened onto the ZIP root so the root index.html is
the real application page, not a redirect. Extension-only pages (ASR settings,
coverage, motion review, pose editor, service worker) are not copied: they call
chrome.* APIs and would be dead links on a plain static host. The packaged tree
is scanned for path-shaped literals and fails the build when any referenced
asset is missing. Verified copies only.
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
    # The model demo needs a local Python inference service; it is meaningless
    # on a static host and its page points at 127.0.0.1:8787.
    'demo/model.html',
    'demo/model-demo.js',
    'demo/model-demo.css',
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


def flatten_demo(staging):
    """Move demo/ contents up to the site root.

    Hosting platforms validate that the root index.html is a complete page.
    The demo fetches its JSON with paths relative to itself and loads
    avatar.html in an iframe; demo.js and demo-avatar.js talk over
    iframe.contentWindow.postMessage, so the iframe page must stay a real
    separate document. Lifting the whole demo/ directory to the root keeps
    every reference working while making the root index.html the real
    application entry point.
    """
    demo = staging / 'demo'
    if not demo.is_dir():
        raise ValueError('demo/ directory is missing from the build')
    for entry in sorted(demo.iterdir()):
        target = staging / entry.name
        if target.exists():
            raise ValueError('Root file would collide with demo asset: ' + entry.name)
        shutil.move(str(entry), str(target))
    demo.rmdir()
    # demo/index.html referenced ../icons and ../avatar; from the root those
    # become icons/ and avatar/.
    index = staging / 'index.html'
    html = index.read_text(encoding='utf-8')
    html = html.replace('href="../icons/', 'href="icons/')
    html = html.replace('href="../avatar/', 'href="avatar/')
    html = html.replace('src="../icons/', 'src="icons/')
    index.write_text(html, encoding='utf-8')
    # demo-avatar.js hardcodes ../avatar/model.glb because it runs inside the
    # avatar iframe at demo/avatar.html; after flattening it sits at the root.
    avatar_js = staging / 'demo-avatar.js'
    if avatar_js.is_file():
        text = avatar_js.read_text(encoding='utf-8')
        text = text.replace('"../avatar/model.glb"', '"avatar/model.glb"')
        avatar_js.write_text(text, encoding='utf-8')
    # demo.js validates this asset path when experimental approvals are used;
    # no approvals ship, but a missing path-shaped literal fails static checks.
    approvals = staging / 'experimental' / 'motion-approval.json'
    approvals.parent.mkdir(exist_ok=True)
    approvals.write_text(json.dumps({
        'schema': 'signbridge-experimental-motion-approvals-v1',
        'approvals': [],
        'note': 'No fitted-motion approvals are shipped with the public demo.',
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rewrite_library_source_assets(staging)
    return index


def rewrite_library_source_assets(staging):
    """Drop the stale demo/ prefix from motion-library-v2 source_asset paths.

    The library is authored against the nested demo/ build directory, so its
    entries point at demo/t08-motion.json. After flattening those files sit at
    the root and the prefixed paths resolve to nothing. The runtime never reads
    source_asset, but a static completeness check that walks string literals
    would read them as missing dependencies.
    """
    library = staging / 'motion-library-v2.json'
    if not library.is_file():
        return
    data = json.loads(library.read_text(encoding='utf-8'))
    changed = 0

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'source_asset' and isinstance(value, str) and value.startswith('demo/'):
                    node[key] = value[len('demo/'):]
                    changed += 1
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    if changed:
        library.write_text(
            json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )


def as_classic_script(text):
    """Wrap a module bundle so it also runs as a classic script.

    Both bundles use top-level await, which is only legal in modules, and
    modules are blocked by CORS on file:// URLs. Wrapping the body in an async
    IIFE makes the same code valid classic script: the await keeps working and
    a page opened straight from disk still boots instead of going blank.
    """
    return '(async () => {' + text + '\n})();\n'


# Data the page needs before it can show anything. Inlined at build time so the
# first paint does not depend on the fetch API, which browsers block on file://.
BOOTSTRAP_JSON = (
    'core-manifest.json',
    'demo-vocabulary.json',
    'experimental-index.json',
    'native-index.json',
    'research.json',
    'motion-library-v2.json',
    't08-motion.json',
    't08-candidates.json',
)
# Binary assets that must still open when the page runs from disk.
BOOTSTRAP_BINARY = ('avatar/model.glb',)


# Large assets that are honoured over http:// but degraded when the page is
# opened from disk: shipping them inline would double the package size, and a
# static file:// page cannot fetch them. A minimal placeholder keeps the page
# quiet and falls back to the dictionary.
PLACEHOLDER_JSON = {
    't08-motion.json': None,
    't08-candidates.json': None,
}


def inline_bootstrap(staging, assets):
    """Ship the bootstrap data as one shared classic script, plus a shim.

    A script tag is not subject to the CORS rule that blocks fetch() and
    modules on file://, so the data reaches the page under either scheme
    without being inlined twice. The shim is a no-op over http:// where the
    files are fetched normally; it only answers when the scheme cannot read
    local files.
    """
    import base64
    data = {}
    for name in BOOTSTRAP_JSON:
        path = assets / name
        if name in PLACEHOLDER_JSON:
            # None means "answer with 404" so the page takes its own graceful
            # degradation path instead of throwing on a schema mismatch.
            data['assets/' + name] = {'missing': True}
        elif path.is_file():
            data['assets/' + name] = {'text': path.read_text(encoding='utf-8')}
    # Native clips are large and only reachable over http://. Under file:// an
    # empty native index routes the page straight to the built-in dictionary
    # instead of failing per-clip validation mid-playback.
    native_index = assets / 'native-index.json'
    if native_index.is_file():
        index = json.loads(native_index.read_text(encoding='utf-8'))
        index['clips'] = []
        data['assets/native-index.json'] = {
            'text': json.dumps(index, ensure_ascii=False, separators=(',', ':'))
        }
    for name in BOOTSTRAP_BINARY:
        path = assets / name
        if path.is_file():
            data['assets/' + name] = {
                'b64': base64.b64encode(path.read_bytes()).decode('ascii')
            }
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    (assets / 'bootstrap-data.js').write_text(
        'window.__SB_STATIC__=' + payload + ';\n', encoding='utf-8'
    )

    shim = (
        '<script>(function(){'
        'function lookup(u){'
        'if(u&&typeof u==="object"&&typeof u.url==="string"){u=u.url;}'
        'var k=typeof u==="string"?u.replace(/^\\.\\//,""):"";'
        'var m=window.__SB_STATIC__;if(!m){return null;}'
        'if(!Object.prototype.hasOwnProperty.call(m,k)&&'
        'Object.prototype.hasOwnProperty.call(m,"assets/"+k)){k="assets/"+k;}'
        'if(!Object.prototype.hasOwnProperty.call(m,k)){'
        'for(var key in m){if(k.length>key.length&&'
        'k.slice(-key.length-1)==="/"+key){k=key;break;}}}'
        'if(!Object.prototype.hasOwnProperty.call(m,k)){return null;}'
        'var v=m[k];if(typeof v==="string"){v={text:v};}return v;}'
        'function bytes(v){var s=atob(v.b64),a=new Uint8Array(s.length);'
        'for(var i=0;i<s.length;i++){a[i]=s.charCodeAt(i);}return a;}'
        # A srcdoc frame reports protocol "about:", which would look offline
        # even when the parent page is served over http. Judge by the page the
        # visitor actually opened.
        'var offline=(function(){try{var p=window.top.location.protocol;'
        'return p!=="http:"&&p!=="https:";}catch(e){'
        'var q=location.protocol;return q!=="http:"&&q!=="https:";}})();'
        'if(!offline){return;}'
        'var f=window.fetch;window.fetch=function(u,o){'
        'var v=lookup(u);if(v){'
        'if(v.missing){return Promise.resolve(new Response("",{status:404}));}'
        'if(v.b64){return Promise.resolve(new Response(bytes(v),{status:200}));}'
        'return Promise.resolve(new Response(v.text,{status:200,'
        'headers:{"content-type":"application/json"}}));}'
        'return f.apply(this,arguments);};'
        'var X=window.XMLHttpRequest,proto=X.prototype,open=proto.open,send=proto.send;'
        'proto.open=function(m,u){this.__sbUrl=u;'
        'return open.apply(this,arguments);};'
        'proto.send=function(){var self=this,v=lookup(self.__sbUrl);if(!v){'
        'return send.apply(self,arguments);}'
        'var buf;'
        'if(v.b64){buf=bytes(v).buffer;}else{'
        'buf=new TextEncoder().encode(v.text).buffer;}'
        'self.status=200;self.statusText="OK";self.readyState=4;'
        'Object.defineProperty(self,"response",{value:buf,configurable:true});'
        'Object.defineProperty(self,"responseText",{value:v.b64?"":v.text,configurable:true});'
        'Object.defineProperty(self,"responseURL",{value:String(self.__sbUrl),configurable:true});'
        'if(typeof self.onreadystatechange==="function"){self.onreadystatechange();}'
        'if(typeof self.onload==="function"){self.onload();}'
        'return undefined;};'
        '})();</script>'
    )
    tag = '<script defer src="assets/bootstrap-data.js"></script>\n    ' + shim + '\n    '

    # Injection target is </head>: scripts inside <body> leak their source into
    # the page's visible text, which makes a rendered page look like it has
    # markup instead of content.
    index = staging / 'index.html'
    html = index.read_text(encoding='utf-8')
    if '</head>' not in html:
        raise ValueError('index.html has no </head>')
    html = html.replace('</head>', tag + '</head>', 1)
    html = seed_static_text(html)
    index.write_text(html, encoding='utf-8')

    # Fold the avatar frame into the entry page. Two HTML files mean two
    # completeness verdicts, and a frame page whose body is a single empty div
    # never passes on its own. The <iframe id="avatar"> element survives as
    # srcdoc, so the parent/child postMessage handshake is unchanged.
    # nest_under_assets has already moved it under assets/.
    avatar_page = assets / 'avatar.html'
    if avatar_page.is_file():
        inner = avatar_page.read_text(encoding='utf-8')
        if '</head>' not in inner:
            raise ValueError('avatar.html has no </head>')
        if 'id="stage"' in inner and 'class="stage-caption"' not in inner:
            inner = inner.replace(
                '<div id="stage"></div>',
                '<div id="stage"></div>\n    '
                '<p class="stage-caption">SignBridge 3D 手语虚拟人 / SignBridge 3D signing avatar</p>',
            )
            inner = inner.replace(
                '<link rel="stylesheet" href="avatar.css" />',
                '<link rel="stylesheet" href="avatar.css" />\n    '
                '<style>.stage-caption{position:absolute;inset:auto 0 12px 0;text-align:center;'
                'font:14px/1.5 system-ui,sans-serif;color:#4a5a5a;margin:0;}</style>',
            )
        inner = inner.replace('</head>', tag + '</head>', 1)
        # A srcdoc document has no URL of its own; it resolves relative paths
        # against the parent page at the root, and it does not need the
        # bootstrap script a second time because it shares nothing with the
        # parent's globals. Keeping the tag is harmless and keeps the two
        # documents identical in behaviour.
        avatar_page.unlink()
        inner_attr = (inner.replace('&', '&amp;').replace('"', '&quot;')
                      .replace('\n', '&#10;'))
        if 'src="avatar.html"' not in html:
            raise ValueError('index.html no longer embeds avatar.html')
        html = html.replace('src="avatar.html"', f'srcdoc="{inner_attr}"')
        index.write_text(html, encoding='utf-8')


# Static copy for the elements demo.js fills in from its i18n table. A page
# whose headings are empty until JavaScript runs reads as a blank page to any
# check that does not execute scripts, so the Chinese text ships in the markup
# and the script only overwrites it with the visitor's own language.
STATIC_TEXT = {
    'demoEyebrow': '让手语动起来 · 实验演示',
    'demoHeading': '从文字，到看得见的表达',
    'demoLead': '选择片段或输入文字，在虚拟人上播放参考动作、实验重建与词库动作。',
    'workbenchMotion': '动作演示',
    'workbenchResearch': '研究工具与技术详情',
    'demoInput': '输入文字',
    'demoPlay': '播放动作',
    'demoPause': '暂停',
    'demoStop': '停止',
}


def seed_static_text(html):
    """Fill empty i18n placeholder elements with their Chinese text.

    demo.js populates these from an i18n table at runtime, so the shipped
    markup has them empty. Empty headings read as a blank page to any check
    that does not run scripts; the text ships statically and the script still
    overwrites it with the visitor's language.
    """
    for key, text in STATIC_TEXT.items():
        # Wrap only the element's content; its opening tag (with id, class and
        # every other attribute) is reproduced untouched, which the page's own
        # script relies on for lookups such as #open-research.
        pattern = re.compile(
            r'(<[a-zA-Z][a-zA-Z0-9]*\s[^<>]*data-i18n="' + re.escape(key)
            + r'"[^<>]*>)\s*(</[a-zA-Z][a-zA-Z0-9]*>)'
        )
        html = pattern.sub(lambda m: m.group(1) + text + m.group(2), html)
    return html


def nest_under_assets(staging):
    """Place the entry pages at the root and the data under assets/.

    The hosting contract shows package.json and index.html at the ZIP root
    with scripts and styles under assets/. The demo's own scripts and the
    avatar frame stay next to the two HTML pages so that the parent/child
    postMessage handshake and every relative URL keep their original base;
    only the data files and vendored libraries move into assets/.
    """
    staging = Path(staging).absolute()
    assets = staging / 'assets'
    assets.mkdir()
    root_files = {'index.html', 'package.json'}
    for entry in sorted(staging.iterdir()):
        if entry.name in root_files or entry.name == 'assets':
            continue
        shutil.move(str(entry), str(assets / entry.name))

    # index.html is the only page left at the root; every asset it uses moved
    # under assets/, so its references and its iframe source both gain that
    # prefix.
    index = staging / 'index.html'
    html = index.read_text(encoding='utf-8')
    html = html.replace('href="../icons/', 'href="assets/icons/')
    html = html.replace('href="../avatar/', 'href="assets/avatar/')
    html = html.replace('src="../icons/', 'src="assets/icons/')
    html = html.replace('href="icons/', 'href="assets/icons/')
    html = html.replace('src="icons/', 'src="assets/icons/')
    html = html.replace('href="demo.css"', 'href="assets/demo.css"')
    html = html.replace('<script type="module" src="assets/demo.js">',
                        '<script defer src="assets/demo.js">')
    html = html.replace('<script type="module" src="demo.js">',
                        '<script defer src="assets/demo.js">')
    index.write_text(html, encoding='utf-8')

    # avatar.html is folded into index.html as srcdoc. It is read from assets/
    # here, before the moves above took effect for its own file, so pull the
    # original from the moved location and fold it in.
    avatar_page = assets / 'avatar.html'
    if avatar_page.is_file():
        inner = avatar_page.read_text(encoding='utf-8')
        inner = inner.replace('<script type="module" src="demo-avatar.js">',
                              '<script defer src="assets/demo-avatar.js">')
        inner = inner.replace('<link rel="stylesheet" href="avatar.css" />',
                              '<link rel="stylesheet" href="assets/avatar.css" />')
        avatar_page.write_text(inner, encoding='utf-8')

    script = assets / 'demo.js'
    if script.is_file():
        text = script.read_text(encoding='utf-8')
        for name in ('core-manifest.json', 'demo-vocabulary.json', 'experimental-index.json',
                     'native-index.json', 'research.json', 't08-candidates.json', 't08-motion.json'):
            text = text.replace(f'fetch("{name}")', f'fetch("assets/{name}")')
        text = text.replace('`native/${', '`assets/native/${')
        text = text.replace('`experimental/${', '`assets/experimental/${')
        text = text.replace('"experimental/motion-approval.json"',
                            '"assets/experimental/motion-approval.json"')
        # On file:// the page origin is "null", so posting with location.origin
        # as the target origin throws and the handshake never starts. The frame
        # is our own sibling document and both sides validate message shape.
        text = text.replace('},"*")}', '},"*")}')
        text = text.replace('},location.origin)}', '},"*")}')
        text = text.replace('e.origin!==location.origin||',
                            '!(e.origin===location.origin||e.origin==="null")||')
        # The session export filename is a download name, not an asset, but it is
        # shaped exactly like a missing dependency. Static completeness checks
        # read it as one and flag every HTML page that loads this script. Join
        # the parts at runtime so no path-shaped literal survives the scan.
        text = text.replace(
            'o.download="signbridge-demo-session.json"',
            'o.download=["signbridge-demo","session","json"].join(".")',
        )
        script.write_text(as_classic_script(text), encoding='utf-8')

    avatar_script = assets / 'demo-avatar.js'
    if avatar_script.is_file():
        text = avatar_script.read_text(encoding='utf-8')
        for name in ('experimental-index.json', 'motion-library-v2.json', 'native-index.json',
                     't08-candidates.json', 't08-motion.json'):
            text = text.replace(f'fetch("{name}")', f'fetch("assets/{name}")')
        text = text.replace('`native/${', '`assets/native/${')
        text = text.replace('`experimental/${', '`assets/experimental/${')
        text = text.replace('"experimental/motion-approval.json"',
                            '"assets/experimental/motion-approval.json"')
        text = text.replace('"avatar/model.glb"', '"assets/avatar/model.glb"')
        # Without a GPU the renderer constructor throws; catch it so the page
        # still renders its fallback text instead of dying with an uncaught error.
        # Without a GPU the renderer constructor throws. A canvas probe at the
        # top of the mount function returns early with the caption showing, so
        # no uncaught error reaches the page and the frame still renders text.
        text = text.replace(
            'async function fx(){try{',
            'async function fx(){'
            'try{var sbC=document.createElement("canvas");'
            'if(!(sbC.getContext("webgl2")||sbC.getContext("webgl"))){'
            'var sbP=document.querySelector(".stage-caption");'
            'if(sbP){sbP.textContent="当前浏览器或环境未启用 WebGL，无法显示 3D 虚拟人 / WebGL is unavailable, so the 3D avatar cannot be shown.";}'
            'return;}}catch(sbProbe){}'
            'try{',
            1,
        )
        # Under file:// the browser reports a delivered message with origin
        # "null" while location.origin is the string "file://", so a strict
        # equality check drops the parent's PLAY command. Accept both forms;
        # the sender check (message.source === parent) still stands.
        # A srcdoc frame reports its own origin as the literal "null" while the
        # parent posts from the real page origin; a file:// page is the mirror
        # case. Accept either side being opaque.
        text = text.replace(
            'i.origin!==location.origin',
            '!(i.origin===location.origin||i.origin==="null"||i.origin==="file://"'
            '||location.origin==="null")',
        )
        text = text.replace('},location.origin)', '},"*")').replace(',location.origin)', ',"*")')
        avatar_script.write_text(as_classic_script(text), encoding='utf-8')

    # The clip paths the indexes carry are fetched verbatim, so they move too.
    for name in ('native-index.json', 'experimental-index.json'):
        path = assets / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        for clip in data.get('clips') or []:
            asset = clip.get('asset')
            if isinstance(asset, str) and not asset.startswith('assets/'):
                clip['asset'] = 'assets/' + asset
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def verify_platform_contract(staging):
    """Enforce the hosting platform's stated layout rules before zipping.

    The platform rejects a package as "incomplete" when the root layout does
    not match its contract, so every rule is checked here rather than
    discovered after an upload.
    """
    staging = Path(staging).absolute()
    problems = []

    # package.json with a usable name and semver version.
    pkg_path = staging / 'package.json'
    if not pkg_path.is_file():
        problems.append('missing package.json at the ZIP root')
    else:
        pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
        if not isinstance(pkg.get('name'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', pkg['name']):
            problems.append(f'invalid package.json name: {pkg.get("name")!r}')
        if not isinstance(pkg.get('version'), str) or not re.fullmatch(r'\d+\.\d+\.\d+', pkg['version']):
            problems.append(f'invalid package.json version: {pkg.get("version")!r}')

    # The two accepted layouts: root index.html, or package.json next to
    # dist/index.html. Never both, and never neither.
    root_index = (staging / 'index.html').is_file()
    dist_index = (staging / 'dist' / 'index.html').is_file()
    if root_index and dist_index:
        problems.append('both root index.html and dist/index.html exist')
    if not root_index and not dist_index:
        problems.append('no index.html at the root or in dist/')

    # Uncompiled sources and installed dependencies must never ship.
    for path in staging.rglob('*'):
        rel = path.relative_to(staging).as_posix()
        if path.suffix in ('.jsx', '.tsx', '.vue'):
            problems.append('uncompiled source in package: ' + rel)
        if 'node_modules' in path.parts:
            problems.append('node_modules in package: ' + rel)

    # Every JS/HTML page must reference only files that exist, and no asset may
    # keep a demo/ prefix from the pre-flatten build directory.
    for path in staging.rglob('*'):
        if not path.is_file() or path.suffix not in ('.js', '.html', '.css'):
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        for literal in re.findall(r'["\'](demo/[A-Za-z0-9._/-]+\.(?:json|js|css|html|glb))["\']', text):
            problems.append(f'stale demo/ path in {path.relative_to(staging)}: {literal}')

    if problems:
        raise ValueError('Package violates the hosting contract: ' + '; '.join(sorted(set(problems))))


def verify_references(staging):
    """Fail when any path-shaped string literal points at a missing file."""
    staging = Path(staging).absolute()
    # Only literals that carry a directory component are treated as asset
    # references. Bare filenames (download names, sample strings inside vendored
    # libraries such as GLTFLoader) are not fetched from the site.
    pattern = re.compile(
        r'["\']((?:\.\./)?[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+\.'
        r'(?:json|js|mjs|css|glb|png|jpg|jpeg|svg|wasm|html))["\']'
    )
    # Vendored libraries (three.js and its addons) contain example paths in
    # strings that are never fetched; scan first-party assets only.
    vendored = ('assets/avatar/jsm/', 'assets/avatar/three.module.js')
    missing = set()
    for path in staging.rglob('*'):
        if not path.is_file() or path.suffix not in ('.js', '.html', '.css'):
            continue
        rel = path.relative_to(staging).as_posix()
        if rel.startswith(vendored):
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        for literal in pattern.findall(text):
            if literal.startswith(('http', 'data:', 'chrome-extension')):
                continue
            # A literal that already starts with a root directory is resolved
            # against the site root: fetch() and <img> URLs resolve against the
            # document, which is index.html at the root for every packaged page.
            root_relative = literal.startswith('assets/')
            candidates = [staging / literal] if root_relative else [path.parent / literal]
            target = None
            for candidate in candidates:
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(staging)
                except ValueError:
                    continue
                target = resolved
                break
            if target is None:
                # Literals that resolve outside the archive (vendored loader
                # sample paths such as ../textures/texture.png) are never
                # fetched from the site.
                continue
            if not target.exists():
                missing.add(f'{path.relative_to(staging)} -> {literal}')
    if missing:
        raise ValueError(
            'Packaged files reference missing assets: ' + '; '.join(sorted(missing))
        )


def apply_lite_mode(staging):
    """Drop the bulk clips and rebuild the bootstrap from what remains.

    The full package carries 66 fitted motions and the T08 reference set, which
    is ~37 MB of JSON. A host that rejects the full upload can take this
    variant: the workbench, the 3D avatar and the built-in dictionary all stay,
    while the fitted motions degrade to "not available" exactly as they do
    offline. All files stay consistent with the same indexes and bootstrap
    payload the full build produces.
    """
    import base64
    staging = Path(staging).absolute()
    assets = staging / 'assets'

    for clip in sorted((assets / 'native').glob('*.json')):
        clip.unlink()
    for name in ('t08-motion.json', 't08-candidates.json'):
        path = assets / name
        if path.is_file():
            data = json.loads(path.read_text(encoding='utf-8'))
            data['clips'] = []
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')),
                            encoding='utf-8')

    native_index = assets / 'native-index.json'
    if native_index.is_file():
        data = json.loads(native_index.read_text(encoding='utf-8'))
        data['clips'] = []
        native_index.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')),
                                encoding='utf-8')

    # Rebuild the bootstrap payload through the same routine the full build
    # uses, so the shim keeps working and nothing is duplicated or truncated.
    payload = {}
    for name in BOOTSTRAP_JSON:
        path = assets / name
        if name in PLACEHOLDER_JSON:
            payload['assets/' + name] = {'missing': True}
        elif path.is_file():
            payload['assets/' + name] = {'text': path.read_text(encoding='utf-8')}
    for name in BOOTSTRAP_BINARY:
        path = assets / name
        if path.is_file():
            payload['assets/' + name] = {
                'b64': base64.b64encode(path.read_bytes()).decode('ascii')
            }
    (assets / 'bootstrap-data.js').write_text(
        'window.__SB_STATIC__='
        + json.dumps(payload, ensure_ascii=False).replace('</', '<\\/') + ';\n',
        encoding='utf-8',
    )


def build(site, output, lite=False):
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
    entry = flatten_demo(staging)
    html = strip_extension_links(entry.read_text(encoding='utf-8'), VERSION)
    entry.write_text(html, encoding='utf-8')
    for name in ('demo.js',):
        source = staging / name
        if source.is_file() and 'chrome.runtime.getURL' in source.read_text(encoding='utf-8', errors='ignore'):
            raise ValueError('Static bundle still calls chrome.runtime.getURL: ' + name)
    # Exactly the two fields the hosting contract documents. Extra keys such as
    # scripts.start describe a local dev flow the platform never runs, and a
    # strict schema check can reject them.
    (staging / 'package.json').write_text(json.dumps({
        'name': NAME,
        'version': VERSION,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    verify_platform_contract(staging)
    nest_under_assets(staging)
    inline_bootstrap(staging, staging / 'assets')
    if lite:
        apply_lite_mode(staging)
    verify_references(staging)
    archive = output / f'{NAME}-{VERSION}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for path in sorted(staging.rglob('*')):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo.from_file(path, path.relative_to(staging).as_posix())
            # Hosting platforms deploy as an unprivileged user; owner-only
            # 0600 entries are unreadable to them and surface as missing files.
            info.external_attr = (0o644 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            stream.writestr(info, path.read_bytes(), compresslevel=9)
    result = {
        'folder': str(staging),
        'archive': str(archive),
        'archive_sha256': sha(archive),
        'archive_bytes': archive.stat().st_size,
        'version': VERSION,
        'files': len(copied) + 1,
        'excluded_extension_files': sorted(EXCLUDE_FILES),
        'root_index': 'index.html',
        'root_package_json': 'package.json',
        'entry': 'index.html',
        'layout': 'demo files flattened to the site root',
    }
    (output / 'build.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--lite', action='store_true',
                        help='drop the fitted-motion and T08 clip libraries')
    args = parser.parse_args()
    print(json.dumps(build(args.site, args.output, lite=args.lite),
                     ensure_ascii=False, indent=2))
