# SignBridge 本地展示 Demo

日期：2026-10-12。目标是用现有资源展示“文字匹配 → 动作编码/重建 → 当前虚拟人播放”的可运行过程。本轮复用固定 T08 checkpoint，通过 CPU 导出浏览器动作资产，无需新 GPU 训练。

## 打开方式

已有本地构建时，双击内层项目 `signbridge/dist/start-demo.command`。它使用 macOS 的 Python 3 启动仅监听 `127.0.0.1` 的本地服务，自动打开 Demo，并自动选择空闲端口。展示期间保持终端窗口开启；按 Ctrl+C 结束。也可以运行：

```bash
cd signbridge
npm run build
python3 src/tools/sign-demo-serve.py
```

如果需要固定端口或手动打开浏览器：

```bash
python3 src/tools/sign-demo-serve.py --port 8766 --no-open
# 浏览器打开 http://127.0.0.1:8766/demo/index.html
```

扩展模式：在 Chrome 的扩展管理页加载 `signbridge/dist/`，点击插件弹窗中的“打开演示工作台”。页面采用独立 iframe 渲染同一个 Godette 角色，保持现有扩展权限。请用本地服务或扩展页面打开，直接双击 HTML 的 `file://` 模式无法正常读取动作 JSON。

本地最终交付目录为仓库根下的 `local-data/demo-20261012/`；其中包含动作资产、对照图、浏览器证据和打包成品。`local-data`、`dist` 和 `.zip` 均不提交。

## 功能与展示顺序

1. 保持“自动匹配”，播放默认示例“工作忙吗？谢谢”。第一段显示“T08 · 参考动作重建”，接着显示“词库 · 内置动作”。
2. 输入“你好，谢谢，宇宙飞船🚀”，可播放已有词语，同时显示未覆盖文字。界面不会用待机或无关片段冒充未知内容。
3. 在“T08 参考短句”模式选择完整句子。目录中的 14 段均来自真实 token 解码，可以展开“查看最近播放的动作编码”检查身体、左手、右手三路 token。
4. 暂停、继续、停止、重播；切换正面/左侧/右侧视角，以及 0.5×/0.75×/1×/1.25×/1.5× 速度。Ctrl/⌘+Enter 也可播放。
5. 搜索已有词条或完整参考句。点击条目把文字放入输入框，并停止上一段动作；点击播放启动新计划。
6. 查看六张授权教学研究关键帧对照图；点击条目展开，点击“收起对照”关闭。这些是候选证据，与当前播放来源分别标记。
7. 点击“导出本次结果”下载 JSON：输入、模式、匹配 ID/来源、未覆盖文本、checkpoint SHA/step、最近播放的片段与实际 token。下载内容明确标记 `textToSignGenerated=false`、`researchOnly=true`。

输入最多 500 字符，单次最多 40 个动作。参考句采用最长匹配并优先于词库，忽略空白和标点差异，但不删除未知符号。英文别名按完整单词匹配。词库为 52 个动作、177 个原有别名；可匹配不表示手语语言质量已获批准。

## T08 覆盖目录

下面的完整参考句可以直接调用。片段中的单个词不会自动获得整个句子的 T08 动作。

| 片段 ID | 参考文字 | 帧数 | 时长（25 FPS） |
| --- | --- | ---: | ---: |
| pilot-greeting-answer-002 | 是啊，你过得好不好？ | 174 | 6.96 秒 |
| pilot-greeting-how-004 | 很好，你呢？ | 153 | 6.12 秒 |
| pilot-greeting-busy-005 | 工作忙吗？ | 148 | 5.92 秒 |
| pilot-greeting-lunch-006 | 一起去吃饭吧！我请客。 | 153 | 6.12 秒 |
| pilot-greeting-well-007 | 我也很好！ | 122 | 4.88 秒 |
| pilot-greeting-overtime-008 | 很忙，最近经常加班。 | 177 | 7.08 秒 |
| pilot-hospital-cold-009 | 有些感冒，喉咙发炎了，其他都很好，别担心。 | 282 | 11.28 秒 |
| pilot-hospital-rest-010 | 好好休息，大概一周就会好转。 | 159 | 6.36 秒 |
| pilot-hospital-allergy-011 | 可以。药物过敏吗？ | 180 | 7.20 秒 |
| pilot-hospital-dose-012 | 这个药每天三次，早、中、晚各一次，每次2片，饭后服用。 | 318 | 12.72 秒 |
| pilot-hospital-pay-013 | 先交费，然后去取药。 | 163 | 6.52 秒 |
| pilot-hospital-temperature-014 | 刚量过体温，36.2度，嗓子疼，头痛，流鼻涕。 | 329 | 13.16 秒 |
| pilot-hospital-serious-015 | 有什么问题吗？严重吗？ | 155 | 6.20 秒 |
| pilot-hospital-iv-016 | 我需要打针、输液吗？ | 219 | 8.76 秒 |

合计 2,732 帧、109.28 秒。字典补充动作在页面目录中直接可查。

## 数据链路与复现

T08 是运动 VQ-VAE，不是文字到手语的生成模型。本轮对训练所用的 14 段参考特征重新执行 `encode → token IDs → decode`；检查 token 解码与前向重建的最大数值差小于 `1e-4`。这些检查证明导出链路一致，不构成独立测试集的泛化评估。

- checkpoint：`local-data/remaining14-research-20261010/verified/training/tokenizer-smoke.pt`，step 1000，SHA256 `438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b`。
- SOKE commit：`5cbc55d84b5a7cbf05a9cf020c468052e8d94d00`。
- 源特征：`local-data/remaining14-research-20261010/verified/motions/`，133 维；身体/左手/右手模型输入分别为 43/45/45 维。
- 身体、左手、右手 codebook 大小为 16/32/32，时间下采样为 4。
- 浏览器资产：`local-data/demo-20261012/t08-motion.json`，SHA256 `0087d5024d320ea2564640f538e4cc7a8ff06f36898f9875c32d9add94ed8a6f`，7,571,295 字节。
- 使用的 SMPL-X 文件 SHA256：`376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992`。模型本体、源视频、PyTorch checkpoint 不随浏览器包分发。

从仓库根执行 CPU 导出：

```bash
.venv-wilor/bin/python signbridge/src/tools/sign-demo-export.py \
  --checkpoint local-data/remaining14-research-20261010/verified/training/tokenizer-smoke.pt \
  --motions local-data/remaining14-research-20261010/verified/motions \
  --soke-root local-data/deps/SOKE \
  --smplx-model local-data/deps/SMPLer-X/common/utils/human_model_files/smplx/SMPLX_NEUTRAL.npz \
  --output local-data/demo-20261012/t08-motion.json
cd signbridge
npm run build
```

导出器校验固定 checkpoint、人体模型、SOKE revision、14 段训练顺序和特征数值。资产保留每段源视频和特征 SHA、token、decode parity 与实验标记。有效手部轴角添加一次 SMPL-X hand mean；姿态转换为四元数后，依据源静止骨架和 Godette 静止骨架校准 40 个骨骼，包括双臂与 30 个手指骨骼。头部使用直立的静止朝向，避免误用面部子骨骼方向。骨架与当前模型的实际层级一致，包括中间辅助骨骼。

根部、下身和未建模躯干保持角色静止姿态；下颌和表情参数尚未完整映射。手型、遮挡、身体比例差异与穿模仍可能影响效果。完整参考句匹配和词库拼接用于展示，不声称通用文字生成、准确语言翻译或新句子泛化。

构建默认从 `local-data/demo-20261012/` 复制资产，可通过 `SIGNBRIDGE_DEMO_ASSET_DIR` 指定另外的本地资产目录。新克隆仓库若没有授权 T08 资产，仍能构建并使用 52 个字典动作；界面显示 T08 不可用，T08 目录为空。加载角色失败提供可点击的重载入口。参考资产与对照图不会修改生产动作库中的启用状态。

## 代码导航与验证

- `signbridge/src/demo/demo-motion.js`：完整参考句/字典最长匹配、未知文本、数据契约校验。
- `signbridge/src/demo/demo-retarget.js`：SMPL-X 轴角、源世界旋转、静止骨架方向与 Godette 四元数映射。
- `signbridge/src/demo/demo-avatar.js`：iframe 三维场景、播放时间、片段缓存、控制协议、资源释放。
- `signbridge/src/demo/demo-playback.js`：处理编译或重播后排队的 RAF 时间，防止负数帧索引。
- `signbridge/src/demo/demo.js`：页面操作、目录/匹配显示、报告下载。播放请求编号隔离已经被停止或替换的旧 iframe 事件。
- `signbridge/src/tools/sign-demo-export.py`：CPU 再编码、实际 token 解码与参数导出。
- `signbridge/src/tools/sign-demo-serve.py`：仅监听 localhost 的展示服务。
- `signbridge/scripts/build.mjs`：离线资产、研究图片摘要和插件入口打包。

常规检查从内层项目执行 `npm run verify`。Python 数据检查从仓库根执行：

```bash
.venv-sign-data/bin/python signbridge/tests/sign-demo-export.test.py
python3 signbridge/tests/sign-demo-serve.test.py
```

真实浏览器验收脚本 `signbridge/tests/demo-browser-qa.mjs` 需要可用的 Playwright 和 Chrome，默认访问 `http://127.0.0.1:8766/demo/index.html`。可用环境变量 `SIGNBRIDGE_PLAYWRIGHT_MODULE`、`SIGNBRIDGE_CHROME`、`SIGNBRIDGE_DEMO_URL`、`SIGNBRIDGE_DEMO_QA_DIR` 指定模块、浏览器、网址和报告目录；`SIGNBRIDGE_EXTENSION_CHROME` 可额外验证 Chromium 的解压扩展和真实弹窗入口。该脚本完整播放 14 段 T08 与 52 个词库动作，并检查快速播放/切模式、重播、暂停继续停止、视角速度、搜索、键盘操作、token、JSON 下载、六张对照图、375/768/1440 像素布局、缺失 T08 与模型加载失败的恢复。

这些自动检查不代替手语专家对语言含义和手型的审核。教学研究对照图仍保留候选与未训练就绪状态，不把展示授权或匹配覆盖率当作语言质量批准。
