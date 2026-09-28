# 手语视频的数据准备

本地工具将手语视频整理成可追溯的清单、候选句子片段、关键点数组和核验预览。视频从用户选择的本地目录读取，处理过程不上传素材。

## 范围与表示

当前工具完成数据准备试点，不训练模型。MediaPipe Holistic 0.10.21 提取每帧 33 个身体点、左右手各 21 个点和 468 个面部点；这些是模型估计的关键点。`pose_image`、双手和面部的相对 z 坐标并不共享可直接拼接的米制坐标系；`pose_world` 是另一组估计的身体世界坐标。

这些结果不是 SMPL-X 关节旋转、手部参数、脸部表情系数，也不是 SignBridge 的 `humanoid-local-v1` 本地骨骼旋转。SOKE 的公开实现使用 SMPL-X 数据：后续须解决稳定的手部跟踪、人工核验、SMPL-X 参数拟合和质量检查，再做 tokenizer 或生成器训练。不能把本工具的 NPZ 更名后当成 SOKE 数据。

烧录字幕仅放入 `text_candidate`，熟练手语使用者确认的表达填写 `text_verified`。示范之外的口语讲解、画面词条和逐步教学不能自动当成完整句子的手语释义。

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
  --authorization-note "用户说明部分视频已获授权；逐文件授权范围待核对"
```

此命令输出：

- `sources.json`：相对路径、SHA-256、时长、分辨率、帧率、逐文件授权待核对状态。
- `videos.csv`：可用表格软件打开的素材清单。
- `overview/*.jpg`：每个视频四个时间点的抽样图。
- `segments-template.csv`：空白片段标注模板。

已有清单不会被覆盖，源目录也不允许作为输出目录。文件摘要用于后续检查视频是否变化。用户仅说明部分视频已获授权，不能推断目录内所有视频均有训练与发布许可；清单中的 `scope_unverified` 表示该文件的授权范围待核对。仅在扫描的每个文件均已确认有处理许可时使用 `--authorization-confirmed`，该选项也不代替查验授权范围。当前试点只在本地进行数据整理，任何文件进入训练集、用于产品或公开发布前，都需逐项核对相应许可。视频和派生数据保持在忽略提交的 `local-data/` 内。

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

`label_ready` 仅表示指定人工审核字段齐全；`model_training_ready` 在本版始终为 false，同时产物保留原视频的 `authorization_status`。此版不检测多个人的数量、不验证字幕语义、不插值缺失帧、不拟合 SMPL-X、不导入虚拟人动作。

## 核验与下一步

1. 逐文件核对许可范围，标记允许训练及派生数据使用的文件；查看每段视频起止位置，确认只有目标表演者且完整表达被包含。
2. 手语使用者核对含义、语序、双手关系和面部/身体表达，填写 verified 文本与审核记录。
3. 单独检查动作期间的手部缺失与误检，必要时重新裁剪、提取或弃用。
4. 制作一小批通过审核的词汇与整句样本，再评估 SMPL-X 拟合及虚拟人重定向的可行性。
5. 在人物/会话分组下划分训练和独立测试数据；这批约 97 分钟的原始课程素材是否足够微调，需要依据最终通过审核的独立样本数及任务范围判断。

## 测试

```bash
.venv-sign-data/bin/python signbridge/tests/sign-data.test.py
cd signbridge
npm run build
npm run lint
npx prettier --check src/
node --test tests/*.test.mjs
```

Python 测试覆盖候选字幕不会自动变成已核验释义、边界与非有限数值、重复 ID、路径穿越、审核字段、按视频内容/表演者/会话阻止跨集合泄漏。真实视频试点另行检查解码、NPZ shape、缺失值 mask 和叠加预览；不将这些检查当成语言学验收。
