# 从已核对视频到 SMPL-X 动作

本阶段将已核对视频重建为 SMPL-X，并把**真实拟合结果**转换成 SOKE 的 133 维表示。**截至 2026-10-09，两段重建、导入、关键帧试修和只读出图已完成，但视觉审核仍发现手型/接触错误，正式训练状态保持 false。** 受限肘部模式改善了手腕位置，不代表完整手语动作通过。现已运行独立的 SOKE 动作 tokenizer 技术验证训练并保存权重：仅用于未审核数据上的训练链路联调，不是文字到手语生成模型，不是可部署结果。其余 14 段及正式生成器训练未执行。

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
3. **拟合前先做一次实际 EGL 小网格渲染，要求返回非空可见像素**；缺少 GLU、后端错误、空白输出等立即失败，不加载 CUDA 人体或进入优化。稀疏 LBS 仅计算 55 个关节和 10 个指尖。每帧先与原生 CUDA SMPL-X 关节/指尖逐项比较，最大绝对坐标误差必须 ≤ `5e-5` 米；手部均值只加一次，`use_pca=False, flat_hand_mean=False`。不通过则停止，不继续优化。
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
- 默认等待 300 秒。若尚未结束，不重复 `run`；换为 `collect` 收取证据或 `status` 读日志。重复 `run` 只复用已确认仍运行或正在打包的状态，不静默重启已完成试修；仅当上一轮退出码明确非零且本地拟合工具摘要已变化，才允许新建隔离任务，不删除旧任务。上传/启动阶段写入状态文件；若上传失败、启动未确认、进程中断或打包失败，明确报错并保留记录，不能把“未启动”误称为“后台仍运行”，也不自动重启。

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

独立完整 NumPy LBS 与稀疏 LBS 已通过合成旋转数值对照；也在已有真实 neutral 模型上作合成姿态对照（最大坐标误差约 `6.7e-16` 米）。这是 CPU 数学验证，不是用户视频修复或 CUDA 原生验收。新增测试覆盖缺失/NaN/错误帧/错误摘要/PCA/错误均值约定/路径覆盖的拒绝，受保护参数不变，合成拟合改善，单手和合并后门槛失败回退，渲染失败释放资源，上传/启动失败不误报运行，以及上传脚本/安全回传。手部工具测试 20 项、Mac 启动器测试 17 项均通过，包括渲染预检失败必须在 CUDA 加载/拟合之前退出、非空像素检查、失败阶段及 traceback 记录、显式 GLU 准备不启动 GPU、真实 shell dry-run 模拟拒绝升级/移除/无关软件、失败回传不能声称已产生候选。

真实 GPU 的第 91 帧拟合已执行并有部分候选参数，但尚未完成渲染和视觉审核；GLU 环境修复需用户终端登录执行，再取得完整两帧 A/B 后判断路线是否可用。通过关键帧视觉验收后，才设计两段全长的手部重估及遮挡/时序处理。其余 14 段和训练继续暂停；不能将两帧候选直接导入为完整训练序列。

## 2026-10-09：GLU 渲染失败及受控修复

已校验回传目录 `/Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-ln9bx0j6/verified`：任务为 `hand-keyframe-pilot-20261009-063407-oE5eJX`，退出码 2，错误 `Library "GLU" not found.`。此前的 `config` 导入问题已解决，不应重复修导入或重装 PyTorch。

- 第 91 帧双手独立拟合及合并投影门槛通过；合并后左手局部 RMSE 从 `24.0127` 降到 `6.1112` 像素，右手从 `36.6505` 降到 `6.2813` 像素。
- 原生 CUDA 最大坐标对照误差：baseline 约 `9.72e-7` 米，candidate 约 `9.40e-7` 米。
- 已保存第 91 帧的 baseline/candidate/proposal NPZ，但尚无 baseline/candidate 渲染或手部对比图；第 159 帧未开始。**这只是对 MediaPipe 估计目标的 2D 数值改善，不是手型、深度或手语质量通过证明。**

新增显式命令 `prepare-render`。正常 `run` 仍不自动安装依赖；此命令在远端检查 `libGLU.so.1`，仅当缺失时用 `apt-get` 安装 `libglu1-mesa`，带 `--no-install-recommends --no-upgrade --no-remove`。先检查英文 dry-run 计划，只允许新装 GLU 及必要的 `libopengl0`，拒绝其他包变更以及升级/移除已有软件；不升级 CUDA/Python、不开拟合/训练、不修改来源参数。检查完成后用现有 Python 验证 GLU 可加载、pyrender 可导入且选择 EGL；实际网格渲染在拟合工具的前置检查中验证。

在 **Mac 终端**依次准备 GLU 和提交已更新的两帧试修，准备失败时 `&&` 会阻止启动：

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py prepare-render && \
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py run
```

所有新失败报告包含 `error_type`、`failure_stage`、完整 `traceback`，`driver.log` 也记录 traceback。收取结果直接打印错误，不再在零候选的失败任务中固定宣称“本次只产生关键帧候选”。`prepare-render` 退出 0 只表示库加载/导入/后端选择通过，不等于实际渲染或手部修正已通过。

## 2026-10-09：候选门槛拒绝与只读复核

最新回传目录 `/Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-trkzf8dr/verified` 的 `report.json` 表示 `candidate_gate_failed`，不是 `failed`。实际 EGL 预检、两帧优化、原生 CUDA 关节/指尖对照及完整网格渲染均已执行，来源摘要末尾复核通过。

| 帧/手 | 局部 RMSE 原始 → 提案 | 绝对 RMSE 原始 → 提案 | 选择 |
| --- | --- | --- | --- |
| 第 91 帧左手 | 24.01 → 6.09 px | 25.81 → 8.69 px | 数值候选通过，非视觉批准 |
| 第 91 帧右手 | 36.65 → 6.28 px | 27.18 → 19.99 px | 数值候选通过，非视觉批准 |
| 第 159 帧右手 | 23.54 → 4.00 px | 16.05 → 19.24 px | 绝对误差变差，提案拒绝，candidate 保存 baseline |

第 91 帧合并后局部 RMSE 为 6.11/6.28 px。第 159 帧虽然相对手腕的手型投影更接近观测，但绝对位置不变差门槛未通过，不应删除或放宽门槛。原图右手拇指竖起，灰色网格图无法可靠确认手指关节与遮挡；也不能把被拒绝帧第三栏未变化误解为优化完全没有发生。

新增 `review`：**不调用 `fit_hand`、不修改已保存参数或候选选择、不新跑 SMPLer-X 网络**。它验证上一轮报告摘要、所有原始输入摘要、baseline 与原帧相等、受保护参数不变、合并候选与原选择策略相等，复算各手投影/手腕位置及原生 CUDA 对照，然后使用相同参数生成新的四栏诊断图：原图 / baseline / 已保存 candidate（拒绝时等于 baseline）/ 原始优化提案（NOT accepted）。

诊断图用相机坐标下的面法向显式颜色和深度测试的 EGL unlit 渲染，提高几何可读性；不声称原灰色剪影的底层光照原因已确定。此着色不改变任何顶点/旋转、不是视频外观或物理灯光真值、不代替手语视觉验收。`review` 退出 0 只意味着已重新出图，**原始 `candidate_gate_failed` 与 `training_ready=false` 不变**。

在 **Mac 终端**执行（不是再次 `run`，不需要重新补 GLU）：

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py review \
  --state /Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-065007-8f5GgO/state.json
```

`latest-review.json` 与拟合的 `latest.json` 分开保存，旧报告和图片保留。后台运行未结束时用 `collect-review` 收取图像，用 `status-review` 看日志；不要重复 `review`。文件名为 `*-hand-review.jpg`；`report.json` 包含 `new_optimizer_run=false` 与 `source_pilot_status`。新出图未经远端实际运行验证，尚不能声明光照或手型已修好。

手部工具本地测试 22 项、启动器测试 19 项覆盖只读复核无优化、原摘要/选择策略审计、独立状态、诊断面颜色不改几何，以及 EGL 渲染的明确着色旗标与资源释放。通过新诊断图后再决定是否扩大优化到相邻帧/腕部位置；不会以像素指标或两个关键帧作为完整训练序列验收。

## 2026-10-09：受限肘部位置试修

只读回传 `/Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-k99wh10f/verified` 已完成：`new_optimizer_run=false`、来源摘要和原生数值对照通过。诊断图可见第 91 帧双指候选明显改善，但接触、指尖间距与位置仍待验收；第 159 帧未接受提案更接近竖拇指握拳，但手指间隙/位置仍有问题。**没有任何完整序列被批准训练。**

右手手腕的投影误差：第 91 帧约 `32.79` 像素，第 159 帧约 `29.40` 像素；baseline、candidate 和 proposal 完全相同。旧模式只改变手指和手腕局部旋转，不能移动手腕关节位置。新增独立的 `run-elbow` 模式用于检验这个受限假设：

- 只额外允许对应侧肘关节旋转，最终旋转改变量最大 `15` 度，不是随意放开整条手臂。
- 肩膀、躯干、根部、相机、形状、表情和另一侧参数固定；不允许平移或跨侧交换。
- 加强绝对投影和手腕位置监督，保留旧的局部误差改善 20%、绝对/指尖不变差、收敛及旋转门槛；并额外要求明显偏移的手腕误差至少改善 20%。合并两手后再次复核。
- 使用独立的 `latest-elbow.json` 和新远端任务目录，不覆盖 `latest.json` 或旧参数；直接输出带法向诊断着色的 A/B，始终 `training_ready=false`。

服务器 GLU/EGL 已经通过只读复核，不必重新安装依赖。在 **Mac 终端**运行：

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py run-elbow
```

等待未结束时，不重复启动；用 `collect-elbow` 下载或 `status-elbow` 看日志：

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-sign-data/bin/python \
  /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py collect-elbow
```

这是新的两帧受控优化，不是完整视频重建。拟合仍从原始真实帧参数独立开始，不复用上一轮未接受的提案作为已批准姿态。回传报告记录 `fit_mode=hand_plus_elbow`、肘部旋转改变量、手腕误差前后、原生对照和完整来源摘要。

本地 28 项手部工具、20 项启动器测试通过：合成目标中旧模式手腕不能移动、新模式可改善位置；肘部用相对旋转总角度投影到 15 度内，不仅分别限制三个分量；肩膀/对侧改动拒绝；肘部变化正确合并到 candidate；独立状态与启动范围校验通过。真实 GPU 试修已执行，但仍未通过手型视觉验收。

如 15 度内的候选仍失败，应审计相机/镜像/遮挡和观测质量，再决定下一种约束；不要扩大关节自由度或降低门槛以凑通过。无论数值状态如何，完整时序、接触、手型与手语语义仍需要人工验收。

### 实际肘部试修结果

任务 `hand-keyframe-pilot-20261009-073446-J4C8jT` 采用总旋转 15 度约束、最多 200 次目标函数评估，三手通过数值门槛，状态 `keyframe_candidates_pending_visual_review`。手腕误差分别约为：第 91 帧左手 `8.94 → 0.53` px，右手 `32.79 → 4.20` px，第 159 帧右手 `29.40 → 0.37` px。

本地证据位于 `/Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-dl13uskz/verified`。查看三张 A/B 后，双指卷曲/接触关系仍不可靠；咳嗽候选不是可确认的握拳竖拇指。**所有数值候选仍未获完整动作/手语质量批准，不能写成已完成全片修正。** 之前 `072730-m2RWFf` 任务达迭代上限/肘部总角度不合格，其候选拒绝证据也保留。

## 2026-10-09：实际 Tokenizer 技术验证训练

用户明确授权直接登录服务器执行并监测训练。SSH 密码仅用于交互提示，未写入脚本、命令参数、文档或 Git。服务器维持现有 `torch 1.12.0 / CUDA 11.3 / RTX 4090`，没有升级环境；当前没有完整生成器依赖或预训练 tokenizer/mBart 权重。

新增 `signbridge/src/tools/sign-tokenizer-smoke.py`：使用官方 SOKE 固定提交 `5cbc55d84b5a7cbf05a9cf020c468052e8d94d00` 的 `VQVae`、EMA quantizer 和 ResNet 结构，运行**从零训练的小尺寸动作 tokenizer 联调**。不安装 Lightning/transformers，不调用语言模型，也不下载预训练权重。三个子 tokenizer 按官方维度划分：body+face `43`、左手 `45`、右手 `45`；合计约 266.7 万参数，不是官方完整宽度配置或 checkpoint。

- 输入为严格导入的两段**原始未审核**动作，166/218 帧、共 384 帧；不偷偷将两个修正关键帧当成全片修正。
- 必须显式 `--research-only`，保留 `model_training_ready=false` 和 `motion_review_status=needs_review`；拒绝错误路径、维度、帧数、非有限值、不完整导入和伪装成可训练的输入。
- 从零训练的 mean/std 只由本次训练样本计算，不能用于官方预训练 tokenizer；固定种子、批量、学习率和 500 步上限。
- 训练输出包含权重、归一化、三类动作 token、两段重建数组、历史 loss、来源摘要、原数据末尾复核和 checkpoint 重新加载检查。
- 全部误差是同一训练数据上的重建指标；没有独立验证/测试集，没有文字条件，不能宣称新句子生成能力、手语正确率或泛化。

首次真实任务 `tokenizer-smoke-20261009-074134-Q9JVxL` 在 RTX 4090 上完成 500 步、约 26 秒优化，归一化训练窗口 MSE `0.74390 → 0.02085`。保存 step 500 checkpoint 并重新加载完成编码/重建，两段输出 `(166,133)`、`(218,133)` 全为有限值。报告状态是 `research_smoke_trained_not_deployable`；`training_ready=false`、`deployment_ready=false`、`text_to_sign_trained=false`、`generalization_evaluated=false`。这是训练链路已运行的证据，不是手语大模型已训练好。

工具随后增加 checkpoint 重载误差一致性检查，再以新任务运行，旧任务不覆盖。所有模型/视频/SOKE 源码及下载结果放在 Git 忽略的 `local-data/`；SOKE 与人体文件仍按研究许可约束使用，不分发成产品模型。

最终验证任务为 `tokenizer-smoke-verified-20261009-074538-KncThF`，仍是 500 步/266.7 万参数；归一化训练窗口 MSE `0.74390 → 0.01473`，checkpoint 重载后的 MSE 与保存时一致。优化耗时约 24.84 秒，两个完整序列的样本内原始特征 RMSE 分别为 `0.02788`、`0.02371`（混合特征单位，不是手语准确率）。归档、内部文件和 checkpoint SHA-256 校验通过，当前训练脚本与回传脚本摘要相同；这证明训练技术验证确实执行了。

Mac 产物目录：`/Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-verified-20261009-074538-KncThF/verified`。权重为 `results/tokenizer-smoke.pt`（约 10.8 MB），报告为 `results/report.json`，曲线为 `training-curve.png`；两段各含 `reconstructed-133.npy` 与 body/left/right token 数组。脚本参数没有 SSH 密码，报告和 Git 也不含凭据。服务器任务已退出，GPU 释放，无后台训练任务运行。

GPU 手动复现入口如下（输出目录必须新建）：

```bash
/root/autodl-tmp/signbridge/envs/smplerx/bin/python /path/to/sign-tokenizer-smoke.py \
  --motions /root/autodl-tmp/signbridge/pilot-import-20261007-145811-33tXE7/motions \
  --soke-root /root/autodl-tmp/signbridge/research/SOKE \
  --output /path/to/new/research-smoke-results --research-only --steps 500
```

正式路线仍需要：获得完整高质量动作序列、按表演者/来源分组划分训练/验证/测试、验证正确预训练 tokenizer 与归一化、接入文本生成器，并用手语专家审核和独立测试衡量生成质量。当前烟测权重不得接入插件，也不得用训练 loss 下降替代这些验收。

## 2026-10-09：用户下载 MANO v1.2 后的准备

用户提供 `/Users/mac/Desktop/手语/mano_v1_2/`。已保留原下载目录，将所需文件按原字节复制到 Git 忽略的 `local-data/mano/`：

- `MANO_RIGHT.pkl`，3,821,356 bytes，SHA-256 `45d60aa3b27ef9107a7afd4e00808f307fd91111e1cfa35afd5c4a62de264767`。
- `MANO_LEFT.pkl`，3,821,391 bytes，SHA-256 `c4022f7083f2ca7c78b2b3d595abbab52debd32b09d372b16923a801f0ea6a30`。
- `MANO-LICENSE.txt` 为随包 `LICENSE.txt` 的副本；`manifest.json` 记录来源路径、文件大小、摘要和验证范围。

这些摘要用于本地文件身份和复制完整性核对，不是官方发布签名或官方账户下载的独立认证。没有修改模型文件，也没有复制额外的 SMPLH 男/女人体模型或执行包内旧示例代码。

两个 PKL 的只读结构检查通过：778 个顶点、1538 个三角面、16 个关节、10 个 shape 系数、45 维 hand mean 和 45×45 PCA 组件；数组有限、三角面索引有效、skin weights 归一化、joint regressor 形状正确。检查时仅允许 NumPy/SciPy 模型构造器，旧 Chumpy 对象以无计算行为的容器读取，不导入/执行下载包或 Chumpy 代码，不重写 PKL。

**这只代表 MANO 输入文件已准备，不代表 WiLoR 能加载或已经完成 CUDA 推理。** Manifest 中 `wilor_native_load_verified=false`、`cuda_inference_verified=false`、`training_ready=false`；后续须在独立手部重建环境中验证原生加载与已知关键帧。随包许可一并保留，尚未验证商业许可，模型不提交 Git、不放入插件发行包。

本次尝试获取官方 WiLoR 源码，两次均遇到 GitHub 连接/接收超时，尚未取得可用 checkout；未安装 WiLoR 依赖、未下载其推理权重、未启动服务器推理。不能把准备 MANO 文件描述成 WiLoR 环境或手部修复已经完成。

### 启用代理后的源码重试

用户启用网络代理后，官方 WiLoR 源码于 2026-10-09 下载成功，路径为 `/Users/mac/Documents/ChatGPT/signbridge/local-data/deps/WiLoR`，固定提交 `fcb911312a38fa8badd30d9656a167485d61b8f9`。实际 origin 为 `https://github.com/rolpotamias/WiLoR.git`；浅克隆包含 47 个跟踪文件，约 23 MB（含 Git 数据及示例资源）。`git fsck --no-dangling` 退出 0，工作区干净，无待初始化 Git 子模块。

来源和关键文件 SHA-256 记录于 Git 忽略的 `local-data/wilor-source.json`；第三方源码、MANO 文件和后续权重不提交到本项目。README 的参考环境为 Python 3.10、PyTorch 2.0.0、CUDA 11.7；其要求 `pretrained_models/detector.pt`、`pretrained_models/wilor_final.ckpt` 和 `mano_data/MANO_RIGHT.pkl`。目前只有源码/配置已下载，没有安装依赖、下载上述预训练权重或执行 WiLoR 原生 MANO 加载/GPU 推理。后续使用独立环境，不升级已跑通的 `smplerx` 环境，也不把源码下载成功视为模型可用或手部修复成功。

## 2026-10-09：WiLoR 权重与新 GPU 主机阶段验证

启用 Mac 系统代理后，命令显式经本地代理下载官方 README 指向的 `detector.pt` 与 `wilor_final.ckpt`。下载后的大小/SHA-256 与官方 Space 固定版本 `99fe3d7acff8104ecca1055df7467709506c2fa6` 的 LFS 元数据一致：

| 文件 | Bytes | SHA-256 |
| --- | --- | --- |
| `detector.pt` | 53,582,271 | `5ef3df44e42d2db52d4ffe91f83a22ce9925e2acc9abebf453f2c5d22e380033` |
| `wilor_final.ckpt` | 2,564,989,533 | `3e97aafc7dd08d883a4cc5a027df61fdb6fda6136dbd1319405413862ada6bb2` |

文件在 `local-data/deps/WiLoR/pretrained_models/`，记录在 `local-data/wilor-weights.json`。用户下载的 `MANO_RIGHT.pkl` 与官方 Space 同名模型摘要相同，没有重新下载或改写 MANO。Mac 的独立 `.venv-wilor` 完成 MANO CPU 数值加载、完整 WiLoR 约 6.41 亿参数权重检查及检测器推理；这些本地检查不冒称 CUDA。

用户随后提供新 GPU 主机 `connect.cqa1.seetacloud.com:26919`，本阶段只用这个端口，旧 `22210` 不再用于新任务。SSH 凭据仅输入交互提示，未写入工具/文档/配置。克隆主机保留旧视频、SMPLer-X、SOKE 实验产物，目标图片摘要相同；实测 RTX 4090/24 GB、CUDA 设备可用。

服务器新建 `/root/autodl-tmp/signbridge/envs/wilor`，Python 3.10、PyTorch `2.2.2+cu118`、torchvision `0.17.2+cu118`，其余固定直接依赖见 `signbridge/src/tools/requirements-wilor-pilot.txt`。`pip check` 和实际 CUDA GEMM 均通过。原 `envs/smplerx` 仍为 `torch 1.12.0/CUDA 11.3`，GPU 自检通过，未升级或替换。没有修改驱动或增加系统权限；原主机无 GPU 挂载的检查记录与新主机结果分开。

新增 `sign-wilor-pilot.py`：两帧限定推理、固定源码/配置/权重/MANO 摘要、完整 checkpoint `strict=True`（无 missing/unexpected keys），FP32、batch size 1、不使用 `--fast`、跳层或编译。手部类别明确为 `0:left,1:right`；只对图像空间顶点/关节做左手镜像并反转面索引，原预测 MANO 旋转矩阵以 right-canonical 约定保留。输出 NPZ、OBJ、检测框及手部对照图，始终 `training_ready=false`、`smplx_parameters_replaced=false`，不把 MANO 参数直接套入 SMPL-X 或插件。

首次 CUDA 推理任务 `keyframes-20261009-103036-gGmysJ` 在约 16.3 秒内完成第 91 帧双手、第 159 帧右手，置信度约 0.9065/0.8976/0.9092；姿态矩阵、网格/关节和数值来源检查通过。但首次渲染出现条带，**非空 EGL 像素不足以证明出图正确**，初始图像不可用于审核。

### 渲染失真根因和只读修复

在新服务器 NumPy 1.23.5/OpenBLAS 环境，复现了 `np.dot(matrix, homogeneous_vertices.T)` 对 778 个顶点的错误结果，而 `homogeneous_vertices @ matrix.T` 正常；指定 `OPENBLAS_CORETYPE=Haswell` 后，原失败方向误差为零。`trimesh.transform_points` 正好使用失败方向，造成手部顶点变形。这里只记录本机可复现现象，不泛称所有 NumPy/Trimesh 均有该问题。

共享渲染工具的固定 Rx(pi) 改为精确逐元素 `(x,y,z) -> (x,-y,-z)`，不依赖 BLAS、不改输入顶点/相机。只读重新出图任务 `rerender-20261009-105438-hduStU` 用原 WiLoR 保存参数，无模型推理/优化；核对初始归档所有内部摘要前后不变，三只手的渲染像素 bbox 都落在解析透视投影 bbox 的 2 px 取整容差内。原图/旧条带图保留，新的只读证据在：

`/Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-keyframes-rerender-20261009/verified`

初步视觉抽检显示，第 91 帧双指及第 159 帧握拳竖拇指的外形明显优于原全身 SMPLer-X 估计。但双手接触、深度、穿插、连续帧和手语语义仍未通过完整验收；不能把两帧候选变成训练序列。新工具增加投影-vs-渲染 bbox 门槛，遇到同类失真直接失败。最终完整 CUDA 回归用新任务保存，旧结果不覆盖。

最终任务 `verified-keyframes-20261009-110100-ETLZnv` 完成约 15.8 秒全模型 CUDA 推理，三手输出及渲染投影检查均通过，状态 `inferred_pending_visual_review`。最终结果、日志、依赖 freeze 和脚本已打包下载至 `/Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-keyframes-verified-20261009/verified`；外层和全部内部文件摘要校验通过，回传脚本与本地当前版本一致。原图、每手 `*-compare.jpg` / `*-overlay.jpg`、联合叠加图、原生 NPZ 和 OBJ 均保留。全部数组有限、旋转矩阵正交且 determinant 为 1；这不等于手语专家批准。

本阶段结束时，新主机没有运行中的 WiLoR/手部优化/tokenizer 任务，GPU 显存约 1 MiB（空闲），旧 CUDA 环境复核正常；所有训练/部署标志仍为 false。MANO 模型加载指 WiLoR 使用原 right model 并镜像左手图像几何，不表示单独 native left model 已测试。源码中的 `.py` 和模型文件保持摘要不变；WiLoR 仓库包含跟踪的 Python bytecode，初始 Mac 导入改变过这些缓存，后续推理用 `PYTHONDONTWRITEBYTECODE=1`，不得把 bytecode 缓存更改解释成源码改动。

GPU 调用入口（不含任何账号密码；输出目录必须新建）：

```bash
PYOPENGL_PLATFORM=egl OPENBLAS_CORETYPE=Haswell PYTHONDONTWRITEBYTECODE=1 \
/root/autodl-tmp/signbridge/envs/wilor/bin/python /path/to/sign-wilor-pilot.py \
  --wilor-root /root/autodl-tmp/signbridge/research/WiLoR \
  --mano-model /root/autodl-tmp/signbridge/research/mano/MANO_RIGHT.pkl \
  --batch /root/autodl-tmp/signbridge/sign-language-gpu-stage-v2/batch \
  --output /path/to/new/wilor-keyframe-results --device cuda
```

后续阶段才进行相邻帧时序试跑、MANO/SMPL-X 坐标与手姿态均值对齐，并由手语审核者确认后形成新数据版本。当前没有重建剩余 14 段、覆盖旧动作或开始新的正式生成器训练。

## 2026-10-09：下一阶段短窗口和 MANO → SMPL-X 对齐

用户授权自主运行到阶段结束，本阶段继续使用 `26919` GPU 主机。首次重连短暂断开，随后指定密码认证成功建立连接；没有切换未知主机、保存凭据或改动原环境。

### 短窗口真实推理

`sign-wilor-pilot.py --short-window` 的范围固定：第 88–94 帧和第 156–162 帧，共 14 张图、21 次目标手部观测。输入仍逐帧核对已有 frame manifest / SHA-256 / 时间/图片路径，输出按 segment/frame 分目录，不影响原关键帧工具的默认两帧模式。没有插值、填零、复制缺失手或平滑数据。

真实任务 `windows-20261009-120054-AQUSlM` 用完整 FP32 WiLoR 在 RTX 4090 上完成，约 24.7 秒。21 次目标手均检测到；七帧窗口内没有同侧多检测歧义，旋转/网格有限、渲染投影检查通过、来源末尾复核通过。`temporal_audit` 只比较相邻且唯一的真实检测，不跨漏检/歧义连接轨迹，使用旋转测地角；手指角变化 >45°、全局腕部朝向变化 >30° 或腕部 2D 步长 >40 px 仅提示复核，不自动判质量通过。

- “你好”左手最大相邻手指变化约 67.31°，右手约 58.97°；两手均提示第 91→92、92→93 帧。原视频可见此处实际从双指变为另一手型且有运动模糊，因此提示不能直接归因为抖动，更不能自动抹平动作。身份一致性只检查检测类别/唯一性，不等于真实遮挡期间的跟踪身份已获人工确认。
- “咳嗽”右手最大手指变化约 18.14°，没有触发上述提示；第 159–162 帧变化较小。仅七帧、0.24 秒相邻间隔的局部结果，不能证明完整 218 帧稳定或语义正确。

本地证据：`/Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-windows-20261009/verified`。外层归档和 132 个内部文件摘要通过，下载解包仍拒绝路径越界/链接/重名并限制文件数与大小。`results/*-window-sheet.jpg` 为七列原图/估计对照；`*-slow-review-5fps.mp4` 仅供慢速目视（原数据 25 fps，不改变序列时间和参数），对应 JSON 明确标记 playback 与 source fps 不同。

### 两个关键帧的原生 SMPL-X 对齐候选

新增 `sign-mano-align.py`，只用阶段 1 的第 91、159 帧保存参数：核对固定 WiLoR 报告 SHA、原始 inference 内部文件摘要、原 SMPLer-X run SHA、源码提交、输入 batch 和人体文件来源。阶段 1 预测 MANO 矩阵是右手规范坐标下的有效局部旋转；左手采用 `S R S`，`S=diag(-1,1,1)`，而非简单全轴角取负。转换为 SMPL-X 手部轴角输入时扣除其相应 hand mean **一次**；绝对腕部朝向转为原身体父关节的局部旋转。

直接骨骼对应得到姿态候选，形状/相机不同不可能保证两个网格完全相同。只拟合对应侧肘部相对旋转（总角度 15° 上限），每次根据父关节重新计算腕部局部旋转，保持 WiLoR 的有效手指姿态和绝对腕部朝向；不再次优化手指、不改变肩膀/躯干/根部/shape/expression、另一侧参数、相机或 translation。不复制 MANO betas/camera 到 SMPL-X。目标为 WiLoR 估计的图像投影，不是人体真值；baseline 数字因目标不同不能直接与 MediaPipe 审计数字混用。

任务 `alignment-20261009-121024-05RSFm` 已真实执行 CUDA 原生 SMPL-X 对照/渲染，全部候选通过数值门槛及合并后复核：

| 关键帧/手 | 绝对 RMSE 原始 → 保存候选（px，对 WiLoR 估计） | 肘部改变量 |
| --- | --- | --- |
| 第 91 帧左手 | 27.72 → 5.31 | 15° |
| 第 91 帧右手 | 29.38 → 5.57 | 6.41° |
| 第 159 帧右手 | 17.83 → 2.58 | 15° |

原生 CUDA 对照的最大绝对坐标误差约 `1.03e-6` 米，低于 `5e-5` 门槛。来源末尾复核通过，原 fits 未改动。新候选/原 baseline/逐手 proposal 分别保存，原始帧并未写回原数据集；图中手型明显改善，但接触、穿插、深度、形状差异和连续融合仍待独立审核。

证据在 `/Users/mac/Documents/ChatGPT/signbridge/local-data/mano-smplx-alignment-20261009/verified`：`results/report.json`、每段 `candidate.npz`/`baseline.npz`/`*-alignment-proposal.npz`、原生叠加图与四栏 `*-alignment-compare.jpg`。本阶段原生映射只验证两个关键帧，不声称已融合14帧或完成完整384帧动作。`alignment_candidates_pending_visual_review` 不等于可训练；所有 `training_ready` 和 `deployment_ready` 仍为 false。

最终重复任务 `alignment-final-20261009-122132-Oi6kdC` 在新 26919 主机完成，三手候选仍通过数值/保护门槛：手指最大相对变化约 64.61°、71.20°、77.28°，均低于 155°；对应局部腕部变化约 34.95°、24.29°、24.55°，均低于 80°；同侧肘部仍限制在 15°。最终下载证据位于 `/Users/mac/Documents/ChatGPT/signbridge/local-data/mano-smplx-alignment-final-20261009/verified`。这只是 WiLoR 估计到固定 SMPL-X 的姿态对应候选，三张最终对照图仍需人工判断双指接触、竖拇指握拳、深度和穿插；不自动写入训练数据。

本阶段测试覆盖相邻帧来源校验、14帧固定范围、漏检/歧义不跨帧补齐、姿态测地跳变提示、左手 proper reflection、手姿态均值恰好扣除一次、腕部父关节坐标、15° 肘部边界和参数冻结。阶段结束前确认 GPU 无活动任务，保留输出，不重建剩余14段或启动正式生成器训练。

下一阶段应在短窗口上验证融合结果的时序与接触，再扩大到两段全长，并由懂手语的审核者确认训练目标。不要直接把两个候选关键帧替换后称为全片训练数据，也不要用模型间投影误差下降代替手语正确性。

## 2026-10-09：14 帧连续 SMPL-X 融合候选

用户继续授权自主运行到阶段结束，本阶段**复用上一阶段的真实 WiLoR 短窗口参数**，不重新运行网络、不下载模型、不扩大至完整视频。`sign-mano-align.py --short-window` 固定在“你好”88–94帧（双手）、“咳嗽”156–162帧（右手），与 `sign-wilor-pilot.py` 共用范围定义；验证精确帧集合、唯一手身份、原始 `output_relative` 与参数摘要，不按“最像目标”的检测重新挑选手。

真实任务 `fusion-windows-final-20261009-132945-5kyw3D` 在新 26919 / RTX 4090 主机完成，状态 `alignment_candidates_pending_visual_review`。本地证据：

`/Users/mac/Documents/ChatGPT/signbridge/local-data/mano-smplx-fusion-windows-final-20261009/verified`

- 14帧 / 21个目标手候选全部通过逐帧与双手合并后的数值门槛，原生 SMPL-X CUDA 关节/指尖对照最大误差约 `1.16e-6` 米，低于 `5e-5` 门槛。渲染投影 bbox 校验支持原相机偏移主点和不同 fx/fy，未假定 WiLoR 的居中相机。
- 原始 baseline、每帧 candidate 和逐手 proposal 在新目录保存；原 fits、相机、身体形状、躯干、另一侧参数不被覆盖。肘部仍限定15°，有效手指旋转不优化，只做左右手/手部均值/父关节映射。各手拒绝时保存精确 baseline，不填补或伪造候选。
- 每段 `baseline-candidate-series.npz` 保存所有原生参数的 baseline/candidate 帧序列、真实 `frame_ids` / `(frame_id-1)/25` 时间戳、左右手 observed mask 和 candidate applied mask，以及 `training_ready=false`。两段各7帧，全部有限；打包数组逐项等于保存的单帧 NPZ。医院左手 mask 全false，表示未观察/未替换，不是检测到有效左手数据。
- 外部归档和134个内部文件摘要核对通过，回传3个脚本的摘要与执行时保存版本一致，输入/原fits摘要运行末尾复核通过。旧窗口和关键帧结果保留。最终本地增加未观测侧不得批准的 mask 校验后，用当前 `pack_series` 重新验证实际 GPU 输出：两段打包数组、时间戳、mask与重新构造值逐项完全相等；没有重写旧归档或伪称新 guard 曾在旧GPU任务中执行。

### 时序与回退审核

报告分别记录 baseline、WiLoR输入和融合candidate的相邻旋转测地角 / 腕部朝向 / 腕部像素步长。三个轨迹不存在候选-baseline切换；融合candidate没有相较WiLoR输入新增异常提示。“你好”两手仍在92、93帧触发提示，原图在此转换手型且有运动模糊，不能直接把提示当作抖动；“咳嗽”轨迹没有触发提示。

提示门槛只用于定位：最大手指变化>45°、腕部朝向变化>30°或腕部2D步长>40px。通过覆盖/无新提示不表示真实连续姿态、深度或语义通过。未执行平滑、插值、跨遮挡补全；帧间差异没有被人为删掉。

### 接触诊断仍未通过

双手融合的投影和外形有改善，但“你好”88–91帧的模型估计食指/中指指尖最小3D距离仍约 `5.80 / 3.58 / 3.14 / 3.98 cm`，原视频看起来有靠拢/接触。这不是人体真值或表面碰撞检测，但说明模型间投影误差下降不等于接触正确。

`contact_diagnostic` 仅记录模型估计的指尖3D/2D接近程度；即使距离为零也不自动批准，固定 `contact_approved=false`、`surface_collision_evaluated=false`。当前未加接触约束、未碰撞修复、未随意修改形状或深度来凑接触。不可宣称两段动作已获手语质量审核，更不可设置训练状态。

### 回传媒体与结束状态

本地 `results/*-fusion-sheet.jpg` 按原图/baseline/candidate三行展示7帧。`*-fusion-5fps.mp4` 为慢速复核，`*-fusion-25fps.mp4` 保留原帧率，两类视频实际均为7帧，`ffprobe` 帧数/帧率检查通过；生成的 `*-review-media.json` 明确原数据25fps、未平滑、不可训练。播放器的慢速帧率不修改参数时间轴。

本阶段结束时不启动新的网络训练，不修改已有133维训练联调数组。完整生成器仍待高质量动作、分组数据划分及手语专家验收。后续应优先研究两手接触/深度约束和转换帧可信观测，再考虑两段全长融合；不要用14帧短窗口代替完整384帧或16段数据集。

复现实验需传固定WiLoR报告摘要 `0620e8ce3a17920c9d082f5fa744855d0a0879acea621e1adbefa7f380919b2d` 与原SMPLer-X run摘要，例：

```bash
PYOPENGL_PLATFORM=egl OPENBLAS_CORETYPE=Haswell PYTHONDONTWRITEBYTECODE=1 \
/root/autodl-tmp/signbridge/envs/wilor/bin/python /path/to/sign-mano-align.py \
  --wilor-results /root/autodl-tmp/signbridge/wilor-jobs/windows-20261009-120054-AQUSlM/results \
  --wilor-report-sha256 0620e8ce3a17920c9d082f5fa744855d0a0879acea621e1adbefa7f380919b2d \
  --fits /root/autodl-tmp/signbridge/pilot-job-20261007-122150-DECIeP/fits \
  --fit-run-sha256 20f320c5bb3f4082e60d73b9f19ee3972a534785135f9098e34291f030526908 \
  --smplerx-root /root/autodl-tmp/signbridge/sign-language-gpu-stage-v2/SMPLer-X \
  --batch /root/autodl-tmp/signbridge/sign-language-gpu-stage-v2/batch \
  --output /path/to/new/fusion-window-results --short-window
```

## 2026-10-09：四帧双手接触假设的受限试验

用户授权继续下一阶段，新增 `sign-contact-pilot.py`，只检验“你好”88–91帧可能存在的双指靠拢/接触假设，不约束92–94帧的真实手型转换，也不改“咳嗽”窗口。没有再次运行WiLoR网络、没有上传新训练数据或改变相机/身体形状。

输入固定为上一阶段 `fusion-windows-final-20261009-132945-5kyw3D` 的候选，报告摘要 `c9762060a4fe24d44b3a095bbbdb857c82654d12fcd41281568be1665ccd00c2`，上游WiLoR仍为固定14帧输出。逐一核对两份旧归档内部文件及摘要、原fits-baseline相等、参数保护、人体文件和全部记录来源路径。报告和数据不携带SSH密码。

冻结手指有效旋转、双手绝对腕部朝向、相机、translation、肩膀、躯干、shape/expression，只联合调整两侧肘部，仍相对原fits限制总旋转15°，局部腕部变化不超过80°。手腕局部旋转仅随父关节变化补偿，绝对朝向最终保存误差均低于 `1e-6` radians。原融合/未接受提案/保存结果分开存，不覆盖原14帧序列。

每帧在不改动融合中选择最接近的一对食指/中指指尖作为固定实验目标；四帧实际选中两手中指 `[12,12]`。**该配对不是人工标注接触点，指尖距离也不等于表面接触或碰撞。** 目标用指尖XYZ差、WiLoR的2D投影、原融合腕部位置和小幅姿态先验。门槛仅是实验候选：距离≤1.5cm且至少缩小40%，每手绝对RMSE不得比原融合多2px、腕部误差不得多3px；即使通过也始终 `contact_approved=false`、`training_ready=false`。

### 数值检查与最终实际结果

第一轮在中间参数提前转换float32，微小有限差分可能被舍掉，导致接近原点停止；保留该轮 `contact-proximity-20261009-140117-Om7YX9` 为诊断，不把它当作可行性结论。新增回归测试确认 `1e-8` 肘部扰动必须保留，优化中间值改为float64，只在求解后转换回原参数dtype。独立合成案例还验证该求解器能缩小可行指尖间隙，不是固定拒绝所有输入。

最终任务 `contact-final-20261009-141346-2j9u2O` 正常收敛，所有提案原生CUDA数值对照通过，最大关节/指尖差约 `1.04e-6` 米，渲染投影校验通过，原来源文件末尾复核通过；结果是 **`contact_proposals_rejected`，不是程序崩溃**：

| 帧 | 原融合指尖距离 → 未接受提案（cm） | 左/右腕部误差原融合 → 提案（px） |
| --- | --- | --- |
| 88 | 5.80 → 4.58 | 1.90→10.42 / 2.82→2.02 |
| 89 | 3.58 → 2.38 | 2.12→6.81 / 2.56→6.58 |
| 90 | 3.14 → 1.75 | 0.39→4.14 / 3.26→9.00 |
| 91 | 3.98 → 2.89 | 1.90→6.73 / 2.99→5.97 |

四帧都未通过距离门槛，也都未同时通过投影保护；两侧肘部均接近15°上限。所有 `saved-candidate.npz` **逐项等于上一阶段fusion candidate**，手指参数精确不变，绝对腕部朝向数值不变（误差最大约 `6.3e-8` radians）。没有把未接受提案写回训练数组/旧结果，也没有扩大可动关节或调整相机凑通过。

原融合间隙主要是左右方向，不只是深度：原XYZ间隙的XY分量约2.92–5.68cm，Z差约0.01–1.17cm。这个受限单初始化局部试验只能证明**本次提案失败**，不是全局无解、也不是准确诊断原模型深度；不据此自动放开肩膀/手指或降低保护门槛。

### 本地回传与下一步边界

最终证据在 `/Users/mac/Documents/ChatGPT/signbridge/local-data/contact-final-20261009/verified`：`results/report.json`，四帧各有 `previous-fusion.npz`、`raw-contact-proposal.npz`、`saved-candidate.npz`、三份叠加图及四栏 `contact-compare.jpg`。外层归档、内部文件摘要与执行脚本核对通过，全部模型文件及视频留在Git忽略目录。回传日志及依赖freeze保留。

本地生成 `results/contact-hypothesis-sheet.jpg`、`contact-hypothesis-5fps.mp4`、`contact-hypothesis-25fps.mp4`，四栏原图/原融合/被拒绝提案/实际保留结果分开标注，`ffprobe` 确认4帧和指定播放速率。慢速复核不改变原25fps时间轴。

阶段结束仍保持 `training_ready=false`、`deployment_ready=false`、`contact_approved=false`，没有表面碰撞检测、平滑、全片重建或正式生成器训练。下一实验应先确认实际接触点、二维手部标注/遮挡、人体手部比例和模型坐标对应，再评估是否需要新的有证据支撑的身体联合约束；不要连续盲目增加自由度或把这4帧局部像素指标当作完整手语数据验收。

## 2026-10-09：接触与指尖对应只读审计

对 `pilot-greeting-hello-001` 第 88–91 帧完成 MediaPipe、WiLoR 和融合 SMPL-X 指尖对应审计。工具为 `signbridge/src/tools/sign-contact-audit.py`；输入均按 SHA-256 清单及报告交叉摘要校验。最终报告和逐帧叠加图保存在 `local-data/contact-observation-audit-20261009-final/`，目录内 `SHA256SUMS` 可独立复核产物。

- MediaPipe 与 WiLoR 输出像素单位的完整 5×5 指尖距离矩阵；融合 SMPL-X 输出模型坐标系下、米单位的 5×5 三维距离矩阵。证据包缺少逐帧相机元数据，因此不伪造 SMPL-X 二维投影，也不将不同单位的距离直接比较。
- 第 88 帧 MediaPipe/WiLoR 最近对都是左中指—右食指；第 89 帧两者不一致；第 90 帧 MediaPipe 右手未检出，不产生该来源的配对且不插值；第 91 帧三个来源的最近对都是中指—中指。
- contact pilot 固定的中指—中指只是待核验假设。几何最近点不是人工接触标签；此次审计没有修改拟合参数或批准训练，`contact_approved` 与 `training_ready` 仍为 `false`。
- WiLoR 的 MANO→OpenPose 映射、5 个 MANO 指尖顶点与 21 个手部关节逐帧核对通过，没有发现简单的索引错位。SMPL-X 掌部尺度约为 WiLoR/MANO 的 `1.1366–1.1580` 倍，指尖链长约为 `1.0538–1.0862` 倍；这是两个模型的几何估计差异，未执行尺度拟合，也不能单独证明哪一个更接近真实手部。

复跑应使用新的 `--output` 目录，并传入已核验报告的 SHA-256；不得覆盖原始拟合或已保存候选。手语标注人员确认指尖身份、镜像状态与真实接触之前，不应继续接触优化。

复跑入口示例（需换成新的输出目录）：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-contact-audit.py \
  --batch local-data/sign-language-gpu-stage-v2/batch \
  --wilor-results local-data/wilor-windows-20261009/verified/results \
  --wilor-report-sha256 0620e8ce3a17920c9d082f5fa744855d0a0879acea621e1adbefa7f380919b2d \
  --fusion-results local-data/mano-smplx-fusion-windows-final-20261009/verified/results \
  --fusion-report-sha256 c9762060a4fe24d44b3a095bbbdb857c82654d12fcd41281568be1665ccd00c2 \
  --contact-results local-data/contact-final-20261009/verified/results \
  --contact-report-sha256 77856f6a47abbc310407e1abe81d3817533b2c03f6f18082ff48a76803f4daaa \
  --wilor-root local-data/deps/WiLoR \
  --smplerx-root local-data/sign-language-gpu-stage-v2/SMPLer-X \
  --output local-data/contact-observation-audit-<new-run>
```

## 2026-10-09：14 帧双窗口时序审计

新增只读工具 `signbridge/src/tools/sign-temporal-audit.py`，复核 WiLoR 与融合 SMPL-X 的两个 7 帧窗口。报告位于 `local-data/temporal-hand-audit-20261009-validated/`，含逐帧五指最近对、来源分歧、MediaPipe 缺失、手腕/指尖步长分解和近景总览。来源目录和参数未修改，未运行 GPU、平滑、接触优化或训练。

- `pilot-greeting-hello-001`：MediaPipe、WiLoR、SMPL-X 三种最近对分别在 89/92/93、91/92/94、92/93/94 帧发生切换；88–94 中有 5 帧至少两个来源不一致。MediaPipe 右手第 90 帧缺失，不插值。
- `pilot-hospital-cough-003` 是单手窗口，双手最近对标记为不适用，不能将其统计成漏检或“零次配对变化”。右手 7 帧都存在，WiLoR 没有超过既有阈值的姿态跳变。
- SMPL-X 融合候选第 92→93 帧根平移改变约 1.777 米，去除共同平移后的腕/指尖最大步长仍约 0.125–0.142 米；该变化同时遇到手型转换和 WiLoR 跳变提示，当前无法判定是合法手语动作还是重建误差。
- 第 160→161 帧根平移改变约 0.941 米，但去除共同平移后的腕/指尖最大步长约 0.012 米、手指相对腕点的最大变化约 0.0014 米。这说明绝对 3D 坐标步长很大程度受 SMPL-X 每帧根/深度估计影响，不应直接当作手指抖动；本报告不把根平移解释为测量到的真实世界运动。
- 14 帧候选与各自 baseline 的受保护参数逐项一致，根平移变化沿用原始估计。腕部局部坐标只去除共同位移，未再次扣除根平移，也未去除旋转或形状变化；这些步长不是自动训练验收指标。

目前最有价值的下一步是人工逐帧确认“你好”92–94 的五指形状/转换与手掌遮挡，并检查 SMPLer-X 每帧相机深度估计；确认前不拟合平滑、尺度或接触约束，`training_ready=false` 保持不变。

复跑使用新的输出目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-temporal-audit.py \
  --batch local-data/sign-language-gpu-stage-v2/batch \
  --wilor-results local-data/wilor-windows-20261009/verified/results \
  --wilor-report-sha256 0620e8ce3a17920c9d082f5fa744855d0a0879acea621e1adbefa7f380919b2d \
  --fusion-results local-data/mano-smplx-fusion-windows-final-20261009/verified/results \
  --fusion-report-sha256 c9762060a4fe24d44b3a095bbbdb857c82654d12fcd41281568be1665ccd00c2 \
  --smplerx-root local-data/sign-language-gpu-stage-v2/SMPLer-X \
  --output local-data/temporal-hand-audit-new-run
```

## 2026-10-09：384 帧相机坐标实验

已从现有 26919 GPU 主机只读取回原始两段 `fits` 的 `run.json`、384 份相机元数据及384份参数，共769个文件，保存在 `local-data/camera-source-20261009/`。已验证原始run摘要、回传文件摘要、此前融合报告中的29项来源摘要；没有重跑网络或修改服务器环境。新工具 `sign-camera-audit.py` 在本地CPU完成全长相机坐标实验，输出为 `local-data/camera-reference-pilot-20261009/`。

固定H32的 `inference.py` 将人体裁剪框尺寸换算成原图虚拟焦距及主点。两段的逐帧焦距与原始 `transl.z` 相关系数分别为0.989、0.964；原坐标系随裁剪框变化，不应把原始深度差直接当成实际人物前后运动。

本实验每段固定参考焦距为全片焦距中位数、主点为图像中心，仅生成根平移提案。骨盆像素投影保持不变，其余关节/指尖的投影差单独统计。姿态、双手、面部和形状参数均不优化；没有时序平滑，也没有标定物理相机。

| 片段 | 原始最大相邻深度差 | 参考相机提案最大相邻深度差 | 关节/指尖重投影差P95 / 最大值 |
| --- | --- | --- | --- |
| 你好（166帧） | 4.860米 | 0.741米 | 1.835 / 6.349像素 |
| 咳嗽（218帧） | 2.436米 | 0.488米 | 1.305 / 3.707像素 |

“你好”92→93帧从1.777米变为约0.670米，“咳嗽”160→161帧的绝对深度差从0.940米变为约0.090米。这说明裁剪相机坐标变化能够解释一部分跳变；剩余变化依然需要重建/观测核验，不能据此认定真实深度已修复。

每段 `camera-proposals.npz` 保存完整原始/提案平移、帧号、时间轴、相机与重投影差；`camera-depth.png` 是全长曲线。已融合14帧另外生成 `reference-camera-review.jpg`，原图/原相机投影/参考相机提案分三行。提案没有写回原始fits、融合参数或133维训练数组，仍为 `training_ready=false`、`physical_motion_approved=false`。其余370帧的手部重建质量没有因此得到修正。

本地分析依赖由 `signbridge/src/tools/requirements-sign-camera.txt` 固定，验证环境为Python3.12；需要安装时只用于本地分析环境，不替换服务器的CUDA依赖。复跑使用新的输出目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-camera-audit.py \
  --fit-source local-data/camera-source-20261009 \
  --fit-run-sha256 20f320c5bb3f4082e60d73b9f19ee3972a534785135f9098e34291f030526908 \
  --batch local-data/sign-language-gpu-stage-v2/batch \
  --fusion-results local-data/mano-smplx-fusion-windows-final-20261009/verified/results \
  --fusion-report-sha256 c9762060a4fe24d44b3a095bbbdb857c82654d12fcd41281568be1665ccd00c2 \
  --smplerx-root local-data/sign-language-gpu-stage-v2/SMPLer-X \
  --output local-data/camera-reference-new-run
```

下一实验应先在稳定裁剪框的短窗口上验证剩余深度/手型变化，并评估画面重投影，再扩大至全片手部融合。相机坐标转换不会解决指尖接触、镜像或缺失的人工手型标签。

## 2026-10-09：稳定裁剪框的真实 GPU 短窗口实验

使用新的独立任务 `/root/autodl-tmp/signbridge/stable-crop-20261009-b9mgiypf`，在26919主机的RTX4090上重新运行固定版SMPLer-X H32，范围仍是“你好”88–94帧和“咳嗽”156–162帧。权重、固定源码提交、原始输入图片和人体文件摘要通过；沿用Python3.8/PyTorch1.12/CUDA11.3及现有兼容补丁，没有升级依赖。任务退出码0，14份参数的原生SMPL-X最大关节/指尖对照差约 `1.093e-6` 米，EGL渲染通过，来源末尾复核不变，GPU任务已经结束。

`sign-stable-crop.py` 根据原始窗口框的中心及宽高分别取中位数，为每段确定一个固定裁剪框。21次WiLoR目标手投影都在该框内。脚本只在新任务目录创建官方推理脚本的副本，加入固定框参数并替换裁剪框赋值，模型/检测/渲染逻辑沿用原实现，原始源码及fits均保留。官方 `--end` 是帧数，本实验传7，不传窗口最后帧号。

回传56个文件留在 `local-data/stable-crop-pilot-20261009/verified/`，包含计划、执行脚本、日志、14帧参数/相机/叠加图及报告，文件摘要全部通过。`sign-stable-crop-review.py` 的独立比较报告和四行原图/原始SMPLer-X/稳定裁剪SMPLer-X/WiLoR图保存在 `local-data/stable-crop-review-20261009-validated/`。

为避免将裁剪坐标变化直接算作模型改善，比较分成原始深度、原始参数换算到本次固定相机的深度、固定框重新推理的深度：

| 窗口 | 原始最大相邻深度差 | 原始参数换算到本次固定相机 | 固定裁剪重新推理 |
| --- | --- | --- | --- |
| 你好88–94 | 1.777米 | 0.721米 | 0.574米 |
| 咳嗽156–162 | 0.940米 | 0.319米 | 0.093米 |

这里参考相机由7帧窗口框确定，和上一阶段按全片焦距中位数得到的参考相机不同，数值不能不加说明地混用。深度单位仍是虚拟相机坐标，不是已标定的实际世界位移。本次没有设置时序平滑或接触约束，也没有用降低深度跳变的指标自动批准候选。

对相同WiLoR投影点的7帧平均绝对RMSE：你好左手 `19.61→18.86` 像素、右手 `22.16→21.88` 像素，咳嗽右手 `19.58→19.96` 像素。“你好”两手第93帧仍触发旋转复核提示。WiLoR是模型估计比较对象，不是独立人工真值；结果表明固定裁剪有助于相机一致性，但不能替代专用手部重建，手部误差并未一致改善。该表比较的是未融合的原始SMPLer-X与新重建，不是此前手部融合候选。

稳定裁剪结果没有覆盖旧融合、133维数组或完整视频；`training_ready=false`、`full_sequence_refined=false` 和 `contact_approved=false` 保持不变。下一步应在该基线上评估已有WiLoR→SMPL-X映射，检验手部投影改善和相机一致性能否同时保留，再考虑扩展全长。

本地复核命令（使用新的输出目录）：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-stable-crop-review.py \
  --fit-source local-data/camera-source-20261009 \
  --batch local-data/sign-language-gpu-stage-v2/batch \
  --stable-results local-data/stable-crop-pilot-20261009/verified/results \
  --stable-report-sha256 aea092ab2020e8549738799a87afd9b2c79d1fdedbbc054a2b4b1d479ff7da26 \
  --wilor-results local-data/wilor-windows-20261009/verified/results \
  --wilor-report-sha256 0620e8ce3a17920c9d082f5fa744855d0a0879acea621e1adbefa7f380919b2d \
  --smplerx-root local-data/sign-language-gpu-stage-v2/SMPLer-X \
  --output local-data/stable-crop-review-new-run
```

## 2026-10-09：稳定裁剪基线上的 WiLoR→SMPL-X 融合

本阶段复用此前14帧WiLoR输出，在稳定裁剪重建参数上应用相同的左右手/均值/父关节映射和15°肘部约束。`sign-mano-align.py` 新增显式稳定裁剪来源校验：`--stable-report-sha256` 和 `--stable-source-manifest` 与 `--short-window` 配合使用，验证完整帧范围、固定相机、已通过的原生数值对照、参数摘要和原始run来源。不把稳定裁剪参数冒充原始逐帧fits，不改变已有候选接受门槛。

第一次任务 `stable-fusion-20261009-2_evo5je` 在导入阶段退出：SMPLer-X内置的smplx被PYTHONPATH优先选中，它需要WiLoR环境没有的mmcv，尚未开始拟合。错误日志和报告保留在 `local-data/stable-crop-fusion-20261009/failed-start-evidence/`。随后在新任务 `stable-fusion-native-20261009-4urlzway` 使用此前已验证的WiLoR环境独立smplx包运行，沿用Python3.10/PyTorch2.2.2+cu118，没有安装或升级软件。

最终GPU任务退出码0，21次目标手候选均通过现有单手及合并门槛。14帧保存候选的原生SMPL-X最大关节/指尖误差约 `1.059e-6` 米，EGL渲染投影检查及来源末尾复核通过。138个回传文件保存在 `local-data/stable-crop-fusion-20261009/verified/`，融合报告摘要为 `828183ce3116283b3e812d0915269ea5de3e7d2006306832299990b17408f69c`。

新增 `sign-stable-fusion-review.py` 独立读取保存参数，逐项确认其baseline与稳定裁剪原始输出相等、受保护参数不变、保存序列与逐帧参数/接受mask相等，并重新计算WiLoR投影误差，核对与GPU报告一致。复核输出在 `local-data/stable-fusion-review-20261009-validated/`，含原图/旧融合/稳定裁剪基线/稳定裁剪新融合/WiLoR估计的五行近景和深度/手部误差曲线。

| 目标手 | 旧逐帧裁剪基线 | 旧融合候选 | 稳定裁剪基线 | 本轮稳定裁剪融合 |
| --- | --- | --- | --- | --- |
| 你好左手 | 19.61像素 | 5.00像素 | 18.86像素 | 4.98像素 |
| 你好右手 | 22.16像素 | 4.72像素 | 21.88像素 | 4.72像素 |
| 咳嗽右手 | 19.58像素 | 2.51像素 | 19.96像素 | 2.59像素 |

表中是各7帧对同一份WiLoR模型估计的平均绝对RMSE，不能当成人工手型准确率。本轮手部拟合与旧融合基本持平；主要收益是保留稳定裁剪的相机一致性。根平移、形状、表情和非目标关节相对本轮baseline精确不变，相机仍固定；“你好”“咳嗽”窗口最大相邻虚拟深度差分别保持0.574米与0.093米。

“你好”88–91帧融合后的模型食指/中指最近间距约2.8–5.9厘米，接触仍未解决；92、93帧的两手旋转复核提示继续存在。“咳嗽”右手没有该阈值下的跳变提示。两段各7帧的candidate mask没有接受/回退切换，医院左手仍未观察、未修改。没有执行接触约束、碰撞检测、平滑或全片融合，原fits、旧融合和133维训练数组均保留，`training_ready=false`、`contact_approved=false`、`full_sequence_refined=false`。

复跑本地独立比较时使用新输出目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-stable-fusion-review.py \
  --batch local-data/sign-language-gpu-stage-v2/batch \
  --fit-source local-data/camera-source-20261009 \
  --stable-results local-data/stable-crop-pilot-20261009/verified/results \
  --stable-report-sha256 aea092ab2020e8549738799a87afd9b2c79d1fdedbbc054a2b4b1d479ff7da26 \
  --fusion-results local-data/stable-crop-fusion-20261009/verified/results \
  --fusion-report-sha256 828183ce3116283b3e812d0915269ea5de3e7d2006306832299990b17408f69c \
  --previous-fusion-results local-data/mano-smplx-fusion-windows-final-20261009/verified/results \
  --previous-fusion-report-sha256 c9762060a4fe24d44b3a095bbbdb857c82654d12fcd41281568be1665ccd00c2 \
  --wilor-results local-data/wilor-windows-20261009/verified/results \
  --wilor-report-sha256 0620e8ce3a17920c9d082f5fa744855d0a0879acea621e1adbefa7f380919b2d \
  --smplerx-root local-data/sign-language-gpu-stage-v2/SMPLer-X \
  --output local-data/stable-fusion-review-new-run
```

## 测试与来源

```bash
.venv-sign-data/bin/python signbridge/tests/sign-motion.test.py
.venv-sign-data/bin/python signbridge/tests/sign-gpu.test.py
.venv-sign-data/bin/python signbridge/tests/sign-data.test.py
.venv-sign-data/bin/python signbridge/tests/sign-hand-refine.test.py
.venv-sign-data/bin/python signbridge/tests/sign-hand-pilot.test.py
.venv-sign-data/bin/python signbridge/tests/sign-tokenizer-smoke.test.py
.venv-sign-data/bin/python signbridge/tests/sign-wilor-pilot.test.py
.venv-sign-data/bin/python signbridge/tests/sign-mano-align.test.py
.venv-sign-data/bin/python signbridge/tests/sign-contact-pilot.test.py
.venv-sign-data/bin/python signbridge/tests/sign-contact-audit.test.py
.venv-sign-data/bin/python signbridge/tests/sign-temporal-audit.test.py
.venv-sign-data/bin/python signbridge/tests/sign-camera-audit.test.py
.venv-sign-data/bin/python signbridge/tests/sign-stable-crop.test.py
.venv-sign-data/bin/python signbridge/tests/sign-stable-crop-review.test.py
.venv-sign-data/bin/python signbridge/tests/sign-stable-fusion-review.test.py
cd signbridge && npm run verify
```

测试用临时合成视频/参数验证审核来源、时间与缺失 mask、摘要检查、路径安全、帧连续性、参数维数及顺序、缺帧拒绝、旋转角检查和完整转换。这些测试结果不代表已运行用户视频的 3D 重建。

官方参考：

- [SOKE](https://github.com/2000ZRL/SOKE) 与固定提交的 `mGPT/data/humanml/load_data.py`、`mGPT/utils/human_models.py`、`license.txt`。
- [SMPLer-X](https://github.com/MotrixLab/SMPLer-X) 与固定提交的 `main/inference.py`、`common/utils/human_models.py`、README。
- [SMPL-X 官方模型](https://smpl-x.is.tue.mpg.de/) 和 [SMPL 官方模型](https://smpl.is.tue.mpg.de/)。


旧版 SMPLer-X 的 vendored SMPL-X 源码会使用顶层 `from config import cfg`。试修启动时会显式加入固定源码的 `SMPLer-X/main` 和 `common/utils/smplx` 到导入路径，并校验实际载入的 `smplx` 来源；因此试修脚本不依赖当前工作目录。
