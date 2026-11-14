#!/usr/bin/env python3
"""Build the portable Windows SignBridge Demo from a hash-verified static build.

Output is a folder (not an installer): the user unzips it and double-clicks the
.bat. It ships a PowerShell static server plus the plugin site, so nothing is
installed, no admin rights are needed, and Windows' own tooling is enough.
"""
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

VERSION = '2.1.1'
BUILD_NUMBER = '20261114.1'
LAUNCHER = '启动 SignBridge Demo.bat'
SERVER = 'serve.ps1'
README = 'README-Windows.txt'


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
    if (
        not isinstance(files, dict)
        or not files
        or 'manifest.json' not in files
        or 'demo/model.html' not in files
        or 'BUILD.json' in files
    ):
        raise ValueError('Site BUILD.json is not a plugin build')
    return files


def readme_text():
    return f"""SignBridge 演示版 {VERSION}（Windows 便携版）

怎么用
------
1. 解压整个文件夹到任意位置（不要只解压到压缩包预览里）。
2. 双击「{LAUNCHER}」。
3. 会弹出一个黑色命令行窗口（这是本地服务器，使用期间不要关闭），
   并自动用 Chrome 打开演示页面。没有 Chrome 时会用默认浏览器。
4. 演示结束后直接关闭那个黑色窗口。

包含什么
--------
* 141 条手语词条：104 条有动作（66 条视频拟合动作 + 38 条内置手工姿势），
  其余 37 条只在词表中显示，不会用别的动作冒充。
* 全部离线运行，只监听 127.0.0.1，不联网、不上传任何数据。

限制
----
* 这是演示原型，不是通用手语翻译器。所有动作均为未认证候选，
  未经手语专家审核，不能当作正确手语使用。
* 不含语音识别和语义模型推理。
* 未做 Windows 代码签名，首次运行如被 SmartScreen 拦截，
  请点「更多信息」→「仍要运行」。

安装浏览器插件（可选）
----------------------
演示页面本身无需插件即可使用。如需在任意网页上使用浮层：
1. 打开应用窗口后，把本文件夹里的 site 子文件夹作为「加载已解压的扩展程序」
   在 Chrome 扩展页（chrome://extensions，需打开开发者模式）载入。
2. 弹窗显示 v{VERSION} 才算加载成功。

版本 {VERSION}（{BUILD_NUMBER}）
"""


def build(site, output, tools):
    site, output, tools = Path(site).absolute(), Path(output).absolute(), Path(tools).absolute()
    if output.exists():
        raise FileExistsError('Choose a NEW output directory')
    files = verified_site(site)
    app = output / f'SignBridge-Demo-{VERSION}-Windows'
    site_root = app / 'site'
    site_root.mkdir(parents=True)
    for name in sorted(files):
        target = site_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(site / name, target)
        if sha(target) != files[name]:
            raise ValueError('Copy differs: ' + name)
    shutil.copy2(site / 'BUILD.json', site_root / 'BUILD.json')
    for name in (LAUNCHER, SERVER):
        source = tools / name
        if not source.is_file():
            raise ValueError('Launcher asset is missing: ' + name)
        shutil.copy2(source, app / name)
    (app / README).write_bytes(readme_text().replace('\n', '\r\n').encode('utf-8'))
    archive = output / f'SignBridge-Demo-{VERSION}-Windows.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for path in sorted(app.rglob('*')):
            if path.is_file():
                stream.write(path, (Path(app.name) / path.relative_to(app)).as_posix())
    result = {
        'folder': str(app),
        'archive': str(archive),
        'archive_sha256': sha(archive),
        'archive_bytes': archive.stat().st_size,
        'platform': 'Windows 10/11 x64',
        'version': VERSION,
        'build': BUILD_NUMBER,
        'site_source': str(site),
        'site_build_sha256': sha(site / 'BUILD.json'),
        'site_files': len(files),
        'install_required': False,
        'signature': 'none',
        'research_only': True,
        'training_ready': False,
        'csl_translation_verified': False,
    }
    (output / 'build.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, help='Verified static build directory (contains BUILD.json)')
    parser.add_argument('--output', required=True, help='NEW output directory')
    parser.add_argument('--tools', default=str(Path(__file__).resolve().parent / 'windows-demo'))
    args = parser.parse_args()
    print(json.dumps(build(args.site, args.output, args.tools), ensure_ascii=False, indent=2))
