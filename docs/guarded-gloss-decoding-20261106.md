# Gloss 解码修正与本地研究推理

本轮固定 `ce686c381227bf49cd7f8527767e74a8e58169d164835aea3149b03adfee08e7`
权重和冻结 BERT，只比较输出搜索方式。入口为
`signbridge/src/tools/sign-csl-guarded-decoding.py`。

## 可用范围与数据边界

这是中文到原始 Gloss 标签的研究工具。格式完整不代表中国手语语义正确；所有输出保留
`research_only=true`、`semantics_approved=false`、`training_ready=false`、
`model_training_ready=false`、`can_play=false`。它不会连接人物动作，也不会恢复此前删除的
“意思分析”页面。

沿用 4,368 条 train、489 条 G 开发数据；G 已被多次使用，不能当作独立测试。
H 和正式 test 不读取，优化器更新为 0。原动作库、待人工审阅包和历史批准状态保持独立。

## 本轮修正

- EOS 只能出现在完整 Gloss 边界之后；空词、PAD、BOS、UNK 不参与约束解码。
- 对照配置预先固定为边界约束贪心，以及宽 4、最终长度指数 0.6 的束搜索。
  按累计原始对数概率裁剪束，末尾作长度归一化重排；约束在 log-softmax 后应用。
- 不强制补 EOS，不按答案或训练标签树约束词义，不删除重复词，不把缺失输出补成正确答案。
  达到 63 步仍未结束时，原始错误和完整 token 证据继续保留。
- 训练数据支持最多 3 次连续同标签重复，合法重复原样保留。超过训练支持范围只触发研究输出拒绝，
  不能证明所有 4 次重复在语言上都不合法。
- 新推理只读取输入文本；不再为生成构造参考目标。
- 加载实验结果时校验全部预测文件的哈希、ID、文本、目标、原始 token、结束状态和质量标记，
  重算总体、人物、否定、删除与格式指标，再重算每项选用条件。
  缺预测文件、空 guardrails、伪造指标、未复现基线均拒绝加载。
- 所有候选和失败输出都计入完整 GER；结构拒绝不会被当成翻译正确。

## 运行

使用已经核验的独立 Transformers 4.40.2/PyTorch 环境，设置
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1`。
编码器从本地核验资产加载，不下载新模型或执行远端模型代码。

```sh
python signbridge/src/tools/sign-csl-guarded-decoding.py prepare \
  --control /absolute/old/control \
  --baseline /absolute/old/lr001-results \
  --output /absolute/new/prepared

# GPU 对照，保持权重不变。
python signbridge/src/tools/sign-csl-guarded-decoding.py evaluate \
  --prepared /absolute/new/prepared \
  --encoder-root /absolute/verified/bert \
  --output /absolute/new/results

# 本机 CPU 推理，不进行训练；结果目录必须通过重算核验。
python signbridge/src/tools/sign-csl-guarded-decoding.py predict \
  --prepared /absolute/new/prepared \
  --encoder-root /absolute/verified/bert \
  --result /absolute/verified/results \
  --text '我想去学校' \
  --output /absolute/new/prediction

# 只加载一次模型，逐行输入中文，/quit 退出。
python signbridge/src/tools/sign-csl-guarded-decoding.py interactive \
  --prepared /absolute/new/prepared \
  --encoder-root /absolute/verified/bert \
  --result /absolute/verified/results
```

每次实验、验证和交付均使用新目录，原始失败证据不覆盖。回退时继续使用上一版工具和权重；
本轮没有改动既有 Demo 或其动作资产。

## 验证记录

定向测试覆盖合法重复、异常拒绝、输入边界、参考无关、概率保持、束结束状态、非有限值、
预测缺失、报告伪造和完整指标重算。实验结果与独立复核记录写入版本化桌面交付目录。

真实运行后，原始贪心与边界贪心均为 GER 71.90%、格式异常 1、结构拒绝 10；
束 4 为 GER 70.21%、格式异常 0、结构拒绝 1，但删除 687→784，否定 GER 65.75%→66.44%，
未通过完整选用条件。保留原研究基线，不把低总错误率掩盖的删除/否定退步带入默认配置。
全部三种配置的 489 条输出已在本机 CPU 上逐条复现，与 GPU 一致。
