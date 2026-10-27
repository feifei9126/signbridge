# 1.0.6 公开动作 Demo：T08 + 83 条拟合动作

## 公开范围

2026-10-27 用户明确授权“公开t08，后期83条也公开”。本次只发布固定 public-motion-v1 快照：

| 来源 | 数量 | 实际内容 |
| --- | ---: | --- |
| T08 原参考 | 14 | 冻结 tokenizer 的预计算 token 编码／解码参考 |
| T08 候选 | 3 | 同一 T08 权重的候选重建，仍保持候选标记 |
| 后期 SMPL-X 拟合 | 83 | 原视频拟合的姿态，动作质量已人工批准，不是 T08 token 输出 |
| 合计 | **100 段** | 不是 100 个独立词条或已认证手语句子 |

三类资产原字节、姿态、来源摘要和既有批准记录均保留，不重新训练或改变 T08 检查点。后续新动作默认私有，不能自动沿用本次发布授权。

## 下载与安装

- [Chrome 扩展与离线 Demo ZIP](assets/signbridge-chrome-extension-1.0.6-public-motion-20261027.zip)
- [SHA-256](assets/signbridge-chrome-extension-1.0.6-public-motion-20261027.zip.sha256)
- [ZIP 逐文件清单](assets/signbridge-chrome-extension-1.0.6-public-motion-20261027.zip.contents.json)
- [可读动作 JSON 与输入清单](../signbridge/assets/public-motion-v1/)

ZIP 大小 **39,694,867 字节（约 39.7 MB / 37.9 MiB）**，包含 141 个文件。SHA-256：

```text
a983b2ed854e1ec1cf7566d3d1bf78ffe9e38800c1d33589343103f90e6b1652
```

1. 下载 ZIP 及 .sha256，在下载目录运行 `shasum -a 256 -c signbridge-chrome-extension-1.0.6-public-motion-20261027.zip.sha256`。
2. 解压，打开 Chrome 的 `chrome://extensions`，开启开发者模式，停用旧 SignBridge，加载含 manifest.json 的解压目录。插件弹窗应显示 **v1.0.6**。
3. 打开视频页面或插件演示工作台：输入“工作忙吗？”应显示 T08；输入“认识你很高兴”应显示 SMPL-X 实验重建。后者没有 T08 token；“你好”“谢谢”等仍来自内置词库，不是动作漏传。
4. 独立 Demo 可双击 `start-demo.command`，或在解压目录运行 `python3 start-demo.py`，访问终端打印的 127.0.0.1 地址，保持终端开启。不要用 file:// 直接打开 Demo。

动作、人物和页面资源在包内；语义模型服务不包含，Whisper 的首次语音识别模型下载也不是此包的离线资产。

## 从源码复现

需要 Node.js >=20.19.0、npm 和 Python 3；打包工具仅使用 Python 标准库。

```bash
git clone --branch codex/t08-avatar-demo https://github.com/feifei9126/signbridge.git
cd signbridge/signbridge
npm ci
npm run verify
npm run build:motion
npm run package:motion -- --build dist --output /absolute/new/signbridge-motion.zip
```

输出 ZIP、ZIP.sha256、ZIP.contents.json；已有同名文件会拒绝覆盖。ZIP 时间戳和成员顺序固定，同一构建内容可以得到相同 ZIP。源码改变时 BUILD.json 的 source_sha256 会改变，因此不要期待任意未来提交的 ZIP 仍等于本版摘要。

### 三种构建不能混淆

| 命令／profile | 动作来源 | 用途 |
| --- | --- | --- |
| npm run build / public-demo | 内置公开词库，研究动作占位为空 | 原有默认构建，不应误称含 T08 |
| npm run build:motion / public-motion-demo | 仓库内固定 14 + 3 + 83 快照 | 本次公开下载版 |
| npm run build:research / local-research | 显式本地路径和 SHA 清单 | 未公开后续研究，不能自动分发 |

public-motion-demo 拒绝私有动作环境变量；输入清单 SHA-256 锁定为 `243e4345dd07d33af6f16b0e2cec300f731e3feae5ed48da779b95c2585ba946`。88 个 JSON 输入逐一校验，批准记录和姿态摘要再验证；清单或动作变化会失败，不静默回退成“看似带动作”的包。构建生成 avatar/t08-index.json，运行时按来源加载。

## 本轮验证结果

- `npm run verify`：构建、Lint、格式检查通过；253 项 JavaScript 测试通过，571 项 Python 测试运行，其中 12 项按原有条件跳过。跳过不等于通过 GPU 训练验收。
- 新增公共发布测试：固定数量与唯一 ID、私有路径拒绝、清单篡改拒绝、确定性 ZIP、逐文件摘要、额外未列文件拒绝、路径穿越／软链接／错误 profile／训练就绪升级拒绝。
- **从新 ZIP 解压后独立验收 100/100 动作**：每条实际来源和 ID 正确，无词库回退；100 个画面非空且有运动；14+3 条 T08 的 token 精确一致；无页面错误和缺失资源。此测试是短时播放与渲染检查，不是逐帧语言学或抖动重新认证。
- 完整 Chrome for Testing 的真实扩展路由 **8 项通过**：版本、T08 参考加载、词库与参考／拟合的混合字幕顺序、实际字幕 DOM、音频转写交付路由、故障局部回退、取消旧请求。ASR 本身未重新执行。
- 初次使用默认无头 shell 因不支持扩展后台而超时，保留失败报告；指定已有完整 Chrome for Testing 后通过，不修改产品逻辑来掩盖失败。
- ZIP 外部哈希与内部 141 个文件哈希全部核对。公开包不含源视频、研究 JPEG、训练权重、CE-CSL 数据、私有服务令牌或未授权未来动作。

本机完整证据位于 local-data/public-motion-release-20261027-v1，失败及通过记录均保留。

### 上传后的 CI 配置修正

首次 GitHub 自动验证中，构建、Lint 和 JavaScript 测试通过，Python 测试因 `ModuleNotFoundError: No module named 'numpy'` 终止。原因是 `verify:release` 已递归执行 Python 测试，而工作流将 Python 依赖安装排在该命令之后。现将 Python 环境和原有依赖安装提前，并加入顺序回归检查；动作资产和下载 ZIP 字节保持不变。云端自动验证结论以对应提交的 GitHub Actions 记录为准，不能将成功上传等同于 CI 通过。

复跑还发现公共 runner 缺少 Matplotlib、FFmpeg／ffprobe，现补齐这些测试依赖。一项依赖本机私有审核证据的历史集成测试，在缺少私有目录时明确标记为未执行；本机目录存在时仍完整运行。不会为了公共 CI 上传或伪造私有审核材料。公开动作的 100 个 ID、摘要和播放检查仍独立执行，不使用该跳过替代公开包验收。

## 能力、授权与许可边界

公开 JSON 可被读取和提取；此版本不承诺防复制。现有显示层平滑继续存在，原始姿态不改写，也不把平滑当作手语含义正确的证据。training_ready、model_training_ready、deployment_ready 均为 false；未启用新训练或 Demo 语义自动生成。

83 条的批准范围仅为动作质量。中文含义、词级边界、镜像方向、惯用手、手语者和划分资格不因公开而获批。历史运行摘要和原 JPEG 哈希缺失等 provenance_limitations 保留。

项目自有代码继续 MIT。公开分发不重新许可 SMPL-X、SMPLer-X、SOKE、人物模型、源视频及其衍生权利；使用者须核对相关来源条款，不能把项目 MIT 当作所有第三方资产的无限制商业许可。

旧安装包和研究证据不删除、不覆盖。默认下载链接切换到本版；未来动作须另行授权发布。
