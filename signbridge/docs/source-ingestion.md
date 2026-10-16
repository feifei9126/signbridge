# 新视频批次接入

原始视频保留在用户指定目录，项目生成的数据统一写到 `local-data/`。文件授权、字幕语义、动作边界、重建质量和模型训练是不同的记录，不能用某一步通过来替代下一步。

## 可重复执行的流程

1. 用 `src/tools/sign-data.py scan` 生成原视频哈希、时长、分辨率和缩略图。确认文件授权来自用户后才使用 `--authorization-confirmed`。
2. 用 `src/tools/sign-source-inventory.py` 对旧来源清单按 SHA-256 比对。必须通过 `--exclude-root` 排除当前批次的整个生成目录，避免把刚扫描的视频当成旧来源。批内重复路径、跨批重复内容和新哈希分别记录；近似画面只能作复核线索。
3. 用 `src/tools/sign-source-candidates.py screen` 对选定来源做 macOS Vision OCR。保留每张抽样图、图像摘要、文本位置、置信度和名义时间。默认每 2 秒抽一帧，时间窗不是精确动作边界。
4. 用 `src/tools/sign-caption-candidates.py` 提取底部字幕及左右词汇面板。每个文字独立追踪连续出现，避免同一画面的两条文字互相打断。输出所有候选和每源最多三条优先复核项，保持 `text_verified` 为空、审批及训练标记为 false。
5. 从复核候选构造明确的 2D 参考计划，再用 `src/tools/sign-tutorial-reference.py` 提取 25 FPS 视频、MediaPipe 身体/双手/面部观测和叠加预览。缺失点保留 NaN 和检测掩码，不补点、不插值；这些观测不是 SMPL-X/MANO 旋转目标。

每次使用新的版本目录。失败证据、重复路径和暂未处理的来源保留在报告中，不删除原片，也不覆盖已发布证据。

## 2026-10-15：来源 5

原始目录 `/Users/mac/Desktop/手语/5/` 有 91 个视频文件、85 个内容哈希及 6 个批内重复副本，约 2.62 GB。与旧记录比对没有字节完全相同的视频；抽样画面比对并不构成内容不重复的保证。

当前有效索引位于 `local-data/data-expansion-20261015/source-5/inventory-v2/`。首轮临时索引误匹配了自己的 intake 清单，保留为中间记录；有效 v2 已排除整个当前批次，并有相对路径排除和批内/跨批重复测试。

85 个独立来源中，68 个先进入字幕候选筛查。9 个字母/手型参考、3 个跨语言/国际手语演示、3 个歌曲/舞蹈和 2 个讲解/服务视频保留在独立来源清单。这些分类仅来自文件名线索，不确认实际手语语言、流派或动作语义。

68 个来源保存 5,426 张 OCR 抽样图，生成 1,254 条文字候选及 38 条优先复核项。本轮先选择 24 段、约 5,700 帧作 2D 手部参考；连续叙事、地域变体、疑似动作说明和不完整文字保留作后续复核，未当作标准 CSL 训练标签。

旧来源 4 的 93 段 GPU 重建继续独立运行。来源 5 不改变旧任务、T08 checkpoint、Demo 动作或训练就绪标记。后续启动新拟合/训练前，应先复核这批字幕语义、精确动作边界和手别，再通过真实重建及动作质量门槛。

## 2026-10-15：来源 6

用户新授权目录 `/Users/mac/Desktop/手语/6/` 已单独接入 `local-data/data-expansion-20261015/source-6/`。39 个文件共 2,970,497,095 字节、约 4 小时 39 分钟，批内 39 个不同 SHA-256；与 23 份已登记旧清单比对，发现 1 个字节相同的旧来源。它的文件名是“第一课（入门）”，旧记录名为“一定能用上的日常【手语教学】（完结）”，没有重复计为新增。这里是文件摘要比对，不是完整的语义或重编码内容去重。

38 个新哈希中，29 个来源完成每 2 秒一次的离线 OCR，保留并验证 5,494 张图，提取 2,507 条未核验文字候选。8 个讲解、语序、鉴定及问答来源和 1 个歌曲来源保留为独立参考，不自动当作正确手语标签。分类依据仍只是文件名线索。

公共服务系列的“手语：…”标注位于画面上部，已新增显式标记与相邻续行的提取规则。该规则保留单行原文、位置和原置信度；低至 0.25 的显式标记只作待核候选，未提高 OCR 分数。多行几何邻近不保证语义连续，可能混入教学说明，必须对照原片。普通上方标题不因此成为标签。新候选不再默认声称 `zh-CSL`；同系列课程保守关联，镜像、人物与划分保持未知／未分配。

12 个候选窗口（85 秒、2,125 帧）完成 25 FPS 原片裁剪及 MediaPipe 2D 参考。初次提取成功 10 段；另 2 段的竖屏宽度缩放成奇数，H.264 编码失败。新增真实竖屏编码回归测试并使用 `force_divisible_by=2` 后，只在新目录重试这 2 段，旧失败证据和已成功结果完整保留。当前有效参考由 `hand-reference-v1` 的 10 段和 `hand-reference-retry-v2` 的 2 段组成，聚合关系见 `validation.json`。

7 段的至少一侧手部观测覆盖偏低；提取器左／右槽位分别有 483／939 帧达到当前 2D 观测阈值，不能解释成解剖侧别或手型准确率。NaN 和检测掩码保留，没有补点、插值或生成 SMPL-X/MANO 旋转目标。全部原视频摘要、OCR 图片摘要、参考包内部摘要、观测数组／掩码、时间轴及 24 段参考视频的完整解码与帧数核验通过。

复核入口：`source-6/review-v2/index.html`。页面合并展示 22 条优先／补充候选、39 个来源、103 张图片和 24 个原片／叠加视频，并预留媒体尺寸以减少加载跳动。桌面、平板、手机宽度及播放暂停通过实际浏览器检查。标签、精确边界、语言变体、镜像／手别和人物身份仍待人工确认；本轮未开始 GPU 拟合、模型训练或 Demo 动作扩充。

数据验证完成后，可用本地化的只读工具重新生成到一个新目录：

```bash
cd signbridge
node src/tools/sign-intake-review.mjs \
  --batch ../local-data/data-expansion-20261015/source-6 \
  --output ../local-data/data-expansion-20261015/source-6/review-v3
```

该工具要求 `validation.json` 已通过，验证来源与图像摘要，拒绝虚构审批、越界路径和覆盖已有复核目录；页面不含自动批准控件。

## 2026-10-16：来源 6 的窗口修订与重建候选包

对首轮 12 段回查原视频后发现，稀疏 OCR 的标题持续时间不能代表手语示范时间。“文创商店在那边”的原 9–19 秒窗口大部分是双手放下的口头讲解；“不是的，请跟我来……”原 0–5 秒也尚未开始手语。仅加大检测器能力不能解决这种取材错误。

本轮保留全部旧片段，新增 `source-6/refinement-20261016-v1/`。根据有摘要的原片首尾接触表，制作 12 条**助手目视粗边界及文字建议**，重新裁取原视频中的连续组合示范；部分建议补上了 OCR 漏掉的分句和错字，但 `text_verified` 继续为空，语义、边界和人类审批均未变为通过。新索引重复使用原候选 ID 标明修订关系，必须同时按输入摘要和版本目录定位，不能只凭 ID 覆盖旧记录。

新提取实际为 2,779 帧、111.16 秒；名义时间窗估计为 111.64 秒，不能把估计的 2,791 帧冒充实际帧数。两个窗口的实际视频比名义区间短约 0.08 秒，已列入时长差异标志；10 段靠近原视频结尾，仍需检查动作是否在源文件内完整结束。源时间映射是裁剪起点加 25 FPS 的名义时间，并非逐个原始 PTS 的精确对应。

同一配置的 MediaPipe 观测中，新窗口共有 2,237/2,779 帧检测到至少一只手，原窗口为 996/2,125；约为 80.5% 对 46.9%。这是不同时间窗中动作内容占比的对比，不是检测器准确率上升，也不是手语正确率。按原来的单侧低于 20% 规则，低覆盖片段从 7 段变为 1 段；该段多数为单手表达，不能凭另一侧缺失自动判错。所有缺失数据仍为 NaN 加原掩码，不填点、不改侧别。

`src/tools/sign-reference-refinement.py` 在新的输出目录内复核来源、旧／新片段、观测数组、时间轴、完整解码、实际帧数和摘要，并生成与既有候选序列 runner 兼容的 `signbridge-smplerx-candidate-sequences-v1` 包：12 个连续视频、原二维观测、逐帧名义时间映射、空的独立 MANO 关键帧清单及内部 SHA-256。它是实验重建输入，未启动 GPU、未产生 SMPL-X 参数、未训练。首次本地审计因摘要清单的写入顺序失败，保存在 `audit/failure.json`；修复并通过回归测试后重做至 `audit-v2/`，没有重跑视频提取。

有效入口：

- `source-6/refinement-20261016-v1/review-v1/index.html`：12 个原／新窗口对照，保留旧 OCR 和新的建议文字、关键帧及覆盖对比。
- `source-6/refinement-20261016-v1/audit-v2/report.json`：逐段实际帧数、覆盖、尾部风险及输入摘要。
- `source-6/refinement-20261016-v1/audit-v2/package/`：通过现有 `validate_package` 的连续重建候选输入。

复现时两个工具均须指定新的输出目录，避免覆盖证据：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-reference-refinement.py \
  --batch local-data/data-expansion-20261015/source-6 \
  --references local-data/data-expansion-20261015/source-6/refinement-20261016-v1/references \
  --output local-data/data-expansion-20261015/source-6/refinement-20261016-v1/audit-new
cd signbridge
node src/tools/sign-intake-review.mjs \
  --batch ../local-data/data-expansion-20261015/source-6 \
  --refinement refinement-20261016-v1/audit-v2/report.json \
  --output ../local-data/data-expansion-20261015/source-6/refinement-20261016-v1/review-new
```

下一阶段优先核对建议文字和首尾完整性，再用小批连续重建检查手部、相机和时序稳定性。候选包和数值核验不构成训练资格，不能据此制造语言、镜像、人物、split 或质量审批。

## 2026-10-16：来源 6 新服务器连续重建试跑

用户授权连接克隆后的新 GPU 端口 37077。新端口的 ED25519 公钥与旧端口 26919 已信任的公钥完全一致，连接使用旧记录作为 `HostKeyAlias` 并保持严格核验，没有修改主机信任文件。连接凭据不写入文件或报告。

新服务器的 RTX 4090 D、CUDA 推理依赖、SMPLer-X 固定提交、3 个公共模型／检测器资产和 9 个身体模型资产均通过检查。旧环境已有的一处 OpenGL 兼容修改原样保留，补丁及 307 个受 Git 管理的代码／配置文件摘要纳入本次来源记录。未重新安装依赖或修改 checkpoint。

克隆数据盘只余约 2.7 GB，系统盘还有约 28 GB，因此新任务单独写入 `/root/signbridge-runs/gpu-reconstruction-20261016-b2v1hmy0/`，不清理旧输入、结果或模型。启动前检查无旧推理进程，并为新来源任务持有进程级锁。

先从已冻结的 12 段／2,779 帧候选包派生 2 段／380 帧试跑输入：短句“好的，谢谢你的帮助”和较长的欢迎介绍。逐段原视频摘要、二维观测、帧映射和候选状态原样保留；派生包关联完整输入清单摘要。这里的 380 是连续视频帧数，独立 MANO 关键帧数为 0，与旧的 380 个 MANO 关键帧批次无关。其余 10 段保留待试跑质量检查。

试跑于北京时间 2026-10-16 09:42:55 启动，runner PID 为 2280，输出为上述目录的 `pilot-v1/`。已观察到真实 GPU 推理及逐帧参数／元数据／渲染生成。启动和预检证据已下载、核验至 `local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/remote-launch-evidence/`；该目录的 `handoff.json` 和带时间戳的 `status-*.json` 记录输入摘要及实际进程状态。

完成判定必须同时检查真实 runner／子推理进程退出、全部预期序列及帧集合、有限的原生参数形状、元数据路径、渲染可解码性和日志摘要。结果须另行下载并核验摘要，然后检查原片／网格对照及旋转时序指标。缺失检测保留缺失，多个轨迹不能当作单人完整序列，不提取不完整序列特征。名义源时间映射与片尾完整性风险继续保留。

本阶段是固定模型上的实验 SMPL-X 重建。文字、精确边界、动作质量、镜像、手别和人物仍待核验；`training_ready`、`model_training_ready`、`human_approved` 均为 false。没有开始 tokenizer／生成模型训练，也没有把试跑结果替换进 Demo。

### 试跑完成及余下候选续跑

两段试跑于北京时间 09:47:27 完成，真实 runner 和子推理进程已退出。380 帧均有准确的单人参数／元数据／渲染集合，无漏检。完整归档为 70,901,760 字节，下载后核验外层摘要及内部 1,579 个文件摘要；本地另行验证全部原生参数形状、浮点有限值、元数据到原输入 JPEG 的映射、逐帧解码、源片实际帧数及日志摘要。

本地交付位于同一任务目录的 `pilot-verified-results-83ud9eeq/`，原片／网格关键帧、完整对照视频和原始旋转指标位于 `pilot-review-v1/REVIEW.md` 及 `report.json`。两段身体／手部均无相邻旋转超过 90° 的帧过渡，手部中点残差 P95 约为 7.6–9.8°，仍需复核高频变化；这些指标不是手语准确率或动作质量审批。助手抽帧检查还看到欢迎片段开头夹带前一单词示范、感谢片段结尾夹带后一单词示范，保留粗边界风险；没有凭该检查填入人工审批。

在核验试跑证据后，将剩余 10 段／2,399 帧派生为与试跑 ID 完全不重叠的 `remaining-package/`。再次核验全部模型资产、工具及既有代码摘要并确认无活动推理后，于北京时间 09:52:25 启动新的 `remaining-v1/` 输出，runner PID 为 3501，日志为 `driver-remaining-v1.log`。试跑输出保持原样。启动证据已核验下载至 `remote-remaining-launch-evidence/`，阶段记录为 `RECONSTRUCTION-STAGE.json`；09:54 的状态快照确认子推理进程及逐帧输出正在推进。

后台监控 `signbridge-6-gpu` 每 10 分钟检查真实进程、进度、GPU 和空间，正常推进时不通知；结束后在新的本地目录归档、核验和制作覆盖全部 12 段的审阅材料，遇到有意义的异常或需人工动作质量判断时才通知。候选重建续跑不改变训练、语义、边界、手别或 Demo 集成门槛。

### 全批结构审计完成

10 段续跑于北京时间 10:18:02 完成。2 段试跑加 10 段续跑共 12 段／2,779 帧；两个归档的外层摘要和 1,579 + 9,813 个内部文件摘要均已下载并核验。续跑归档 SHA-256 为 `49933af621d2f41c332b20126bc6a74c36a5d1c0be14acb76d4bddee09e1a4c6`，内部清单摘要为 `61994d031aea9edf8434db324a8d73ac03d0b569e741e449c66cb611ddfcc0aa`。首批归档摘要为 `dc11bcc18537ce4ff9ac5b21002939d3bbca14c8d785997d687ea6eadd04e2ec`。

新增只读审计器 `src/tools/sign-candidate-fit-review.py` 及回归测试 `tests/sign-candidate-fit-review.test.py`。它把两次分开的候选重建与冻结的 12 段输入清单精确合并，核对归档内清单覆盖、压缩片帧数、逐帧源映射、参数字段形状／浮点有限值、单人轨迹、元数据和参数帧号、输入与渲染 JPEG 解码、日志摘要及对照视频帧数。缺失检测和多人帧会被单独列出，不插值、不补零、不平滑；时序旋转指标只作人工复核线索。

最终复核包位于 `local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/candidate-review-v4/`，入口为 `index.html`，详细报告为 `REVIEW.md`，结构化指标与来源摘要为 `report.json`。12 段各有关键帧对照图及完整原片／网格视频；整个包有自己的 `SHA256SUMS`。审计确认 2,779/2,779 帧均有恰好一个人物轨迹、完整原生参数／元数据／渲染，无漏帧、漏检和多人帧。10 段保留原片尾部动作完成复核标记，另 2 段保留名义与实际片长差异标记。动作语义、边界、手势准确性、人物／镜像／侧别和 Demo 适用性未获人工通过；报告中 `human_approved`、`training_ready`、`model_training_ready` 仍为 false。

复现时需另选从未存在的输出目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-candidate-fit-review.py \
  --package local-data/data-expansion-20261015/source-6/refinement-20261016-v1/audit-v2/package \
  --pilot-results local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/pilot-verified-results-83ud9eeq/evidence/pilot-v1 \
  --remaining-results local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/remaining-verified-results-nvbpi1k2/evidence/remaining-v1 \
  --ffprobe /opt/homebrew/bin/ffprobe \
  --ffmpeg /opt/homebrew/bin/ffmpeg \
  --output local-data/data-expansion-20261015/source-6/gpu-reconstruction-20261016-b2v1hmy0/candidate-review-new
```
