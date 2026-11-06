# 专用中文语义学习器与 GPU 阻碍

本轮在 `signbridge/src/tools/sign-csl-typed-semantics.py` 实现了专用训练器，
补齐[上一轮数据准备](basic-semantic-round-20261106.md)列出的三个工程缺项。
**训练尚未启动，未验证质量提升。** 已授权的 GPU 地址端口 37077 连续三次返回
`ssh: connect to host connect.cqa1.seetacloud.com port 37077: Connection refused`，退出码 255。
只使用原有严格主机密钥验证和已信任别名，没有修改 trust、保存凭据或尝试其他地址。
连接错误不能证明 GPU 电源状态；当前只能确认 SSH 不可达。

## 模型和任务

复用已核验的官方 Chinese BERT 文件、revision、tokenizer、Transformers 4.40.2 环境，
编码器保持冻结且 eval。每个规范中文字符必须与 tokenizer 的一个 token 严格对应，
不截断，不用参考目标指导编码器，不把未知 token 或多 token 结果揉成一个字符。

特征送入 Linear(768→128)、LayerNorm、GELU 和双向 GRU，再由两个学习头分别预测：

1. `entity/event/reject`：裸实体、单事件、合同外/歧义拒绝；
2. 每个字符的 BIO 角色标签：施事、谓词、受事、目标、时间、体、否定、情态等。

顺序不同的学习角色用于显式图组合：“不→想→去”与“想→不→去”形成不同图。
显式有限词值、谓词参数、BIO、角色顺序检查只验证模型输出，不重解析文本、不填角色，
也不把句子替换成规则答案。非法角色、反向“去我”、错配“我喝书”、谓词后的情态等会拒绝。
这些约束必须与学习模型收益分别记录，不能归因成端到端中国手语理解。

推理对内部标点、控制字符、超长输入及超出训练字符支持的内容保守拒绝；
不擦掉内部句界来凑成可接受的输入。原始 kind 和全部 BIO 保留，拒绝结果也要校验原始标签长度、类型及 ID。

## 新数据与隔离

最终包为 **10,348 train / 2,840 dev**，全部是开发者合成的中文监督，未生成 Gloss 或动作目标。

| 类型 | train | dev |
| --- | ---: | ---: |
| 裸实体 | 4 | 3 |
| 事件 | 8,964 | 2,469 |
| 拒绝 | 1,380 | 368 |
| 其中双操作符事件 | 2,972 | 822 |

人称/谓词/对象组合的全部时间、体和操作符变体保持在同一分区，当前 train/dev 的文本和组合互斥。
原先 138 条挑战和历史 76 条对照的规范文本不进入 train/dev；原先 52 条 dev 不得进入 train，
可以与当前 dev 重合并在后续审计中披露。原先 train 的合成中文样本允许复用，重合 ID 单独报告。
裸复数人称只在 dev：需要检验其从单数实体及事件内复数施事角色学习的组合迁移，不能提前声称已学会。

历史 76 条对照原文件随包保留并绑定 SHA256；新旧诊断共 266 行在选检查点后才测。
其内容可为冻结校验及预留检查被解析，但不进入训练损失或选检查点指标。
这些都是已经消耗过的开发诊断，不能当作独立测试；H 和正式 CE-CSL test 本轮不读取。

实体种类非常稀少。为避免分类头只学多数事件，训练采用按 kind 频率倒数的有放回抽样，
每轮抽样总次数仍为 train 长度，不把重采样计作新数据或新增证据。

## 固定训练与检验

计划最多固定 18 轮，batch 128，AdamW LR 0.001，weight decay 0.01，clip 1，seed 20261106，
每轮 81 次、总 1,458 次更新。编码器特征只计算一次，头部训练优化器只在 CUDA 上创建。
本机只允许准备、推理和不调用优化器的前向/反向合同验证。

选模只用 dev，顺序为错误接受最少、合同内正确解析最多、正确拒绝最多，同分最早轮。
训练后还需要完成：真实进程终止/exit0、归档与内外层校验、best/recovery 有限值和形状、
CPU 逐条复现、266 条诊断、现有基线对照、延迟和输入拒绝测试。
全部拒绝不能通过覆盖条件；只降低平均分不能掩盖实体或范围退步。

受限中文工程验收条件预先固定为：合同内正确解析和范围正确率至少 98%，
实体全部正确、完整成对对照全部正确，错误接受和合同外错误接受均为 0。
它们即使通过也只能支持这个有限中文合同的工程结论，不能验证真实中国手语翻译或动作质量。

结果加载重算 ID、文本、raw kind/BIO、角色/图、dev 指标与选模，核对全部输入/工具摘要、预算、
权重摘要、形状/dtype/有限值。推理与训练共用同一特征及输出处理。

## 实际验证状态

本机已验证真实 BERT 下全部 13,188 条源文本对齐、20 条混合类别前向和反向、
冻结编码器无梯度、头部梯度有限、检查点往返预测一致；参数均未改变，优化器更新 0。
未经训练的输出不计作质量证据，不作为可用模型交付。预检通过不等于任务质量通过。

准备、预检、连接错误和代码快照保存在桌面 `SignBridge-语义专项训练-20261106-snbfyoho` 的新版本目录；
旧输入包和前期检查也保留。没有覆盖原模型、动作、T08、Demo 或人工审阅状态，没有推送 GitHub。
`human_approved`、`semantics_approved`、`training_ready`、`model_training_ready`、`can_play` 保持 false。

## 复现入口

```sh
python signbridge/src/tools/sign-csl-typed-semantics.py prepare \
  --previous /absolute/prior/preparation-v3 \
  --legacy-fixture /absolute/project/signbridge/tests/fixtures/semantic-contrast-v1.json \
  --encoder-root /absolute/verified/bert \
  --output /absolute/NEW/prepared

# 仅在服务器完成 CUDA/输入/运行时/活动进程预检后执行；本轮尚未运行。
python signbridge/src/tools/sign-csl-typed-semantics.py train \
  --prepared /absolute/prepared \
  --encoder-root /absolute/verified/bert \
  --output /absolute/NEW/results

# 已下载并校验真实训练结果后，CPU复现与开发诊断：
python signbridge/src/tools/sign-csl-typed-semantics.py audit \
  --prepared /absolute/prepared \
  --results /absolute/verified/results \
  --encoder-root /absolute/verified/bert \
  --output /absolute/NEW/audit
```

使用已有独立运行时，设置 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1`。
不安装新依赖，不改变检查点；恢复连接后必须先核验服务器上的文件和实际进程，不能直接假定环境仍在。
