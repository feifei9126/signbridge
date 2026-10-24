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
- 这些结果支持另建视频→Gloss 模型，而不是继续加训文本→Gloss 模型。用户已明确授权将 CE-CSL 用于本项目，并另行授权仅把 train 视频和 train Gloss 标签传到其私有 GPU 服务器做研究训练；dev/test 不上传、不读取，视频不进入 GitHub。上游公开许可条款仍未独立核实，因此本轮只限私有研究用途，不做再分发。A-L 来源代码仍未证明对应唯一 signer。
- 视频审计结果：`local-data/ce-csl-video-readiness-20261023-v2/`。来源代码分组折：`local-data/ce-csl-source-code-folds-20261023-v1/`。第一版审计因本工具把 ffprobe/ffmpeg 路径变量混用而产生失败报告，保留在 v1；回归测试修复后 v2 的 5,488 条全部通过。

## 视频→Gloss 首轮研究基线

- 新增独立工具 `signbridge/src/tools/sign-csl-video-gloss.py`，与文本→Gloss 模型、SMPL-X/动作库及 Demo 播放完全分离。模型采用逐帧轻量 CNN 空间特征 + 双向 GRU 时间编码 + CTC Gloss 解码；均匀采样 32 帧，保持 16:9 全画面并补边到 128×128，避免中心裁剪切掉手部。训练输入逐条校验 SHA-256/字节数；相同视频字节的重复记录在划分前整体隔离，避免跨折泄漏或矛盾标签。
- 数据仅来自 4,973 条 train 记录。来源代码 G 仅用于每轮 checkpoint 选择；来源代码 H 只在选择完 checkpoint 后做一次最终 holdout 评估；两者都不是已验证的 signer 独立划分。其余 train 来源代码用于梯度更新。词表仅从梯度训练子集构建，selection/final holdout 未见 Gloss 映射到 `<unk>`，并单独报告 OOV。
- 训练包只含 train 样本 ID、来源代码、Gloss 序列、视频相对路径及完整性摘要；不含原始中文句子、用户本机绝对路径或 dev/test。视频单独传到私有 GPU 机器系统盘，先逐条校验后使用，不写空间紧张的数据盘；不安装依赖、不改旧权重。
- 初始配置：固定 seed 20261023、32 帧、128×128、batch 8、AdamW、learning rate 2e-4、最多 20 epoch、patience 6；按 G 组 GER 选权重，在所选 checkpoint 上对 H 组仅评估一次。结果必须报告 Gloss GER、整句 exact match、substitution/deletion/insertion、OOV 和逐条预测，不把训练损失当作识别率。
- 训练中缓存的缩放帧是可重建的临时派生输入，与正式模型产物分开。模型和输入验证结束后仍需审查日志、摘要、有限权重与预测复算；实验成功不等于真实 CSL 理解，也不授权动作播放或 Demo 上线。

截至视频模型训练验证完成前，`test_read=false`、`training_ready=false`、`model_training_ready=false`、`deployment_ready=false`；不接入 Demo、不修改 T08 或动作库。

## 视频→Gloss 三次 GPU 尝试的最终结论（2026-10-23）

- 三次尝试均使用同一台 RTX 4090 D 私有服务器、同一批 4,973 条 train 视频，并复用逐条 SHA-256 校验通过的 4,971 条 32×128×128 缓存帧；官方 dev/test 从未读取或上传，H 组在 V2/V3 中完全排除。
- V1（原始词表，G 选模、H 最终留出）运行 7 轮后停止：train/G/H 均 blank collapse，GER 100%，exact match 0，最终留出 101 条全部空预测。
- V2（Gloss 最低出现次数 3、词表约 1,091 类、blank penalty 0.1，G 选模、F 最终留出、H 排除）运行 7 轮后停止：G/F GER 均 100%，exact match 0，空预测率 100%。
- V3（V2 配置 + blank penalty 1.0 + blank logit 初始偏置 -2.0）运行 7 轮后停止：第 1 轮训练集短暂出现非 blank 输出，但 G 组仍全 blank；最终 F 留出 492 条 GER 100%、exact match 0、空预测率 100%。
- 三次的 checkpoint 参数均有限、可加载，训练进程均已终止，训练输出内部 SHA-256 和预测复算均通过；因此结论是**当前轻量 CNN+GRU+CTC 基线在这批 sequence-level Gloss、无词级边界的监督下发生系统性 blank collapse**，不是服务器、磁盘、视频摘要或归档损坏。
- 证据归档：`local-data/ce-csl-video-gloss-results-20261023-v1/`；远端外层归档 SHA-256 为 `06fe97a3474cb514a1a795e6db750bb5ec4c57a5511421442f00c7804102eb8d`。三次尝试、日志、配置、权重、预测和包清单均保留。
- 本轮停止继续训练，不把 0% 识别结果接入 Demo，不把它称为中国手语理解模型。后续若要继续，必须改变监督/模型目标（例如可靠词级边界或不同的视频识别架构）并建立新的独立实验；不能只重复增加 epoch。

最终状态仍为：`test_read=false`、`dev_read=false`、`training_ready=false`、`model_training_ready=false`、`deployment_ready=false`；动作库、T08 checkpoint 和公开 Demo 未修改。

## 小样本训练链路诊断（2026-10-24）

- 已实现 train-only 缓存过拟合诊断入口：从当前梯度训练来源中按固定 seed 确定性选择 8 条、Gloss 长度不超过 6 的片段，复用 V1 已验证 32×128×128 帧缓存；诊断前要求缓存清单摘要、train samples SHA-256、源报告视频完整性通过且缓存 ID 集精确匹配。
- 诊断只训练这 8 条，最多 200 步，每 10 步记录 train 子集 GER/exact、CTC blank/空预测、CNN/GRU/head 梯度范数和参数变化。它不做泛化评估，不读取 G/F/H 视频用于评估，不接入 Demo，也不改变任何现有 checkpoint。
- 固定本地配置和脚本快照：`local-data/ce-csl-video-gloss-overfit-diagnostic-20261024-v1/`。抽样 ID 固定保存在 provenance 中；再次运行须使用新的输出目录。
- 2026-10-24 检查授权 GPU 主机时，SSH 端口 37077 返回 `Connection refused`，因此诊断尚未启动；没有改为 CPU 或其他服务器。恢复运行的门槛是 8 条训练片段达到至少 95% exact match，且 CNN、GRU、输出头梯度均有限、非零、参数发生更新。未达到门槛则只根据诊断证据修训练链路，不开始全量训练。
- 此诊断门槛只证明可以记忆小型训练子集，不代表 CSL 识别或泛化准确率。官方 dev/test 与模型晋升状态继续保持不变。
