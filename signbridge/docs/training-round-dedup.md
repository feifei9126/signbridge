# 历史训练轮次去重与后续门禁

## 范围

本次把训练注册表中最近的三个研究轮次 T08、T09、T10 作为比较范围。三者都只是在 14 段、2,732 帧动作上进行 1,000 步 research smoke tokenizer 训练；不是文本条件的手语生成模型。T10 原先只有远端记录，本次从服务器只读取回完整 12 MB 训练目录，并验证 checkpoint SHA-256 与报告吻合。

## 去重规则与结果

- 不删除或改写任何历史原始文件；新 bundle 只将精确 SHA-256 重复内容存一份，并保留每个 round/path 到内容对象的映射。
- 14 段 `features-133.npy` 在 T08/T09/T10 间全部逐字节相同，规范成 14 个唯一特征对象。
- T08 没有手部质量 mask。T09 与 T10 的 mask 是监督版本，分别保留：跨两轮有 20 个唯一 mask 内容对象，其中 6 段 mask 不同。
- T08/T09/T10 三个 checkpoint 哈希各不相同，全部保留，不能按“重复文件”删除或互相覆盖。
- 全部训练目录和动作输入目录共索引 8,577 个文件引用，形成 3,016 个唯一内容对象，精确折叠 5,561 个副本。原始报告、权重和动作源都没有删除。

产物：

- 去重内容库：`local-data/training-dedup-20261015/deduplicated-bundle-v3/`
- T08/T09/T10 同目标比较：`local-data/training-dedup-20261015/T08-T10-comparison-v1/COMPARISON.md`
- T10 冻结评估：`local-data/training-dedup-20261015/T10-frozen-common-reference-v2/`
- 下一步复核队列：`local-data/training-dedup-20261015/T08-T10-next-step-review-v1/NEXT-STEP.md`

## 同目标评估

T08、T09 和 T10 使用同一个冻结评估器、同两个动作参考片段与同一组 398 个参考文件摘要进行推理；每次均为 0 次权重更新。T10 在全部 raw RMSE 上低于 T08/T09，但左手 raw RMSE 高于 T08 35.1%、高于 T09 19.0%。评估参考是模型拟合的 SMPL-X 动作，不是人工采集的 3D 真值；两段评估片段还与训练样本共享记录的来源/人物组，不能据此声称独立真人泛化。

raw RMSE 可在共同参考上作数值诊断；各轮 normalized MSE 与训练 MSE 使用不同训练 mask/归一化，不应直接横比。T09/T10 只有六段 mask 内容不同，详见 `T08-T10-next-step-review-v1/review.json`。

## 下一步门禁

本次已开始并完成去重后的下一步：统一冻结评估和分项错误分析。**没有启动第四次同数据 smoke training**，因为它会重复同一 14 段，且现有结果呈现明显左手分项回退。下一步是人工复核六段 mask 差异和两段共同参考左手误差，再确认手型、镜像/手别、精确边界及人物/来源分组。现有三轮和去重数据仍为 `training_ready=false`、`deployment_ready=false`；通过质量门之前不产生新的模型 checkpoint。
