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
