# 从已核对视频到 SMPL-X 动作

本阶段把已核对的句子与视频边界保存为新版本，导出逐帧图片，运行 SMPLer-X 的人体重建，并把**真实拟合结果**转换成 SOKE 使用的 133 维表示。重建工具和转换工具已实现；当前 Mac 的运行检查未通过，尚未生成用户视频的 SMPL-X 动作，也尚未训练手语模型。

## 已准备的数据

- 当前核对对象为 `sign-language-candidates-v3` 的 16 段视频、3116 帧。
- 用户于 2026-09-28 表示“人工核对过了，下一步”。新版本 `sign-language-reviewed-v4` 按“沿用现有释义和边界，无修改”记录此次确认，并保存原话及输入清单摘要。
- 镜像方向保持 `unknown`；表演者标识暂未跨视频归并，集合保持 `unassigned`。视频内容核对与 3D 动作质量核对分别记录。
- 可携带到 GPU 机器的输入为 `local-data/sign-language-smplx-input-v1`。包括 1 起始的 `images/000001.jpg`、句子释义、逐帧时间、原片段、缺失值及 mask 保持原样的观察数据、SHA-256 清单。
- 处理产物及依赖模型留在 Git 忽略的 `local-data/`；原视频和原候选版本保留。

## 这一步选用的模型

SMPLer-X 用作首批全身、双手、脸部重建的基线，直接从视频图片估计 SMPL-X 参数。转换器对应其官方 `inference.py` 输出，不依赖当前缺失较多的 MediaPipe 手部点作为训练标签。逐帧估计仍可能产生错误手形、手腕翻转、接触位置错误和抖动，必须先查看拟合叠加图再判断是否可用于训练。第一批结果用于评估重建路线；需要时再增加专用手部重建与时序优化。

为使接口可以复现，当前支持以下源代码版本：

| 项目 | 固定提交 | 对应文件 |
| --- | --- | --- |
| SMPLer-X | `064baef0e4ab5277a3297691bc1d46ea5412586f` | `main/inference.py` |
| SOKE | `5cbc55d84b5a7cbf05a9cf020c468052e8d94d00` | `mGPT/data/humanml/load_data.py` |

依赖源码已放在 `local-data/deps/SMPLer-X`。官方 Faster R-CNN 检测权重及配置已下载并校验；H32 主权重和账户下载的人体文件尚未安装。SMPLer-X 的官方推理使用 CUDA；此工具目前调用原实现，未提供 MPS 适配。

## 保存人工核对

此操作已经为当前批次执行。以下命令用于了解来源或处理后续新批次；已有输出不会覆盖。

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-motion.py review \
  --manifest local-data/sign-language-pilot/sources.json \
  --segments local-data/sign-language-pilot/segments-v3.csv \
  --batch local-data/sign-language-candidates-v3 \
  --reviewer user-reported-manual-review \
  --statement '人工核对过了，下一步' \
  --output local-data/sign-language-reviewed-v4
```

`review-decision.json` 保存审核依据、输入 SHA-256、具体样本、释义和范围。命令仅确认当前释义/边界，不修改镜像方向、表演者身份或 split。不接受与已制作片段不一致的边界/候选标签，也不会将 rejected 样本自动改为通过。需要改正的片段先修改标注并重新 prepare，再记录新审核。

## 导出拟合输入

当前批次已执行：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-motion.py export \
  --reviewed local-data/sign-language-reviewed-v4 \
  --output local-data/sign-language-smplx-input-v1
```

图片与片段保持同样的分辨率、帧数和 25 fps，不插值、不镜像、不裁掉字幕。时间为已制作片段的采样时间与原视频名义时间，不是原视频逐帧 PTS。`observations.npz` 的身体/手/脸相对 z 坐标不能当成一个米制空间，也不能当成 SMPL-X 参数。

`tasks.jsonl` 和 `contract.json` 给出输入约定。每次 fit/import 都检查 SHA-256、图片连续性和视频摘要；如果图片或清单被修改，请重新导出新版本。

## GPU 环境和模型文件

在有 NVIDIA CUDA 的机器上，根据固定版本 SMPLer-X 的官方 README 安装其 Python 3.8、PyTorch 1.12、CUDA 11.3、mmcv-full 1.7.1、随源码附带的 mmpose 及其余依赖。控制本工具使用 Python 3.10–3.12 和数据准备依赖；通过 `--python` 指定独立的 SMPLer-X 环境解释器。不要将 Mac 的虚拟环境直接拷贝到 Linux。

首先准备以下文件。精确缺失列表由 `fit --dry-run` 输出到 `run.json`。

- `pretrained_models/smpler_x_h32.pth.tar`：使用官方发布的修正相机估计版 `smpler_x_h32_correct.pth.tar`，下载工具核对 Hugging Face 元数据中的 LFS SHA-256、尺寸及源码版本，再保存为推理脚本要求的文件名。当前电脑访问该地址超时，**尚未取得该权重**。
- `pretrained_models/mmdet/`：官方 Faster R-CNN 权重及固定配置；本机已校验 SHA-256。推理时**不需要**训练用 `vitpose_huge.pth`：固定源码的 `get_model('test')` 从完整 SMPLer-X 权重初始化网络，ViTPose 单独权重只在 `mode == 'train'` 时加载。
- `common/utils/human_model_files/smplx/`：`SMPLX_NEUTRAL.npz`、`SMPLX_MALE.npz`、`SMPLX_FEMALE.npz`、`SMPLX_to_J14.pkl`、`MANO_SMPLX_vertex_ids.pkl`、`SMPL-X__FLAME_vertex_ids.npy`。固定版本的 `smplx.create` 默认读取 `.npz`，推理不需要 `SMPLX_NEUTRAL.pkl`。
- `common/utils/human_model_files/smpl/`：`SMPL_NEUTRAL.pkl`、`SMPL_MALE.pkl`、`SMPL_FEMALE.pkl`；原代码导入时也创建这些模型。

下载公开检测资源并复验：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-gpu.py assets \
  --smplerx-root local-data/deps/SMPLer-X
```

如果运行主权重所在网站在 GPU 机器上可访问，加入 `--download-model`。它先取官方 LFS 校验值，然后按该仓库的固定 revision 下载并校验哈希；连接失败不会保存未经验证的 `.part`。主权重和检测权重均不提交 Git。

人体文件从官方 SMPL/SMPL-X 下载账户获取；视频授权不等同于人体模型文件的许可。SOKE 仓库的 `license.txt` 是 CC BY-NC-ND 4.0，当前按研究验证处理，商业使用与派生分发需要另外确认适用许可。

## 搬运到 GPU 机器

已生成忽略 Git 的 `local-data/sign-language-gpu-stage-v1/`，包含 16 段 3116 帧的图片、视频与来源记录、固定源码及 `.git`、已经校验的检测权重与配置、运行工具、`stage.json` 和整包 `SHA256SUMS`。推荐私下复制到无空格路径（例如 `/srv/sign-language-gpu-stage-v1`）；人体模型文件需要从各自官方账户取得后，按上面目录放入该机器的 `SMPLer-X/common/utils/human_model_files/`。本机没有将视频或数据包上传到第三方服务。

GPU 机器上安装两个独立环境（示例为 Linux、NVIDIA CUDA 11.3 的官方旧版栈；依赖组合需要在实际 GPU 机器上验证）：

```bash
cd /srv/sign-language-gpu-stage-v1
python3.10 -m venv /srv/signbridge-driver-venv
/srv/signbridge-driver-venv/bin/python -m pip install 'numpy<2' opencv-python-headless
conda create -n smplerx python=3.8 -y
conda install -n smplerx pytorch==1.12.0 torchvision==0.13.0 torchaudio==0.12.0 cudatoolkit=11.3 -c pytorch -y
conda run -n smplerx python -m pip install numpy==1.23.5
conda run -n smplerx python -m pip install mmcv-full==1.7.1 -f https://download.openmmlab.com/mmcv/dist/cu113/torch1.12.0/index.html
conda run -n smplerx python -m pip install -r SMPLer-X/requirements.txt
conda run -n smplerx python -m pip install -v -e ./SMPLer-X/main/transformer_utils
```

对应 Python 3.8 和 CUDA 版本来自固定 SMPLer-X README；驱动 Python 3.10 用于输入核验、执行和导入；旧版栈把 NumPy 固定为 1.23.5，安装完成后仍需在 GPU 机器上检查依赖兼容。主权重可在能访问 Hugging Face 的机器上下载：

```bash
/srv/signbridge-driver-venv/bin/python tools/sign-gpu.py verify --stage .
/srv/signbridge-driver-venv/bin/python tools/sign-gpu.py assets --smplerx-root SMPLer-X --download-model
/srv/signbridge-driver-venv/bin/python tools/sign-gpu.py stage --batch batch --smplerx-root SMPLer-X \
  --output ../sign-language-gpu-stage-v2
cd ../sign-language-gpu-stage-v2
../sign-language-gpu-stage-v1//srv/signbridge-driver-venv/bin/python tools/sign-gpu.py verify --stage .
export PYOPENGL_PLATFORM=egl MPLBACKEND=Agg
```

下载主权重后执行 `stage` 生成新目录和新 SHA256SUMS；原交付目录只在修改前可通过完整性检查。驱动解释器放在交付目录外，避免破坏原包的文件清单；`fit` 指向新目录下的工具和输入即可。安装人体模型也会改变清单；应保留经校验的原交付目录作为对照，两个人体模型下载需遵守各自许可，不在未经允许时分享带有人体模型文件的目录。

先检查环境。`--python` 的路径替换为该机器的真实 CUDA 环境路径，输出使用一个新目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-motion.py fit \
  --batch local-data/sign-language-smplx-input-v1 \
  --smplerx-root local-data/deps/SMPLer-X \
  --python /path/to/smplerx/bin/python \
  --segment-id pilot-greeting-hello-001 \
  --segment-id pilot-hospital-cough-003 \
  --dry-run --output local-data/sign-language-fit-plan-gpu-v1
```

`run.json` 包含 CUDA/依赖/权重检查与真实命令。`commands.txt` 使用正确的 shell 引号；源代码目录固定在 `main`。官方 `--end` 参数表示**帧数**，不是最后帧的编号。

在打包目录中，先跑两段试验（把 SMPLer-X 环境解释器路径换为实际路径）：

```bash
/srv/signbridge-driver-venv/bin/python tools/sign-motion.py fit \
  --batch batch --smplerx-root SMPLer-X \
  --python /path/to/miniconda/envs/smplerx/bin/python \
  --segment-id pilot-greeting-hello-001 \
  --segment-id pilot-hospital-cough-003 \
  --dry-run --output ../fits-plan-v1
```

环境检查通过后，去掉 `--dry-run`、改用 `--output ../fits-pilot-v1` 才会运行实际重建。`fit` 默认设置 EGL 和无交互 Matplotlib，并拒绝上游 `cp` 无法安全处理的带空格路径。不要将 fit 输出放在 batch 或源码里面。

## 先拟合两段

建议先跑“你好，好久不见”和“咳嗽一个星期”两段，检查这批教材视频的分辨率、双手遮挡和脸部表情是否支持可靠重建。通过后再跑其余片段。

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-motion.py fit \
  --batch local-data/sign-language-smplx-input-v1 \
  --smplerx-root local-data/deps/SMPLer-X \
  --python /path/to/smplerx/bin/python \
  --segment-id pilot-greeting-hello-001 \
  --segment-id pilot-hospital-cough-003 \
  --output local-data/sign-language-fits-pilot-v1
```

命令逐段保存日志、`run.json` 及官方输出的 `img/` 叠加图片、`smplx/` 参数、`meta/` 相机数据。不加 `--segment-id` 时处理全批。出现进程错误立即停止，未完成片段不能导入；检测失败导致缺帧则在导入时拒绝该片段。仅有退出码为 0 还不代表拟合完整或动作正确。

## 转换为 SOKE 表示

真实拟合完成后执行，不能将 dry-run 目录作为 `--fits`：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-motion.py import-smplerx \
  --batch local-data/sign-language-smplx-input-v1 \
  --fits local-data/sign-language-fits-pilot-v1 \
  --output local-data/sign-language-soke-motion-pilot-v1
```

未被选择拟合的其余片段列为 `skipped`；两段完整拟合且校验通过时退出码为 0。拟合失败或缺帧的已完成任务列为 `rejected` 并使退出码为 2。最终全批导入需要全批拟合。

每段要求所有 `00001_0.npz` 到最后一帧连续、仅有目标人物 `_0`，以及全长 axis-angle 参数。拒绝 PCA 手部参数、NaN、缺键、缺帧和额外人物；不会填零、重复上一帧或删掉缺失帧来凑齐序列。导入器不反序列化外部 pickle。

输出：

- `samples/<id>/fitted-smplx.npz`：全参数、相机平移、眼部旋转及时间；保留以便重建与重定向。
- `samples/<id>/features-133.npy`：`[T,133]`，未归一化。
- `poses/<id>/*.pkl`：从已校验的数组生成的 SOKE `load_csl_sample` 兼容逐帧数据。
- `soke-annotations.jsonl`：`name/text/fps/split`。尚未划分训练集时不生成 `csl_clean.train` 等文件。
- `quality.json`：旋转的相邻帧测地角，避免 axis-angle 在 ±π 表示切换造成假跳变；超过 90° 只提示复核，不自动插值。
- `verification.json` / `fit-sources.jsonl`：导入结果、拒绝原因、拟合输入与输出来源摘要。

SOKE 按 root(3)、body(63)、left hand(45)、right hand(45)、jaw(3)、shape(10)、expression(10) 拼成 179 维，删除前 36 维和 shape 的 10 维，最终为上身(30)+左手(45)+右手(45)+下颌(3)+表情(10)=133。不能误删 expression，也不能把手部顺序交换。默认手姿态基准为 `use_pca=False, flat_hand_mean=False`，与本次核对的两份官方实现一致。

这些文件完成数据接口转换；SOKE 的完整自定义数据集配置、训练划分和训练流程仍待接入。沿用预训练 tokenizer 时应沿用其 mean/std，不要用这 16 段重新定义归一化。镜像、跨课程表演者身份和重建动作需分别核对后，才能设为训练可用。

## 测试与来源

```bash
.venv-sign-data/bin/python signbridge/tests/sign-motion.test.py
.venv-sign-data/bin/python signbridge/tests/sign-gpu.test.py
.venv-sign-data/bin/python signbridge/tests/sign-data.test.py
cd signbridge && npm run verify
```

测试用临时合成视频/参数验证审核来源、时间与缺失 mask、摘要检查、路径安全、帧连续性、参数维数及顺序、缺帧拒绝、旋转角检查和完整转换。这些测试结果不代表已运行用户视频的 3D 重建。

官方参考：

- [SOKE](https://github.com/2000ZRL/SOKE) 与固定提交的 `mGPT/data/humanml/load_data.py`、`mGPT/utils/human_models.py`、`license.txt`。
- [SMPLer-X](https://github.com/MotrixLab/SMPLer-X) 与固定提交的 `main/inference.py`、`common/utils/human_models.py`、README。
- [SMPL-X 官方模型](https://smpl-x.is.tue.mpg.de/) 和 [SMPL 官方模型](https://smpl.is.tue.mpg.de/)。
