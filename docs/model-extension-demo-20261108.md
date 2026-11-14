# 插件内模型演示 Demo · 2026-11-08

这份本地交付把有限中文语义模型演示接入 Chrome MV3 插件。插件弹窗新增 **模型演示 Demo**，打开插件内的 `demo/model.html`；人物和动作从插件自身资源加载，模型由本机 Python 服务推理。原动作工作台入口保留。

## 安装与展示

1. 解压桌面“手语”目录中的新版插件模型 Demo 包。
2. 打开 Chrome 扩展管理页，启用开发者模式，选择“加载已解压的扩展程序”，加载包内 **`chrome-extension/`** 文件夹。此文件夹直接包含 `manifest.json`；不要选择整个交付目录，也不要选择 `private-model/`。
3. 双击同一交付目录的 **`启动模型Demo.command`**，保持终端开启。
4. 点击插件图标 → **模型演示 Demo** → **授权并连接**，允许访问本机地址。默认服务地址是 `http://127.0.0.1:8787`。
5. 展示“我／你／他／我们／你们／他们”、“我帮你／你帮我”、“我不想去／我想不去”的角色与范围区别。在下方独立动作卡片中演示真实视频拟合动作、暂停、继续、停止、速度和视角切换。

这份包针对当前 Mac。它复用同级 `SignBridge-中文迁移实验-20261106-98r014yn/runtime/bin/python`，权重与编码器快照已经放入交付包的 `private-model/`。它不需要 GPU，不会自动下载模型。移动交付目录时，保留上述运行时目录的相对位置。

## 本次实际接入范围

- 使用冻结 BERT 编码器与已训练语义头；检查点 SHA-256：`c6997e70392afac6748999e2e311131e7c2d0928b06da6ee97b184ef13e8af2d`。
- 语义功能仍为有限中文研究演示。支持集合以模型合同为准，超出范围保留拒绝；不是任意中文到中国手语翻译，也不是视频手语识别。
- 插件保留原公开动作快照：14 条 T08 参考、3 条 T08 候选和83条历史动作质量批准的拟合片段。
- 新模型演示页从83条拟合片段中按已有质量记录、数值稳定性、时长和哈希绑定选取8条独立动作参考；其余仍在原工作台。
- 当前模型词汇与这8条参考标签未形成已确认的自动映射。理解例句后，人物可能没有对应动作；下方参考卡片用于独立展示。页面明确说明缺口，没有自动查词拼接后备。
- 沿用原显示稳定配置；没有改写原始姿态，没有声称零抖动、零穿插或新增手语语义批准。
- `research_only=true`，`human_approved/semantics_approved/training_ready/model_training_ready/csl_translation_verified=false`。旧片段历史动作质量批准范围独立保留。

## 本机连接与资源边界

模型服务只监听127.0.0.1，校验 Host；浏览器同源访问继续保留。打包时注入固定**公钥**，插件 ID 为 `imnkigcbpjdnaaobmefpjcdkdblkfdeo`。服务只允许此扩展来源跨域，没有任意来源通配。

插件显式点击后请求 `http://127.0.0.1/*` 可选权限，不新增全网必需权限；Chrome 的匹配模式不限制端口，客户端进一步限制为完整127.0.0.1地址与合法端口。会话凭据只存于页面传输模块内存，关闭页面或服务重启后重新连接，不写文件、扩展存储、URL或日志。

连接时校验协议、检查点与本地动作索引的ID、标签、审核范围、姿态资产和来源摘要。换地址、网络失败、版本不符会停止旧播放、清空旧结果；修改输入和切换动作使用代次隔离，迟到的推理结果不能覆盖新输入。

HTTP静态服务仅开放构建清单中的人物与公开动作资源，不提供权重、语料、配置、Python代码或目录列表。交付包本身含本地研究模型，**本次未上传或推送 GitHub**。

## 构建与复现

在应用目录执行：

```sh
npm run verify
SIGNBRIDGE_BUILD_DIR=/absolute/new/build npm run build:motion
python3 src/tools/sign-extension-model-package.py stage \
  --base /absolute/previous/verified-model-demo \
  --build /absolute/new/build \
  --output /absolute/new/delivery
```

`stage`先核验上一版逐文件摘要与新构建清单，复制模型快照和当前冻结工具，分隔扩展与本机模型，注入公钥并重算manifest摘要，保留原构建摘要。补齐README、SUMMARY和验证资料后执行：

```sh
SIGNBRIDGE_MODEL_DEMO_ROOT=/absolute/new/delivery \
  node tests/model-extension-browser-qa.mjs
python3 src/tools/sign-extension-model-package.py seal \
  --root /absolute/new/delivery --archive /absolute/new/demo.zip
```

浏览器验收使用实际 MV3 扩展、实际可选权限和本机真实模型。ZIP重新打开并核验CRC和逐文件SHA-256；服务状态、日志、活动会话不在打包成员中。权重不进入 `chrome-extension/`。

## 常见故障

- **模型服务不可用**：启动同包 `.command`，保持终端开启，确认地址端口；原工作台不依赖模型服务。
- **模型或动作版本不匹配**：加载同一包的扩展，启动同一包的服务；不要混用旧插件和新服务。
- **8787已占用**：不要结束不明进程。可显式用 `tools/sign-model-demo-serve.py --config model-config.json --port 新端口` 启动，并在插件连接栏填相同地址。
- **运行时缺失**：恢复上面注明的本机运行时同级目录；当前交付不是跨平台独立安装器。
- **人物不随语义自动播放**：查看动作缺口提示；仅有词语识别不足以证明有完整中国手语动作。
