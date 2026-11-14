# 手语视频续处理（2026-10-13）

本轮对 `/Users/mac/Desktop/手语/` 做了全量内容哈希登记，再复用旧来源清单与 OCR。当前快照有 149 个视频文件、134 份不同内容、15 个完全相同的额外文件路径。后续 v2 教学清单已经收录 `100` 目录中的全部 48 份不同内容；只对照 v1 清单会漏算后续已登记素材。

本轮处理阶段及成果：

| 阶段 | 实际完成范围 |
| --- | --- |
| 全量来源进度 | 134 份不同内容登记，保留旧关键点、连续动作和来源索引 |
| 新视频筛查 | 42 份 `2/bilibili/` 视频；8,026 张 OCR 采样图、6,176 个原始字幕候选区间 |
| 句子参考提取 | 85 个粗窗口候选；9 个与旧参考句文本相同，另取 76 个候选窗口 |
| 连续二维关键点 | 76 个窗口，25fps，共 17,300 帧；身体、面部、双手、缺失掩码及名义源时间 |
| 其它未详细处理来源 | 73 份来源各取 5 帧独立手部观测，共 365 帧；不是整段动作标注 |
| 后续拟合输入 | 380 个与参考片同帧的关键帧案例，供独立 SMPL-X/MANO 拟合使用 |
| 验证 | 152 个原片/叠加视频完整解码；149 个原视频哈希、数组掩码、像素转换、文件摘要核验 |

输出保存在 Git 忽略的 `local-data/data-expansion-20261013/`；素材、人体模型、密码和派生视频不提交或公开分发。

## 调用入口

- `review-delivery/index.html`：可搜索句子、视频来源和原始字幕，查看原片/叠加同步播放与5帧手部裁剪。
- `review-delivery/fitting-reference-index.jsonl`：76 个参考窗口的程序索引，包含源 SHA-256、名义源时间、视频尺寸、关节点坐标、检测掩码和文件摘要。
- `catchup-index/source-registry.json`：全部来源、重复别名、旧处理状态和待办。
- `sentence-reference-pack/`：连续参考片、关键点数组和质量记录。
- `source-hand-observations/`：73 个来源的独立抽样观测。
- `native-hand-plan/plan.json`：380 案例的有序计划。
- `gpu-inputs/manifest.json`：现有 GPU 批处理器可校验的输入；`frames_are_temporally_contiguous=false`，不直接用于时序训练。
- `validation.json`、`browser-qa/report.json`、`gpu-connection.json`：本轮实际验证和连接结果。

## 状态约束

所有新数据保持 `human_approved=false`、`training_ready=false`、`mirror_status=unknown` 和 `language=unconfirmed`。OCR 可以把多句问答合并、漏字或错字（例如“爸爸”被识别成其它字）；位置筛选只提供候选，不能自动批准手语含义或完整边界。香港手语标题单独提示，不自动并入中国手语训练。

关键点是二维图像上的模型估计，NaN 和检测掩码原样保留；左右是提取器估计槽。像素坐标对应缩放后的参考视频，不是原视频像素或米制三维坐标，更不是 SMPL-X 关节角。不得把教师的点直接复制到其它人物。完整原视频尚未被逐帧语义标注。

本轮没有更新 T08 或向 Demo 自动加入新的训练句子。新的 76 个窗口是后续筛选常用句的真实视频参考，不能当成76句已经训练完成。

## 复用工具

使用现有 `.venv-sign-data` 环境以及系统 `ffmpeg`、`ffprobe`、Swift。不要用缺少 Pillow/MediaPipe 的系统 Python 执行关键点提取。

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-source-catchup.py \
  --source-root '/Users/mac/Desktop/手语' --dataset local-data \
  --new-manifest local-data/data-expansion-20261013/unprocessed-manifest.json \
  --new-screen local-data/data-expansion-20261013/source-screen \
  --output local-data/catchup-index-new-version

.venv-sign-data/bin/python signbridge/src/tools/sign-source-catchup-review.py \
  --audit --index local-data/data-expansion-20261013/review-delivery \
  --output local-data/catchup-validation-new-version.json
```

新视频若在扫描后加入，索引器会拒绝把它们算作已处理，应另建清单和输出目录。视频仅重命名但哈希相同可复用；哈希不同的视频即使标题相同，也不能自动认定为独立人物或新的手语表达。

## 连续候选重建

2026-10-14 用户确认查看关键帧 MANO/SMPL-X A/B 页面后，准备对76个候选片段单独运行完整25fps SMPLer-X。候选标签仍是 `text_candidate`，包内 `text_verified` 为空；即使连续拟合成功也不自动批准语义、边界、镜像或训练状态。

输入准备工具会校验原片与候选片段哈希，并把380个MANO关键帧映射到各自的原始片段帧序号；见 `signbridge/src/tools/sign-source-catchup-smplx.py` 的 `prepare` 命令。远端 `run` 在 SMPLer-X `main/` 工作目录依次推理，逐段写入状态，完整审计每帧渲染/参数/元数据及缺失检测。一次失败不会覆盖旧的结果目录，重跑应使用新版本输出名。

完整片段推理耗时显著高于380张独立关键帧，按当前GPU约1帧/秒估算，76段共17,300帧需要数小时；不要把离散关键帧或自动补帧伪装成连续时序。完成后仍需同片原视频重渲染核查、手语语义/镜像/分组审核，再导出133维训练表示。训练需另行按不泄漏来源/签名者的分组评估，并使用独立checkpoint。

接下来需要在线 CUDA 主机重建独立候选，再检查手型、镜像、遮挡与时序。此轮的 SSH 连接状态见实际 `gpu-connection.json`；连接失败不会触发租赁、开机或旧结果覆盖。
