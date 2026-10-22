# CE-CSL 中文到 Gloss 序列训练

2026-10-22，用户明确要求开始下一步训练。本轮利用已经导入的 CE-CSL 整句中文/Gloss 标签训练一个新的研究模型，授权范围为本机文本到 Gloss 序列基线实验。原始候选审核状态、旧 T08、中文角色模型、视频和三维动作文件不修改。

## 本轮训练的任务

输入中文句子，输出 CE-CSL 的 Gloss 标签序列。模型由训练样本更新参数，在推理时逐步预测标签；不执行整句检索，也不把内置词库动画当成预测结果。

这是一项有限的文本序列转换实验。没有输入视频帧，也没有预测 SMPL-X、手指旋转或面部系数；不是视频手语识别或数字人动作生成。Gloss 是数据集的离散标签，当前输出仍是未获人工批准的候选。

## 数据与评价边界

- 数据来自 `local-data/ce-csl-intake-20261022-v1/candidate-library-v1/`，三份分集 JSONL 都按输入清单校验 SHA-256。
- train 4,973条用于梯度更新；dev 515条用于检查点选择；test 500条只在选定检查点后评价，不用于调参或选模型。
- 字符词表和目标 Gloss 词表只从 train 建立。dev/test 专有标签不加入训练词表；计分使用原始标签，不能将未知参考替换为 `<unk>` 从而制造正确匹配。
- “考试1”等编号变体作为不同目标标签保留，标点不作为 Gloss 目标。
- 原始集合不重新打散。评估同时报告官方集合全量和排除与 train 重叠样本的切片。重叠依据为规范化中文相同、Gloss 序列相同或原视频字节相同；ID与原因保存在 `overlap-review.json`。
- 数据集 Translator 编号跨集合出现；本实验不声称人物独立或现实场景中国手语准确率。
- 原候选仍为 `training_ready=false`、`human_approved=false`。新的研究训练根据本轮用户指令执行，不补造语义、镜像、词界或动作批准。

## 模型与训练配置

从零训练约2,058,626参数的小型 Transformer：字符编码器2层、自回归 Gloss 解码器2层、宽度128、4个注意力头、前馈宽度384、dropout 0.15。输入采用 NFKC，移除 Unicode 标点和空白；原始数据不改写。

优化器为 AdamW，初始学习率0.0007，batch size 64，交叉熵忽略 padding，标签平滑0.05，梯度范数限制1.0，固定随机种子20261022。最多40轮，按 dev 不重叠切片的 Gloss 错误率选择检查点，连续6次评价不改善则提前结束。模型不使用预训练语言模型；这不是大模型微调。

首轮复用本机 `.venv-wilor` 中已有 Python 3.10 / PyTorch 2.2.2 环境，在 CPU 上使用4个线程；未安装或修改依赖，没有提交远端 GPU 作业。脚本还可显式指定可用的 MPS 设备。项目普通测试环境没有 PyTorch 时跳过模型梯度和CUDA选择测试，其余数据与指标测试仍运行；模型梯度测试已在首轮已有训练环境通过，CUDA路由测试也已在该环境单独通过。

用户随后要求后续训练连接 GPU 服务器。首轮本地基线已完成，不再启动新的本机训练；当前脚本默认 `--device cuda`，CUDA不可用时直接失败，不自动回退CPU。下一轮应先检查用户提供的最新SSH连接、GPU进程、磁盘和CUDA运行时，在独立新目录预检并启动；本轮尝试此前端口返回连接拒绝，尚未提交新训练。模型的本机推理与数据校验不属于新一轮训练。

## 基线与指标

对照组是只从 train Gloss 频次建立的文字最长匹配基线：数字后缀可作为标签变体的表面匹配候选，输出仍保留原编号，不能当作已核验词级对齐。未匹配字符保留在预测里参与计分，不悄悄丢弃。它没有更新神经模型权重，也不代表中国手语语法规则。

主指标为 Gloss 错误率：`(替换数 + 删除数 + 插入数) / 参考Gloss数`，越低越好，可超过100%。另报告整段标签完全一致率、参考标签数和三种错误次数。既报告 Transformer，也报告文字基线；不把训练损失下降直接称为理解能力提升。

## 复现

在仓库根运行，输出必须是新目录：

```sh
.venv-wilor/bin/python signbridge/tests/sign-ce-csl-gloss.test.py -v

.venv-wilor/bin/python -u signbridge/src/tools/sign-ce-csl-gloss.py train \
  --library local-data/ce-csl-intake-20261022-v1/candidate-library-v1 \
  --output local-data/ce-csl-gloss-training-new/experiment-v1 \
  --research-only --epochs 40 --batch-size 64 --learning-rate 0.0007 \
  --threads 4 --device cpu --evaluate-every 2 --patience 6
```

上面是已完成CPU首轮的历史复现命令，后续执行以GPU要求为准：在确认可用的GPU服务器上使用其已验证的Python环境和上传后校验一致的数据路径，显式指定 `--device cuda`，不照搬本机 `.venv-wilor` 路径。

首轮结果目录为 `local-data/ce-csl-gloss-training-20261022-v1/experiment-v1/`。实际运行状态与指标以该目录 `report.json` 为准，`progress.json` 是进度，`training.jsonl` 记录每轮损失和 dev 指标。改善时生成独立的 `checkpoints/epoch-XXX.pt`；不会覆盖之前的 T08 或其他研究权重。

完成后可本机推理：

```sh
.venv-wilor/bin/python signbridge/src/tools/sign-ce-csl-gloss.py predict \
  --model local-data/ce-csl-gloss-training-20261022-v1/experiment-v1 \
  --text "我今天去学校。"
```

输出包含候选 Gloss、检查点摘要和未见输入字符，固定 `can_play=false`。分数未校准，不提供虚构置信度。数据、预测文件和权重均保存在被忽略的 `local-data/`，不自动进入插件、公开下载或 GitHub。

## 首轮结果

40轮训练完成，共3,120次优化器更新；按dev不重叠切片选择第40轮。训练token损失从首轮6.336降至1.175，但保留集整体误差仍高。

| 模型/切片 | dev Gloss错误率 | test Gloss错误率 | test整句完全匹配率 |
| --- | ---: | ---: | ---: |
| Transformer，官方全量 | 70.82% | 75.90% | 1.40% |
| 文字最长匹配基线，官方全量 | 86.16% | 93.37% | 1.20% |
| Transformer，去除train重叠 | 71.30% | 76.08% | 1.01% |
| 文字最长匹配基线，去除train重叠 | 86.04% | 93.47% | 1.01% |

dev不重叠切片509条，test不重叠切片497条。错误率降低不等于中国手语准确率；尤其整句正确率仍低，当前模型没有接入Demo或自动生成动作。少量未见Gloss、稀疏编号变体、语序变化与省略均是后续分析对象，不能仅靠增加轮次宣称解决。

检查点SHA-256为 `606880a672338eca766a12a43aff25356bcde6375e848c241ffac5f29a1088fa`。完整训练/逐句预测在结果目录；独立复核位于上级 `verification/independent-audit.json`，重算保存的全部dev/test指标，并复现各8条已选检查点推理。为保留精确来源，增加CUDA路由前的训练脚本字节另存于上级 `source-snapshot/training-tool-source.py.txt`，其摘要与已封存训练报告一致。

## 后续决策

先依据保留集的错误分析判断这组资源能学到什么，再决定扩大文本模型、训练视频到 Gloss 识别、或制作词级时间对齐。任何文本预测都不能自动借用同名内置动作，也不能将 Gloss 序列机械拼接后声称为正确中国手语表达。数字人集成仍需动作来源、空间指代和非手控表达等证据。
