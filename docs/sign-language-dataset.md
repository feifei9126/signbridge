# 手语视频的数据准备

本地工具将手语视频整理成可追溯的清单、候选句子片段、关键点数组和核验预览。视频从用户选择的本地目录读取，处理过程不上传素材。

## 范围与表示

当前工具完成数据准备试点，不训练模型。MediaPipe Holistic 0.10.21 提取每帧 33 个身体点、左右手各 21 个点和 468 个面部点；这些是模型估计的关键点。`pose_image`、双手和面部的相对 z 坐标并不共享可直接拼接的米制坐标系；`pose_world` 是另一组估计的身体世界坐标。

这些结果不是 SMPL-X 关节旋转、手部参数、脸部表情系数，也不是 SignBridge 的 `humanoid-local-v1` 本地骨骼旋转。SOKE 的公开实现使用 SMPL-X 数据：后续须解决稳定的手部跟踪、人工核验、SMPL-X 参数拟合和质量检查，再做 tokenizer 或生成器训练。不能把本工具的 NPZ 更名后当成 SOKE 数据。

烧录字幕仅放入 `text_candidate`，熟练手语使用者确认的表达填写 `text_verified`。示范之外的口语讲解、画面词条和逐步教学不能自动当成完整句子的手语释义。

## 新增教学视频参考库（2026-10-10）

用户授权的 `100/` 与 `shouyu/` 新增视频已整理为95个文件、81个摘要去重来源、518条字幕候选与80条详细教学手部参考。查阅方式、来源证据、2D拟合输入和状态限制见[教学视频的学习、标注与手部参考](sign-tutorial-reference.md)。交付保存在本地 `local-data/tutorial-hand-reference-20261010-v2/`，原视频和派生参考不上传到公开文档站点。

## 安装

从仓库根目录执行，使用 Python 3.10–3.12，并确保 `ffmpeg` 和 `ffprobe` 在 PATH 中。首次安装依赖需要网络，处理视频在本地完成。

```bash
uv venv .venv-sign-data --python 3.12
uv pip install --python .venv-sign-data/bin/python -r signbridge/src/tools/requirements-sign-data.txt
```

## 清点素材

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-data.py scan \
  --source-root "/Users/mac/Desktop/手语" \
  --output local-data/sign-language-pilot \
  --authorization-confirmed \
  --authorization-note "2026-09-28 用户确认所提供视频全部获得授权"
```

此命令输出：

- `sources.json`：相对路径、SHA-256、时长、分辨率、帧率、逐文件授权记录（用户确认）。
- `videos.csv`：可用表格软件打开的素材清单。
- `overview/*.jpg`：每个视频四个时间点的抽样图。
- `segments-template.csv`：空白片段标注模板。

已有清单不会被覆盖，源目录也不允许作为输出目录。文件摘要用于后续检查视频是否变化。用户于 2026-09-28 确认所提供全部视频已经授权；现有 13 个源文件均记录为 `user_reported`，表示根据用户陈述记录，未单独审核许可文本或推断任意公开分发权限。视频和派生数据保存在忽略提交的 `local-data/` 中。已有清单请直接复用；`scan` 要求全新输出目录，不覆盖原清单。

## 从视频画面采集候选字幕（macOS）

Mac 上可以运行本地 Vision OCR，抽样取画面下方 32% 的烧录字幕。Vision 支持指定识别语言和精确识别模式；本工具传入简体中文与英文，输出原始 OCR 行、置信度、抽帧图和近似时间戳。OCR 有漏字、错字，且字幕出现时间不等于手语动作起止时间。

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-data.py ocr \
  --manifest local-data/sign-language-pilot/sources.json \
  --source-id source-23efbaded8944f2f --start 252 --end 302 \
  --fps 1 --output local-data/sign-language-ocr-greetings
```

输出 `captions.jsonl`、`provenance.json`、`frames/`。新扫描区间使用新的输出目录；OCR 仅接受清单中有用户授权记录且哈希未变化的源文件。优先从单人镜头里选取连续句子，并在 `segments-v3.csv` 中保留 OCR 释义为 `text_candidate`；所有审核字段保持待审核。

## 标注片段

复制模板为 `segments.csv`。首批建议采用正面单人的完整演示，暂缓双人对话。

| 字段                        | 含义                                             |
| --------------------------- | ------------------------------------------------ |
| segment_id                  | 唯一的 ASCII 片段 ID，用于目录名                 |
| source_id                   | 来自 sources.json                                |
| start_seconds / end_seconds | 原视频中的秒数；覆盖完整表达，避开标题与镜头切换 |
| text_candidate              | 从画面文字暂记的候选含义                         |
| text_verified               | 人工确认的中文释义                               |
| sample_type                 | word 或 sentence                                 |
| language                    | 本批目标为 zh-CSL；手语地域或变体可在 notes 补充 |
| signer_id                   | 表演者标识，需要跨视频统一；试点标识仍需人工确认 |
| split_group                 | 同一课程或会话的分组                             |
| split                       | 初始 unassigned；后续 train / validation / test  |
| semantics_status            | needs_review / approved / rejected               |
| boundaries_status           | needs_review / approved / rejected               |
| mirror_status               | unknown / normal / mirrored                      |
| reviewer                    | 审核者标识                                       |
| notes                       | 截断、遮挡、非手控表达、变体等备注               |

不要为了提高样本量把同一句的重放或相邻帧分别放进训练和测试集。验证命令拒绝同一源视频内容、同一 signer_id 或同一 split_group 跨集合；身份标识必须先统一，内容相近但文件不同的重复样本还需要人工去重。

## 生成片段和关键点

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-data.py validate \
  --manifest local-data/sign-language-pilot/sources.json \
  --segments local-data/sign-language-pilot/segments.csv

.venv-sign-data/bin/python signbridge/src/tools/sign-data.py prepare \
  --manifest local-data/sign-language-pilot/sources.json \
  --segments local-data/sign-language-pilot/segments.csv \
  --output local-data/sign-language-first-batch-v2
```

当前试点目录已生成，再运行时使用新的输出目录。

默认以 25 fps、长边不超过 1280 像素制作无音频的中间片段，不覆盖原视频。每个样本输出 `clip.mp4`、叠加关键点的 `overlay.mp4`、`landmarks.npz`、`quality.json`、`segment.json`。`prepared.jsonl` 是整批清单，`review.html` 提供原片段和提取预览，可同步播放。

缺失点保留 NaN，分别记录 detection mask，不使用零坐标伪装有效点。检测率表示模型返回关键点的帧占比，不是精度，也不代表手语正确；下垂到画外的手、遮挡和运动模糊可能造成缺失。镜像状态会记录，但此版不执行左右手纠正。逐帧时间戳对应重采样后的片段时间及其在原视频中的名义采样时间，不是原始文件的逐帧 PTS。

可复核数据包后运行完整解码及形状/mask 校验：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-data.py audit \
  --batch local-data/sign-language-candidates-v3
```

此命令输出 `verification.json`，逐帧读取原片段和叠加片段，检查关键点数组及缺失标记一致性。结构校验通过不表示语义或动作正确。

`label_ready` 仅表示指定人工审核字段齐全；`model_training_ready` 在本版始终为 false，同时产物保留原视频的 `authorization_status`。此版不检测多个人的数量、不验证字幕语义、不插值缺失帧、不拟合 SMPL-X、不导入虚拟人动作。

## 已核对批次的动作重建

用户于 2026-09-28 确认当前 16 段已经人工核对。确认记录保存在新版本 `local-data/sign-language-reviewed-v4`；逐帧拟合输入为 `local-data/sign-language-smplx-input-v1`。

详见 [从已核对视频到 SMPL-X 动作](sign-language-motion.md)：包括审核来源、SMPLer-X 运行工具、模型文件要求、真实结果的 SOKE 133 维转换及其限制。原候选版本保持原有审核字段，追溯时应同时查看新核对记录。

## 核验与下一步

### 2026-10-10：新增来源筛查与候选扩充

原13个已由用户确认授权的源视频中，11个未进入此前两来源的动作模型训练。本轮对这11个原文件重新核对SHA-256，在Mac本地以0.5fps采样并使用Vision OCR，完成2,235张画面筛查；原视频没有修改、素材没有上传，未启动新的GPU推理或训练。

`sign-source-candidates.py` 把单人示范标记、字幕位置和连续同文本样本一起记录，得到1,575个OCR字幕区间，其中263个带单人示范章节文字。`sign-text-ocr.swift` 新增Vision归一化文本框，坐标原点位于左下角；筛查整句字幕时忽略画面上方词条、章节和标识。旧OCR调用仍输出原有text/confidence字段。

这些数量是候选区间，含OCR错字、字幕缺失和一句话被拆开的情况，不是1,575条有效手语标签。采样时间是名义时间，区间为首末观测点周围半个采样间隔，不能当作动作起止真值。单人示范文字也不证明已准确数过画面中的人物或确认身份。

首批自动选择每个教材视频最多3个有至少两个连续文字观测、4–12秒且不以续句标点结尾的区间，准备了27段整句示范候选（3,850帧）。另两份教程中的“你好／你好吗”和“你好／朋友”制作成4段词汇/分步教学复核片段（700帧），独立保留，没有混入整句候选。共31段、4,550帧，覆盖全部11个新增来源；两类原片和关键点叠加视频都已完整解码并核对NPZ维数、时间轴、NaN与mask。

目录为 `local-data/data-expansion-20261010/`：

- `source-screen/`：11个来源的采样帧、位置OCR及字幕区间，`candidate-index/` 内有原始候选和标注模板。
- `prepared-candidates/`：27个整句候选的clip、overlay、landmarks和quality；边界及手语释义仍未批准。
- `prepared-tutorials/`：4个词汇/分步教学候选，标签词条来自画面文字，不代替完整表达核对。
- `review-delivery/review.html`：可按类别筛选的逐段原片/关键点同步复核页；`annotation-review.csv` 是核对表，`samples.jsonl` 保存媒体/数组来源摘要，`summary.json` 保存本轮统计。

31段中8段有单侧手部返回率低于20%的复核提示。画外手、遮挡和误检都可能造成缺失，返回率不是手型准确率，缺失帧仍保留NaN而不补零/插值。本轮没有SMPL-X参数重建，也不将MediaPipe点更名为可直接训练的SOKE数据。

`source-group-proposal.json` 将同一目录的教材课程保守关联为 `unverified-textbook-family`，包含原问候/医院视频，防止不同课程文件被误当作已确认人物独立的来源。依据是课程/本地来源记录，不是脸部匹配或外貌识别。两份教程是另行核对的来源候选，没有自动获得独立测试资格。所有新signer_id使用 `unconfirmed-<source_id>`，split为unassigned；旧16段的身份或split记录未覆写。

制作过程的可复跑入口（输出目录必须新建）：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-source-candidates.py screen \
  --manifest local-data/sign-language-pilot/sources.json \
  --exposed-tasks local-data/sign-language-gpu-stage-v2/batch/tasks.jsonl \
  --fps 0.5 --output local-data/new-source-screen

.venv-sign-data/bin/python signbridge/src/tools/sign-source-candidates.py prepare-candidates \
  --manifest local-data/sign-language-pilot/sources.json \
  --candidate-index local-data/new-source-screen/candidate-index \
  --per-source 3 --max-side 960 --output local-data/new-source-prepared
```

本轮新字段均保留 `text_verified=''`、semantics/boundaries needs_review、mirror unknown、split unassigned、label_ready/model_training_ready false，新人工核验标签数为0。此前已经人工核对的同源剩余14段独立保留，不沿用那次确认来批准本次新字幕和边界。下一步是按复核页修正字幕/完整区间、确认镜像及实际人物/重复内容；通过后重新制作对应片段，再进入SMPL-X/WiLoR动作重建。OCR错字即使能从上下文猜到，也没有自动写入text_verified。

1. 查阅具体授权约定与拟用范围；查看每段视频起止位置，确认只有目标表演者且完整表达被包含。
2. 手语使用者核对含义、语序、双手关系和面部/身体表达，填写 verified 文本与审核记录。
3. 单独检查动作期间的手部缺失与误检，必要时重新裁剪、提取或弃用。
4. 制作一小批通过审核的词汇与整句样本，再评估 SMPL-X 拟合及虚拟人重定向的可行性。
5. 在人物/会话分组下划分训练和独立测试数据；这批约 97 分钟的原始课程素材是否足够微调，需要依据最终通过审核的独立样本数及任务范围判断。

## 测试

```bash
.venv-sign-data/bin/python signbridge/tests/sign-data.test.py
.venv-sign-data/bin/python signbridge/tests/sign-source-candidates.test.py
swiftc -typecheck signbridge/src/tools/sign-text-ocr.swift
cd signbridge
npm run build
npm run lint
npx prettier --check src/
node --test tests/*.test.mjs
```

Python 测试覆盖 OCR 源文件授权记录与时间范围、候选字幕不会自动变成已核验释义、边界与非有限数值、重复 ID、路径穿越、审核字段、按视频内容/表演者/会话阻止跨集合泄漏。真实视频试点另行检查解码、NPZ shape、缺失值 mask 和叠加预览；不将这些检查当成语言学验收。

本批 16 个候选片段的本地核验页位于 `local-data/sign-language-candidates-v3/review.html`；16 段不等于 16 条已可用训练标签。
