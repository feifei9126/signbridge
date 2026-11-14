# 全量拟合诊断与学习率对照 · 2026-11-06

本轮按用户授权完成：旧模型全部4368条训练句及489条G组的CPU前向诊断，再在GPU执行一次只改变学习率的对照。新模型训练拟合与G开发指标均有改善，但仍有重复输出未正常结束，**不接入Demo，不自动替换旧权重**。H和正式test未读取或上传。

## 先诊断，再冻结实验

旧BERT迁移模型在全训练集teacher-forcing token匹配33613/59051（56.92%），自由生成仅17/4368句完全匹配，原始Gloss GER75.61%；G组teacher-forcing token匹配3669/6746（54.39%），自由生成GER76.16%、0/489句匹配。训练句本身仍有明显拟合问题，不能将错误都归因于新句子泛化。训练集成绩不是验证成绩。

所有原始ID、参考Gloss、逐句自由生成、teacher-forcing token/整句计数与NLL保存；PAD不计分，EOS和词界计分，分组NLL按token加权。人物、否定、稀有标签及未知目标字符切片独立报告。CPU只前向，权重和冻结encoder摘要前后不变；489条G预测完全复现原GPU结果。

## 单因素对照

以同一官方固定BERT、相同冻结策略、词表/分词/数据顺序和seed20261105进行全新初始化；初始可训练参数hash与基线逐字节一致。共享6个源码文件也与封存基线一致，新的研究脚本及全部7个摘要在控制计划中固定，GPU更新前强制核对。

AdamW lr **0.0002→0.001**，其余实际更新设置不变：batch64、weight_decay0.01、label_smoothing0.05、梯度clip1。严格匹配基线实际15轮/1035次更新，不续训旧best，不延长预算。基线在第15轮触发早停；本实验预先固定15轮无提前停止，实际比较预算一致，但停止政策不同，不能声称政策完全一致。两者都在观察的15轮中按G原Gloss GER选最佳，同分最早。

## 实际结果

| 指标                            |     旧lr0.0002 |      新lr0.001 |
| ------------------------------- | -------------: | -------------: |
| train teacher-forcing token匹配 |         56.92% |         76.50% |
| train原Gloss错误率，4368句      |         75.61% |         55.64% |
| train完整匹配                   |        17/4368 |       319/4368 |
| G teacher-forcing token匹配     |         54.39% |         62.36% |
| G原Gloss错误率，489句           |         76.16% |         71.90% |
| G完整匹配                       |          0/489 |          4/489 |
| G人物切片GER，404句             |         72.06% |         67.37% |
| G否定切片GER，29句              |         77.40% |         65.75% |
| G删除 / 替换 / 插入             | 864 / 913 / 28 | 687 / 944 / 73 |
| G未正常结束的输出               |              0 |              1 |

新run完成15轮、1035步，选中第12轮，driver记录训练退出0且无残留训练进程。G总错误减少101次，改善约4.26个百分点，删除少177次，但替换和插入分别增加31/45次。训练拟合改善更大，G依然不可靠；这是一个seed、重复用于开发的G组结果，不是独立泛化成绩。

格式失败保留原样：`csl_ce_csl_train_03396`（“所有的节目都通过卫星播出”）反复生成“都”，达到固定上限仍无EOS，并留下未完成词界；无效Gloss参与全部计分，没有去重、截断刷分或丢弃该句。训练集输出另有7条格式问题。整体GER、人物/否定GER和G删除数门槛通过，输出合法性门槛失败，因此不晋升。不能把仅一条格式失败理解为模型已经有可靠表达能力；G完整匹配仍仅4/489。

## 验证、交付和恢复

冻结BERT参数全程未改变；初始可训练参数、共享源码、输入和目标原始字节绑定均通过核对。best小checkpoint和末轮recovery/optimizer张量有限，shape/dtype正确；实际步数、最佳轮与历史一致。全部4368条train和489条G重新在Mac CPU前向，自由生成与GPU逐条一致，teacher-forcing计数完全一致，NLL在1e-5容差内。CPU验证0次优化更新。

完整`npm run verify`退出0：323项JavaScript通过；Python775项中30项跳过，其余通过，构建、ESLint、格式通过；现有PyTorch环境下7项专项全部通过。独立代码审查要求将源码一致性从“记录”改为“强制校验”，修订后复查通过；早期v1输入未运行，实际运行v2。

交付目录：`/Users/mac/Desktop/手语/SignBridge-全量拟合与学习率-20261106-w0ll56v0/`。

- `baseline-fit-v1/`：CPU全量基线诊断，含train/G逐句预测和teacher-forcing计数。
- `control-v2/`、`gpu-input-v2/`：实际控制计划及源码/数据摘要。
- `gpu-evidence-v1.tar.gz`：48个文件成员，外层SHA256 `ef363177305459b9f8ea07666e98ef8d7edc88ade9f573bf246450d65dcdb5aa`；内外、解压和所有嵌套清单逐项校验。
- `verified-v1/evidence/results/lr001-v1/`：全部训练历史、原始预测、checkpoint和optimizer恢复；最佳适配checkpoint SHA256 `ce686c381227bf49cd7f8527767e74a8e58169d164835aea3149b03adfee08e7`。
- `independent-validation.json`、`comparison.csv`：本机复算、全量重放和并列指标。

新归档引用而不重复打包约412MB的官方冻结BERT；`encoder-reference.json`记录实际路径及逐文件hash。本地权重原样保留在上一轮中文迁移实验的`pretrained/`及其完整归档，小checkpoint必须和该编码器配套。旧模型、runtime和所有视频/动作/审批文件均未更改，恢复只需继续选择旧run，无需覆盖文件。已本地提交，未推送GitHub。human_approved/training_ready/model_training_ready/deployment_ready继续false。
