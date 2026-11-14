# CE-CSL 词条与元数据候选库

2026-10-22导入阶段：按用户选择接入本地 CE-CSL，范围为词条、整句标签与视频元数据。用户明确确认可用于本项目。原数据库保留，新结果写入被 Git 忽略的 `local-data/`；该导入阶段未训练模型、未生成三维动作，也未把新候选写入 Demo 的播放词库。随后用户另行授权的中文到Gloss基线训练见[训练记录](ce-csl-gloss-training.md)，不更改本候选库的审批标记。

## 这次接入的内容

本地快照位于 `/Users/mac/Desktop/手语/CE-CSL/CE-CSL/`，包含 `label/{train,dev,test}.csv` 和 `video/<split>/<Translator>/<Number>.mp4`。CSV 列为 `Number`、`Translator`、`Chinese Sentences`、`Gloss`、`Note`。

| 原始划分 | 序列标签数 |
| --- | ---: |
| train | 4,973 |
| dev | 515 |
| test | 500 |
| 合计 | 5,988 |

本地标签中有 **3,859 个不同的 Gloss 候选**，不含单独的句末标点；总计 28,155 次 Gloss 出现。这是当前本地文件的统计，不代表官方全部版本的规模，也不代表项目已经新增 3,859 个可播放或已人工核准的手语词。

该候选库位于 `local-data/ce-csl-intake-20261022-v1/candidate-library-v1/`。本次5,988个视频全部找到，头信息读取全部通过，逐文件摘要另经独立重算；容器报告累计约10.51小时、1,126,122帧，未逐帧解码。盘点发现1组相同视频字节（在同一划分内），以及3组跨集合相同中文原句、8组跨集合相同Gloss序列。81个Gloss标签与现有动作概念或别名文字精确相同，仍不据此自动复用动作。

Gloss 用 `/` 分隔。编号变体（如 `考试1`、`上班2`）、数字标签、原始序列、标点和备注均保留。`Note` 不自动当成词义；原始 CSV 字节副本留在结果目录的 `label/` 下。JSONL 保留未改写的字段，CSV 便利导出会给可能被表格软件当成公式的前缀加单引号。

## 数据契约

- `samples.jsonl`：整段候选，包含原始行、来源 CSV 摘要和行定位、原视频摘要及头信息；`source_split` 保留原始划分，`project_split` 为 `unassigned`。
- `gloss-lexicon.jsonl`：汇总词条候选，按完全相同的标签去重，保留每次出现的序列 ID、原划分和 token 位置。token 位置是标签顺序，不是视频帧号。
- `splits/{train,dev,test}/`：各集合的独立样本和词表。train 导出不包含 dev/test 的次数或样例；全量词表仅用于盘点。
- `candidates.sqlite`：`samples`、`gloss_terms`、`occurrences` 三张关联表，可按词条和中文句子查询；项目工具用只读连接与 SQL 参数查询。
- `video-inventory.jsonl`：视频绝对路径、文件 URI、SHA-256、字节数、容器报告的帧数、时长、帧率和尺寸。只读视频头信息，**没有逐帧解码或验证手语动作**。
- `gloss-frequency.csv` / `samples.csv`：方便表格软件筛选。
- `project-label-overlap.csv`：与当前 52 个内置动作概念的原始 gloss/别名做精确文字比较。文字相同不证明是同一种手语动作，不生成播放路由。
- `duplicates.json`：相同视频字节、中文原句和 Gloss 序列的重复组及跨集合标志。保留全部来源，不删除样本或重排原始集合。
- `report.json` / `REVIEW.md` / `SHA256SUMS`：输入、工具与运行时来源、统计、异常和输出文件摘要。

`Translator` 仅作为数据集提供的编号使用，不据外观确认真实身份，不与旧六批视频的人物身份合并。原始 A–L 编号出现在三个集合中；当前划分不能称为人物独立留出。跨集合重复也必须在后续评价中单独审查。

候选均保留 `text_verified=""`、`word_spans=[]`、`human_approved=false`、`word_boundaries_verified=false`、`training_ready=false`、`model_training_ready=false`、`native_3d_available=false`、`can_play=false`。数据集已有整段 Gloss 标签属于来源标注，不因导入自动升级为项目的人工动作审核。

## 导入与检索

工具仅使用 Python 标准库，建议沿用项目 Python 3.10–3.12 环境。导入需要本机 `ffprobe`；不需要 GPU 或安装新模型。下列命令从仓库根目录执行：

```sh
.venv-sign-data/bin/python signbridge/src/tools/sign-ce-csl-import.py import \
  --source "/absolute/path/to/CE-CSL/CE-CSL" \
  --output local-data/ce-csl-new-candidate-library \
  --authorization-note "用户确认可用于本项目；本地词条和元数据候选接入" \
  --workers 6
```

输出必须不存在，并且不能位于源数据目录内或包含源数据目录。CSV 身份或路径有问题直接拒绝；视频缺失或头信息读取失败会记入报告，原标签仍保留。视频、标签和导入脚本在处理期间变化会拒绝宣称快照完成。不会修改原视频，亦不会把 9 GB 视频复制进项目或公开构建。

```sh
# 默认只查 train：找含指定 Gloss 的原句与原视频
.venv-sign-data/bin/python signbridge/src/tools/sign-ce-csl-import.py query \
  --library local-data/ce-csl-intake-20261022-v1/candidate-library-v1 \
  --gloss 去 --limit 10

# 中文子串检索；显式选择集合，返回 JSON
.venv-sign-data/bin/python signbridge/src/tools/sign-ce-csl-import.py query \
  --library local-data/ce-csl-intake-20261022-v1/candidate-library-v1 \
  --text 考试 --split train --limit 10
```

`--split all` 只用于数据审阅；不自动解除评估集合的用途边界。查询结果给出原始视频位置，可用本机播放器对照；不能从一段视频同时出现多个 Gloss 就声称每个词的开始/结束时间已知。

本轮授权按用户陈述登记为 `user_reported`。本地没有找到许可文件，公开来源连接未核实成功；没有据此推断任意再分发许可。视频、完整标签和派生候选库均留在本地，不进入 GitHub、插件包或公开站点。

## 对项目的用途与下一步

候选库现在可用于查看真实中文句子与整段 Gloss 的对应、筛选常见词和编号变体、为已有词建立原视频检索线索，以及准备保持集合隔离的研究数据。它不应直接传给现有 `--unit-candidates`：那个接口指向教学动作证据，这里的证据只到整段标签层级。

下一阶段可先从 train 中选择少量高频且可清楚观察的词句，对照原片核准含义和词级边界，再建立连续观测/SMPL-X 拟合输入及质量报告。只有获得相应动作与语言证据后，才另行决定是否训练识别/对齐模型或接入播放。当前 tokenizer、中文角色模型、T08 检查点和此前 83 条动作批准不受本次导入影响。

## 回归检查

```sh
.venv-sign-data/bin/python signbridge/tests/sign-ce-csl-import.test.py -v
cd signbridge
npm run verify
```

单测覆盖原标签/编号变体/划分保留、候选状态、train 导出隔离、跨集合重复、只读参数检索、缺视频保留、路径与符号链接拒绝、输入变更拒绝以及输出逐文件摘要。

本次独立数据复核在 `local-data/ce-csl-intake-20261022-v1/verification/independent-audit.json`：19个内部文件摘要、3份原始CSV字节、5,988条完整记录、3,859种Gloss及28,155次出现、全部原视频SHA-256、SQLite完整性/外键及JSONL一致性、train默认查询均通过。完整项目验证日志为同目录 `project-verify.log`：构建、ESLint、237项JavaScript测试、504项Python测试和Prettier通过。这些是数据/工程检查，不是手语准确率或训练成果。
