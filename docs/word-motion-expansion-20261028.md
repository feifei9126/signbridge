# 从六批授权视频扩展词语动作候选

本阶段在本机对已有六批视频建立可追溯的词语/短语候选库。它为独立词动作的后续连续三维重建和核验提供输入，不把字幕数量当作词汇识别准确率，也不把抽出的参考视频算成已训练动画。

## 范围

- 原片来自用户提供的桌面“手语”目录 1–6 批；CE-CSL 不在本轮视频挖掘范围。
- 逐路径保留 341 个现存视频，按完整 SHA-256 去重为 313 份内容；重复路径作为别名保存。
- 旧登记的 23 个失效路径中，22 个已按相同 SHA-256 找到现存别名，另 1 份历史内容仍缺失。缺项保留，未用相似文件代替。
- 参考已有定时字幕、教程标题、空间字幕候选、80 段教程参考及 57 段长课定位参考；另外对两份代词教学视频做本机离线密集 OCR。不同版本输入分别保存。
- 地域变体与指拼内容单独标注；其他手语语言、歌曲/编舞、讲解/评论类素材不自动当作 CSL 词动作。

## 从视频到候选的实际步骤

1. 验证原片路径位于授权批次内，并重新计算 SHA-256。每份字幕索引通过完整源哈希绑定原片，不靠文件名相似性或 source_id 后缀猜测。
2. 将重复出现、时间较窄的短字幕/标题以及已有教学标注提为候选窗口。明确引述的教学子单元保留其解释证据。长字幕保留为句子上下文，不按文字长度平均切词。
3. 使用 FFmpeg 提取独立视频与三个关键帧联系表，记录完整解码帧数、帧映射和视频哈希。复用旧参考片前检查相对路径、哈希和解码结果。
4. 仅在同一视频 SHA、完整连续拟合及可用帧槽完全覆盖候选窗口时，裁取既有骨骼显示投影。先检查原生文件清单哈希、逐帧参数/元数据哈希、精确帧/人物集合、数组形状/有限值和图像映射。五个独立 MANO 关键帧不充当连续动画。
5. 独立审核检查全部文件哈希、原片输入、每段视频的完整解码、精确帧映射、联系表以及骨骼裁片与其源数组的逐值一致性；计算原始旋转连续性指标，不自动平滑或补缺帧。
6. 在离线审阅页查看证据、按词/批次/来源检索；另外保存词库覆盖缺口和未启动的三维重建队列。

## 重要的数据契约

所有本次新生成资料均满足：

```json
{
  "text_verified": "",
  "human_approved": false,
  "training_ready": false,
  "model_training_ready": false,
  "word_boundaries_verified": false
}
```

- 字幕显示不证明相应手语动作的词义或起止位置正确。候选中可能有说明文字、OCR 误读、同词不同手语或不完整演示，审阅时必须回看原片。
- 时间为原片的名义秒数。未声称测量原片每帧 PTS，亦未声称新生成 JPEG 与历史推理输入 JPEG 字节相同。
- 三维文件是旧动作的有效上身显示投影，保留有效手部轴角，省略原生根节点、下半身、眼球、形状、表情和位移参数；它不是完整原生 SMPL-X 参数导出。原生文件与旧证据保持原样。
- 数值连续不等于动作正确、无穿模或可读。旋转跳变和手部残差只作风险提示，不能自动批准手语语义。
- 所有新文件属于本地研究候选。既有公开 14 T08 + 3 candidate + 83 fitted 动作包、旧审批与检查点保持独立；本轮不推送 GitHub，不启动训练，不接入 Demo 自动播放。

## 工具与复现

工作目录是仓库根目录。使用已有 `.venv-sign-data` 环境和 FFmpeg，无需新增依赖。

```sh
# 从已核验清点生成新的配方（输出文件必须不存在）
.venv-sign-data/bin/python signbridge/src/tools/sign-word-motion-library.py \
  --make-recipe \
  --inventory local-data/word-motion-expansion-20261028-v1/discovery/video-inventory.json \
  --dictionary local-data/word-motion-expansion-20261028-v1/dictionary-lexicon.json \
  --native-map local-data/word-motion-expansion-20261028-v1/discovery/native-motion-map.json \
  --tutorial local-data/tutorial-hand-reference-20261010-v2/fitting-reference-index.jsonl \
  --recipe /absolute/path/to/new-recipe.json

# 先估算候选数量与总时长，不生成片段
.venv-sign-data/bin/python signbridge/src/tools/sign-word-motion-library.py \
  --recipe /absolute/path/to/new-recipe.json \
  --output /absolute/path/to/new-candidates --dry-run

# 提取到新目录；禁止覆盖已存在结果
.venv-sign-data/bin/python signbridge/src/tools/sign-word-motion-library.py \
  --recipe /absolute/path/to/new-recipe.json \
  --output /absolute/path/to/new-candidates --workers 4

# 独立审核到另一个新目录
.venv-sign-data/bin/python signbridge/src/tools/sign-word-motion-library.py \
  --audit /absolute/path/to/new-candidates \
  --output /absolute/path/to/new-audit --workers 4
```

`--make-recipe` 从清点确定性选择每源主字幕/标题/教学字幕，避免把全局索引的所有行错误归给单一视频。新增 OCR 索引用 `{path, source_sha256}` 绑定并加入新版本配方。`additional_input_files` 可保存用于此次提取的额外 OCR 帧、工具与日志。

审核页装配：复制 `src/tools/word-motion-review.html` 为输出根的 `index.html`，CSS 为 `review.css`，用已有 esbuild 将 `word-motion-review.js` 打包为经典 IIFE `review.js`；同目录先载入生成的 `review-data.js`。无需网络或本机服务。装配后生成覆盖页面文件的最终 `SHA256SUMS`，再做独立审核；截图/验证报告放在结果目录之外，避免审核后改变封存清单。

## 结果文件与后续

- `report.json` / `candidates.jsonl`：候选来源、窗口、提取结果及未核准状态。
- `caption-context.jsonl`：仅供上下文查找的字幕，不作为词动作。
- `coverage.json` / `video_path_coverage`：全部视频与重复别名的覆盖和排除原因。
- `lexical-coverage.json`：已内置词库别名与候选的精确文本对应、代词缺口；相同标签不构成语义批准。
- `reconstruction-queue.jsonl`：只有参考视频、尚无可复用骨骼的候选；`automatic_launch_allowed=false`。
- `native-candidates/`：满足全部技术门槛的现有骨骼显示投影裁片。
- `inputs.json` / `input-snapshots.json` / `provenance-inputs/`：输入哈希和用于此次处理的元数据、工具及参数快照。原始视频不重复打包。
- `failures.json` / `exclusions.json`：失败和排除证据；失败不以空姿态、零值或插值替代。
- `SHA256SUMS`：精确覆盖交付目录的内部文件清单。

下一阶段优先从“我、你、他、我们、你们、他们、自己”和展示场景高频词开始核准完整窗口，再对缺少骨骼的候选进行独立连续三维重建。重建仍不同于语言理解训练；只有词义、词界、镜像/侧别和动作质量有证据时，才适合进入可组合词动作库。本阶段不能保证每段视频中的所有词已经提取或所有候选动作正确。

## 本轮实测交付（2026-10-28）

最终 `candidates-v2`：2,132 段候选视频、1,581 个原始文本标签、46,897 个上下文窗口、16 段既有骨骼显示投影裁片、0 项导出失败。另 2,116 段参考视频没有通过本轮复用条件的连续骨骼，保留在三维重建待办中。首轮两个旧数据兼容失败保留在 `candidates-v1`；第二版基于经哈希验证的首轮视频复用，补充旧序列描述/参考视频证据后修复，没有重新解码原片来重做全部提取。

全量独立技术审计验证 15,297 个交付内部文件、7,157 个当前输入哈希、2,132 段视频的 267,967 帧，并逐值验证全部 16 个骨骼裁片。其底层共使用 15 条既有完整序列、2,890 个原生帧；清点中的 198 条“完整序列可用”指历史清点状态，不能读成此次重新核验了全部 198 条的每一帧。

| 原片所在批次 | 本轮候选视频数 |
|---|---:|
| 1 | 198 |
| 2 | 482 |
| 3 | 2 |
| 4 | 970 |
| 5 | 413 |
| 6 | 67 |

候选按完整源 SHA 和窗口去重后归到一个现存原片路径。不同批次有相同视频别名时，这些数目不是各批次独立词汇量。另有 30 段指拼候选、8 段地域变体候选，在页面中可单独筛选。

代词候选：我 4 段、你 2 段、他 1 段、我们 3 段、你们 3 段、他们 2 段、自己 2 段；这些代词本轮可复用独立骨骼数均为 0。实际关键帧抽查发现“他”的短字幕窗口落在淡入阶段，“我们”的部分窗口含过渡，不能据此直接开始组合播放。新候选全部保持未核准，并未撤销旧动作已有的用户批准。

16 个骨骼裁片中 13 个触发手部中点残差 P95 > 10° 或关节相邻跳变 > 90° 的风险门槛。这是原始裁片的数值分诊，不是手语错误率，也不能用统一加大平滑掩盖。

另用 `sign-word-motion-visual-triage.py` 在 CPU 检查全部 6,396 个关键帧，逐候选绑定亮度、暗像素比例及可选 Haar 人脸检测。851 个候选触发至少一种复查提示，技术证据不可用为 0；**851 不是语义错误数量**。黑色背景可使实际有人物的画面被亮度规则提示；未检出脸也不能证明无人，且检出脸不证明此人在打手语。本工具不删除候选、不生成新词界、不批准动作。

```sh
.venv-sign-data/bin/python signbridge/src/tools/sign-word-motion-visual-triage.py \
  --report /absolute/path/to/new-candidates/report.json \
  --output /absolute/path/to/new-visual-audit \
  --expected-count 2132 --workers 4
```

浏览器验收覆盖全部 89 页、精确代词检索、三种来源范围、原片首/中/末视频的实际播放、移动端宽度及原生 JSON 访问。数据技术有效、播放可用与手语含义正确是三个分别检验的结论。

## 后续连续骨骼拟合输入

2026-10-28 的全局骨骼拟合运行还没有完成：本机 SMPLer-X 运行器的预检显示 CUDA 不可用、Python 推理依赖缺失；此前已授权的 GPU 服务两个 SSH 端口当前都返回 `connection refused`。因此本轮没有在本机模拟 CUDA、没有安装大模型依赖，也没有声称 2,132 条已经成为骨骼动作。

已用字节级 MP4 SHA-256 将 20 个重复编码片段合并为一次拟合任务，形成 2,112 个独立内容任务，同时保留全部 2,132 个候选标签/来源/原时间窗别名；拟合包共 265,686 帧。未发现既有 16 个上身姿态数组之间的逐值完全重复；相似动作不自动删除。

完整传输包位于 `/Users/mac/Desktop/手语/SignBridge-骨骼去重拟合包-20261028-v1/`，总共 4,774 个已校验文件；用 `BUNDLE-SHA256SUMS` 校验包内所有其它文件。主唯一视频输入位于 `fit-input/`，88 个逐批输入位于 `chunks/`，每批含自己的 SHA256 清单。

输入分为 88 个小批次，每批最多 24 个唯一视频、2,487–3,410 帧，均通过 SMPLer-X 连续帧输入契约校验。已有 200 帧序列实测输出约 16.9 MB，按旧样本比例粗估 3,410 帧批次的拟合渲染/参数约 288 MB；实际大小依分辨率和签者而变，应在 GPU 服务器上确认空闲磁盘并一次只跑一个批次。

服务器恢复后，在 GPU 环境的项目目录按批次运行，例如：

```sh
/root/autodl-tmp/signbridge/envs/smplerx/bin/python \
  /root/signbridge-runs/word-motion-expansion-20261028-v1/sign-source-catchup-smplx.py run \
  --package /root/signbridge-runs/word-motion-expansion-20261028-v1/chunks/chunk-001 \
  --smplerx-root /root/autodl-tmp/signbridge/sign-language-gpu-stage-v2/SMPLer-X \
  --python /root/autodl-tmp/signbridge/envs/smplerx/bin/python \
  --model smpler_x_h32 \
  --output /root/signbridge-runs/word-motion-expansion-20261028-v1/attempts/chunk-001-attempt-1
```

每批都应使用独立新输出目录，完成后先核实 `report.json`、原生参数/元数据/渲染、连续帧映射和 `SHA256SUMS`，再取回本机独立目录审计。失败批次保留证据；不要悄悄重跑覆盖。全部批次的完整原生输出预计约 20+ GB（只是按旧片段体积估算，不是实测全量输出），须先确认 GPU 主机的系统盘空间。本机 1.6 TB 空余磁盘不提供 NVIDIA CUDA 运行能力。

精确重复内容只合并拟合工作，别名表保留不同字幕标签。抽取窗口完全相同却有不同候选标签的片段不能自动选一个语义，也不能丢弃另一文字候选。骨骼结果仍是重建候选，不因拟合成功而语义正确或可进入 Demo。建议每批完成人工动作质量审阅后再决定是否集成。
