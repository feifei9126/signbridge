# 配对分层微调

入口：`signbridge/src/tools/sign-csl-upper-transfer.py`。
基线及历史证据见 [解码修正](guarded-gloss-decoding-20261106.md)。

解码对照中束搜索虽将 G GER 从 71.90% 降至 70.21%，却增加删除并损伤否定切片，未通过选用条件。
本轮进一步区分继续拟合解码器与适配中文编码器上层的效果。

两个实验臂从完全相同的 LR001 第 12 轮解码器和官方 BERT 权重初始化：

| 实验臂 | 可训练参数 | 编码器策略 |
| --- | ---: | --- |
| frozen-continuation | 1,031,811 | 编码器全部冻结 |
| upper2-adaptation | 15,207,555 | 只允许最后第 10、11 层接收梯度；前 10 层与 embedding 冻结 |

每组固定 8 轮、552 次更新，batch 64，decoder LR 0.0002，适配组的 encoder LR 0.00002，
AdamW weight decay 0.01，label smoothing 0.05，梯度裁剪 1，seed 20261106。
两组编码器 dropout 都关闭，解码器保留原训练模式。选中旧权重对应的优化器状态缺失，
因此两组都新建 AdamW，不把此次执行描述为完整优化器续跑。

训练只在 CUDA GPU 上运行；本机做准备、无优化器的梯度合同测试和推理核验。
原始模型文件不改，更新只存在于新模型内存及新输出目录。每组的 best 和 recovery-last
包含该组实际可训练参数；适配组包括 BERT 最后两层，恢复时校验所有键、形状、dtype 和有限值。

数据保持 train 4,368/G 489，文本及原始 Gloss 标签不改，H/test 不读取。
G 是反复使用的开发集，不是独立测试；数据来源代码不能被解释成已核准的 signer 身份。
每组按完整 G GER 最低、同分最早轮选检查点，然后检查总体、人物、否定、删除、格式及异常重复。
失败样本继续计入错误率；条件不全满足时回退到前一版带异常拒绝的研究基线。

结果读取会重算所有预测的 ID、原始字符 token、边界、EOS、拒绝标记、指标和选用条件。
本机从哈希校验后的检查点重建模型，再逐条复现 GPU 输出；原始/提取后内部清单、运行日志和退出状态分别保存。

研究输出保持 `human_approved=false`、`semantics_approved=false`、`training_ready=false`、
`model_training_ready=false`、`deployment_ready=false`、`can_play=false`。格式或指标改善不能代替中国手语语义核验，
本轮不连接人物、不改 T08 或待人工动作审阅集合。

## 操作

```sh
python signbridge/src/tools/sign-csl-upper-transfer.py prepare \
  --baseline-prepared /absolute/verified/guarded-prepared \
  --decoding-results /absolute/verified/guarded-results \
  --output /absolute/new/prepared

python signbridge/src/tools/sign-csl-upper-transfer.py train \
  --prepared /absolute/new/prepared \
  --encoder-root /absolute/verified/bert \
  --output /absolute/new/results

python signbridge/src/tools/sign-csl-upper-transfer.py interactive \
  --prepared /absolute/new/prepared \
  --results /absolute/verified/results \
  --encoder-root /absolute/verified/bert
```

复用已核验的独立 Transformers 4.40.2 运行环境，设置
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1`。
终端逐行输入中文，`/quit` 退出；该本机推理过程没有优化器，不消耗 GPU 服务器。

## 本次真实结果

| 实验臂 | 选中轮 | G GER | 完全匹配 | 否定 GER | 格式异常 | 结构拒绝 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 原第 12 轮基线 | 12 | 71.90% | 4/489 | 65.75% | 1 | 10 |
| 冻结续训 | 4/8 | 72.95% | 6/489 | 73.29% | 1 | 11 |
| 末两层适配 | 4/8 | 72.49% | 7/489 | 71.92% | 0 | 8 |

两组各完成 552 次 GPU 优化器更新，任务退出 0。两组总体、人物和否定指标均未优于原基线，
因此均未采用；默认研究推理回退到原权重并继续拒绝格式/异常重复输出。
适配组训练集 GER 从原先 55.64% 降至 46.35%，但 G 没有同向改善，继续加轮数没有此次证据支持。

所有结果已归档到桌面 `SignBridge-分层微调-20261106-tyxldvr6`，
归档 SHA256 为 `9d6dd92eac7b3e508602381106e9f9aa0a2ff070bc542e5f9823900ff623bfe6`，
47 个内部文件通过提取后校验。独立本机 CPU 对两组分别复现 train 4,368、G 489 条全部原始输出、
teacher-forcing 统计、完整指标、参数哈希及 recovery 检查点有限值；推理未修改权重。

真实输入探针显示“我们”生成“我们/是”，“我不想去”与“我想不去”生成相同序列，
所以结构有效也不能开放为可靠翻译或动作指令。原重复失控句仍保留原输出并标为 `abstained`。
本轮完成的是可复现的实验、可靠的结果核验及本机研究终端，未完成通用手语语义理解。
