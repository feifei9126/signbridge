# 授权教学视频的学习、标注与手部参考

2026-10-10 对用户新增的 `100/` 与 `shouyu/` 视频完成本轮来源清点、整流采样、字幕索引和选定教学窗口的手部参考。授权依据为用户在本会话明确陈述；原视频留在本地，许可文本未另行审核，也不推断公开分发权限。

## 本轮范围

| 项目 | 结果 | 口径 |
| --- | ---: | --- |
| 视频文件 | 95 | `100` 62份、`shouyu` 33份 |
| 独立来源 | 81 | 按整个文件 SHA-256 去重 |
| 完全重复文件 | 14 | 别名仍保存在清单中 |
| 去重后总时长 | 403.934分钟 | 容器时长；验证另记录视频流时长 |
| OCR采样帧 | 10,332 | 短课1fps、长课0.25fps；全部来源覆盖 |
| 去重字幕片段 | 6,338 | 原始OCR可误读，保存图片证据 |
| 词条/章节候选 | 518 | 稀疏字幕窗口，不代表518条精确动作 |
| 详细参考窗口 | 80 | 33条基础词教学、30条指拼教学、17条医疗/购物教学 |
| 逐帧详细观测 | 10,927 | 25fps，含缺失检测帧 |

本轮复用了39个原摘要未变的旧来源采样，并新处理42个独立来源。两份片头的时长和画面相近，但文件摘要不同，分别保留，划入同一课程家族。旧版本的部分结果保存在 `local-data/tutorial-hand-reference-20261010-v1/`。

“学习”在这里表示读取教学字幕、查看抽样画面、整理课内动作说明并保存可查询的资料。没有声称逐帧专家审阅全部404分钟，也没有更新语言模型权重。详细80条均为 `step_instruction`：包含讲解、动作分解、示范和可能的复述，不自动升级为完整、连续的词动作训练对。

## 调用入口

本地交付根目录：

```text
/Users/mac/Documents/ChatGPT/signbridge/local-data/tutorial-hand-reference-20261010-v2/
```

直接打开该目录的 `review.html`。页面无需网络，支持词名/教学说明搜索、来源和样本类型筛选；可切换全部课程、字幕候选与详细参考，播放原教学窗口和关键点叠加视频，查看原帧、手部裁剪与字幕来源。

| 文件 | 用途 |
| --- | --- |
| `DELIVERY.md` | 本轮状态、计数、调用方法和验证记录 |
| `sources.json` | 95个物理文件、81个独立来源、摘要、别名、授权记录 |
| `lessons.jsonl` / `course-study.jsonl` | 全课程覆盖、内容类型提示与来源学习证据 |
| `LEARNING-NOTES.md` | 按81课组织的学习笔记与教学字幕证据 |
| `subtitle-reading-all.txt` | 全课程字幕阅读文本 |
| `annotations-index.jsonl` | 518条原始字幕词条/章节窗口及证据 |
| `annotations-detailed-all.jsonl` / `annotations-detailed.csv` | 80条助手详细标注和原片时间 |
| `hand-reference-pack/` | 首批63条参考、原窗口、叠加、关键点与检测质量 |
| `new-hand-reference-pack/` | 新增17条医疗和购物参考 |
| `fitting-reference-index.jsonl` | 80条可程序检索的路径、摘要、坐标和时间约定 |
| `fitting-reference/<annotation_id>/` | 2D观测NPZ、5张等距关键帧及估计手部槽裁剪 |
| `smplerx-reference-plan.json` | 手部拟合的输入约定、使用步骤及状态限制 |
| `validation.json` | 原文件摘要、覆盖、数组/掩码、时序及完整视频解码验证 |
| `browser-validation.json` | 离线查阅页搜索、筛选、分页、媒体与本地链接验证 |
| `python-tests.json` / `plugin-verification.log` | Python契约测试及插件完整验证 |
| `provenance/` | 本轮脚本、生成时使用的工具快照 |
| `SHA256SUMS` | 本地交付文件摘要；原视频摘要另存来源清单 |

检索示例（从仓库根目录执行）：

```python
import json
from pathlib import Path

root = Path("local-data/tutorial-hand-reference-20261010-v2")
rows = [json.loads(line) for line in (root / "fitting-reference-index.jsonl").read_text().splitlines()]
for row in rows:
    if row["label"] == "你好":
        print(row["annotation_id"], row["source_window_seconds"], row["hand_shape_note"])
        print(root / row["artifacts"]["observations-2d.npz"]["relative_path"])
```

## 怎样辅助SMPLer-X

“你好”的参考说明保存食指指向前方、再竖拇指的次序；“谢谢”保存拇指弯动与其它手指状态；医疗课区分医生的完整教学解释和简化变体，购物课保留双手接触及遮挡说明。指拼来自本教程的汉语指拼教学，未标成ASL字母表。课内示范并不自动代表唯一的中国手语标准。

使用这些说明检查手型候选、动作次序和接触阶段。若拟合本参考窗口，可使用同帧的估计2D观测；若拟合其它人物或旧训练视频，须在那个视频重新提取观测，不能把教师的2D坐标直接复制过去。

`observations-2d.npz` 提供左右估计槽各21点的归一化xy、参考片像素xy、检测掩码、技术候选掩码、近乎重复手部槽掩码、参考帧编号及名义源时间。其像素映射为 `x * reference_width, y * reference_height`，对应解码后的参考片尺寸。映射到原视频分辨率前必须确认缩放、旋转和解码几何。源时间为窗口起点加参考帧序号/25，未宣称精确原视频PTS对齐。

技术筛选要求有限坐标、点在图内、掌尺度至少15像素，且没有发现左右槽近乎重复；它不测量真实准确率。`eligible_for_2d_fit` 表示可以进一步核验的观测候选，**不表示解剖侧别、镜像或语义已确认**。缺失保留NaN，检测失败、小手、离图和重复槽不参与候选筛选，不补零、不交换侧别、不插值。

独立拟合仍须确认相机、解剖侧别、手均值/关节表示、身体约束和原片遮挡，在原帧重新渲染比较，并检查接触、手腕方向、抖动及面部/身体表达。本轮未生成MANO/SMPL-X旋转、3D掌向或真实接触距离，也未将这些NPZ当成项目的133维SMPL-X训练数据。

## 数据状态与分割

所有新标注保持 `human_approved=false`、`training_ready=false`、`mirror_status=unknown`，所有详细参考保持解剖侧别未确认。之前用户对旧训练片段的人工审核不延伸为这批新教学标注的语义核准。

来源家族记录为 `tutorial-series-100`、`tutorial-series-shouyu`，分割为 `unassigned`。后续拆分时按课程家族、源摘要和已知人物身份分组，保留别名；相近片头和同课变体不能独立随机跨训练/验证集合。现有训练权重、延后片段和总训练历史快照均未由本次标注改写。

## 重新提取已标注窗口

工具位于 `signbridge/src/tools/sign-tutorial-reference.py`，沿用项目数据环境和FFmpeg。已有输出和源目录均不会被覆盖；原摘要改变时提取前拒绝执行。示例输出须为不存在的新目录：

```bash
.venv-sign-data/bin/python signbridge/src/tools/sign-tutorial-reference.py \
  --manifest local-data/tutorial-hand-reference-20261010-v2/sources.json \
  --annotations local-data/tutorial-hand-reference-20261010-v2/annotations-detailed-new.jsonl \
  --output local-data/tutorial-reference-rebuild-new

.venv-sign-data/bin/python signbridge/tests/sign-tutorial-reference.test.py
```

每条标注要求安全ID、在源视频时长内的有限起止时间、非空文字标签和证据、明确样本类型、未知镜像与未人工核准状态。工具输出按参考片目录保存摘要和质量记录，并保留实际提取器数据。

14项工具测试覆盖标注类型与状态不可提升、非法边界/ID、空标签/证据/计划、原文件摘要变化、已有证据不可覆盖、缺失点不填充、重叠手不交换，以及标题与教学字幕的区分，以及缺失核验来源不能宣称画面复核。插件完整验证使用 `cd signbridge && npm run verify`；数据契约测试另外使用 `.venv-sign-data`，不把这些CPU测试冒称GPU训练。
