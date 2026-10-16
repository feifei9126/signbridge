# 来源 6 人物预览实施计划

**Goal:** 交付 12 个来源 6 连续重建候选在 Godette 上的可回退预览和量化检查。

**Architecture:** 新只读导出工具读取冻结包、已审计的本地原生输出和固定 SMPL-X 中性模型。复用既有实验动作合约、懒加载、人物映射和显示平滑，将独立构建存至新的本地证据目录。

**Tech Stack:** Python/NumPy、JavaScript/Three.js、现有 esbuild、Node test、unittest、Playwright。

## 执行与验收

- [x] 先写 `signbridge/tests/sign-demo-source6-export.test.py`：完整原生姿态到 55 关节显示数组、mean 恰好一次、不修改输入、审批保持未核验、缺帧拒绝。
- [x] 新增 `signbridge/src/tools/sign-demo-source6-export.py`，只输出未审批 Demo 候选。命令使用 `--package`、`--review`、`--pilot-results`、`--remaining-results`、`--smplx-model` 和新的 `--output`。报告及派生包绑定输入、源图像清单、模型和工具摘要。
- [x] 更新通用实验动作提示，显式包含候选文字和边界风险；所有 UI 字符串经 `src/i18n/locales.js`。如有来源 6 扩展元数据则校验不允许升级审批。
- [x] 本地生成来源 6 包，使用 `SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR` 构建、复制到新的预览目录后恢复默认构建；不改旧资产和 checkpoint。
- [x] 运行 `sign-motion-stability-audit.mjs` 对实际人物骨骼检查 raw/smoothed 轨迹。Playwright 对新预览逐段加载和动画、raw 切换、暂停／停止做实际检查。
- [x] 更新 `signbridge/docs/source-ingestion.md`、`docs/demo.md`。运行 `npm run verify` 和全部相关 Python 测试，明确提交范围，保留原有未跟踪文件。

验收记录：独立最终构建 `preview-build-v2/`；导出 12 段／2,779 帧；最终浏览器检查 `browser-qa-v4/` 通过全部 12 段完整播放、暂停／恢复、原始切换、活动停止及会话来源导出。`stability-audit-v1/` 保留人物量化轨迹证据。`npm run verify` 的 181 项 JavaScript 测试及 427 项 Python 测试全部通过。候选状态、原生参数及模型 checkpoint 保留。
