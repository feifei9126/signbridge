# 六批动作逐项质量检查

2026-10-16 的检查产物位于本地 `local-data/six-batch-motion-audit-20261016-b3j952wo/review-v5/index.html`，文字结论为同目录 `REVIEW.md`，逐项结果为 `report.json`。目录包含 336 张对照表，并通过原视频 SHA-256 重新归属批次 1–6；训练轮次 T01–T10 与视频批次分开统计。

检查覆盖 200 条连续原生重建任务、24 条二维参考、685 个独立身体关键帧、665 个独立 MANO 案例、62 条保存的训练解码，以及 112 条当前 Demo/独立预览动作。这些阶段有对应和重复，不能相加当作句子数。341 个当前原视频文件也逐一记录有无对应阶段结果，没有完成结果的视频不视为已训练。

| 视频批次 | 连续完整/任务 | 完整轨迹触发原始时序筛查 | 当前 Demo/预览触发筛查 |
| --- | --- | --- | --- |
| 1 | 19/19 | 19 | 0/17 |
| 2 | 15/15 | 13 | 无当前运行时动作 |
| 3 | 61/61 | 54 | 无当前运行时动作 |
| 4 | 91/93 | 91 | 2/83 |
| 5 | 只有 24 条二维参考 | 三维稳定性不可评估 | 无当前运行时动作 |
| 6 | 12/12 | 10 | 0/12 |

原始筛查包含 Demo 未映射的身体关节，且快速手势也可能触发尖峰，不能把这一列直接当成错误句子数。当前显示指标采用实际 Godette 骨架、现有映射和现有默认平滑；未新增平滑、未改写参数或检查点。

确定缺失：第 4 批「基本」缺原生参数帧 221–227，「人民」缺 1–45；第 2 批 `shouyu-cand-4d36e4ad-01-f000025` 独立身体关键帧无重建。缺失不得补零或插值。MANO 的 13 个无检测案例与可选二维观测缺失继续显式保留；全 NaN 的可选 `mediapipe_slot_xy` 不等于三维拟合损坏。

当前显示仍超过手腕残差 P95 2cm 的两句：

- 「手语要多练习才可以熟能生巧」：2.27cm，重点帧 184、192、187、194、261。
- 「从今天起就由我们来给大家讲手语课程」：2.64cm，重点帧 248、240、237、247、238。

原始相邻旋转 >90°、单关节中点残差 >30°、总体残差 P95 >10° 用于定位可疑帧。当前人物筛查使用角度残差 P95 >10°、手腕残差 P95 >2cm 或相邻旋转 >90°。它们是排查阈值，不是手语正确率或无穿模证明；T09/T10 更平滑也不代表比 T08 更准确。T03–T05 的 6 条历史解码、T06/T07 各 1 条触发人物筛查，没有替换当前 T08。

10 份权重均与冻结摘要一致；8 份历史证据清单的 171,685 个条目重校验一致。早期溯源限制及第 4 批原始 JPEG 摘要缺口继续保留。全帧执行结构、数值、时序和人物骨架检查；原片/重建对照图为采样，当前 112 条人物动作各捕获 3 个确切帧的原始/当前显示图。没有声称逐段人工观看全部视频或完成语义批准。

复核工具按阶段运行，所有输出均要求新目录：

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

此次检查不产生新的 `human_approved`、`training_ready` 或 `model_training_ready`，不开展生成模型训练、不更新 T08、不替换 Demo 资产。后续优先处理两句当前残余抖动，再处理缺失结果并人工确认边界、手型、镜像、接触及语义。
