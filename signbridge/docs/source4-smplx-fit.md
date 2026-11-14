# Source 4 SMPL-X 拟合阶段

本阶段把 `source-4` 中已经人工复核的 93 条候选整理成可交给 SMPLer-X 的输入包。它不是训练结果，也不会把 MediaPipe 2D 点当作 SMPL-X/MANO 监督目标。

## 输入包

- 目录：`local-data/data-expansion-20261014/source-4/smplx-fit-input-v2/`
- 范围：93 段、28,000 帧、37 个授权来源
- 每段包含：25 FPS 视频、连续 1-based JPG 帧、逐帧 `frames.jsonl`、原始 `observations.npz`
- `SHA256SUMS` 绑定视频、图片、观测、任务清单、审核证明和 contract
- 任务使用 `label_review_status=approved_for_fitting`，但仍保持 `human_approved=false`、`training_ready=false`、`model_training_ready=false`

## 预检结果

当前 Mac 不能执行 SMPLer-X：本机没有 CUDA，`.venv-sign-data` 缺少 `torch`、`torchvision`、`smplx`、`mmcv`、`mmdet`、`mmpose`、`timm` 和 `pyrender`。SMPLer-X 源码 commit `064baef0e4ab5277a3297691bc1d46ea5412586f`、checkpoint 和人体文件已存在且预检文件项通过。

预检证据在 `local-data/data-expansion-20261014/source-4/smplx-fit-plan-v1/`，包括 `run.json`、`REPORT.md` 和 93 条未执行命令。

## GPU 执行

在 CUDA 主机上进入项目目录后运行：

```bash
python tools/sign-source4-fit.py run \
  --package batch \
  --smplerx-root SMPLer-X \
  --python /path/to/cuda/python \
  --model smpler_x_h32 \
  --output fit-output
```

运行前必须确认 `python -c 'import torch; print(torch.cuda.is_available())'` 输出 `True`，并先执行 `--dry-run`。拟合完成后，必须使用 `sign-motion.py import-smplerx` 生成 133 维特征，再进行手部/镜像/时序人工质量门禁；在这些门禁通过前不要设置 `training_ready`，不要修改 tokenizer 或 T08 checkpoint。

## 2026-10-14 GPU 接续记录

GPU 主机已连通，复用 PyTorch 1.12.0 / CUDA 11.3 的 RTX 4090 环境。服务器仅剩约 5 GB 空间，因此上传了独立的 258 MB 视频/观测包，逐段提取图片、重建并检查后释放新生成的临时图片。远端位置是 `/root/autodl-tmp/signbridge/source4-stream-v1/`。

前两段试跑共 600 帧已经下载到 `local-data/data-expansion-20261014/source-4/smplx-fit-pilot-v2/`，通过参数形状/有限值、完整编号、600 条元数据、600 张可解码渲染图及推理日志校验。原始的 133 维特征保存在 `smplx-fit-pilot-v2-audit-v2/`，原片与网格视频复核页在 `smplx-fit-pilot-v2-review-v1/index.html`。剩余 91 段在服务器继续推理。

本次流式结果使用自己的 `report.json`，不能伪造 `sign-motion.py` 期望的 `run.json` 来绕过来源验证。接续结果应通过专用的严格审计入口导入：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-source4-stream-fit.py audit \
  --package local-data/data-expansion-20261014/source-4/smplx-fit-input-v2 \
  --results /path/to/new-verified-download \
  --remote-output-root /root/autodl-tmp/signbridge/source4-stream-v1/pilot-v2 \
  --output /path/to/new-audit-directory
```

审计拒绝缺帧、多人物参数、错误元数据、损坏渲染或推理日志哈希变化；缺失检测会在拒绝记录中保留，不插值、不生成虚假训练特征。生成的特征仍标记动作质量待复核、`training_ready=false`、`model_training_ready=false`。

两个试跑片段的首帧仍有上一词字幕（“召集”“协商”）；第二段的抽样原生渲染存在明显位置/比例偏移。应进一步检查动作边界、相机估计和双手姿态。用户已授权推进训练，但训练数据的动作质量门槛仍需满足，数值审计不能替代这项检查。

旧流式 runner 接续时报告的 `status`、`finished_at` 和 `selected_tasks=2` 可能仍来自试跑。当前任务是否完成必须同时核对实际进程、全部 93 条完成/失败记录及 28,000 帧总数。新版本已增加接续状态重置与任务摘要验证；运行中的旧脚本保持原样。本地后续审计会明确保留旧报告未携带任务摘要、临时输入图已释放的来源限制。


## 2026-10-15：本轮重建完成

GPU 推理于 2026-10-15 07:10:01（Asia/Shanghai）结束，93 个任务全部有完成/失败记录：91 段完整、27,550 帧导入为原始 133 维特征；2 段因原片黑场/标题过渡缺失检测，保持原证据、不插值。全套 28,000 帧原生渲染、27,948 组参数与元数据已下载并审计。`基本` 缺第 221–227 帧，`人民` 缺第 1–45 帧。

本轮交付根目录是 `local-data/data-expansion-20261014/source-4/reconstruction-delivery-20261015-69rzrm_g/`：

- `STAGE-REPORT.md` 是完整过程、计数、来源限制及调用入口。
- `review-v1/index.html` 是覆盖 93 段的原片/网格对照、抽样图和可播放视频。
- `review-v1/review-data.json` 是逐段机器可读索引，包含原标签、原视频摘要、帧数、缺口、特征路径和待复核状态。
- `import-audit-v1/motions.jsonl` 与 `import-audit-v1/samples/` 是 91 段真实特征和原生参数；动作质量仍为 `needs_review`，所有 `training_ready/model_training_ready=false`。
- `rotation-review-priority.json` 将 6 段相邻帧手关节旋转超过 90° 的序列列为复核线索，未自动平滑或认定语义错误。
- `evidence/EXPORT.json`、`evidence/SHA256SUMS` 与 `download-verification.json` 记录外层归档及 84,459 项内部文件校验、checkpoint/任务/工具来源。

全部 93 个原片与 93 个对照视频已经逐帧解码校验。浏览器中的 93 张对照图、93 个视频元信息/帧解码、播放暂停和 3 种屏幕宽度布局通过检查。无视觉回归基线，因此报告没有宣称视觉回归或手语语义准确率通过。

本轮完成的是 SMPL-X 重建和数据准备，未启动 tokenizer/动作模型训练或修改 T08、Demo。接续训练前仍需复核动作语义、手型/手腕方向、镜像/手别、精确边界及人物分组/数据划分。GPU 监测在交付验证完成后删除；等待人工质量决策，不自动启动新的重建或训练。
