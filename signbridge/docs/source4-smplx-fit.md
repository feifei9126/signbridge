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
