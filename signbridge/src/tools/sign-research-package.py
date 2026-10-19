#!/usr/bin/env python3
"""Build allowlisted public research downloads; never copy private data roots."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile

KIT_NAME = 'signbridge-csl-research-kit-20261018.zip'
CLIENT_NAME = 'signbridge-research-client-0.1.0.zip'
SOURCE_FILES = {
    'signbridge/src/tools/sign-csl-learned.py': 'src/tools/sign-csl-learned.py',
    'signbridge/src/tools/sign-private-serve.py': 'src/tools/sign-private-serve.py',
    'signbridge/tests/sign-csl-learned.test.py': 'tests/sign-csl-learned.test.py',
    'signbridge/tests/sign-private-serve.test.py': 'tests/sign-private-serve.test.py',
}
CLIENT_FILES = {'BUILD.json', 'manifest.json', 'worker.js', 'private/index.html', 'private/client.js', 'private/client.css'}
README = '''# SignBridge 中文语义研究 Demo

研究和演示版，2026-10-18。训练的是有限中文语义角色，不是中国手语翻译或手语视频识别。

## 快速运行

需要 Python 3.10–3.12（已在 Python 3.12 / NumPy 1.26.4 验证）。无需 GPU 或 Node.js。
解压后在本目录打开终端。macOS / Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/tools/sign-csl-learned.py --output runs/roles-v1 --examples 8000 --epochs 14 --seed 17
.venv/bin/python src/tools/sign-private-serve.py --model runs/roles-v1 --client client --port 8770
```

Windows：第一步使用 `py -3.12 -m venv .venv`，后续将 `.venv/bin/python` 替换为 `.venv\\Scripts\\python.exe`。无需激活虚拟环境。

服务终端会显示本机页面地址和本次会话口令。打开页面并输入口令，即可测试“我帮你”“你帮我”“今天我去学校”“你去吗”。复杂／未知输入会拒绝，不强行生成动作。训练输出必须使用新目录；重试时请换 `roles-v2` 等新目录。

## Chrome 客户端（可选）

同一页面也可作为独立扩展使用。打开 chrome://extensions，开启开发者模式，选择“加载已解压的扩展程序”，选中 `client` 目录。点击扩展图标后打开语义页面。若从插件跨来源连接，重启服务并附加：

```sh
.venv/bin/python src/tools/sign-private-serve.py --model runs/roles-v1 --client client --port 8770 --allow-extension chrome-extension://YOUR_32_CHARACTER_EXTENSION_ID
```

用 Chrome 显示的准确32位扩展 ID 替换占位内容；口令仍从本次终端获取。服务只绑定127.0.0.1，不接受通配 Origin。直接访问本机网页无需此参数。

## 复现检查

```sh
.venv/bin/python tests/sign-csl-learned.test.py
.venv/bin/python tests/sign-private-serve.test.py
```

模型使用 NumPy 平均结构感知机和 BIO 字符角色标签，实际更新权重。训练、验证、测试按施事／谓词／对象组合分组隔离，挑战文本从所有生成集合排除。学习范围由训练数据支持表限制，超出范围则拒绝。

## 已知范围

- 训练和评估均为 `assistant_synthetic_chinese` 合成中文监督；32种谓词表面形式和11类角色。不代表32个已验证手语词。
- 参考运行：训练6355、验证881、测试764；验证和测试角色完整匹配，34条同开发者构造挑战通过（17条拒绝）。模板简单、评估有偏差，这不是现实语言或中国手语准确率。
- 无人类中国手语批准，无已确认词级动作边界、镜像、手语者、空间指代或非手部表达；不自动播放词库、整句动作或生成手语。
- 该包不包含预训练权重、六批视频、原始动作、完整词库或原始评估语料。首次运行从代码生成合成样本并在自己的电脑训练。
- 服务是本机研究用途，不是已部署的公网多用户推理服务。随机口令仅终端显示，重启失效，不写文件、URL或浏览器存储；单进程共享60次／分钟，最多12连接／2并发推理。
- 代码与客户端作为临时公开研究 Demo 分发，可被下载和复制；不保证防提取。原始授权素材和后续私有资产不由此包分发。

## 文件核验

`MANIFEST.json` 记录源码版本、范围与每个内容文件的 SHA256；`SHA256SUMS` 包含该元数据。使用系统校验工具核对，或用 Python hashlib 逐文件核验。不要把自己的会话口令、原视频或模型目录放进再次发布的包。

代码许可见 LICENSE；外部素材不随包提供。所有模型标注 `csl_translation_trained=false`、`human_approved=false`、`model_training_ready=false`。
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_safe(root, name):
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Unsafe or missing publication input: ' + name)
    return path.read_bytes()


def archive(path, files):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None or set(z.namelist()) != set(files):
            raise ValueError('Archive roundtrip failed')
        for name, data in files.items():
            if z.read(name) != data:
                raise ValueError('Archive byte mismatch: ' + name)


def package(repo, client, output, commit):
    repo, client, output = Path(repo).resolve(), Path(client).resolve(), Path(output).resolve()
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A full source commit SHA is required')
    if output.exists():
        raise FileExistsError(output)
    actual = {p.relative_to(client).as_posix() for p in client.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != CLIENT_FILES:
        raise ValueError('Client must contain only the six allowlisted files')
    client_files = {name: read_safe(client, name) for name in CLIENT_FILES}
    if json.loads(client_files['manifest.json']).get('version') != '0.1.0':
        raise ValueError('This frozen 20261018 packager requires client 0.1.0; use a new release version for later clients')
    build = json.loads(client_files['BUILD.json'])
    if (build.get('schema') != 'signbridge-private-client-build-v1' or build.get('private_assets_included') is not False
            or build.get('csl_translation_trained') is not False or set(build.get('files', {})) != CLIENT_FILES - {'BUILD.json'}):
        raise ValueError('Invalid client build contract')
    if any(sha(client_files[name]) != expected for name, expected in build['files'].items()):
        raise ValueError('Client digest mismatch')
    files = {target: read_safe(repo, source) for source, target in SOURCE_FILES.items()}
    files.update({'client/' + name: data for name, data in client_files.items()})
    files['LICENSE'] = read_safe(repo, 'LICENSE')
    files['README.md'] = README.encode('utf-8')
    files['requirements.txt'] = b'numpy==1.26.4\n'
    manifest = {'schema': 'signbridge-public-research-kit-v1', 'published_for': 'research_and_demo',
                'source_commit': commit, 'code_license': 'MIT', 'training_supervision': 'assistant_synthetic_chinese',
                'weights_included': False, 'original_video_included': False, 'full_motion_library_included': False,
                'csl_translation_trained': False, 'human_approved': False,
                'files': {name: sha(data) for name, data in sorted(files.items())}}
    files['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    files['SHA256SUMS'] = ''.join(f'{sha(data)}  {name}\n' for name, data in sorted(files.items())).encode()
    output.mkdir(parents=True, exist_ok=False)
    archive(output / KIT_NAME, files)
    archive(output / CLIENT_NAME, {**client_files, 'LICENSE': files['LICENSE']})
    report = {'schema': 'signbridge-public-research-release-v1', 'source_commit': commit,
              'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'bounded Chinese semantic role research, not CSL translation',
              'artifacts': {name: {'bytes': (output / name).stat().st_size, 'sha256': sha((output / name).read_bytes())}
                            for name in [KIT_NAME, CLIENT_NAME]},
              'original_video_included': False, 'weights_included': False, 'full_motion_library_included': False}
    (output / 'research-release.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (output / 'research-downloads.SHA256SUMS').write_text(''.join(f'{entry["sha256"]}  {name}\n' for name, entry in report['artifacts'].items()))
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--client', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--source-commit', required=True)
    args = ap.parse_args()
    print(json.dumps(package(args.repo, args.client, args.output, args.source_commit), ensure_ascii=False))
