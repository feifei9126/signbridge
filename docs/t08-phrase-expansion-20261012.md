# T08 常用句候选扩充记录 · 2026-10-12

本轮使用已有授权资料和固定 T08 checkpoint。没有重训、微调或覆盖权重；新增的是三条由原模型编码/解码的候选动作，供 Demo 比较。

## 匹配结果与数据状态

现有内置词库为52个动作、177个别名，主要是单词/词组，并非完整句子模型。当前T08训练参考为14段完整句。新视频筛选表中共有31条记录，其中27条是句子候选、4条是单词候选；27条句子的 `text_verified` 为空，身份为 `unconfirmed-source-*`。这些句子与14条T08参考句、177个词库完整别名的精确匹配数均为0。词面重合不批准整句手语等义替换。

新教程手部结果还包含400与285个独立关键帧；报告分别标明无连续序列验收，`training_ready=false`。本轮没有把单张关键帧当作完整句子训练数据。

在另外的 `confirmed-pilot-20261010-v1/motion-approved-v1` 中发现三段连续动作：已有文字及时间边界人工确认、SMPL-X对照视频人工通过、逐帧133维特征，且特征摘要与动作审核记录一致。这三段仍不是正式训练就绪数据：镜像方向、跨视频人物身份、重复内容和源组划分仍未确认。本轮据此保留 `training_ready=false`，只导出显式候选。

| 完整候选句 | 帧数 / 秒数 | 当前词库能匹配的词 | 未覆盖词 | T08候选归一化重建MSE |
| --- | ---: | --- | --- | ---: |
| 如果下雨可以借你一把。 | 100 / 4 | 如果、可以、你 | 下雨、借、一把 | 0.6633 |
| 我给她买了一件衣服 | 150 / 6 | 我、她 | 给、买、一件、衣服 | 0.4655 |
| 去人民广场怎么走？ | 200 / 8 | 去、怎么、走 | 人民、广场 | 0.5073 |

逐条匹配结果和27条未确认句子保存在 `local-data/demo-20261012/t08-matching-report.json`。候选MSE平均约0.5454；同一CPU诊断中，原14段的平均值约0.0824、原有两段保留样本平均约0.4273。这些数值是动作特征的重建误差，不是手语语言准确率，也不能替代手型/手腕/时序复核。较高误差是本轮保留候选标签的原因之一。

## 本轮新增什么

- 3段候选采用相同T08训练均值/标准差，经真实 `encode → token IDs → decode` 导出；token解码与模型前向结果最大差小于 `1.2e-6`。
- 原14条仍为固定训练参考，新增3条单独存放；原52条动作库不改。
- Demo显示“原参考句14”和“候选3”，候选词条与播放徽标单独标色，并显示归一化误差；页内说明镜像/人物分组待确认。
- 完整候选句可通过实时字幕入口调用，来源为候选重建。它们不是14条训练样本，也不代表模型已学习了新的文字到手语映射。
- 报告下载保留 `source=candidate`、`trainingDataMember=false` 和候选MSE。原视频、特征与训练权重不改。

候选文件为 `local-data/demo-20261012/t08-candidates.json`，包含三路tokens、姿态、来源与特征摘要、审核摘要、误差以及待确认状态。checkpoint仍为SHA256 `438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b`、step1000。

## CPU复现

从仓库根运行：

```bash
.venv-wilor/bin/python signbridge/src/tools/sign-demo-candidate-export.py \
  --source local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1 \
  --checkpoint local-data/remaining14-research-20261010/verified/training/tokenizer-smoke.pt \
  --soke-root local-data/deps/SOKE \
  --smplx-model local-data/deps/SMPLer-X/common/utils/human_model_files/smplx/SMPLX_NEUTRAL.npz \
  --output local-data/demo-20261012/t08-candidates.json
cd signbridge
npm run verify
```

导出器核对固定权重/人体文件/SOKE源码摘要、三段审核范围、已确认文字、源ID、特征摘要与形状。它不会运行优化器。构建时有候选文件就打包三段，无候选文件则保持原14条和词库回退。

## 下一批真正的训练数据

优先从已授权视频中确认以下短句的文字、完整动作边界和镜像方向：`你平时喜欢做什么？`、`你做什么工作？`、`你喜欢什么运动？`、`有事可以和我联系。`、`今天天气很好。`。现有筛选记录仅为OCR候选，不能因文字看起来通顺就标为已审核。

下一次权重训练需将完整动作连续重建、审核元数据补齐，按源/人物组划分训练与保留样本后创建独立候选checkpoint。原T08和原两段保留样本不混入新训练决策；权重推广还需要独立评估。本轮不把候选编码扩充称作新训练，也不声称能生成任意未见句子。

## 验证入口

Python：`sign-demo-candidate-export.test.py`；JavaScript：候选契约校验、精确路由、三段真实骨架四元数验收；浏览器：`demo-browser-qa.mjs`逐段播放14原句、3候选与52词条，`realtime-t08-browser-qa.mjs`验证候选来源消息。

源码入口：`src/tools/sign-demo-candidate-export.py`、`src/demo/demo-motion.js`、`src/demo/demo-avatar.js`、`src/avatar/iframe-bundle.js`、`scripts/build.mjs`。所有候选结构保留非训练成员和镜像待确认标记。
