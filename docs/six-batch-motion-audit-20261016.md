# 六批动作逐项质量检查

2026-10-16 的基线检查和修复后逐项报告分别是本地 `local-data/six-batch-motion-audit-20261016-b3j952wo/review-v5/index.html`、`review-v6/index.html`，文字结论在 `review-v6/REVIEW.md`，逐项结果在 `review-v6/report.json`。最新页面包含 336 张对照表，并通过原视频 SHA-256 重新归属批次 1–6；训练轮次 T01–T10 与视频批次分开统计。两句显示修复包位于 `display-fix-v2/`，隔离 Demo 在 8768 端口；原 8766 Demo 也已由修复版资产重建。

检查覆盖 200 条连续原生重建任务、24 条二维参考、685 个独立身体关键帧、665 个独立 MANO 案例、62 条保存的训练解码，以及 112 条当前 Demo/独立预览动作。这些阶段有对应和重复，不能相加当作句子数。341 个当前原视频文件也逐一记录有无对应阶段结果，没有完成结果的视频不视为已训练。

| 视频批次 | 连续完整/任务 | 完整轨迹触发原始时序筛查 | 基线 Demo/预览触发筛查 |
| --- | --- | --- | --- |
| 1 | 19/19 | 19 | 0/17 |
| 2 | 15/15 | 13 | 无当前运行时动作 |
| 3 | 61/61 | 54 | 无当前运行时动作 |
| 4 | 91/93 | 91 | 2/83 |
| 5 | 只有 24 条二维参考 | 三维稳定性不可评估 | 无当前运行时动作 |
| 6 | 12/12 | 10 | 0/12 |

原始筛查包含 Demo 未映射的身体关节，且快速手势也可能触发尖峰，不能把这一列直接当成错误句子数。当前显示指标采用实际 Godette 骨架、现有映射和现有默认平滑；未新增平滑、未改写参数或检查点。

确定缺失：第 4 批「基本」缺原生参数帧 221–227，「人民」缺 1–45；第 2 批 `shouyu-cand-4d36e4ad-01-f000025` 独立身体关键帧无重建。缺失不得补零或插值。MANO 的 13 个无检测案例与可选二维观测缺失继续显式保留；全 NaN 的可选 `mediapipe_slot_xy` 不等于三维拟合损坏。

基线检查发现当前显示超过手腕残差 P95 2cm 的两句：

- 「手语要多练习才可以熟能生巧」：2.27cm，重点帧 184、192、187、194、261。
- 「从今天起就由我们来给大家讲手语课程」：2.64cm，重点帧 248、240、237、247、238。

这两句已在独立构建中采用 100 ms 手臂窗口的显示恢复配置；复测分别为 0.57 cm、0.59 cm，显示动作范围保留约 89%、84%。原始姿态仍可切换且参数数组未更改。第 4 批「基本」「人民」缺失轨迹继续排除，见 `display-fix-v2/recovery-report.json`；没有伪造帧或插值。

原始相邻旋转 >90°、单关节中点残差 >30°、总体残差 P95 >10° 用于定位可疑帧。当前人物筛查使用角度残差 P95 >10°、手腕残差 P95 >2cm 或相邻旋转 >90°。它们是排查阈值，不是手语正确率或无穿模证明；T09/T10 更平滑也不代表比 T08 更准确。T03–T05 的 6 条历史解码、T06/T07 各 1 条触发人物筛查，没有替换当前 T08。

10 份权重均与冻结摘要一致；8 份历史证据清单的 171,685 个条目重校验一致。早期溯源限制及第 4 批原始 JPEG 摘要缺口继续保留。全帧执行结构、数值、时序和人物骨架检查；原片/重建对照图为采样，当前 112 条人物动作各捕获 3 个确切帧的原始/当前显示图。没有声称逐段人工观看全部视频或完成语义批准。

修复后的六批逐项页位于 `local-data/six-batch-motion-audit-20261016-b3j952wo/review-v6/index.html`。它引用修复版 112 段重测结果：两句手腕残差 P95 均低于 2 cm，动作仍标为需要人工语义和手型复核；两条缺帧结果继续列为错误并排除。基线审计 `review-v5/` 保持不变。复核工具按阶段运行，所有输出均要求新目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-batch-motion-audit.py \
  --plan local-data/six-batch-motion-audit-20261016-b3j952wo/plan.json \
  --output /path/to/new-native-audit

.venv-sign-data/bin/python signbridge/src/tools/sign-batch-evidence-review.py \
  --root local-data/six-batch-motion-audit-20261016-b3j952wo \
  --output /path/to/new-evidence-review

node signbridge/src/tools/sign-batch-avatar-audit.mjs \
  --report /path/to/new-evidence-review/evidence-review.json \
  --output /path/to/new-avatar-review
```

`sign-batch-avatar-capture.mjs` 使用本地 Playwright/Chrome、真实模型和同一映射，仅监听随机本机端口；抓取结束释放 Three.js 材质、纹理、几何体及 WebGL 上下文。`sign-batch-audit-gallery.py` 读取本次冻结阶段目录、生成本地报告，`--sheets-from` 可校验并复用旧对照图，输出仍是新目录。

中间版本保留：`evidence-review-v1` 曾把缺失的可选二维观测误记为非有限拟合，已由 v2 更正；`avatar-audit-v2` 绑定更正后的报告。`review-v1` 因本机字体路径缺失未完成，v2 起生成成功，v3 补充来源覆盖、二维低覆盖标记和完整对照视频链接，v4 修正手机表格溢出，v5 绑定格式化后重跑且数值一致的 avatar-audit-v3，并补全机器报告的视频路径。原生初版工具快照保留在 `tool-snapshots/`，其摘要与原生初版报告绑定；当前工具另有元数据孤立文件的计数回归修复。

此次显示修复不产生新的 `human_approved`、`training_ready` 或 `model_training_ready`，不开展生成模型训练、不更新 T08。后续需处理两条缺帧并人工确认边界、手型、镜像、接触及语义。

## 中国手语语义原型

2026-10-17 已确认目标语言为中国手语，并新增一个受限语义原型。原型将中文解析成角色和操作符，再检查动作证据；不会把中文整句直接当作中国手语翻译。支持的简单句只用于生成带明确警告的候选表达计划，否定、人物交换、时间、情态和疑问会保留不同语义。帮助的空间方向、疑问非手控表达、复杂从句、被动和未知词会阻止播放。

新语义证据索引收录既有教学资料的 80 条词级参考，重点候选包括“来、去、今天、昨天、明天”。这些资料是教学步骤/采样证据，不是通用中国手语词典；`human_approved`、`training_ready` 和 `model_training_ready` 均保持 false。原始视频和拟合参数没有改写。
