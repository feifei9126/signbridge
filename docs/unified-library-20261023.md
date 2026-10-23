# 统一研究库与多任务模型（2026-10-23）

## 本轮目标与边界

用户要求复用历次训练与 CE-CSL 数据，训练新的文字理解库，同时避免人物抖动。本轮采用统一来源清单、分别监督的多任务文字模型和独立动作显示门槛，而不是平均不兼容权重。

中文理解、中文到 Gloss、人体重建和动作 tokenizer 是不同任务。旧角色标签属于助手合成中文监督；CE-CSL 提供中文句子与原始编号 Gloss；已批准 83 条动作仅批准 motion_quality_only，未建立已核验词级 CSL 对齐。六批未对齐资料不伪造标签，测试集不并入训练，原视频和旧权重不修改。

## 冻结输入

- 新包：`local-data/unified-library-20261023-v1/package/`。
- Gloss：原 4,973 条 train 中隔离 15 条，保留 4,958 条；515 条 dev 保持独立。
- 角色：复用旧 corrected roles-v3 的 6,355 条 train、881 条 validation，保持 synthetic Chinese 来源，23 个 BIO 标签不改写。
- 15 条隔离原因：4 条精确重复、4 条同文异标签、2 条 dev 同文、5 条 dev 同 Gloss 序列。原始记录与隔离理由全部保留。
- 训练用词表只由两个 train 构建，不使用 dev 或 test。原始 Gloss 编号不合并。
- 历史 T01–T10 十个动作 checkpoint 均重新核对摘要，全部保留为来源而非文字权重；旧中文感知机只复用标签，不将 NPZ 权重拼入 Transformer。
- 旧 epoch-040 权重作为初始化；它曾接触历史训练/验证重叠，清理新包不抹除这个历史。因此新 dev 仅用于开发比较，不能宣称独立最终泛化。

## 固定新实验

共享既有小型 Transformer 编码器，Gloss 解码器维持原始目标，新增字符级角色输出头。从首轮选中权重初始化，按 train-only token 映射迁移可复用参数；旧 checkpoint 没有优化器状态，因此新建 AdamW，不能称完整恢复。

正式参数更新仅在已授权 RTX 4090 D 的既有 Python 3.10 / PyTorch 2.2.2 CUDA 11.8 环境执行。最多 30 轮，batch 64，学习率 0.0002，角色损失权重 0.3，seed 20261023，patience 8；每轮记录 Gloss dev 错误率、角色 token/exact 指标。保存初始 dev 对照，全部改善的候选独立保留，旧输出不覆盖。test 不上传、不读取。

参数/输入/运行时摘要和日志必须封存；报告说明合成角色任务不等于中国手语监督。模型预测仍为研究候选，未知字符、非法 BIO、未支持结构或作用域需要拒绝/标记不确定，不能冒充正确中国手语，也不能自动把 Gloss 变成同名词库播放。

## 动作稳定性门槛

83 条来源/姿态/审批摘要核验后，在当前 Godette 骨架比较原始、当前 profile 与 recovery profile；不改源姿态、不补帧、不修改 T08。固定门槛：腕部中点残差 P95 不超过 1cm、相比当前 profile 不退步，腕部运动幅度保留至少 90%，指端骨关节偏移不超过当前 profile 加 0.2cm，完整有限单位四元数、相同骨集合/帧数和端点。

两次完整运行逐字节一致：83/83 来源通过；当前 profile 25 条通过、58 条排除；raw 与 recovery 都是 0 条通过。25 条中仍有 3 条源质量警告，必须保留。强平滑没有同时通过幅度与手部细节门槛，不批量采用。

新索引位于 `local-data/unified-library-20261023-motion-v1/stable-library-index.json`，只引用原资产和显示配置。源动作批准不被撤销；派生显示 `derived_display_human_approved=false`，不自动启用。该数值筛选不证明完全无抖动、真实接触或手语正确，也未评价跨片段接续。

## 完成与晋升条件

先通过数据/模型/动作工具专项测试，再检查远端 GPU 无旧作业、CUDA 和磁盘，使用系统盘全新目录启动唯一实验；来源/配置不符则不启动。完成后核对真实进程终止、外层和内部 SHA、参数有限性、保存预测指标复算与推理复现。

Gloss 或角色分项退化不得被训练 loss 或其他分项的高分掩盖。训练完成不等于生产可用；`training_ready`、`model_training_ready`、`deployment_ready` 均为 false，研究模型与动作稳定子库独立保存，不自动替换公开 Demo。

## 实际训练结果（2026-10-23）

- RTX 4090 D / CUDA 11.8 / PyTorch 2.2.2+cu118；从 epoch-040 权重初始化，新建 AdamW；test 未上传、未读取。
- 21 轮后按 patience 提前停止；以 Gloss dev GER 选择 epoch-013。Gloss GER 从 70.82% 降至 70.35%，改善幅度有限；完整句 exact match 仍为 11/515。
- 合成中文角色 dev token accuracy 从 3.46% 升至 99.60%，exact match 为 858/881。该分数只反映合成角色标签拟合，不能作为真实中文语义或中国手语理解成绩。
- 人工对照推理中，人物交换可区分；“我不想去／我想不去”均因作用域未解决而拒答；部分 Gloss 序列仍有遗漏或次序问题。对照句不是独立测试集。
- 新检查点 SHA-256：`eceb74609bb1afb2b6639636542b3cf3092d540fe15f1ef4ebb885e6ad1c5e13`。完整输入、运行时、训练日志、检查点、dev 预测和摘要见 `local-data/unified-library-20261023-v1/verified-results-20261023-r1/`。
- 83 条动作仍是独立动作库：25 条通过固定数值显示代理门槛，58 条排除；其中 3 条候选带源质量警告。数值门槛不证明无抖动或手语正确，派生动作未获新的人审，也未启用播放。

训练完成后仍保持 `human_approved=false`、`training_ready=false`、`model_training_ready=false`、`deployment_ready=false`；模型未接入 Demo，旧动作权重未与文本权重混合。

## 视频识别准备审计（2026-10-23）

- 本机 CE-CSL train/dev 共 5,488 段视频，均与候选库的句子及整句 Gloss 记录一一对应。新审计重新核对了视频 SHA-256、文件大小和容器元数据，并对所有 5,488 段做完整解码；全部通过。审计没有打开或枚举 test 视频/标签。
- 标签是 sequence-level Gloss，不含已核验的词级帧边界。原 train/dev 共享来源代码 A-L，导入记录也明确 `source_split_is_signer_independent=false`；代码只是数据集内来源标识，尚未证实每个代码与唯一手语者身份的一一关系。
- 为防止普通随机划分掩盖来源差异，已从 train-only 数据生成 12 个 leave-one-source-code-out 折。折清单是评估准备，不是已验证的 signer-independent 测试，也不是训练结果。官方 dev/test 内容没有进入折生成。
- 当前统一文字模型的独立 dev 误差分析见 `local-data/unified-library-20261023-v1/dev-error-analysis-current-v1/`。Gloss GER 70.82%→70.35%，句子 exact match 仍为 11/515；95 条逐句编辑距离改善、93 条退步、327 条持平。常见诊断线索包括“你/我”替换、编号 Gloss 变体替换，以及“我/不/想”等删除。编辑对齐存在并列路径，不据此自动更改标注。
- 这些结果支持另建视频→Gloss 模型，而不是继续加训文本→Gloss 模型。视觉训练尚未开始：上次训练的明确边界是不上传原视频，CE-CSL 上游授权条款也未独立核实。原视频目前只在本机，未传服务器；必须先解决数据移动授权与实际来源代码/手语者映射，再启动 GPU 训练。
- 视频审计结果：`local-data/ce-csl-video-readiness-20261023-v2/`。来源代码分组折：`local-data/ce-csl-source-code-folds-20261023-v1/`。第一版审计因本工具把 ffprobe/ffmpeg 路径变量混用而产生失败报告，保留在 v1；回归测试修复后 v2 的 5,488 条全部通过。

截至此审计，`test_read=false`、`training_ready=false`、`model_training_ready=false`、`deployment_ready=false`；没有发生视频识别训练或 Demo 集成。
