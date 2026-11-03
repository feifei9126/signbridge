# SMPL-X 动作分流归档（2026-11-03）

按用户指示将需人工审阅的数据暂存，停止该分支的后续处理；未触发自动风险的数据继续完成下一轮技术整理。本次全部在本地运行，没有使用 GPU、启动训练或修改 Demo。

## 本次实际结果

输入为全量独立审计和已校验的原片/网格审阅包，覆盖 2,112 段、2,132 个别名。

| 分流 | 数量 | 本次处理 |
| --- | ---: | --- |
| 人工审阅暂存 | 1,853 段 | 1,658 段动作风险、195 段漏检；独立离线页面、原片、网格对照、关键帧、风险记录、空白审阅表；封装并验证 ZIP |
| 自动候选技术整理 | 259 段 | 28,041 帧原始参数无损堆叠；源文件哈希复查；额外旋转时序检查；精确内容去重 |

技术候选保留 261 个别名、227 种候选标签；没有发现全参数和帧率完全相同的动作，保留 259 个独立原始参数文件。新增根部、下颌和双眼旋转检查未触发额外风险。这里的候选标签数量不等于已核准中国手语词条数。

## 本地交付

目录：`/Users/mac/Desktop/手语/SignBridge-动作分流-20261103-v1/`

- `manual-review.zip`：人工审阅暂存包，解压后打开 `manual-review/index.html`。`review-decisions.csv` 的审阅字段全部为空。本分支没有安排后续任务。
- `technical-round.zip`：下一轮技术整理结果。`native/` 保存无损参数，`index.json` 保存来源、别名、原始风险指标、额外检查、每个原始 NPZ/metadata 文件的哈希；`evidence/index.html` 是 259 段的独立对照页。
- 两个 ZIP 均有 `.zip.sha256`；各自内部有 `SHA256SUMS`。归档完成后直接读取 ZIP 内每个成员，核验精确文件集合和全部内部哈希。
- `report.json`：完整不重叠分流名单、数量、输入/工具来源和归档校验记录。

原全量审计目录、原始逐帧参数、视频、JPEG、metadata、日志、历史证据均保留。本轮没有改写它们。

## 数据契约

工具：`signbridge/src/tools/sign-smplx-post-stage.py`。

参数容器保留原始 `global_orient`、`body_pose`、`left_hand_pose`、`right_hand_pose`、`jaw_pose`、`leye_pose`、`reye_pose`、`betas`、`expression`、`transl`。只增加帧轴和 `frame_ids_1based`；不转换 float32/float64，不降采样、不平滑、不插值。每个保存后的数组重新打开并与内存源数组逐项核对。

精确去重将帧率、参数名、dtype、shape、原始数组字节共同纳入 SHA256。只有完全相同时共享一个参数容器；所有候选 ID 和别名继续保留。相同中文标签不会触发动作合并。

额外时序检查复用独立审计的 SO(3) 相邻旋转角和测地中点残差。根部、下颌、双眼沿用相邻角 90°、中点残差 30° 的未校准风险阈值；短于三帧或新增异常转回暂存包。位移、形状和表情只报告原始数值变化，没有用未经验证的阈值判定手语质量。

没有提取训练特征、创建训练集划分或训练模型。所有输出保持 `human_approved=false`、`semantic_approved=false`、`training_ready=false`、`model_training_ready=false`、`training_started=false`、`feature_extraction_allowed=false`、`demo_integration_ready=false`、`text_verified=""`。

自动阈值未触发不代表零抖动、无穿插、人物身份稳定或词义正确。词义、词界、镜像和手性仍未核准；既有 `attempt_proofs_verified=null` 来源缺口原样记录，不补造历史证明。

## 复现与验证

```sh
.venv-sign-data/bin/python -B signbridge/src/tools/sign-smplx-post-stage.py \
  --audit '/Users/mac/Desktop/手语/SignBridge-全量重建审计-20261103-v1/native-smplx-post-audit-20261103-v1/report.json' \
  --review '/Users/mac/Desktop/手语/SignBridge-全量重建审计-20261103-v1/review-v1' \
  --output '/absolute/new-output-directory'
```

输出必须是新目录；原证据不变即为恢复基线。回归测试覆盖分流完备且不重叠、禁止隐式批准、精确帧集/浮点值/形状/dtype、原始文件篡改、根部突变转人工、去重不丢别名、目录穿越和 ZIP 内部哈希。

本轮 `npm run verify` 退出码为 0：构建、ESLint、Prettier 通过，295 项 JS 测试通过；Python 共运行 719 项，其中 12 项跳过，其余通过。两个 ZIP 在构建时及另一轮独立读取中核验了全部内部哈希；分流 ID 精确覆盖一次。独立复核另对全部 259 段的首/中/末帧做了 7,770 组原始数组字节对照，并检查全部堆叠数组为有限值。
