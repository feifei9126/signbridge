# SignBridge 本地展示 Demo

> 1.0.5现有资源优化：新增独立作用域分析、观测候选和自适应过滤对照。浏览器工作台只提供对照，不默认应用未通过的过滤配置；准确率和审核状态边界见[优化说明](existing-resources-optimization-20261019.md)。1.0.4功能精简仍保留：默认动作演示、训练模型意思分析独立入口、研究详情收起。

> 2026-10-19更新：当前构建配置、词边界和语义禁播行为以[审计整改说明](audit-remediation-20261019.md)为准；下文按日期保留历史记录。普通构建不再自动读取本地T08／拟合动作。下文旧环境变量构建命令属于历史记录，当前复现须使用审计整改说明中的完整local-research命令与新输出目录。

## 2026-10-16：来源 4 两句显示抖动修复

修复版构建目录是 `local-data/six-batch-motion-audit-20261016-b3j952wo/display-fix-v2/build/`。原有 Demo 服务 `http://127.0.0.1:8766/demo/index.html` 现在提供修复版资产；隔离验证地址是 `http://127.0.0.1:8768/demo/index.html`。仅「手语要多练习才可以熟能生巧」和「从今天起就由我们来给大家讲手语课程」绑定 `quaternion-temporal-recovery-v1` 显示配置：手臂窗口 100 ms，手指仍为 30 ms。训练权重和源拟合姿态未更改。

真实 Godette 骨架复测：两句腕部位置中点残差 P95 从 2.27/2.64 cm 降至 0.57/0.59 cm；显示动作范围保留约 89%/84%。逐项数值在 `display-fix-v2/avatar-audit-v2/avatar-review.json`，真实浏览器播放及原始/恢复滤波切换在 `display-fix-v2/browser-recovery-qa-8766.json`。原始模式仍可一键切换。此调整只影响显示；原生拟合姿态数组、T08 和其他训练权重均未修改。

「基本」与「人民」仍分别缺 7 帧和 45 帧原生参数，且不在现有 Demo 资产中。输入帧齐全，但已有运行记录是参数集不完整。本修复没有补零、插值或猜测姿态；两条保留为失败并排除在 Demo 外。逐条证据与有效后续操作见 `display-fix-v2/recovery-report.json`。

隔离构建复现时使用新 `SIGNBRIDGE_BUILD_DIR`，不要覆盖现有 `dist/`：

```bash
SIGNBRIDGE_BUILD_DIR="$PWD/../local-data/six-batch-motion-audit-20261016-b3j952wo/display-fix-v2/build" \
SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR="$PWD/../local-data/six-batch-motion-audit-20261016-b3j952wo/display-fix-v2" \
npm run build
```

## 2026-10-16：六批动作逐项检查

[六批质量检查记录](six-batch-motion-audit-20261016.md) 覆盖原生重建、独立关键帧、历史训练解码及当前 112 条 Demo/预览动作。基线审计发现 2 句来源 4 动作抖动筛查超限，已在本节单独修复；第 4 批另有 2 条连续重建及第 2 批 1 个独立身体关键帧存在缺失，仍明确排除。修复后逐项页、原视频/网格对照、人物确切帧截图和阈值见本地 `local-data/six-batch-motion-audit-20261016-b3j952wo/review-v6/`。

## 2026-10-16：来源 6 独立人物预览

12 段／2,779 帧来源 6 原生连续重建已转换为当前 Godette 人物可播放的候选资产，位于 `local-data/data-expansion-20261015/source-6/avatar-preview-20261016-hjzppz64/`。独立构建为 `preview-build-v2/`，本地服务地址是 `http://127.0.0.1:8767/demo/index.html`；服务关闭后可双击该目录的 `start-demo.command`，或用 `start-demo.py --no-open --port 8767` 启动。它含本批 12 个实验候选，以及原有 14 条参考、3 条旧候选和 53 条词库组合，共 82 个去重条目。打开后默认文字选本批真实候选，并显示文字和首尾未核验的说明。

这批资产通过现有的人物骨骼映射和按需加载实际播放，包含完整 25 FPS 轨迹及原始／显示平滑切换。根部、下身、躯干保持现有 Demo 的待机规则；相机平移和面部系数未映射。手部 mean 仅加一次，帧数和时长保留，原始重建参数、模型权重及 T08 checkpoint 均保持原样。

实际人物骨骼量化结果（12 段均值）：四元数中点残差 P95 从约 8.75° 降到 3.25°；手腕中点残差 P95 从约 2.03 cm 降到 0.82 cm；平滑后最小手腕动作范围保留率约为 96.2%。这是显示层处理，不是手型准确率或训练效果。仍可见手部接触／位置误差，一些窗口混入教学指令或相邻动作；原片／人物截图比较采用 UI 的 0.1 秒显示值，有舍入及截图延迟，不能声称精确帧一致。

导出工具为 `signbridge/src/tools/sign-demo-source6-export.py`，生成独立校验清单和每段原生参数文件摘要。元数据增加 `source_batch=source-6`、`preview_only=true`、空 `text_verified` 和未通过的语义／边界标志；浏览器校验拒绝把这些状态或来源摘要剥离／升级。逐句浏览器检查为 `signbridge/tests/source6-preview-browser-qa.mjs`。前两次本地 QA 因测试误用会话字段、以及在已经结束时点击禁用的停止按钮失败，原记录保留；修正测试后实际播放、暂停／恢复、原始切换、完整结束和会话来源导出均已验证。

独立人物预览未覆盖默认的 83 段实验动作集，也未装入插件的正式句子库。`human_approved`、`training_ready`、`model_training_ready` 仍为 false。后续数据接受须针对实际动作和句子边界逐条确认。

复现使用新的输出目录（`$PREVIEW` 是新本地目录）：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-demo-source6-export.py \
  --package local-data/data-expansion-20261015/source-6/refinement-20261016-v1/audit-v2/package \
  --review local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/candidate-review-v5 \
  --pilot-results local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/pilot-verified-results-83ud9eeq/evidence/pilot-v1 \
  --remaining-results local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/remaining-verified-results-nvbpi1k2/evidence/remaining-v1 \
  --smplx-model local-data/sign-language-gpu-stage-v2/SMPLer-X/common/utils/human_model_files/smplx/SMPLX_NEUTRAL.npz \
  --output "$PREVIEW/motions"
cd signbridge
SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR="$PREVIEW/motions" npm run build
```

复制该次构建到独立位置后运行常规 `npm run build` 恢复默认本地资产集。无需上传、修改或训练 checkpoint。

## 1.0.2 实验动作平滑

2026-10-15：后期 source-4 的 83 个实验片段来自逐帧 SMPL-X 拟合，原先直接播放，没有时序降噪。原始关节的高频跳变经映射保留下来，手腕位置也随之颤动。此前“画面非空且运动”的验收未覆盖此类稳定性问题。

1.0.2 默认仅对实验片段的角色四元数轨迹做居中的时间平滑。双侧窗口使用最短弧旋转插值，手臂等骨骼的时间尺度为 45 ms，手指为 30 ms，以减少对快速手型变化的影响。首尾帧、帧数、25 FPS 时间轴和时长不变；没有补齐缺失检测，也不改写源姿态、源特征、checkpoint 或审批标签。原 14 条 T08 和 3 条旧候选默认保持原轨迹。

工作台的“动作平滑”复选框默认开启，可以在暂停或播放时切换原始／平滑显示，不重新开始时间轴。来源徽标和导出的会话 JSON 标明 `quaternion-temporal-v1` 或 `raw`。插件实时字幕默认使用相同平滑处理，仍显示实验来源，不将其声称为新的训练或质量审批。

新增量化验收：

```bash
cd signbridge
node src/tools/sign-motion-stability-audit.mjs --output ../local-data/demo-experimental-20261015/stability-audit-new
```

该命令要求新的输出目录，检查完整角色骨架、每段全部帧、局部旋转中点偏差、世界空间手腕中点偏差、手腕运动范围、原资产摘要及原 T08 轨迹不变，并保存代码摘要以绑定平滑实现。中点偏差是高频稳定性代理指标，不是手语准确率或相对真人的绝对误差。平滑可能减弱快速的真实动作；严重拟合错误、手型、镜像和穿模仍需对照原视频审查，不能靠平滑宣告正确。

插件用户需加载 **1.0.2** 并刷新已打开的视频页；网页 Demo 用户刷新页面即可。保留前述 1.0.1 的字幕分段和来源修复。

## 1.0.1 插件播放修复

2026-10-15：插件原先要求整条字幕等于参考句，因此“工作忙吗？谢谢”会整条走词库，只播放“谢谢”，丢掉实际已覆盖的 T08 句子。现在使用与 Demo 共用的完整参考片段匹配，保持原文顺序播放参考与实验动作，仅未覆盖的间隙走已有词库或已启用的自定义动作。未知内容不会用空姿态冒充。

例如“谢谢，工作忙吗？认识你很高兴”依次播放词库、真实 T08 token 解码和 SMPL-X 实验重建。片段来源徽标在动作真正开始时更新，不在入队时提前显示后续词库来源。悬停徽标可查看片段 ID；加载失败只对对应片段回退，并显示“参考动作加载失败”，不会把后续可用参考一起降级。

同时修复了先播放词库、再首次加载参考时的骨骼校准偏移：校准总是基于 REST 骨架，校准和编译均保留当前姿态。该修复不更新模型权重或数据审批状态。

安装修复包后，在 `chrome://extensions` 确认版本为 **1.0.1**，再刷新已经打开的视频网页。若从新目录加载，请先停用旧的 SignBridge，避免两个副本同时注入。插件弹窗版本号现在来自实际安装的 manifest。已有参考句不会变成任意文字生成模型；没有对应参考的“你好”“谢谢”等词仍可能正常使用词库。

新增 `signbridge/tests/realtime-motion-browser-qa.mjs` 在真实 HTTP 视频页内通过内容脚本、网页代理和扩展 iframe 检查手动预览、字幕 DOM、授权转写投递、混合片段顺序、实际播放徽标、损坏资产局部回退与异步取消，并保存角色像素与运动证据。该测试不执行 Whisper 识别或评价手语语义。

## 2026-10-15 可用 Demo 更新

本地最新版新增第四批视频拟合动作，目录为 **153 个去重入口**：14 个 T08 参考、3 个旧候选、83 个 SMPL-X 实验重建、53 个词库组合。其中包含词语，不代表 153 句已经训练。放宽的是 Demo 的动作观感要求，不是伪造审核或训练状态；T08/T09/T10 权重未修改。

仍使用下文的启动方式。打开后选择“参考与实验动作”，搜索“认识你很高兴”“你的公司地址在哪里”或“我家附近有一家咖啡店”，再点击播放。实验动作显示独立来源徽标，不会显示假的 T08 token；有明显旋转跳变的片段单独提示。自动模式可将这些动作与旧参考、词库接续播放，未知文字仍会列出。

83 个动作来自 91 个完整序列，重复的 8 个展示项只从新目录排除，原始文件全部保留。2 个缺帧序列“基本”“人民”不导出。合计 24,900 帧，无缺失检测插值。实验动作未完成镜像、人物、运动质量核验，继续保留所有训练就绪标记为 false。先前 76 段与 source-5 的二维观测并未因此冒充可播放训练资产。

默认构建额外读取 `local-data/demo-experimental-20261015/experimental-index.json`；可通过 `SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR` 切换实验资产目录。索引在启动时加载，姿态文件按需读取并验证 SHA-256，加载失败可重新加载或切换词库继续展示。插件实时字幕也能精确匹配实验文字并播放，失败时回退词库；无需新增权限或 GPU。

可从仓库根复现到一个**不存在的新目录**，再用环境变量指定该目录构建：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-demo-experimental-export.py \
  --source local-data/data-expansion-20261014/source-4/reconstruction-delivery-20261015-69rzrm_g/import-audit-v1 \
  --smplx-model local-data/deps/SMPLer-X/common/utils/human_model_files/smplx/SMPLX_NEUTRAL.npz \
  --exclude-bundle local-data/demo-20261012/t08-motion.json \
  --exclude-bundle local-data/demo-20261012/t08-candidates.json \
  --output local-data/demo-experimental-20261015-reexport
cd signbridge
SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR=../local-data/demo-experimental-20261015-reexport npm run build
```

本轮新增验收为 `tests/experimental-browser-qa.mjs`：逐条检查 83 个角色画面非空且运动、暂停/继续/停止、速度和视角、手机布局、延迟请求取消、损坏资源拒绝与词库可用性。旧 Demo 与真实扩展路由测试继续保留。浏览器证据保存在新的本地 QA 目录；这些是工程检查，不是手语语言准确率。

以下为 2026-10-12 原始 T08 基线说明，表格只列原 14 条，新增目录及去重策略见 [目录说明](../signbridge/docs/demo-phrase-catalog.md)。

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

## 实时字幕中的 T08

插件的网页字幕和本地语音转写共用同一条实时动作路由。输入中覆盖完整参考句的片段优先播放固定 T08 checkpoint 的离线解码姿态，并在浏览器中重定向到 Godette；其他已覆盖片段使用候选或实验动作，剩余内容使用词库与自定义动作。浏览器不执行 PyTorch。浮窗左上显示当前真正开始播放的来源，而不是最后入队的来源。参考句内部出现未知符号则不会拼出虚假的完整参考匹配。

例如，“工作忙吗？”会调用 `pilot-greeting-busy-005`；“工作忙吗？谢谢”先调用同一个 T08 完整句，再播放词库中的“谢谢”。单独的“谢谢”仍走词库，因为 T08 当前没有它的独立训练序列。字幕通过浏览器内容脚本，不需要打开独立 Demo，也不会上传视频或字幕。

T08 动作资产只在首个完整参考片段匹配时按需加载到扩展 iframe，并在当前播放器生命周期内缓存。资源缺失、来源校验失败或重定向失败时，仅对应片段回退到既有动作库，不影响其他可用参考。下表为原 14 条 T08 参考句，新增候选和实验片段见目录；不会生成未覆盖句子的手语。

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

| 片段 ID                        | 参考文字                                              | 帧数 | 时长（25 FPS） |
| ------------------------------ | ----------------------------------------------------- | ---: | -------------: |
| pilot-greeting-answer-002      | 是啊，你过得好不好？                                  |  174 |        6.96 秒 |
| pilot-greeting-how-004         | 很好，你呢？                                          |  153 |        6.12 秒 |
| pilot-greeting-busy-005        | 工作忙吗？                                            |  148 |        5.92 秒 |
| pilot-greeting-lunch-006       | 一起去吃饭吧！我请客。                                |  153 |        6.12 秒 |
| pilot-greeting-well-007        | 我也很好！                                            |  122 |        4.88 秒 |
| pilot-greeting-overtime-008    | 很忙，最近经常加班。                                  |  177 |        7.08 秒 |
| pilot-hospital-cold-009        | 有些感冒，喉咙发炎了，其他都很好，别担心。            |  282 |       11.28 秒 |
| pilot-hospital-rest-010        | 好好休息，大概一周就会好转。                          |  159 |        6.36 秒 |
| pilot-hospital-allergy-011     | 可以。药物过敏吗？                                    |  180 |        7.20 秒 |
| pilot-hospital-dose-012        | 这个药每天三次，早、中、晚各一次，每次2片，饭后服用。 |  318 |       12.72 秒 |
| pilot-hospital-pay-013         | 先交费，然后去取药。                                  |  163 |        6.52 秒 |
| pilot-hospital-temperature-014 | 刚量过体温，36.2度，嗓子疼，头痛，流鼻涕。            |  329 |       13.16 秒 |
| pilot-hospital-serious-015     | 有什么问题吗？严重吗？                                |  155 |        6.20 秒 |
| pilot-hospital-iv-016          | 我需要打针、输液吗？                                  |  219 |        8.76 秒 |

合计 2,732 帧、109.28 秒。字典补充动作在页面目录中直接可查。

另外增加3条候选重建，单独显示为候选，不计作T08训练样本：

| 候选完整文字           | 帧数 | 时长 | 归一化重建MSE |
| ---------------------- | ---: | ---: | ------------: |
| 如果下雨可以借你一把。 |  100 |  4秒 |        0.6633 |
| 我给她买了一件衣服     |  150 |  6秒 |        0.4655 |
| 去人民广场怎么走？     |  200 |  8秒 |        0.5073 |

候选原始拟合动作与文字已人工确认。三段使用原T08模型离散码本重建后的归一化均方误差分别为0.6633、0.4655、0.5073，高于14条原参考句平均0.0824；镜像方向和人物分组也未确认。界面保留候选标识与误差。没有更新模型权重。来源、词库对照和复现方式见 [候选扩充记录](t08-phrase-expansion-20261012.md)。

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

## 2026-10-17：中国手语语义原型

Demo 新增“中国手语语义原型”模式。它先把中文解析为有限的语义角色：施事、动作/状态、受事/目标、时间、否定、情态、疑问和请求，再检查现有动作是否足以组成一个候选表达。比如“我今天去”会展示候选单元“今天 → 我 → 去”；“我帮你”会明确提示人物空间方向尚未核验；“你去吗？”会阻止播放，因为疑问所需的面部/头部非手控表达还没有动作证据。

这不是中国手语翻译模型，也不是把中文词序宣称为中国手语语法。没有可靠动作、空间指代、疑问表情或情态表达时，原型保留缺口并不播放不完整组合。完整的视频拟合片段仍按整段检索；教学视频的“来/去/今天/昨天/明天”词级候选索引位于 `local-data/six-batch-motion-audit-20261016-b3j952wo/csl-semantic-evidence-v2/`，状态为 `assistant_candidate_only`，没有新增人工批准或训练。

语义原型的可复现代码是 `signbridge/src/demo/csl-semantic-plan.js`，回归测试是 `signbridge/tests/csl-semantic-plan.test.mjs`。浏览器验证记录为 `local-data/six-batch-motion-audit-20261016-b3j952wo/csl-semantic-browser-qa-v1.json`。所有现有自动、T08、词库和实验模式保持原行为。
