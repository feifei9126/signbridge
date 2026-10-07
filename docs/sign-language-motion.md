# 从已核对视频到 SMPL-X 动作

本阶段把已核对的句子与视频边界保存为新版本，导出逐帧图片，运行 SMPLer-X 的人体重建，并把**真实拟合结果**转换成 SOKE 使用的 133 维表示。**截至 2026-10-07，两段真实 GPU 重建及严格参数导入已完成，但视觉抽检发现错误手型，仍不可训练。** 当前增加受控关键帧手部试修；尚未执行真实试修、处理剩余 14 段或训练手语模型。

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

依赖源码已放在 `local-data/deps/SMPLer-X`，GPU 交接包包含固定版本源码、H32 主权重、Faster R-CNN 检测权重和已记录来源的人体文件。服务器的 RTX 4090、CUDA 扩展、人体文件加载及 EGL 离屏渲染已实测；旧版 torchgeometry 布尔掩码兼容修复亦已验证。不得为试修升级这套已跑通的环境。SMPLer-X 的官方推理使用 CUDA；此工具目前调用原实现，未提供 MPS 适配。

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

- `pretrained_models/smpler_x_h32.pth.tar`：使用官方发布的修正相机估计版 `smpler_x_h32_correct.pth.tar`，下载工具核对 Hugging Face 元数据中的 LFS SHA-256、尺寸及源码版本，再保存为推理脚本要求的文件名。本地下载完成情况以 `pretrained_models/signbridge-public-assets.json` 的记录及权重文件实际存在为准；模型大小约 7.94 GB。
- `pretrained_models/mmdet/`：官方 Faster R-CNN 权重及固定配置；本机已校验 SHA-256。推理时**不需要**训练用 `vitpose_huge.pth`：固定源码的 `get_model('test')` 从完整 SMPLer-X 权重初始化网络，ViTPose 单独权重只在 `mode == 'train'` 时加载。
- `common/utils/human_model_files/smplx/`：`SMPLX_NEUTRAL.npz`、`SMPLX_MALE.npz`、`SMPLX_FEMALE.npz`、`SMPLX_to_J14.pkl`、`MANO_SMPLX_vertex_ids.pkl`、`SMPL-X__FLAME_vertex_ids.npy`。固定版本的 `smplx.create` 默认读取 `.npz`，推理不需要 `SMPLX_NEUTRAL.pkl`。
- `common/utils/human_model_files/smpl/`：`SMPL_NEUTRAL.pkl`、`SMPL_MALE.pkl`、`SMPL_FEMALE.pkl`；原代码导入时也创建这些模型。

下载公开检测资源并复验：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-gpu.py assets \
  --smplerx-root local-data/deps/SMPLer-X
```

加入 `--download-model` 可下载公开的 SMPLer-X 主权重。工具会从官方 Hugging Face LFS 元数据读取 `sha256`（或旧版 `oid`）和仓库 revision，下载后校验哈希；断线或校验失败不会保存未经验证的 `.part`。主权重和检测权重均不提交 Git。

本地研究验证的人体文件取自 SMPLer-X 作者公开演示仓库 `caizhongang/SMPLer-X`（Hugging Face Space），固定修订 `2de1f98db5c59da6326dc8fac4c00c78010fa6e5`；九个必需文件分别按仓库 LFS SHA-256 和大小核对，来源记录保存在忽略 Git 的 `common/utils/human_model_files/signbridge-body-assets.json`。运行 `.venv-sign-data/bin/python signbridge/src/tools/sign-gpu.py body --smplerx-root local-data/deps/SMPLer-X` 可复验已经下载的文件，或在另一台可联网的机器上按固定修订重新下载。这是作者演示仓库提供的副本，并非从用户的 SMPL-X 登录账户获取；下载可访问不代表已取得 SMPL、SMPL-X 或 ExPose 用于产品的许可。视频授权不等同于人体模型文件的许可。SOKE 仓库的 `license.txt` 是 CC BY-NC-ND 4.0，当前按研究验证处理，商业使用与派生分发需要另外确认适用许可。

## 搬运到 GPU 机器

本地忽略 Git 的 `local-data/sign-language-gpu-stage-v2/` 包含 16 段 3116 帧的输入、固定源码与 `.git`、检测权重、已校验的 SMPLer-X H32 主权重、九个人体文件、来源记录、运行工具及整包 `SHA256SUMS`。已在本机生成并复验。旧版 `sign-language-gpu-stage-v1` 仅包含公开检测资源。可将 v2 私下复制到无空格目录（如 `/srv/sign-language-gpu-stage-v2`）后运行下列命令；复制到云端或向他人分发含有人体模型的包之前须核对相应许可及账号授权。当前没有将视频或数据包上传到第三方服务。

GPU 机器上安装两个独立环境（示例为 Linux、NVIDIA CUDA 11.3 的旧版栈；依赖组合还需要在实际 GPU 机器上验证）：

```bash
cd /srv/sign-language-gpu-stage-v2
python3.10 -m venv /srv/signbridge-driver-venv
/srv/signbridge-driver-venv/bin/python -m pip install 'numpy<2' opencv-python-headless
conda create -n smplerx python=3.8 -y
conda install -n smplerx pytorch==1.12.0 torchvision==0.13.0 torchaudio==0.12.0 cudatoolkit=11.3 -c pytorch -y
conda run -n smplerx python -m pip install numpy==1.23.5
conda run -n smplerx python -m pip install mmcv-full==1.7.1 -f https://download.openmmlab.com/mmcv/dist/cu113/torch1.12.0/index.html
conda run -n smplerx python -m pip install -r SMPLer-X/requirements.txt
conda run -n smplerx python -m pip install -v -e ./SMPLer-X/main/transformer_utils
```

对应的 Python 3.8 和 CUDA 版本来自固定 SMPLer-X README；驱动 Python 3.10 用于输入核验、执行和导入；旧版栈把 NumPy 固定为 1.23.5。v2 已包含权重和人体文件，无需再次下载。复制后在交接包目录复验：

```bash
/srv/signbridge-driver-venv/bin/python tools/sign-gpu.py verify --stage .
export PYOPENGL_PLATFORM=egl MPLBACKEND=Agg
```

驱动解释器放在交接包目录外，避免破坏 `SHA256SUMS`；`fit` 指向交接包内的工具和输入。Mac 上的 `local-data/sign-language-fit-plan-mac-v6/run.json` 已确认所需文件全部齐全，仍缺 NVIDIA CUDA 和该机器上的推理依赖；下载文件不等于运行了动作拟合。

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

## 2026-10-07 手部重建关键帧试修

### 现有结果与问题

- 两段重建分别为 `pilot-greeting-hello-001`（166/166 帧）和 `pilot-hospital-cough-003`（218/218 帧）；133 维导入、帧序、有限值及来源摘要检查通过。
- 原生网格抽检中，“你好”第 91 帧的并拢双指被重建成多指展开；“咳嗽”第 159 帧的握拳竖拇指也被重建成多指展开。错误已经存在于 SMPLer-X 叠加预览，不能靠修改 133 维导入顺序来解决。
- 抽检及局部连续帧证据不是全片质量通过证明。镜像方向仍为 `unknown`，接触、时序、手语语义仍待验收，`training_ready=false`。

### 试修方法与保护范围

工具位于仓库的 `signbridge/src/tools/sign-hand-refine.py`。Python 3.8+；依赖 NumPy/SciPy/Pillow，GPU 模式另使用现有 torch、vendored smplx、pyrender 和 trimesh，不安装新依赖或下载新模型。

1. 只试修第 91、159 帧中**已经检测且视觉核对过的三只手**：第一帧双手、第二帧右手。第二帧缺失的左手观测不填零、不插值；不扩大到全序列。
2. 校验输入约定及 SHA-256、固定源码提交、完成任务、原生完整 axis-angle 参数、相机的准确图片/人物归属和 neutral 模型来源。正文档对应的 `run.json` SHA-256 为 `20f320c5bb3f4082e60d73b9f19ee3972a534785135f9098e34291f030526908`。
3. 稀疏 LBS 仅计算 55 个关节和 10 个指尖。每帧先与原生 CUDA SMPL-X 关节/指尖逐项比较，最大绝对坐标误差必须 ≤ `5e-5` 米；手部均值只加一次，`use_pca=False, flat_hand_mean=False`。不通过则停止，不继续优化。
4. 每只手从同一个原始帧独立拟合，只修改该手 45 个手指旋转分量及对应手腕旋转，固定相机、根部、形状、表情、其他身体关节及另一只手。目标是手腕相对和绝对 2D 投影，附原始姿态先验和旋转改变量限制；**不使用 MediaPipe 相对 z 作为米制 3D 监督**。
5. 候选要求优化正常收敛、手腕相对 RMSE 至少改善 20%、绝对/指尖误差不变差，以及旋转变化限制通过。不通过的手保留 baseline，原始优化提案单独保存。独立拟合结果合并后，再逐手检查实际投影（含 pose blend shape 的跨手影响），也不允许原本被拒绝的手变差；合并检查失败则整帧回退 baseline。像素误差下降只是候选门槛，不能证明深度、解剖姿态、握拳接触或手语语义正确。
6. 使用原生 CUDA SMPL-X 完整网格重新渲染原始/候选 A/B，渲染器总在 `finally` 中释放。保存全图和手部近景供视觉复核；不修改原重建、导入数据或训练状态。

输出目录必须新建且位于所有来源目录之外。`report.json` 记录原生数值对照、每手指标、来源摘要、失败原因；`baseline.npz` / `candidate.npz` 保留原数据类型；`*-optimizer-proposal.npz` 是未经接受或可能被拒绝的提案。`*-hand-compare.jpg` 为原图、原生 baseline、保存的候选近景；门槛失败时第三栏可能仍是 baseline，须结合报告查看，不能把第三栏当成修正成功。始终 `full_sequence_refined=false, training_ready=false`。

### Mac 一条命令启动、收取证据

自动化入口位于 `signbridge/src/tools/sign-hand-pilot.py`，只使用 Python 标准库、系统 `ssh/scp`。在 **Mac 终端**运行（不是在服务器提示符下）：

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py run
```

连接 `root@connect.cqa1.seetacloud.com:22210` 时，密码由 SSH 在用户终端读取，不交给助手或保存进状态文件。只上传小型试修工具及启动文件，不上传视频、不解压 9.2 GB 大包、不重新推理。远端以 `flock` 防止并行重复运行，使用现有 GPU Python，后台执行，不因 Mac 连接断开而主动取消。

- 原始结果只读：`/root/autodl-tmp/signbridge/pilot-job-20261007-122150-DECIeP/fits`。
- 新目录：`/root/autodl-tmp/signbridge/hand-keyframe-pilot-<日期时间>-<随机后缀>/results`。
- 本地状态及回传证据：`/Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/`；不提交 Git。
- 默认等待 300 秒。若尚未结束，不重复 `run`；换为 `collect` 收取证据或 `status` 读日志。重复 `run` 只复用已确认仍运行或正在打包的状态，不静默重启已完成试修。上传/启动阶段写入状态文件；若上传失败、启动未确认、进程中断或打包失败，明确报错并保留记录，不能把“未启动”误称为“后台仍运行”，也不自动重启。

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py status

/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py collect
```

`plan` 可离线显示范围而不连接服务器；`--state /绝对路径/state.json` 可读取指定试修记录。回传包和所有内部文件逐一校验，拒绝路径穿越、符号链接、重名文件及过大的归档；失败运行也回传日志及可用报告。退出码 0 的含义最多是“关键帧候选待视觉审核”，不是“整段修复/训练完成”。

直接 GPU 调用（上述启动器自动执行）：

```bash
/root/autodl-tmp/signbridge/envs/smplerx/bin/python /path/to/sign-hand-refine.py pilot \
  --batch /root/autodl-tmp/signbridge/sign-language-gpu-stage-v2/batch \
  --fits /root/autodl-tmp/signbridge/pilot-job-20261007-122150-DECIeP/fits \
  --smplerx-root /root/autodl-tmp/signbridge/sign-language-gpu-stage-v2/SMPLer-X \
  --fit-run-sha256 20f320c5bb3f4082e60d73b9f19ee3972a534785135f9098e34291f030526908 \
  --max-nfev 120 --output /path/to/new/keyframe-results
```

### 本地验证与尚未完成事项

独立完整 NumPy LBS 与稀疏 LBS 已通过合成旋转数值对照；也在已有真实 neutral 模型上作合成姿态对照（最大坐标误差约 `6.7e-16` 米）。这是 CPU 数学验证，不是用户视频修复或 CUDA 原生验收。新增测试覆盖缺失/NaN/错误帧/错误摘要/PCA/错误均值约定/路径覆盖的拒绝，受保护参数不变，合成拟合改善，单手和合并后门槛失败回退，渲染失败释放资源，上传/启动失败不误报运行，以及上传脚本/安全回传。新增手部工具测试 18 项、Mac 启动器测试 12 项均通过。

真实 GPU 关键帧修正仍需用户终端登录运行；取得 A/B 后再判断路线是否可用。通过关键帧视觉验收后，才设计两段全长的手部重估及遮挡/时序处理。其余 14 段和训练继续暂停；不能将两帧候选直接导入为完整训练序列。

## 测试与来源

```bash
.venv-sign-data/bin/python signbridge/tests/sign-motion.test.py
.venv-sign-data/bin/python signbridge/tests/sign-gpu.test.py
.venv-sign-data/bin/python signbridge/tests/sign-data.test.py
.venv-sign-data/bin/python signbridge/tests/sign-hand-refine.test.py
.venv-sign-data/bin/python signbridge/tests/sign-hand-pilot.test.py
cd signbridge && npm run verify
```

测试用临时合成视频/参数验证审核来源、时间与缺失 mask、摘要检查、路径安全、帧连续性、参数维数及顺序、缺帧拒绝、旋转角检查和完整转换。这些测试结果不代表已运行用户视频的 3D 重建。

官方参考：

- [SOKE](https://github.com/2000ZRL/SOKE) 与固定提交的 `mGPT/data/humanml/load_data.py`、`mGPT/utils/human_models.py`、`license.txt`。
- [SMPLer-X](https://github.com/MotrixLab/SMPLer-X) 与固定提交的 `main/inference.py`、`common/utils/human_models.py`、README。
- [SMPL-X 官方模型](https://smpl-x.is.tue.mpg.de/) 和 [SMPL 官方模型](https://smpl.is.tue.mpg.de/)。
