# SignBridge 手语模型研发、训练与评估整体报告

> 版本：2026-10-10 本地证据冻结版 v1；时区：Asia/Shanghai（UTC+08:00）。
>
> 本报告用于后续接手、定位产物、调用权重、复跑研究流程以及判断哪些结果可采用。它整合数据准备、环境建设、重建、试修、训练、评估、失败、回退和未完成项。自动报告是证据，不是对手语正确性的自动批准。

**HTML整体报告：** [完整报告与证据检索](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/index.html>)  
**机器注册表：** [training-registry.json](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/training-registry.json>) · [catalog.json](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/catalog.json>)  
**接手入口：** [RESUME-CONTEXT.md](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/RESUME-CONTEXT.md>)  
本次冻结源码：`26d8d7618a1c8d6302443883a8a4a865ef53ac60`。生成时点：`2026-10-10T10:27:18.085402+08:00`。

## 2026-10-12 追加：T08 虚拟人物 Demo 已交付

2026-10-10 的证据目录、历史训练注册表和下面的研发统计保持冻结。新增实验性 Demo 已把 **T08 的14段实际 token 解码动作**转换到当前 Godette 虚拟人，并与 **52个内置动作**共同按文字检索播放；程序阶段无需新GPU训练。它没有把T08改成通用文字生成模型，也没有升级旧研究候选的正式资格。

- 使用与完整文字清单：[Demo说明](demo.md)。
- 当前验证、发现并修正的问题和成品摘要：[交付验证记录](demo-validation-20261012.md)。
- 最新可调用资产：`local-data/demo-20261012/t08-motion.json`，T08 checkpoint SHA仍为 `438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b`；新增CPU导出不计作新训练。
- 成品：`local-data/demo-20261012/delivery/`，内含独立Demo包、完整插件包和macOS启动器。
- 实际证据：`local-data/demo-20261012/browser-qa/report.json`，完整播放14/14参考段及52/52词条，真实扩展弹窗入口通过；149项JS和5项Python测试通过。

下面第0节起为2026-10-10历史冻结结论；有关“尚无动画接入交付”的历史描述应与本次新增实验Demo一起阅读。任意新句生成与正式语言质量仍未完成。

### 2026-10-12 实时字幕接入补充

实际检查发现，独立Demo可播放T08并不代表插件的网页实时字幕已经接入T08；此前实时字幕确实一直使用原有词库/自定义动作。现已将路由接入插件 iframe：完整字幕严格匹配14条训练参考句时按需加载对应T08解码姿态，其他输入和故障回退仍使用原有翻译管线。来源徽标显示本次动作排入的来源。

代码：`signbridge/src/avatar/iframe-bundle.js`（路由与按需加载）、`signbridge/src/avatar/motion-player.js`（四元数序列插值）、`signbridge/src/demo/demo-motion.js`（完整句匹配）、`signbridge/scripts/build.mjs`（运行时索引打包）。浏览器回归脚本：`signbridge/tests/realtime-t08-browser-qa.mjs`。测试使用独立Chromium扩展页；完整句“工作忙吗？”应进入 `pilot-greeting-busy-005`，单词“谢谢”和额外尾词应回退原动作库。此处仍是已训练参考动作查表/重建，不是泛化文字生成。

### 2026-10-12 候选常用句补充

新增三条文字/拟合对照已经用户确认的连续句子，用原T08在CPU上重新编码/解码，单独作为候选：“如果下雨可以借你一把。”“我给她买了一件衣服”“去人民广场怎么走？”。它们未参与T08训练，且镜像与人物分组未确认；`training_ready=false`、候选标志和较高的归一化重建误差保持可见。详见 [候选扩充记录](t08-phrase-expansion-20261012.md)。没有新权重、没有改变原训练/保留划分，不能算作新增训练轮次或正式语言质量通过。

## 0. 先读：现在处于哪一步

**已经真实跑通的是“授权视频 → 候选/核验片段 → SMPL-X 模型估计 → 133 维动作 → 小型 VQ 动作编码器训练 → checkpoint 重载 → CPU/GPU 推理 → 参数和动画诊断”。还没有训练完成文字到手语生成模型，也没有可部署的手语大模型。**

本地能够核验的研究训练有 **9 份不同 SHA-256 权重**，另有 **1 轮只在历史服务器终端确认的 v2 训练**。数据、优化步数或结果相同不表示同一权重；复核副本、CPU 推理和只读重新出图不再计为新训练。

后续最常用入口：

| 需求 | 优先定位 | 当前资格 |
| --- | --- | --- |
| 继续保留的 14 段动作编码研究 | **T08**：14 段原始 SMPL-X 动作训练权重 | 本轮保留的研究基线；非生产模型 |
| 对照旧两段全长融合/mask技术链路 | **T05**：旧两段输入占位/mask一致性修正版 | 技术复现参考；非正式训练数据 |
| 回看留来源差距 | **T06/T07**：分别从头训练的两折权重 | 来源记录层面的历史诊断；真人/教材独立性未批准 |
| 查看掩码方案的局部收益和失败 | **T09**：14 段自动观测mask v1 | 实验候选，左手退化，未整体替换T08 |
| 恢复歧义手别mask v2 | **T10**：远端专用路径 | 尚未下载本地；当前连接拒绝，摘要未知 |
| 查具体哪个片段/手出错 | 手部质量逐帧清单、WiLoR关键帧与手别诊断 | 技术证据，不是人工标注 |
| 把模型直接接入插件或生成未见句子 | 尚无对应合格模型/重定向交付 | 不可把研究权重当作已实现的生成器 |

`training_ready=false`、`deployment_ready=false`、`text_to_sign_trained=false` 是对正式资格的限制。已经运行过研究训练与这些标志不矛盾。没有把数据或模型升级为生产级。

## 1. 报告覆盖范围与证据强度

- 可检索证据文档/日志/源码快照：**5088份**。
- 其中控制报告、计划、状态、审核、verification：**177份**（包含同阶段不同版本）。
- 项目研究文件目录：**43,294项**，体积大文件以引用为主。
- 证据文本快照体积约**36.66MiB**，完整保留而非只摘结论。
- 本地训练checkpoint摘要：**9份重算匹配**；另1轮远端历史训练未取得本地权重。
- 本次原研究目录：只读；报告整理不改变训练输入、模型或已有划分。


### 1.1 什么叫“全部”

本次全量扫描覆盖项目现存本地研发证据：报告、逐帧相机元数据、运行状态、JSONL、片段表、摘要清单、日志、依赖freeze、源代码和测试快照。原始模型、视频、图片、逐帧数组、归档也登记到文件目录；不重复拷贝这些体积大的二进制产物。

第三方Git对象、第三方源码缓存、`__pycache__`、逐次上游复制的`runtime`源码和YOLO设置不混入研发记录总数。当前项目工具、测试、关键依赖版本文件及官方模型来源清单单独保存快照，足以区分本项目改动与上游版本。

没有保存过的对话、服务器完整日志或未下载权重，不能在整理时补造。本报告明确标出：历史终端输出确认的事实、本地完整文件确认的事实以及尚未确认的事实。

### 1.2 证据分层

| 等级 | 定义 | 本项目例子 |
| --- | --- | --- |
| A | 本地报告和二进制权重存在，SHA-256重算匹配 | T01–T09 |
| B | 本地完整日志/数组/摘要存在，可以定位和复算 | 旧两段、14段、三段重建和评估 |
| C | 历史终端记录确认运行，但本地原始报告/权重尚未完整取得 | T10、早期部分系统兼容修复 |
| D | 静态计划、dry-run、预检或文档建议 | Mac v1–v6 fit-plan、未来文字生成计划 |
| E | 用户对明确对象的核对陈述 | 旧16段内容核对、三段内容及动作观感验收 |

用户授予视频授权或自主运行权限，不等于动作语义已经逐帧确认。三段“通过”只覆盖当时展示的动作观感；没有推导出其他片段的镜像、人物身份、最终数据划分或生产资格。

### 1.3 时间与状态口径

- 所有主时间线用北京时间；原报告`created_at`保留原始UTC字符串，登记时另提供本地转换值。
- 目录日期通常是任务启动日期，结束/审核日期可以更晚。
- `mtime`仅用于查找，不能当作实际训练启动或结束证据。
- `state.json`里的PID和“running”可能只是历史记录。当前正在运行与否必须实时查进程，不依赖旧状态文件。
- 本次报告整理没有启动训练、重建或升级环境。尝试只读连接服务器时收到`Connection refused`，不能据此宣称当前GPU已释放或服务器已经运行某任务。

## 2. 研发目标、现有产品与训练工程的关系

### 2.1 原始目标

用户希望把授权手语视频喂给可学习动作与语言对应关系的模型，最终做成手语大模型，并与SignBridge浏览器插件的虚拟人结合。不是给插件加“播放视频”功能。

### 2.2 已实现的工程层

1. 本地数据清点：来源ID、摘要、授权陈述、元信息。
2. 分段/释义：OCR候选、人工内容确认、边界记录。
3. MediaPipe观察：身体、双手、面部估计和缺失mask。
4. SMPLer-X重建：逐帧SMPL-X参数和虚拟相机。
5. WiLoR/MANO试验：专用手部重建，映射/融合/约束试验。
6. SOKE动作表示：179维原始参数约定转为133维模型输入。
7. 小型动作VQ tokenizer：三个部件的从头训练、编码与重建。
8. 评估/审计：训练内指标、冻结迁移、来源分组诊断、动作对照。

### 2.3 仍未实现或未批准的层

- 没有已经训练好的“文本/字幕 → 动作token序列”语言生成器。
- 没有已完成的mBart等文字条件生成权重，也没有官方完整宽度SOKE预训练tokenizer替代品。
- 研究SMPL-X/MANO参数不能不经重定向直接赋给插件GLB骨骼。
- 插件仍采用现有动作库、`humanoid-local-v1`动作空间、Three.js和实际rig绑定；训练工程不会自动改写该库。
- 没有独立手语专家语义、实际接触、手别/镜像及外部人物数据的全面验收。

## 3. 授权素材、数据版本与逐片段范围

### 3.1 来源总量

源目录：`/Users/mac/Desktop/手语`。源清单：[sources.json](</Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-pilot/sources.json>)。

授权源视频记录 **13个**，总时长约**97.45分钟**，原始文件约**0.90GiB**。以下是清单原记录，不意味着13个独立人物/课程组。

| 来源ID | 原视频文件名 | 时长秒 | 宽×高 | 源fps | 授权字段 |
| --- | --- | --- | --- | --- | --- |
| source-8905e0a55f964a97 | 1/_-10.第十课 旅游_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 505.568 | 1920×1080 | 24.000032 | user_reported |
| source-bd4c412e80d2131f | 1/_-2.第二课 学习_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 434.491 | 1920×1080 | 24.000018 | user_reported |
| source-056e5781ad267f00 | 1/_-3.第三课 家庭_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 376.124 | 1920×1080 | 24.000064 | user_reported |
| source-3c8a1288cdc61c2a | 1/_-4.第四课 兴趣_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 408.624 | 1920×1080 | 24.000020 | user_reported |
| source-fe2208d9680580cd | 1/_-5.第五课 天气_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 434.166 | 1920×1080 | 24.000037 | user_reported |
| source-8ffc3bdb3f8d0763 | 1/_-6.第六课 节日_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 466.930 | 1920×1080 | 24.000034 | user_reported |
| source-58a5b3d6622ea72a | 1/_-7.第七课 出行_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 395.226 | 1920×1080 | 24.000040 | user_reported |
| source-fea78075fabaa414 | 1/_-8.第八课 购物_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 374.746 | 1920×1080 | 24.000021 | user_reported |
| source-efee520987e8d59d | 1/_-9.第九课 聚会_《中国手语教程》_倪兰-手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 490.962 | 1920×1080 | 24.000016 | user_reported |
| source-24f220ed4aef1b2d | 1/_-中国手语教程（中级）倪兰主编  复旦大学出版社-中国手语教程（中级）倪兰主编  复旦大学出版社.mp4 | 987.029 | 1920×1080 | 30.000000 | user_reported |
| source-23efbaded8944f2f | 1/复旦音像-1.第一课 问候_《中国手语教程》_倪兰手语配套视频 《中国手语教程》（初级）倪兰.mp4 | 386.645 | 1920×1080 | 25.000000 | user_reported |
| source-c2210004c741aa52 | 2/_-挑战100天教会大家手语day1：问候篇-挑战100天教会大家手语day1：问候篇.mp4 | 110.086 | 1080×1440 | 30.000182 | user_reported |
| source-3a05845fea103410 | 2/_-跟聋人学手语0基础全套课程教学-跟聋人学手语0基础全套课程教学.mp4 | 476.543 | 1280×720 | 25.000000 | user_reported |


来源通过本地`source_id`和SHA-256定位；路径不同不保证人物或内容独立。同教材不同课程保守关联，实际人物关系没有依靠脸部外貌自动识别。

### 3.2 原始批次版本

| 版本 | 实际用途 | 审核状态/限制 |
| --- | --- | --- |
| `sign-language-pilot` | 来源清点、OCR与16段标注 | 扫描时默认needs_review |
| `sign-language-first-batch` / `-v2` | 早期小批次提取与修正 | 留存旧证据，不混作完整训练 |
| `sign-language-candidates-v3` | 16段、3116帧关键点与预览 | 候选版原始记录保留 |
| `sign-language-reviewed-v4` | 用户2026-09-28核对陈述的新版本 | 内容/边界approved；镜像unknown |
| `sign-language-smplx-input-v1` | 16段逐帧图片、观察数据、时间与摘要 | 全批可重建输入，非生产训练资格 |
| `sign-language-gpu-stage-v1` | 固定源码、检测资源的早期搬运包 | 主人体/网络资源后续补齐 |
| `sign-language-gpu-stage-v2` | 9.2GiB量级GPU搬运包 | 全16段与模型文件，内部SHA256SUMS |

原16段按源记录为7段问候、9段医院。此前“你好”和“咳嗽”两段合计384帧；其余14段2732帧。这三组计数相加关系为`384 + 2732 = 3116`，不能把多次派生处理当成更多独立视频。

### 3.3 原16段完整清单

| 片段ID | 释义 | 源起止秒 | 帧 | 内容/镜像/split | 训练用途 |
| --- | --- | --- | --- | --- | --- |
| pilot-greeting-hello-001 | 你好，好久不见！ | 254.85–261.5 | 166 | 已核对 / unknown / unassigned | T01–T05等旧两段试验；T08未包含 |
| pilot-greeting-answer-002 | 是啊，你过得好不好？ | 281.65–288.65 | 174 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-cough-003 | 我咳嗽了一个星期，一直不见好转。 | 739.0–747.7 | 218 | 已核对 / unknown / unassigned | T01–T05等旧两段试验；T08未包含 |
| pilot-greeting-how-004 | 很好，你呢？ | 262.45–268.6 | 153 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-greeting-busy-005 | 工作忙吗？ | 268.65–274.6 | 148 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-greeting-lunch-006 | 一起去吃饭吧！我请客。 | 274.65–280.8 | 153 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-greeting-well-007 | 我也很好！ | 288.7–293.6 | 122 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-greeting-overtime-008 | 很忙，最近经常加班。 | 293.65–300.75 | 177 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-cold-009 | 有些感冒，喉咙发炎了，其他都很好，别担心。 | 678.5–689.8 | 282 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-rest-010 | 好好休息，大概一周就会好转。 | 702.7–709.05 | 159 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-allergy-011 | 可以。药物过敏吗？ | 709.7–716.9 | 180 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-dose-012 | 这个药每天三次，早、中、晚各一次，每次2片，饭后服用。 | 717.3–730.0 | 318 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-pay-013 | 先交费，然后去取药。 | 730.5–737.0 | 163 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-temperature-014 | 刚量过体温，36.2度，嗓子疼，头痛，流鼻涕。 | 747.7–760.85 | 329 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-serious-015 | 有什么问题吗？严重吗？ | 761.5–767.7 | 155 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |
| pilot-hospital-iv-016 | 我需要打针、输液吗？ | 768.35–777.1 | 219 | 已核对 / unknown / unassigned | T08/T09/T10的14段范围 |


`fps=25`为派生片段及其采样时间轴，不代表源视频本来就是25fps。原片的解码与采样经过严格核验；表中人物ID是已有课程记录，不意味着跨课程真人身份独立。

### 3.4 新11来源候选扩充

2026-10-10对原13个文件中未参与旧两来源训练的11个重新核对源摘要，用0.5fps采样与macOS Vision OCR完成2235张采样图、1575个字幕候选区间，其中263个带单人示范章节文字。章节文字不等于人物身份或人数验证。

制作27段整句候选（3850帧）和4段词汇/教学候选（700帧），共31段4550帧、62个clip/overlay视频。8段某侧手返回率低于20%。缺失观测保持NaN及mask，不填零或插值。OCR时间是稀疏字幕名义区间，不是精确动作真值。

| 新候选ID | 候选文字 | 区间秒 | 类别 | 当前使用说明 |
| --- | --- | --- | --- | --- |
| new-8905e0a55f964a97-0083 | 你喜欢这个宾馆吗？ | 221.0–227.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-8905e0a55f964a97-0088 | 有事可以和我联系。 | 237.0–241.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-8905e0a55f964a97-0127 | 好漂亮，我很想去。 | 335.0–341.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-bd4c412e80d2131f-0096 | 教完了，你们朋白了吗？ | 237.0–243.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-bd4c412e80d2131f-0128 | 下次上课交。 | 333.0–339.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-bd4c412e80d2131f-0129 | 你们有问题可以互相帮助。 | 339.0–347.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-056e5781ad267f00-0065 | 你家有几日人？ | 171.0–177.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-056e5781ad267f00-0066 | 你做什么工作？ | 177.0–181.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-056e5781ad267f00-0067 | 你在哪里读书？ | 181.0–185.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-3c8a1288cdc61c2a-0074 | 你平时喜欢做什么？ | 191.0–197.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-3c8a1288cdc61c2a-0075 | 你喜欢什么运动？ | 197.0–201.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-3c8a1288cdc61c2a-0081 | 我喜欢看体育电视节目。 | 217.0–223.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-fe2208d9680580cd-0081 | 今天天气很好。 | 207.0–211.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-fe2208d9680580cd-0087 | 如果下雨可以借你一把。 | 229.0–233.0 | sentence | 另有三段审核/重建，但用户暂停后不训练 |
| new-fe2208d9680580cd-0089 | 是的，比昨天好多了。 | 237.0–241.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-8ffc3bdb3f8d0763-0084 | 下周就是中秋节了。 | 231.0–237.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-8ffc3bdb3f8d0763-0090 | 我很期待中秋节快点到来。 | 255.0–261.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-8ffc3bdb3f8d0763-0124 | 我给她买了一件衣服 | 345.0–351.0 | sentence | 另有三段审核/重建，但用户暂停后不训练 |
| new-58a5b3d6622ea72a-0068 | 去人民广场怎么走？ | 209.0–217.0 | sentence | 另有三段审核/重建，但用户暂停后不训练 |
| new-58a5b3d6622ea72a-0072 | 大概走多长时间？ | 225.0–231.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-58a5b3d6622ea72a-0095 | 你家离学校远吗？ | 287.0–293.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-fea78075fabaa414-0072 | 有大一点的吗？ | 201.0–205.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-fea78075fabaa414-0077 | 太贵了，可以便宜些吗？ | 213.0–219.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-fea78075fabaa414-0098 | 我想买台电脑。 | 275.0–281.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-efee520987e8d59d-0078 | 我们办一个生日聚会吧！ | 213.0–221.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-efee520987e8d59d-0083 | 可以，我通知朋友。 | 231.0–237.0 | sentence | 仍待内容/边界人工核验；未训练 |
| new-efee520987e8d59d-0089 | 好，我下午休息，我订蛋糕吧。 | 253.0–261.0 | sentence | 仍待内容/边界人工核验；未训练 |
| word-c2210004-hello | 你好 | 3.0–11.0 | word | 仍待内容/边界人工核验；未训练 |
| word-c2210004-question | 你好吗 | 85.0–93.0 | word | 仍待内容/边界人工核验；未训练 |
| word-3a05845f-hello | 你好 | 377.0–383.0 | word | 仍待内容/边界人工核验；未训练 |
| word-3a05845f-friend | 朋友 | 407.0–413.0 | word | 仍待内容/边界人工核验；未训练 |


### 3.5 三段新增试点的全部状态

- 天气：`new-fe2208d9680580cd-0087`，229–233秒，100帧，“如果下雨可以借你一把。”。
- 节日：`new-8ffc3bdb3f8d0763-0124`，345–351秒，150帧，“我给她买了一件衣服”。
- 路线：`new-58a5b3d6622ea72a-0068`，209–217秒，200帧，“去人民广场怎么走？”。

用户确认现有释义/范围无误后新建审核版本，重新prepare成精确三段批次；不把3条标注直接配到27条候选清单。RTX4090实际SMPLer-X推理完成450帧，严格导入3/3、float32全有限。用户对三段叠加动画表示“通过”，保存可追溯动作观感审核。

之后用T05做冻结迁移：归一化MSE1.28843，均值基线1.58914，相对改善18.923%；raw RMSE0.23357；手部投影差53–105px。结果不支持将旧tokenizer直接当作新片段生成器。

用户随后要求“先放弃这三个片段，先对其它片段训练”。因此后三段没有用于T08、T09或T10训练，手部试修未继续。审核记录和参数保留，不删除证据，也不把停止使用等同于原始人工确认被撤销。

## 4. 数据表示和不可混用的坐标约定

### 4.1 MediaPipe观察数据

| 字段 | 每帧形状 | 含义 |
| --- | --- | --- |
| `pose_image` | 33×4 | 图像归一化x/y、模型相对z、visibility |
| `pose_world` | 33×4 | 另一组模型估计身体坐标，不能当作全身/双手统一真值 |
| `left_hand_image` / `right_hand_image` | 21×3 | 图像归一化x/y；z以手腕为参考，不同手/面部不共享metric frame |
| `face_image` | 468×3 | 模型估计归一化面部点 |
| `*_detected` | T布尔值 | 关键点存在，不表示准确率 |
| `timestamps_seconds` | T | 派生片段时间轴 |
| `source_timestamps_seconds` | T | 源片段起点加采样时间，名义时间而非原始逐帧PTS |

没有检测到的数组保留NaN。神经网络内部针对mask的中性归一化占位不写回观察文件或动作参数，也不能据此宣称补出了缺失手。

### 4.2 SMPL-X原生参数

| 参数 | 每帧形状 | 说明 |
| --- | --- | --- |
| global_orient | 1×3 | 根axis-angle |
| body_pose | 21×3 | 躯干/四肢axis-angle |
| left_hand_pose | 15×3 | 左手完整axis-angle |
| right_hand_pose | 15×3 | 右手完整axis-angle |
| jaw_pose | 1×3 | 下颌 |
| leye_pose/reye_pose | 各1×3 | 眼球，常含float64 |
| betas | 1×10 | shape |
| expression | 1×10 | expression |
| transl | 1×3 | SMPLer-X虚拟相机坐标下平移 |


必须完整axis-angle手部，不接受PCA手系数；`use_pca=False, flat_hand_mean=False`。手部均值只应用一次。`global_orient`、相机平移、眼部参数、shape以及不进入133维的下身从真实拟合输入保留，不归功于tokenizer预测。

### 4.3 SOKE 133维精确顺序

先按root3、body63、左手45、右手45、jaw3、shape10、expression10组成179维；删前36维及shape10，结果为：

| 133维切片 | 维度 | 参数 |
| --- | --- | --- |
| `0:30` | 30 | body_pose后10个关节 |
| `30:75` | 45 | 左手15关节×3 |
| `75:120` | 45 | 右手15关节×3 |
| `120:123` | 3 | jaw |
| `123:133` | 10 | expression |

对应网络三部分：body+face=43、左手45、右手45。不要把shape当expression、不要换左右手、不要把相机平移混入这133维。

### 4.4 MANO/WiLoR

WiLoR输出right-canonical MANO旋转矩阵，不是SMPL-X轴角。左手显示时反射图像空间几何并反转三角面顺序；不能把这一步等同于整个视频镜像已确认。MANO/SMPL-X拓扑、手部均值、腕部链和相机约定需要显式映射和受限对齐。

MANO原始模型16关节、778顶点、1538面、10个shape系数；观察图采用21点手部（含指尖）。本地只验证WiLoR原生右MANO加载；LEFT文件保存，但不能推导出原生左模型CUDA调用已验证。

## 5. 本机/远端环境、模型文件和版本冻结

### 5.1 实际环境层次

| 环境 | 目的 | 已记录版本/能力 |
| --- | --- | --- |
| Mac `.venv-sign-data` | 数据准备、数组审计、工具测试 | Python3.12环境；早期要求Python3.10–3.12；NumPy1.26.4/MediaPipe0.10.21/OpenCV4.11系列 |
| Mac `.venv-wilor` | CPU tokenizer推理、SMPL-X数学/投影分析 | Python3.10.21、torch2.2.2、NumPy1.23.5，CUDA不可用 |
| GPU `envs/driver` | fit/export/import驱动、来源校验 | Python3.11.17、NumPy1.26.4/OpenCV4.11.0 |
| GPU `envs/smplerx` | 上游SMPLer-X与研究tokenizer训练 | Python3.8、torch1.12.0、CUDA11.3、mmcv-full1.7.1、mmdet2.26.0、vendored mmpose0.28.0 |
| GPU `envs/wilor` | 固定WiLoR与MANO推理/渲染 | Python3.10、torch2.2.2+cu118、隔离依赖，不替换SMPLer-X环境 |
| GPU硬件 | CUDA实际运算 | NVIDIA GeForce RTX4090，历史显示24564MiB |

旧torch和4090组合已实际做NMS/ROIAlign及完整推理验证，不以版本表推断“必然失败”或自动重装环境。Mac没有torch的系统Python不能代替上述虚拟环境。

### 5.2 固定上游版本

| 项目 | 固定身份 | 已有本地路径 |
| --- | --- | --- |
| SMPLer-X | 064baef0e4ab5277a3297691bc1d46ea5412586f | /Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X |
| SOKE | 5cbc55d84b5a7cbf05a9cf020c468052e8d94d00 | /Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SOKE |
| WiLoR | fcb911312a38fa8badd30d9656a167485d61b8f9 | /Users/mac/Documents/ChatGPT/signbridge/local-data/deps/WiLoR |
| 人体文件来源HF Space | 2de1f98db5c59da6326dc8fac4c00c78010fa6e5 | common/utils/human_model_files/signbridge-body-assets.json |
| WiLoR资源HF Space | 99fe3d7acff8104ecca1055df7467709506c2fa6 | /Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-weights.json |


运行前核对git HEAD和关键源文件摘要；实际执行脚本的摘要可能因后续功能扩展变化，不能要求所有历史脚本都等于当前HEAD。历史脚本和freeze以证据包为准。

### 5.3 资源身份清单

| 文件 | 字节 | SHA-256 | 来源 |
| --- | --- | --- | --- |
| common/utils/human_model_files/smpl/SMPL_NEUTRAL.pkl | 247186228 | 4924f235e63f7c5d5b690acedf736419c2edb846a2d69fc0956169615fa75688 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smpl/SMPL_MALE.pkl | 247101031 | ed4d55bb3041fefc6f73b70694d6c8edc1020c0d07340be5cc651cae2c6a6ae3 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smpl/SMPL_FEMALE.pkl | 247530000 | 6d4a1791b6b94880397e1a3a4539b703a228d2150c57de7b288389a8115f4ef0 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smplx/SMPLX_NEUTRAL.npz | 108752058 | 376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smplx/SMPLX_MALE.npz | 108753445 | ab318e3f37d2bfaae26abf4e6fab445c2a610e1d63714794d60379cc263bc2a5 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smplx/SMPLX_FEMALE.npz | 108794146 | b2a3686c9d6d218ff6822fba411c607a3c8125a70af340f384ce68bebecabe0e | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smplx/MANO_SMPLX_vertex_ids.pkl | 13535 | e5abe70b6574de25470475091e8008314a5b90127eb48c3e63bfa0adf8c04dcf | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smplx/SMPL-X__FLAME_vertex_ids.npy | 40312 | 7e70cdc3659aae699b9732e8dd4af49106310c69b90dc83d9f73e96dbf871e49 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| common/utils/human_model_files/smplx/SMPLX_to_J14.pkl | 4692193 | 5df844ddea85b0a400a2e8dbe63d09d19f2b1b7ec0e0e952daeae08f83d82d61 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/common/utils/human_model_files/signbridge-body-assets.json>) |
| pretrained_models/mmdet/mmdet_faster_rcnn_r50_fpn_coco.py | 见来源清单 | bb2905aaf5ff6aa4ce75d9aa63070368a96e9add16e3baab28debdea7c064c48 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/pretrained_models/signbridge-public-assets.json>) |
| pretrained_models/mmdet/faster_rcnn_r50_fpn_1x_coco_20200130-047c8118.pth | 见来源清单 | 047c8118fc5ca88ba5ae1fab72f2cd6b070501fe3af2f3cba5cfa9a89b44b03e | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/pretrained_models/signbridge-public-assets.json>) |
| pretrained_models/smpler_x_h32.pth.tar | 7942508159 | 3d40511141fa1ef0d022c095c470b7ad2710e390aea68ce87ac0361911af133b | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SMPLer-X/pretrained_models/signbridge-public-assets.json>) |
| MANO_LEFT.pkl | 3821391 | c4022f7083f2ca7c78b2b3d595abbab52debd32b09d372b16923a801f0ea6a30 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/mano/manifest.json>) |
| MANO_RIGHT.pkl | 3821356 | 45d60aa3b27ef9107a7afd4e00808f307fd91111e1cfa35afd5c4a62de264767 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/mano/manifest.json>) |
| MANO-LICENSE.txt | 4330 | 75fc4da03259504ce9a4ed2418ab98dd59647add7ff95e7691c4d55fb0e3cf63 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/mano/manifest.json>) |
| pretrained_models/detector.pt | 53582271 | 5ef3df44e42d2db52d4ffe91f83a22ce9925e2acc9abebf453f2c5d22e380033 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-weights.json>) |
| pretrained_models/wilor_final.ckpt | 2564989533 | 3e97aafc7dd08d883a4cc5a027df61fdb6fda6136dbd1319405413862ada6bb2 | [来源manifest](</Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-weights.json>) |


视频授权陈述、MANO/SMPL-X账号/文件下载、模型资源许可是不同事项。报告记录已有许可文件及`commercial_license_verified=false`等字段，不重新作法律判断。可下载不等于可分发；研究人体模型不打进插件发布包。密码和访问凭据不进入报告。

### 5.4 SSH位置与当前连接缺口

历史第一主机端口22210，之后克隆主机端口26919；宿主`connect.cqa1.seetacloud.com`。`ssh -CNg -L...`是隧道命令，不是交互登录shell；Mac路径与`/root/autodl-tmp/...`远端路径不能互换。

本次报告整理仅一次尝试26919端口，返回连接拒绝。T10完整报告/权重没有恢复本地。报告提供恢复路径与指令，不储存任何SSH密码。

## 6. 全过程时间线：包括计划、失败和候选

| 阶段 | 北京时间段 | 过程 | 主要证据 | 结论/限制 |
| --- | --- | --- | --- | --- |
| P01 | 2026-09-28 | 数据清点与首批候选：13源；数据授权陈述；来源sha；制作小批次并保留早期v1/v2 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-pilot/sources.json>) | 不是训练 |
| P02 | 2026-09-28 | OCR、16段核对与输入导出：字幕候选与用户人工确认分版本；16段3116帧；25fps输入包 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-reviewed-v4/review-decision.json>) | 内容approved；mirror unknown |
| P03 | 2026-09-28–09-30 | 资产下载与6次Mac预检：缺资源→公开检测/主权重与9人体文件补齐；固定source/LFS摘要 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-fit-plan-mac-v6/run.json>) | Mac没有CUDA，blocked不是推理失败 |
| P04 | 2026-10-07 | 原主机22210环境与实际两段重建：pip timeout、EGL、config路径、torchgeometry bool修复；166/218帧真实H32推理 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/camera-source-20261009/run.json>) | 2段完成；导入与视觉审核分开 |
| P05 | 2026-10-07 | 两段动作回传/初步视觉检查：全clip/网格对比；双指、握拳手型错误显现 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/pilot-motion-review-20261007-151306-GgKn6b/review.json>) | 不是手部修正成功 |
| P06 | 2026-10-08–10-09 | 关键帧手部试修失败链：config导入失败两次、GLU缺失、candidate gate拒绝，失败目录完整保留 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-pof7lsms/verified/results/report.json>) | 未覆盖原两段 |
| P07 | 2026-10-09 | GLU/EGL实渲染修复与只读重新出图：仅准备GLU受控包；EGL非空可见且几何投影检查；只读review不再优化 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-k99wh10f/verified/results/report.json>) | 原候选拒绝状态不变 |
| P08 | 2026-10-09 | 受限肘部试修：15°总测地角、200次nfev；三手数值门槛通过但手型不可靠 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs/download-dl13uskz/verified/results/report.json>) | candidate pending review |
| P09 | 2026-10-09 | 原始两段tokenizer初次与复验：T01/T02分别500步；从零小网络，独立checkpoint重载 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-verified-20261009-074538-KncThF/verified/results/report.json>) | 研究联调、无文本模型 |
| P10 | 2026-10-09 | MANO包/代理WiLoR资源准备：用户MANO v1.2复制和受限数值检查；source proxy重试；大权重strict load | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/mano/manifest.json>) | 许可/生产资格未提升 |
| P11 | 2026-10-09 | 克隆GPU26919与WiLoR关键帧：固定WiLoR两帧三手；full FP32，不跳层；渲染投影失真修复 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-keyframes-verified-20261009/verified/results/report.json>) | inferred_pending_visual_review |
| P12 | 2026-10-09 | 14帧WiLoR短窗口：你好88–94、咳嗽156–162，共21目标手；无平滑/接触通过 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-windows-20261009/verified/results/report.json>) | 推理不是融合 |
| P13 | 2026-10-09 | MANO→SMPL-X两帧对齐与14帧融合：映射手均值、手别、global链及相机；保存baseline/proposal/candidate | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/mano-smplx-fusion-windows-final-20261009/verified/results/report.json>) | 接触/时序未全面验收 |
| P14 | 2026-10-09 | 4帧接触假设被拒：指尖最近对不是真值；中指对假设受限优化仍被拒 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/contact-final-20261009/verified/results/report.json>) | 0接触批准 |
| P15 | 2026-10-09 | 2D/3D接触对应只读审计：独立point匹配、观测缺失、深度/手型提示，不改变pose | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/contact-observation-audit-20261009-final/report.json>) | audited pending |
| P16 | 2026-10-09 | 14帧时序审计：旋转测地角、mask、手腕/指尖步长；发现92/93跳变 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/temporal-hand-audit-20261009-validated/report.json>) | 原序列不平滑 |
| P17 | 2026-10-09 | 384帧相机坐标提案：virtual focal/depth相关；参考相机根平移提案降低部分跳变 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/camera-reference-pilot-20261009/report.json>) | 未写回fits或训练输入 |
| P18 | 2026-10-09 | 稳定裁剪真实GPU实验：先固定人体框重跑14帧H32；相机、深度、投影分别检查 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/stable-crop-pilot-20261009/verified/results/report.json>) | inferred pending crop review |
| P19 | 2026-10-09 | 稳定裁剪baseline上的21手融合：首次错环境missing mmcv后改回正确环境；native/EGL/保存参数独立复核 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/stable-crop-fusion-20261009/verified/results/report.json>) | 所有数值候选通过，接触仍未通过 |
| P20 | 2026-10-09 | 两段完整384帧闭环：全长stable/WiLoR/fusion；缺失/多检测/拒绝回退；7122文件回传；后续保守选择 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/verified/fusion-source/results/report.json>) | 报告gate失败保留；不是全帧通过 |
| P21 | 2026-10-09 | 全长tokenizer三次训练修正：T03融合→T04时序→T05mask输入占位一致；每次1000步 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/final-verified/training-final/results/report.json>) | T05技术复现参考 |
| P22 | 2026-10-09–10-10 | T06/T07全新来源折评估：两折1000步从头训练；CPU/GPU复算；明显训练/来源差距 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-review-20261010-final/report.json>) | 不证明actual person independent |
| P23 | 2026-10-10 | 11新来源筛查31段复核交付：2235图、1575字幕区间、27整句+4教学4550帧 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/data-expansion-20261010/review-delivery/delivery.json>) | 0新增标签自动批准 |
| P24 | 2026-10-10 | 3段内容确认、450帧重建、动作观感确认：新batch重新prepare；remote3帧序严格import；审核sha绑定 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-review/motion-review-decision.json>) | 镜像/人物/正式训练资格未批准 |
| P25 | 2026-10-10 | T05→新3段冻结迁移诊断：18.9%优于均值但投影/手角差大；用户随后暂停3段 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/report.json>) | 不继续三段试修或训练 |
| P26 | 2026-10-10 | 其余14段重建和T08训练：2732帧14/14import，1000步135窗口；新独立权重，CPU一致 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/training/report.json>) | 研究基线保留 |
| P27 | 2026-10-10 | T08→旧2段冻结同源评估：MSE0.412、50.2%均值改善；raw/角度/pixel分开核验 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-eval-20261010/frozen-diagnostic/report.json>) | 同源不是final test |
| P28 | 2026-10-10 | 14段手部筛查、WiLoR3帧与T09：左176右974；3帧手别冲突；T09新权重与原权重两口径比较 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/audit/report.json>) | 候选未整体晋级 |
| P29 | 2026-10-10 | 重叠手归属歧义v2/T10：新mask右938，v2终端1000步训练完成0.135545；本地checkpoint缺失 | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/audit-v2/report.json>) | 未采用/未完成可比评估 |
| P30 | 2026-10-10 | 本整体报告与纠偏：冻结历史及证据；纠正paired总体方向与v2比较口径；远端refused | [原报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/paired-comparison.json>) | 不启动训练/不改变旧证据 |


### 6.1 源码提交时间线（不等同于任务运行时间）

| 提交 | 北京时间 | 说明 |
| --- | --- | --- |
| 9edcff1 | 2026-09-28T15:55:33+08:00 | feat(data): prepare local sign video dataset pilot |
| 5fd161d | 2026-09-28T17:10:14+08:00 | feat(data): extract local sign captions and audit candidate clips |
| 2a1519b | 2026-09-28T17:53:30+08:00 | feat(data): prepare smplx motion fitting pipeline |
| c61fa51 | 2026-09-29T15:36:42+08:00 | feat(data): stage verified smplerx gpu handoff |
| a7ef48c | 2026-09-30T08:36:59+08:00 | fix(data): accept current model registry LFS digest |
| 6f69ee8 | 2026-09-30T09:06:48+08:00 | feat(data): fetch verified body assets and stage GPU bundle |
| 79019db | 2026-10-07T16:28:15+08:00 | feat(data): add audited keyframe hand refinement pilot |
| 72eb975 | 2026-10-08T12:10:15+08:00 | fix(data): repair smpl-x pilot import path |
| 056fa1a | 2026-10-09T06:47:40+08:00 | fix(data): preflight EGL rendering and prepare GLU runtime |
| c618527 | 2026-10-09T07:09:55+08:00 | feat(data): add read-only hand candidate visual review |
| 759993b | 2026-10-09T07:26:49+08:00 | feat(data): add bounded elbow hand fitting pilot |
| 17df6d6 | 2026-10-09T07:50:25+08:00 | feat(data): verify bounded hand fitting and train research tokenizer smoke |
| 703fcee | 2026-10-09T08:45:43+08:00 | docs(data): record verified local MANO asset preparation |
| 59812d5 | 2026-10-09T09:39:47+08:00 | docs(data): record pinned WiLoR source download |
| 6fa60e0 | 2026-10-09T11:11:36+08:00 | feat(data): verify WiLoR CUDA keyframes and fix mesh rendering transform |
| f35e1f3 | 2026-10-09T12:28:59+08:00 | feat(data): add short-window WiLoR and MANO alignment validation |
| 5a6454c | 2026-10-09T13:44:45+08:00 | feat(data): validate short-window SMPL-X fusion sequences |
| 381bf85 | 2026-10-09T14:24:56+08:00 | feat(data): evaluate bounded two-hand contact hypothesis |
| ba58f9c | 2026-10-09T16:29:10+08:00 | feat(data): audit sign fingertip correspondence |
| aaa89d4 | 2026-10-09T18:10:28+08:00 | feat(data): audit short-window hand temporal consistency |
| 5856ea4 | 2026-10-09T18:41:28+08:00 | feat(data): evaluate fixed-camera coordinate proposals |
| 27e8d2d | 2026-10-09T20:20:27+08:00 | feat(data): validate stable-crop CUDA reconstruction pilot |
| 6142d06 | 2026-10-09T21:15:57+08:00 | feat(data): fuse hands on stable-crop baselines |
| 1e24b74 | 2026-10-09T23:26:59+08:00 | feat(data): complete full-clip masked tokenizer research pipeline |
| 6557cbc | 2026-10-10T00:26:10+08:00 | feat(data): validate source-heldout tokenizer reconstruction |
| 57e35c5 | 2026-10-10T02:05:30+08:00 | feat(data): prepare unverified new-source sign candidates |
| 4317de3 | 2026-10-10T04:30:09+08:00 | docs(data): record approved three-clip motion review |
| fc71a83 | 2026-10-10T05:37:25+08:00 | docs(model): record frozen tokenizer transfer check |
| eab238b | 2026-10-10T07:30:34+08:00 | feat(ml): train explicit reviewed motion scope |
| 29a5e72 | 2026-10-10T08:18:07+08:00 | feat(eval): add frozen motion checkpoint diagnostics |
| 26d8d76 | 2026-10-10T09:17:58+08:00 | feat(ml): screen ambiguous hand supervision |


历史最终主线：26d8d76。工作区起点干净；本报告是新增文档和证据索引，不改训练参数。训练与重建的任务时间仍以各自run/report/log为准。

## 7. 所有真实训练轮次与权重注册表

### 7.1 汇总

| 编号 | 轮次 | 训练范围/帧 | 优化步/最佳checkpoint | 初始→最好训练窗口MSE | SHA核验 | 采用说明 |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | 两段原始动作初次500步 | 2段 / 384帧 | 500/500 | 0.743904859 → 0.020848549 | 本地匹配 | 历史技术复现 |
| T02 | 两段原始动作重载验证500步 | 2段 / 384帧 | 500/500 | 0.743904859 → 0.014725960 | 本地匹配 | 历史技术复现 |
| T03 | 两段全长融合1000步 | 2段 / 384帧 | 1000/1000 | 0.992911816 → 0.005089032 | 本地匹配 | 历史技术复现 |
| T04 | 两段保守时序版本1000步 | 2段 / 384帧 | 1000/1000 | 0.992557228 → 0.005060637 | 本地匹配 | 历史技术复现 |
| T05 | 两段mask输入一致性修正版1000步 | 2段 / 384帧 | 1000/900 | 0.992552996 → 0.005697748 | 本地匹配 | 历史技术复现 |
| T06 | 医院训练→问候留来源评估 | 1段 / 218帧 | 1000/900 | 0.936800539 → 0.001774815 | 本地匹配 | 历史技术复现 |
| T07 | 问候训练→医院留来源评估 | 1段 / 166帧 | 1000/850 | 0.960316479 → 0.000708216 | 本地匹配 | 历史技术复现 |
| T08 | 其余14段原始动作1000步 | 14段 / 2732帧 | 1000/1000 | 0.744150758 → 0.084840871 | 本地匹配 | 保留的14段研究基线 |
| T09 | 14段自动筛查mask v1 1000步 | 14段 / 2732帧 | 1000/1000 | 0.856639385 → 0.113415748 | 本地匹配 | 实验候选，不整体替换 |
| T10 | 14段歧义手别屏蔽mask v2 1000步 | 14段 / 2732帧 | 1000/未取得 | 未保存 → 0.135544673 | 未知 | 历史终端记录；待下载校验 |


上述本地9份权重合计记录8000个优化步（两轮500、七轮1000），另有T10历史终端1000步；不是9000帧、不是9000独立样本，也不是同一权重连续9000步。所有报告的参数、seed、history、输入sha和完整逐段指标在证据快照中保存。

### 7.2 每轮逐项信息

#### T01 · 两段原始动作初次500步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-20261009-074134-Q9JVxL/verified/results/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-20261009-074134-Q9JVxL/verified/results/report.json>)。
- SHA-256：`81a654d1a34735706e8df5731ec6c9e8c3f9dce540601d263f7fba91e56d7a68`；本次重算一致。
- frames=384；steps=500；best checkpoint step=500；window count=19；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.743904859 / 0.020848549 / 未保存。
- 优化elapsed秒：25.999594357（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-hello-001`, `pilot-hospital-cough-003`。
- quality_masked_hand_targets=None；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T02 · 两段原始动作重载验证500步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-verified-20261009-074538-KncThF/verified/results/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-verified-20261009-074538-KncThF/verified/results/report.json>)。
- SHA-256：`d7abb620bbc66733b367c3b8a0bd6ba087cbef7cedd4d861f04df5fab63077a0`；本次重算一致。
- frames=384；steps=500；best checkpoint step=500；window count=19；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.743904859 / 0.014725960 / 0.014725960。
- 优化elapsed秒：24.843437675（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-hello-001`, `pilot-hospital-cough-003`。
- quality_masked_hand_targets=None；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T03 · 两段全长融合1000步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/verified/training/results/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/verified/training/results/report.json>)。
- SHA-256：`23d3d5e90f8dc63d31be55ece0ffc1f3b16c3bfb4c7969faaacd368e2bb73f3b`；本次重算一致。
- frames=384；steps=1000；best checkpoint step=1000；window count=19；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.992911816 / 0.005089032 / 0.005089032。
- 优化elapsed秒：52.577546909（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-hello-001`, `pilot-hospital-cough-003`。
- quality_masked_hand_targets=True；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T04 · 两段保守时序版本1000步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/curated-verified/training-curated/results/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/curated-verified/training-curated/results/report.json>)。
- SHA-256：`b3bcbaa0fe6833f9b78ad1baf0f6f91ea759cc685d61260717ab1809cbcfbda8`；本次重算一致。
- frames=384；steps=1000；best checkpoint step=1000；window count=19；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.992557228 / 0.005060637 / 0.005060637。
- 优化elapsed秒：56.020537645（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-hello-001`, `pilot-hospital-cough-003`。
- quality_masked_hand_targets=True；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T05 · 两段mask输入一致性修正版1000步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/final-verified/training-final/results/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009/final-verified/training-final/results/report.json>)。
- SHA-256：`1bf74e841b9c6f96dc86372d187ac348e68eb7827edda9500d77644a5d584bfb`；本次重算一致。
- frames=384；steps=1000；best checkpoint step=900；window count=19；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.992552996 / 0.005697748 / 0.005697748。
- 优化elapsed秒：56.076026134（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-hello-001`, `pilot-hospital-cough-003`。
- quality_masked_hand_targets=True；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T06 · 医院训练→问候留来源评估

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-eval-20261009/verified/results/fold-01/tokenizer-heldout.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-eval-20261009/verified/results/report.json>)。
- SHA-256：`6cc96df21009d856bc362d8ebbfd720c6ae74c4f89ba1aef5219ea8fd235a442`；本次重算一致。
- frames=218；steps=1000；best checkpoint step=900；window count=11；seed=20261010。
- 初始/最好/重载训练窗口MSE：0.936800539 / 0.001774815 / 0.001774815。
- 优化elapsed秒：54.929463491（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-hospital-cough-003`。
- 留来源评估片段：`pilot-greeting-hello-001`。
- quality_masked_hand_targets=True；checkpoint reload passed=True。
- 资格：历史留来源诊断复算；实际人物/教材独立性未确认；training_ready=false、deployment_ready=false。

#### T07 · 问候训练→医院留来源评估

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-eval-20261009/verified/results/fold-02/tokenizer-heldout.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-eval-20261009/verified/results/report.json>)。
- SHA-256：`842856b2abb4e739dece661b38af659752e0a8637da971322d68b69e016bacdb`；本次重算一致。
- frames=166；steps=1000；best checkpoint step=850；window count=8；seed=20261011。
- 初始/最好/重载训练窗口MSE：0.960316479 / 0.000708216 / 0.000708216。
- 优化elapsed秒：55.302446552（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-hello-001`。
- 留来源评估片段：`pilot-hospital-cough-003`。
- quality_masked_hand_targets=True；checkpoint reload passed=True。
- 资格：历史留来源诊断复算；实际人物/教材独立性未确认；training_ready=false、deployment_ready=false。

#### T08 · 其余14段原始动作1000步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/training/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/training/report.json>)。
- SHA-256：`438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b`；本次重算一致。
- frames=2732；steps=1000；best checkpoint step=1000；window count=135；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.744150758 / 0.084840871 / 0.084840871。
- 优化elapsed秒：55.634259947（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-answer-002`, `pilot-greeting-how-004`, `pilot-greeting-busy-005`, `pilot-greeting-lunch-006`, `pilot-greeting-well-007`, `pilot-greeting-overtime-008`, `pilot-hospital-cold-009`, `pilot-hospital-rest-010`, `pilot-hospital-allergy-011`, `pilot-hospital-dose-012`, `pilot-hospital-pay-013`, `pilot-hospital-temperature-014`, `pilot-hospital-serious-015`, `pilot-hospital-iv-016`。
- quality_masked_hand_targets=False；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T09 · 14段自动筛查mask v1 1000步

- [权重文件](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/verified/masked-training/tokenizer-smoke.pt>)；[完整训练报告](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/verified/masked-training/report.json>)。
- SHA-256：`2587f85ffae34a44ad4f15986aa84e697ce133b0ee91fe0b685fc7e93bd059f4`；本次重算一致。
- frames=2732；steps=1000；best checkpoint step=1000；window count=135；seed=20261009。
- 初始/最好/重载训练窗口MSE：0.856639385 / 0.113415748 / 0.113415748。
- 优化elapsed秒：56.132506534（不包含下载、重建、出图，也不是市场计费时间）。
- 训练片段：`pilot-greeting-answer-002`, `pilot-greeting-how-004`, `pilot-greeting-busy-005`, `pilot-greeting-lunch-006`, `pilot-greeting-well-007`, `pilot-greeting-overtime-008`, `pilot-hospital-cold-009`, `pilot-hospital-rest-010`, `pilot-hospital-allergy-011`, `pilot-hospital-dose-012`, `pilot-hospital-pay-013`, `pilot-hospital-temperature-014`, `pilot-hospital-serious-015`, `pilot-hospital-iv-016`。
- quality_masked_hand_targets=True；checkpoint reload passed=True。
- 资格：研究复现、编码/重建诊断；非生产手语生成；training_ready=false、deployment_ready=false。

#### T10 · 14段歧义手别屏蔽mask v2 1000步

- 依据：前轮终端输出完成1000步，状态research_smoke_trained_not_deployable。
- 本地完整report、checkpoint、SHA和CPU复核尚未取得。
- 远端报告：`/root/autodl-tmp/signbridge/hand-quality-stage-20261010-v2/training/report.json`。
- 远端权重：`/root/autodl-tmp/signbridge/hand-quality-stage-20261010-v2/training/tokenizer-smoke.pt`。
- 最好训练MSE：0.135544673；不直接与T09比较。
- 当前连接拒绝，未确认即时PID/GPU状态。


### 7.3 公共网络与训练配置

小型SOKE VQVae约2,667,205参数，三个分支分别body/face43、左手45、右手45。常见记录配置：code_dim64、output_emb_width64、width128、down_t2、stride_t2、depth2、dilation_growth_rate2、activation relu、norm None、EMA reset quantizer；code_num16/32/32。

AdamW学习率0.001、weight_decay0、梯度裁剪1.0。训练64帧窗口，每16帧滑窗并补全最后窗口；batch通常最多8窗口，固定种子20261009；来源折分别20261010/20261011。目标重建使用Smooth L1与commitment项（0.02倍）；checkpoint根据训练窗口masked MSE选择，不根据评估误差选择。

推理为完整片段，向4的倍数做边缘pad，输出裁回原帧数。该pad属于网络批形状处理，不补造缺失姿态；对应token长度约ceil(T/4)。归一化从本轮训练数据和对应mask计算，std下限0.05，无有效数据的维度有明确保护。官方预训练tokenizer不能直接套用这些自定义mean/std。

## 8. 重建与手部试修的详细过程

### 8.1 旧两段原始重建

- 先dry-run预检；ready=true才实际推理。
- 166帧和218帧网络推理完成，日志显示H32 checkpoint和Faster R-CNN加载。
- 导入检查所有`00001_0.npz`至最后连续存在、只目标人物`_0`、参数完整、全有限值，原source tasks和fit run摘要相符。
- 生成`features-133.npy`、`fitted-smplx.npz`、`fit-sources.jsonl`、quality以及从已校验数组生成的SOKE兼容pickle；不unpickle外部来源文件。
- 初始手最大相邻旋转：“你好”52.71°/70.91°、“咳嗽”39.73°/43.07°；没有>90°也不能证明手型正确。

### 8.2 关键帧手指/手腕与受限肘部优化

旧试点固定你好91帧双手、咳嗽159帧右手。先用SMPL-X稀疏LBS与原生CUDA关节/指尖对照，阈值5e-5m；原生hand mean约定不一致就停止。仅允许目标手指/腕或附加同侧肘（总测地角≤15°）变化；root、shape、expression、其他手和非目标关节保持。

目标是MediaPipe估计的2D点，不使用其z作为metric监督。候选需局部RMSE下降至少20%、绝对误差不变差、指尖局部误差不变差，再受手指/腕/肘角度约束。合并两手后重算，不通过时回退，不按分别通过强行接受合并。

你好91帧数值改善，咳嗽159帧曾局部改善但绝对误差`16.05 → 19.24px`，因此拒绝；只读重新渲染没有改变这一门槛。带肘约束最后三手数值候选通过，但双指卷曲/接触与竖拇指手型仍不能确认，未写成整段已修正。

### 8.3 WiLoR下载、严格checkpoint加载与渲染修复

用户MANO包复制保持原文件，进行受限结构读取/数组数值核验。WiLoR源码与大checkpoint固定提交和摘要；strict state_dict无missing/unexpected keys，全模型FP32、batch1，无跳层或fast近似。

最初mesh投影失真追踪到相机空间到OpenGL坐标转换和NumPy/OpenBLAS矩阵路径；翻转yz坐标、法向诊断颜色、分析投影边界校验、受控环境变量后重跑，两手/三手原生渲染符合投影框。**“可见像素”不够，mesh显示还必须匹配解析投影。** 原右手参数的正确加载不证明手语语义。

### 8.4 14帧窗口映射与融合

范围：你好88–94、咳嗽156–162；14帧21次目标手。WiLoR预测MANO姿态明确按均值/手别约定映射SMPL-X，固定根/形状，受限调整肘腕，保留原生候选与proposal。原始基线到融合平均像素误差降低，但双手接触和窗口内旋转突变仍有问题。

### 8.5 接触假设与只读对应审计

你好88–91帧尝试固定所选最近指尖对的受限接触优化；最近对不等于人工接触点。本轮实际选择中指[12,12]，候选未通过，保存原baseline和raw proposal，没有强行收缩两手。

进一步2D/3D指尖矩阵审计发现MediaPipe、WiLoR、SMPL-X近点对应分歧，遮挡下深度未知。之后只读几何/时序报告并未修正接触，接触资格保持false。

### 8.6 相机和稳定裁剪

原SMPLer-X裁剪框改变导致虚拟焦距和transl.z高度相关，不能把模型虚拟深度跳变看成人真实前后运动。固定参考相机实验仅变换根平移提案，原参数不写回。

稳定裁剪短窗口真实重跑H32，改用各片段固定人体框，视觉/投影/深度另审核；稳定crop下再WiLoR融合21次目标手，通过数值门槛。主要改善是相机一致性，而不是保证语义正确或物理相机已标定。

### 8.7 全长384帧处理和mask

| 手/片段 | 缺检测 | 多检测 | 拒绝 | 已应用 | 时序后保留 |
| --- | --- | --- | --- | --- | --- |
| 你好左 | 69 | 0 | 42 | 55 | 54 |
| 你好右 | 41 | 0 | 34 | 91 | 91 |
| 咳嗽左 | 191 | 0 | 5 | 22 | 22 |
| 咳嗽右 | 29 | 4 | 15 | 170 | 164 |


出现多检测、缺失、映射拒绝、合并门槛失败时保留baseline。保守两状态时序选择仅在已有candidate/baseline中挑选，回退7次应用，避免额外>90°旋转跳变；不生成平滑姿态。没有在后来14段或三段中默默套用这套全长修正。

### 8.8 新14段重建和训练

用户切换后选择原16段中6段问候、8段医院，排除旧两段和暂停新三段。2732帧独立新目录真实推理，14/14严格导入、拒绝0。输入为原始SMPL-X估计，**不是**旧两段全长WiLoR融合版本。

之后T08新权重训练1000步；135窗口MSE下降88.6%；Mac CPU完整14段三路token一致，最大数组差1.19e-6，独立CPU训练窗口MSE0.084840864与GPU保存值一致。训练内重建视频使用源相机/root/下身，不是从文本生成。

## 9. 全部评估：适用范围和关键指标

### 9.1 T06/T07全新留来源折

医院218帧训练→问候166帧评估，反向再跑；每折从头初始化，训练均值/方差只来自该折训练，codebook和checkpoint选择不使用评估。

| 训练→评估 | 完整训练片段masked MSE | 评估masked MSE | 均值基线 | 改善 |
| --- | --- | --- | --- | --- |
| 医院→问候 | 0.003744 | 3.208630 | 3.625481 | 11.50% |
| 问候→医院 | 0.001023 | 5.955561 | 6.497213 | 8.34% |

此表完整序列训练误差不同于训练窗口checkpoint选择指标，不能混用。医院→问候左手单独比均值基线还差约0.98%；不能只报整体改善。实际真人/同教材独立性尚不明确，这是历史来源记录分组诊断，不是最终独立语言评测。

### 9.2 T05→暂停三段冻结迁移

采用两段旧训练权重，测试未训练过的450帧三段；MSE1.28843/均值1.58914，约18.9%参数误差改善。手部投影53–105px和手关节19–25°平均差都较大，未采用其输出替代新数据或插件动作。

### 9.3 T08→旧两段冻结诊断

原SMPL-X两段重新严格导入，避免混用此前WiLoR融合参考。T08从14段训练，两段未参与本次更新，但同源且已用于过其他研究。

| 片段 | 帧 | normalized MSE | 均值基线 | raw RMSE | 左手/右手角度均值° | 左手/右手投影均差px |
| --- | --- | --- | --- | --- | --- | --- |
| pilot-greeting-hello-001 | 166 | 0.541005275 | 1.051688191 | 0.137764087 | 6.278/5.659 | 111.98/108.95 |
| pilot-hospital-cough-003 | 218 | 0.313694448 | 0.656589240 | 0.111924747 | 4.036/5.201 | 57.24/95.17 |


总体raw RMSE0.123759、normalized MSE0.411959，均值0.827387，相对50.21%改善。投影仍约57–112px；手关节平均4.04–6.28°不等于手位置正确。原参考错误手型也不会因重建相似而变正确。

### 9.4 T09与T08：两种比较必须分开

| 部分 | 全参考T08 | 全参考T09 | 共同mask T08 | 共同mask T09 | 共同mask候选误差变化 |
| --- | --- | --- | --- | --- | --- |
| all | 0.123758661 | 0.165732990 | 0.163928401 | 0.157257342 | -4.07% |
| body_face | 0.185209308 | 0.176194017 | 0.185209308 | 0.176194017 | -4.87% |
| left_hand | 0.077657600 | 0.202024328 | 0.116947885 | 0.132676589 | +13.45% |
| right_hand | 0.080369539 | 0.103455711 | 0.100357225 | 0.093753167 | -6.58% |


- **全原始参考，评估各自普通输入**：T09总体0.165733高于T08的0.123759，左手退化明显；参考包括自动筛查中不可信手，不能只用此比较作最终生产裁定。
- **相同参考、相同共同输入mask、相同有效评分目标**：T09总体0.157257小于T08的0.163928（改善约4.07%），body/face和右手有改善；左手0.132677大于0.116948（退化约13.45%）。
- 两次normalized MSE和训练MSE使用不同训练统计/目标范围，不能直接比。raw RMSE仍是混合参数单位，不是独立手型真值。
- 共同mask仅你好左37/右50帧、咳嗽左13/右73帧；少量偏置观察不可当最终人群泛化。
- 因左手退化、监督不足和手别歧义，T09未整体提升为替换T08。不是“掩码方案在所有维度都失败”，也不是“总体改善就通过”。

### 9.5 T10不能依据当前资料下比较性定论

历史输出说明v2训练结束，训练MSE0.135545。v1是0.113416，但mask有效目标和归一化都已改变；**这些训练MSE不可直接证明v2比v1更差**。T10未取得本地checkpoint SHA、未做同目标评估、未做本地重载/CPU验证。现状是“未采用、未充分验证”，不能写成已严格比较确认全面退化。

## 10. 手部质量自主试验全过程

### 10.1 自动技术门槛（没有放宽）

- 手部被检测且所有点有限、x/y处于[0,1]。
- 中位腕→MCP掌尺度至少15px。
- 平均对应点误差≤0.75个掌尺度。
- 手腕差≤35px。
- 只有前/当前/后3帧都技术通过时，当前帧手部进入loss mask。
- v2额外检测左右手平均对应点距离≤0.25掌尺度、腕距≤0.35掌尺度的重叠歧义，双侧排除而不换侧。

这些是未经过人工准确率标定的研究heuristic，不能称“可靠手语真值”。大部分参数原样保留；身体/面部43维仍是模型估计，质量mask不能假装它们已被人审。

### 10.2 全14段逐手监督结果

| 片段 | 总帧 | 左观测/右观测 | v1左/右loss帧 | v2左/右loss帧 | v2重叠歧义帧 |
| --- | --- | --- | --- | --- | --- |
| pilot-greeting-answer-002 | 174 | 23/94 | 11/27 | 11/27 | 0 |
| pilot-greeting-how-004 | 153 | 32/68 | 13/21 | 13/21 | 0 |
| pilot-greeting-busy-005 | 148 | 28/70 | 0/23 | 0/19 | 2 |
| pilot-greeting-lunch-006 | 153 | 89/127 | 49/93 | 49/73 | 15 |
| pilot-greeting-well-007 | 122 | 0/45 | 0/16 | 0/16 | 0 |
| pilot-greeting-overtime-008 | 177 | 23/100 | 0/44 | 0/43 | 4 |
| pilot-hospital-cold-009 | 282 | 27/210 | 20/106 | 20/103 | 1 |
| pilot-hospital-rest-010 | 159 | 47/150 | 25/68 | 25/68 | 0 |
| pilot-hospital-allergy-011 | 180 | 15/128 | 13/69 | 13/69 | 0 |
| pilot-hospital-dose-012 | 318 | 31/252 | 1/142 | 1/142 | 0 |
| pilot-hospital-pay-013 | 163 | 45/132 | 31/67 | 31/67 | 0 |
| pilot-hospital-temperature-014 | 329 | 26/245 | 5/138 | 5/135 | 2 |
| pilot-hospital-serious-015 | 155 | 52/113 | 0/68 | 0/68 | 0 |
| pilot-hospital-iv-016 | 219 | 62/170 | 8/92 | 8/87 | 3 |


一段左手全程没有观测；v1总左176/右974，v2左176/右938帧。有效帧减少来自排除规则，不是完整修正成果。

### 10.3 三个WiLoR问题帧

| 片段/帧 | 请求手 | 实际检测记录 | 处理 |
| --- | --- | --- | --- |
| 加班113 | right | right与left各一 | 网络/渲染可用；分歧证据保留 |
| 吃饭57 | left | right一手 | requested left不满足，拒绝自动融合 |
| 严重吗31 | left | right一手 | requested left不满足，拒绝自动融合 |

几帧MediaPipe左右手同时靠近同一只可见手，WiLoR与其归属不同。单凭最近投影误差不能推断解剖学左右或确认视频镜像，不能自动交换左右手绕过门槛。

四份单手WiLoR结果均有finite/rotation检查和解析投影边界校验；整批状态`missing_required_hand`，0个MANO候选合并到14段SMPL-X。这里“推理完成”与“修正成功”分开。

### 10.4 两轮mask研究训练的采用决策

T09训练及14段CPU/GPU一致性通过；T10终端训练完成但本地证据缺失。停止重复调整容差，不替换T08，不宣称修正完成；保留两轮实验、side diagnostic和原权重。

## 11. 故障、根因、修复及尚未解决问题

| 问题 | 实际表现 | 定位 | 修复/处理 | 证据依据 |
| --- | --- | --- | --- | --- |
| 本机cd到/root | Mac终端cd失败 | 本机与远端路径混用 | ssh交互/远端命令后进入/root路径；Mac绝对路径保留 | 对话终端陈述 |
| pip阿里源超时 | ReadTimeoutError | 连接慢/不完整读取 | 增加下载容忍、换清华源；pip check和实际import再验证 | 对话；依赖记录 |
| EGL找不到 | Unable to load EGL library | 系统libEGL缺失 | 安装libegl1/libegl-mesa0等；ctypes与实际EGL渲染验证 | 对话终端 |
| MMPose import config | No module named config | vendored模块顶层导入依赖工作路径 | 显式固定main与common源码路径，核对实际来源 | 多个失败report |
| MMPose覆盖后端 | EGL→OSMesa等 | 源码硬设平台覆盖外部PYOPENGL_PLATFORM | 尊重已有设置；验证EGLPlatform和离屏渲染 | 维护文档+用户日志 |
| torchgeometry bool减法 | 新torch bool运算错误 | 旧旋转转换掩码表达式 | 备份并修4处掩码；CPU/CUDA7组转换和SMPLer-X 6D实际路径通过 | 对话终端 |
| GLU渲染缺失 | Library GLU not found | 系统OpenGL utility库缺失 | 受控新增libglu1-mesa/libopengl0；dry-run拒绝升级/删除 | download-ln9bx0j6报告 |
| 手部candidate绝对位置变差 | candidate_gate_failed | 相对手腕形状改善但global像素位置退化 | 保留proposal，candidate回退baseline；不删除门槛 | download-trkzf8dr |
| 肘部迭代/总角度 | candidate_gate_failed | nfev或整体受限旋转不满足 | 保留失败，后来15°总测地角/200nfev新目录 | download-uq0azu_4 / dl13uskz |
| WiLoR mesh显示拉伸 | 解析边界不一致 | OpenGL符号/BLAS矩阵约定 | yz转换与Haswell路径，严格投影边界、重新渲染 | wilor-keyframes及后续报告 |
| 稳定fusion启动mmcv缺失 | No module named mmcv | 错误venv执行native SMPL-X | 改为原SMPLer-X环境，当前进程verified source路径 | failed-start-evidence |
| 三条标注配27条 | Approval must match exact current prepared batch | 严格审核要求集合一致 | 创建3段隔离prepare再review/export | 对话及新review记录 |
| Python3.8 driver | Path.is_relative_to缺失 | 驱动工具使用错解释器 | driver3.11调用上游SMPLer-X3.8 | 对话预检 |
| float64 eye/float32 model | double != float | 原生眼参数dtype与torch不同 | 前向张量转换float32；原NPZ保留 | 对话诊断+保存source |
| 视频960 vs1280 | 断言失败 | 旧数据1280×720、新3段960×540 | 真实图片shape缩放；失败出图隔离目录 | 对话render-review-v2 |
| sha清单父目录 | No such file or directory | relative SHA根错误 | 在清单所在目录核验；不认作传输损坏 | 多处对话/日志 |
| npm根目录 | ENOENT package.json | 插件在signbridge子目录 | 切换正确workdir完整verify | 对话验证 |
| WiLoR手别分歧 | missing_required_hand | MediaPipe左右点可能归属同一可见手 | 不换侧，保留检测与投影证据，0融合 | 当前3帧report |
| 自动mask模型左手退化 | left hand RMSE增加 | 有效左手监督176帧、估计偏差 | 分口径评估，不替换T08 | comparison/paired-comparison |
| 当前服务器不可连 | Connection refused | 服务器端口未接受连接，原因未确认 | 只读一次检查后标证据缺口；不编造T10SHA | 本报告整理 |


### 11.1 需要长期记住的工程教训

- 下载失败/网络超时：只重试下载、校验.part，不能下载不完整却继续加载。
- 上游EGL/OSMesa覆盖：`PYOPENGL_PLATFORM`要在import前生效，修为尊重外部设置；库加载通过不等于实际渲染通过。
- Python驱动与上游环境分离：`Path.is_relative_to`不适合3.8驱动工具，使用driver3.11调上游3.8。
- 布尔掩码：torchgeometry旧减法和新torch bool语义不兼容；按CPU/CUDA旋转转换测试核验，不需重装全部PyTorch。
- 缺`config`/`mmcv`：先看实际import来源和工作目录；相同叫SMPL-X的包可能是上游vendored或独立环境库。
- 渲染空间：OpenGL坐标必须解析检查投影，防止漂亮网格图掩盖几何错误。
- 输入分辨率：旧16段1280×720，新三段960×540，投影缩放按实际尺寸，不能固定2/3。
- 数组dtype：原眼睛参数float64而model float32，只在模型前向张量统一dtype；原保存参数不覆写。
- 内部SHA256SUMS通常相对其所在根目录执行；在父目录报“找不到文件”不是数据损坏。
- 命令失败不要用管道tail吞掉exit code；报告校验以重算断言为准。

### 11.2 参数/手语质量问题不能当作“工具错误”消掉

contact、手别、缺手、参考手型错误、来源/人物独立性都是数据质量问题。用户授权自主排查，也不意味着自动虚构人工确认。数值优化可生成候选，失败仍记录拒绝；不能删失败段、把baseline显示当作优化完成或放宽关键门槛强行通过。

## 12. 证据位置、每阶段主入口和恢复优先级

| 用途 | 绝对目录 | 关键内容 |
| --- | --- | --- |
| 原16内容确认 | [原16内容确认](</Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-reviewed-v4>) | review-decision.json / reviewed.jsonl |
| 标准16段GPU输入 | [标准16段GPU输入](</Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-smplx-input-v1>) | tasks.jsonl / SHA256SUMS |
| 旧两段raw fits | [旧两段raw fits](</Users/mac/Documents/ChatGPT/signbridge/local-data/camera-source-20261009>) | run.json / smplx / meta |
| 手部早期失败链 | [手部早期失败链](</Users/mac/Documents/ChatGPT/signbridge/local-data/hand-keyframe-runs>) | 所有download-*版本 |
| 初次原动作500步 | [初次原动作500步](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-20261009-074134-Q9JVxL>) | verified/results |
| 500步重载验证 | [500步重载验证](</Users/mac/Documents/ChatGPT/signbridge/local-data/tokenizer-smoke-verified-20261009-074538-KncThF>) | verified/results |
| WiLoR最终关键帧 | [WiLoR最终关键帧](</Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-keyframes-verified-20261009>) | verified/results |
| 短窗口WiLoR | [短窗口WiLoR](</Users/mac/Documents/ChatGPT/signbridge/local-data/wilor-windows-20261009>) | verified/results |
| 最终14帧融合 | [最终14帧融合](</Users/mac/Documents/ChatGPT/signbridge/local-data/mano-smplx-fusion-windows-final-20261009>) | verified/results |
| 接触拒绝 | [接触拒绝](</Users/mac/Documents/ChatGPT/signbridge/local-data/contact-final-20261009>) | verified/results |
| 指尖对应 | [指尖对应](</Users/mac/Documents/ChatGPT/signbridge/local-data/contact-observation-audit-20261009-final>) | report.json |
| 时间审计 | [时间审计](</Users/mac/Documents/ChatGPT/signbridge/local-data/temporal-hand-audit-20261009-validated>) | report.json |
| 相机提案 | [相机提案](</Users/mac/Documents/ChatGPT/signbridge/local-data/camera-reference-pilot-20261009>) | report.json / camera-proposals.npz |
| 稳定裁剪GPU | [稳定裁剪GPU](</Users/mac/Documents/ChatGPT/signbridge/local-data/stable-crop-pilot-20261009>) | verified/results |
| 稳定裁剪fusion | [稳定裁剪fusion](</Users/mac/Documents/ChatGPT/signbridge/local-data/stable-crop-fusion-20261009>) | verified/results |
| 全长最终旧两段链路 | [全长最终旧两段链路](</Users/mac/Documents/ChatGPT/signbridge/local-data/full-sequence-20261009>) | final-verified / delivery-motions / review.html |
| 来源两折训练 | [来源两折训练](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-eval-20261009>) | verified/results/fold-01/fold-02 |
| 留来源最终复算 | [留来源最终复算](</Users/mac/Documents/ChatGPT/signbridge/local-data/heldout-review-20261010-final>) | report.json / review.html |
| 11新来源候选 | [11新来源候选](</Users/mac/Documents/ChatGPT/signbridge/local-data/data-expansion-20261010/review-delivery>) | 31片段review.html |
| 暂停新3段 | [暂停新3段](</Users/mac/Documents/ChatGPT/signbridge/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1>) | server-return/verified / transfer-check-v1 |
| 14段研究基线T08 | [14段研究基线T08](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010>) | verified/training / cpu-inference / review.html |
| 14权重同源2段诊断 | [14权重同源2段诊断](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-eval-20261010>) | frozen-diagnostic / review.html |
| 手部mask实验T09 | [手部mask实验T09](</Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010>) | audit / audit-v2 / verified / paired-comparison / review.html |


全部相关目录及文件类型/总大小见`directory-inventory.json`；每文件路径、mtime和是否重算过摘要见`file-inventory.jsonl`。文件存在不等于最终选择，目录名`final`/`verified`也不能覆盖报告里面的`failed`/`needs_review`。

### 12.1 完整原始报告快照

本次将所有发现的文本型证据另存到`evidence/`，包括177份控制报告及其每帧meta、各轮日志、quality、来源、依赖freeze。源文档保留在`snapshot_path`，每份同时记录原字节SHA与快照SHA；UTF-8 BOM规范化可能导致两摘要不同。若发现凭据会删敏感值并标记，当前快照没有检出需要删除的凭据值。

报告正文只概括重要指标；完整history、每个手的before/after、每个帧的拒绝理由和traceback没有在概括过程中丢弃，可点击HTML证据目录打开完整快照。

### 12.2 只在服务器的缺口

T10远端目录、报告、checkpoint路径和历史训练值已登记。恢复服务器后优先下载该目录的report、checkpoint、training.log、14段输出和freeze，生成归档摘要，先校验再CPU重载。未补齐前不提供假SHA、不把`v2`写成已经验证本地模型。

更早的第一次CUDA安装/错误粘贴输出不是所有都有完整本地文件。对应条目注明依据是用户终端陈述或维护文档；不要把文档回顾说成完整raw log。

## 13. 后期直接调用：可复制的准确入口

**以下命令是调用/复现模板；整理报告时没有执行这些训练命令。先做来源和模型摘要核对，输出必须是新目录。**

### 13.1 T08本地CPU编码/重建一段已有动作

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-wilor/bin/python /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-infer.py --checkpoint /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/training/tokenizer-smoke.pt --checkpoint-sha256 438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b --features /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/motions/samples/pilot-greeting-answer-002/features-133.npy --soke-root /Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SOKE --device cpu --output /Users/mac/Documents/ChatGPT/signbridge/local-data/new-run-from-master-report/T08-inference
```

此命令需要动作输入，不接受中文释义当作动作，不能用它宣称文本生成。默认输出保留研究限制。要对T09研究masked输入做推理，必须同时传它的`feature-valid-mask.npy`。

### 13.2 T09有mask的CPU推理

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-wilor/bin/python /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-infer.py --checkpoint /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/verified/masked-training/tokenizer-smoke.pt --checkpoint-sha256 2587f85ffae34a44ad4f15986aa84e697ce133b0ee91fe0b685fc7e93bd059f4 --features /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/audit/masked-motions/samples/pilot-greeting-answer-002/features-133.npy --mask /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-hand-quality-20261010/audit/masked-motions/samples/pilot-greeting-answer-002/feature-valid-mask.npy --soke-root /Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SOKE --device cpu --output /Users/mac/Documents/ChatGPT/signbridge/local-data/new-run-from-master-report/T09-inference
```

### 13.3 冻结T08同源未训练片段评估

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-wilor/bin/python /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-evaluate.py --training-results /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/training --training-motions /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010/verified/motions --evaluation-motions /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-eval-20261010/raw-reference-motions --soke-root /Users/mac/Documents/ChatGPT/signbridge/local-data/deps/SOKE --training-report-sha256 b6e321c180d2edeed9255cbd4809a17d36dccae5d78d205fdb8f493ead3b42c1 --output /Users/mac/Documents/ChatGPT/signbridge/local-data/new-run-from-master-report/T08-frozen-evaluation
```

### 13.4 手部筛查重跑

```bash
/Users/mac/Documents/ChatGPT/signbridge/.venv-wilor/bin/python /Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-quality.py --training-delivery /Users/mac/Documents/ChatGPT/signbridge/local-data/remaining14-research-20261010 --batch /Users/mac/Documents/ChatGPT/signbridge/local-data/sign-language-smplx-input-v1 --output /Users/mac/Documents/ChatGPT/signbridge/local-data/new-run-from-master-report/hand-audit
```

### 13.5 GPU训练明确14段范围

```bash
/root/autodl-tmp/signbridge/envs/smplerx/bin/python /root/autodl-tmp/signbridge/hand-quality-stage-20261010-v1/tools/sign-tokenizer-smoke.py --motions /root/autodl-tmp/signbridge/hand-quality-stage-20261010-v1/audit/masked-motions --soke-root /root/autodl-tmp/signbridge/research/SOKE --output /root/autodl-tmp/signbridge/new-run-from-master-report/T09-research --research-only --steps 1000 --segment-id pilot-greeting-answer-002 --segment-id pilot-greeting-how-004 --segment-id pilot-greeting-busy-005 --segment-id pilot-greeting-lunch-006 --segment-id pilot-greeting-well-007 --segment-id pilot-greeting-overtime-008 --segment-id pilot-hospital-cold-009 --segment-id pilot-hospital-rest-010 --segment-id pilot-hospital-allergy-011 --segment-id pilot-hospital-dose-012 --segment-id pilot-hospital-pay-013 --segment-id pilot-hospital-temperature-014 --segment-id pilot-hospital-serious-015 --segment-id pilot-hospital-iv-016
```

路径模板基于最近服务器目录，是恢复后用于复现，不代表当前可连。`--research-only`明确承认模型估计/未验收输入；mask数据snapshot保留`needs_review`和formal training_ready=false。不要把旧两段、暂停新三段加进去。

### 13.6 特定WiLoR关键帧及其他工具

| 当前工具绝对路径 | 用途 | 运行提醒 |
| --- | --- | --- |
| [sign-camera-audit.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-camera-audit.py>) | 全长虚拟相机参考变换实验 | --help/新output；历史脚本按snapshot复现 |
| [sign-contact-audit.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-contact-audit.py>) | 观测/指尖对应只读审计 | --help/新output；历史脚本按snapshot复现 |
| [sign-contact-pilot.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-contact-pilot.py>) | 受限接触假设试验，候选仍需门槛 | --help/新output；历史脚本按snapshot复现 |
| [sign-data.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-data.py>) | scan/prepare/OCR/audit：数据准备 | --help/新output；历史脚本按snapshot复现 |
| [sign-gpu.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-gpu.py>) | 模型/人体资源及整包准备/校验 | --help/新output；历史脚本按snapshot复现 |
| [sign-hand-pilot.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-pilot.py>) | Mac上SSH启动/受控GLU准备/回传 | --help/新output；历史脚本按snapshot复现 |
| [sign-hand-quality.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-quality.py>) | 原动作不变的观测loss mask和歧义筛查 | --help/新output；历史脚本按snapshot复现 |
| [sign-hand-refine.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-hand-refine.py>) | 限定关键帧2D数值拟合/只读重新渲染 | --help/新output；历史脚本按snapshot复现 |
| [sign-heldout-eval.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-heldout-eval.py>) | 来源连通分组、每折全新训练 | --help/新output；历史脚本按snapshot复现 |
| [sign-heldout-review.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-heldout-review.py>) | checkpoint/统计/指标独立复算 | --help/新output；历史脚本按snapshot复现 |
| [sign-mano-align.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-mano-align.py>) | MANO→SMPL-X受限映射/融合 | --help/新output；历史脚本按snapshot复现 |
| [sign-motion.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-motion.py>) | review/export/fit/import-smplerx：审核和实际重建输入 | --help/新output；历史脚本按snapshot复现 |
| [sign-sequence-curate.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-sequence-curate.py>) | 仅在baseline/candidate间保守时序选择 | --help/新output；历史脚本按snapshot复现 |
| [sign-sequence-export.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-sequence-export.py>) | 完整融合序列133维和mask导出 | --help/新output；历史脚本按snapshot复现 |
| [sign-sequence-media.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-sequence-media.py>) | 全长输入/候选/训练内重建媒体 | --help/新output；历史脚本按snapshot复现 |
| [sign-source-candidates.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-source-candidates.py>) | 11新来源候选筛查/字幕/prepare/review | --help/新output；历史脚本按snapshot复现 |
| [sign-stable-crop-review.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-stable-crop-review.py>) | 稳定裁剪独立比较 | --help/新output；历史脚本按snapshot复现 |
| [sign-stable-crop.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-stable-crop.py>) | 固定框真实H32推理 | --help/新output；历史脚本按snapshot复现 |
| [sign-stable-fusion-review.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-stable-fusion-review.py>) | 稳定融合保存参数独立审核 | --help/新output；历史脚本按snapshot复现 |
| [sign-temporal-audit.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-temporal-audit.py>) | 14帧时间/旋转/步长只读审计 | --help/新output；历史脚本按snapshot复现 |
| [sign-tokenizer-evaluate.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-evaluate.py>) | 冻结checkpoint同源片段技术诊断 | --help/新output；历史脚本按snapshot复现 |
| [sign-tokenizer-infer.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-infer.py>) | hash-verified checkpoint CPU/CUDA编码/重建 | --help/新output；历史脚本按snapshot复现 |
| [sign-tokenizer-review.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-review.py>) | 原生SMPL-X训练内重建渲染 | --help/新output；历史脚本按snapshot复现 |
| [sign-tokenizer-smoke.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-tokenizer-smoke.py>) | 严格研究范围小VQ从头训练 | --help/新output；历史脚本按snapshot复现 |
| [sign-wilor-pilot.py](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-wilor-pilot.py>) | 固定WiLoR keyframe/window/full/显式case-plan | --help/新output；历史脚本按snapshot复现 |
| [sign-text-ocr.swift](</Users/mac/Documents/ChatGPT/signbridge/signbridge/src/tools/sign-text-ocr.swift>) | macOS VisionOCR含定位框 | --help/新output；历史脚本按snapshot复现 |


具体命令参数以当前工具`--help`和原执行版本为准；历史GLU修复/下载文件命令仅为记录，不在再次调用权重时重复升级环境。

### 13.7 可机器调用的注册表

- `training-registry.json`：按T01–T10定位权重、报告、steps、checkpoint step、sha和资格。
- `commands.json`：结构化argv、用途、输入、输出和执行环境，不含密码。
- `catalog.json`：每份报告/日志全文快照、源地址、摘要、schema、status。
- `segment-registry.json`：原16段和31新候选全部字段。
- `failure-registry.json`：所有控制报告中failed/blocked/gate_failed/missing状态。
- `commit-history.json`：源码版本线索。
- `RESUME-CONTEXT.md`：接手时先读的状态和禁止误解项。

## 14. 质量门槛、状态字段和指标解释

| 字段/指标 | 它证明什么 | 不证明什么 |
| --- | --- | --- |
| `ready=true` | 资产/模块/CUDA预检通过 | 视频已经跑过、手语正确 |
| `inferred_pending_import_audit` | 网络任务列表完成 | 文件完整或可训练 |
| `converted`/`rejected` | 参数格式及来源审计 | 手型/边界/语义准确 |
| `candidate_gate_passed` | 候选的特定数值门槛 | 独立3D动作或手语验收 |
| `approved_by_user` | 指定对象/指定字段人工陈述 | 自动扩大到镜像、人物或全部数据 |
| `research_smoke_trained_not_deployable` | 真实训练和技术输出完成 | 正式模型可部署 |
| normalized MSE | 按本轮mean/std和mask计算的参考重建差 | 不同mean/std之间可直接比较 |
| raw RMSE | 原参数空间误差，混合单位 | 全为rad、手语准确率或真实厘米 |
| rotation geodesic | 旋转矩阵关系的角度误差 | 手的位置、接触、表达语义 |
| 投影误差px | 指定虚拟相机下2D差 | 真实3D深度和解剖真值 |
| token一致/CPU-GPU差 | 同权重跨运行时接口一致 | 模型的语言/语义正确性 |
| `independent_final_test=false` | 已明确不能作为独立最终测试 | 不能据此忽略所有诊断价值 |

threshold是防止假通过的研究保护，不是经过标定的手语准确率门槛。为了“少报错”改变threshold后必须新版本、理由、独立例子和比较；本轮没有为放行手别/手型放宽。

## 15. 对前面报告与口头总结的事实校正

1. **T09共同mask比较的总体方向**：此前最终文档写“共同mask下总体和左手均变差”不准确。`paired-comparison.json`显示总体0.163928→0.157257，约4.07%改善；左手变差约13.45%。本报告以该结构化结果为准，保留历史文档全文，不悄悄篡改旧证据。
2. **T10与T09训练MSE不可直接证明优劣**：筛选目标、mask和归一化都改变。T10当前没有共同目标评估或本地完整验证，结论只能是“未采用、需补证”，而非已证实全面更差。
3. **T10文件缺失**：历史自主阶段正文声称“两轮全证据保留”过强。T09本地完整；T10只确认历史终端训练结束，其完整日志与权重仍在服务器路径，当前不可达。不要用本地T09目录替代T10。
4. **步骤完成≠修正通过**：WiLoR手推理4次完成，但关键帧计划3帧、其中2帧required side不满足，整体仍为missing_required_hand。没有MANO参数合入14段。
5. **“14段未训练”是历史时点**：较早资料暂停时确实未训练；之后T08/T09/T10已执行。两段全长融合只作用于384帧，不代表14段也融合了。
6. **“独立来源评估”的语义**：T06/T07是按记录来源从头训练的折实验，不表示已经核实实际真人、教材或语言独立性。T08→旧两段更是同源历史诊断。
7. **三段停止使用≠删除**：用户决定暂时放弃，原审核/参数/冻结诊断保留，后续训练明确排除，不等于31个新候选全部被审核或全部不合格。
8. **性能改善≠已获得手语生成器**：没有训练text-to-sign语言模型，也没有可直接给插件用的生成动画模型。

校正条目有独立`corrections.json`，后续接手优先读此清单，不从历史结论中摘一句当现状。

## 16. 测试、核验与本报告生成验证

历史各阶段test count是当时版本的快照，不应为“次数更多”累加。新测试随工具增长；目前关键保护包括：帧连续性、完整dtype/shape、NaN/finite、来源摘要、同组泄漏、人工审核边界、输出不覆盖、同侧受限参数、candidate回退、EGL真实像素/投影、strict模型加载、训练专用mean/std、token与CPU/GPU一致、评估输入前后不变、缺mask拒绝、歧义观测排除。

本次总报告重算9份本地checkpoint SHA及所有证据文本字节摘要，按报告registry校验训练ID和来源地址。原研究目录无写入；补齐的只有报告包与新文档。正文、HTML、JSON、快照、恢复说明和便携zip有本轮manifest。

具体生成统计、链接验证、凭据扫描和完整构建/测试结果见包内`validation.json`。本次无需GPU训练；服务器连接拒绝是证据缺口，不当作测试通过。

## 17. 接手时的决策顺序

1. 先读`RESUME-CONTEXT.md`与`corrections.json`，再查`training-registry.json`；按任务选择T08或技术复现T05，不自动选最低MSE的权重。
2. 需要处理14段时保持用户暂停三段的决定，保留旧权重/输入。不要把candidate审核扩大为未明确批准的mirror/identity/语义。
3. 将左右手检测/观察归属审计放在融合前，不用换侧去抵消错误；contact/遮挡需要更可靠证据。
4. 新权重要在相同输入、mask、参考和指标下比较，报告左右手/身体分切片，不只报overall。
5. 准备真实独立人物/会话/教材数据，用新group连通分量重新分配评估。已反复看过的旧两来源不能再当未触碰final test。
6. 只有动作数据质量达到任务要求后，再接入文字条件语言生成器、序列长度/语序/非手部表情监督、专家/独立评估和插件重定向。
7. 如果只有技术数据、没有新真值或可靠观测，不重复盲目加步数；保持研究候选及证据，不宣称大模型完成。

## 18. 已知信息缺口与不能补造的部分

- T10服务器report/checkpoint未下载本地，SHA未知；本次远端连接被拒。
- 早期一些系统级安装和训练兼容报错仅以对话及维护文档记录，未能取得所有逐行原日志。
- 原始13源文件的视频授权用途仍以用户许可约定为准，未独立审核授权文本；模型许可文件单独留存。
- 未确认各课程实际真人身份、全视频镜像/剪辑历史、指尖接触真实点和遮挡3D姿态。
- 没有实测独立语言学准确率、陌生句生成质量或生产端-to-end在线效果。
- 没有训练花费/市场订单收费记录；可报告部分网络优化elapsed_seconds，但不能编造总GPU计费或真实训练总时长。

## 19. 全文证据附录与报告阅读建议

- 正文先查0/7/9/15/17，定位现状、权重、比较、校正与下一步。
- 需要准确复跑时查13和`commands.json`，使用相应本地环境、真实SHA及新输出目录。
- 需要了解某次失败所有细节，查HTML“证据检索”或`failure-registry.json`，打开对应快照，不依赖摘要里的一个status。
- 需要所有字段/history/traceback时直接查`evidence/`；来源路径和原字节SHA始终与快照一起登记。
- 可将本报告zip移至别的机器阅读，里面快照自包含；模型/视频等大二进制只保留引用，迁移调用需要另拷贝并校验真实文件。

### 附录A：全部控制报告索引

| 编号 | 源文件 | schema | 原status | 完整快照 |
| --- | --- | --- | --- | --- |
| 2 | local-data/camera-reference-pilot-20261009/report.json | signbridge-camera-coordinate-audit-v1 | reference_camera_proposals_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/camera-reference-pilot-20261009/report.json>) |
| 4 | local-data/camera-source-20261009/capture.json | signbridge-camera-source-capture-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/camera-source-20261009/capture.json>) |
| 389 | local-data/camera-source-20261009/run.json | signbridge-smplerx-run-v1 | inferred_pending_import_audit | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/camera-source-20261009/run.json>) |
| 396 | local-data/contact-final-20261009/verified/results/report.json | signbridge-contact-hypothesis-pilot-v1 | contact_proposals_rejected | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/contact-final-20261009/verified/results/report.json>) |
| 399 | local-data/contact-observation-audit-20261009/report.json | signbridge-contact-observation-audit-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/contact-observation-audit-20261009/report.json>) |
| 401 | local-data/contact-observation-audit-20261009-final/report.json | signbridge-contact-observation-audit-v1 | audited_pending_correspondence_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/contact-observation-audit-20261009-final/report.json>) |
| 403 | local-data/contact-observation-audit-20261009-v2/report.json | signbridge-contact-observation-audit-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/contact-observation-audit-20261009-v2/report.json>) |
| 405 | local-data/contact-observation-audit-20261009-v3/report.json | signbridge-contact-observation-audit-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/contact-observation-audit-20261009-v3/report.json>) |
| 409 | local-data/contact-proximity-20261009/verified/results/report.json | signbridge-contact-hypothesis-pilot-v1 | contact_proposals_rejected | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/contact-proximity-20261009/verified/results/report.json>) |
| 415 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/fit-plan/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/fit-plan/run.json>) |
| 417 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1/motion-review-decision.json | signbridge-motion-visual-review-v1 | approved_by_user | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1/motion-review-decision.json>) |
| 426 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1/verification.json | signbridge-reviewed-motion-snapshot-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-approved-v1/verification.json>) |
| 428 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-review/motion-review-decision.json | signbridge-motion-visual-review-v1 | approved_by_user | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/motion-review/motion-review-decision.json>) |
| 441 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/reviewed/review-decision.json | signbridge-content-review-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/reviewed/review-decision.json>) |
| 901 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/server-return/verified/fits/run.json | signbridge-smplerx-run-v1 | inferred_pending_import_audit | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/server-return/verified/fits/run.json>) |
| 910 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/server-return/verified/motions/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/server-return/verified/motions/verification.json>) |
| 913 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/smplerx-input/review-decision.json | signbridge-content-review-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/smplerx-input/review-decision.json>) |
| 922 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/inference/new-58a5b3d6622ea72a-0068/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/inference/new-58a5b3d6622ea72a-0068/report.json>) |
| 924 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/inference/new-8ffc3bdb3f8d0763-0124/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/inference/new-8ffc3bdb3f8d0763-0124/report.json>) |
| 926 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/inference/new-fe2208d9680580cd-0087/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/inference/new-fe2208d9680580cd-0087/report.json>) |
| 927 | local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/report.json | signbridge-new-clip-frozen-tokenizer-check-v1 | frozen_tokenizer_transfer_check_complete_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/confirmed-pilot-20261010-v1/transfer-check-v1/report.json>) |
| 986 | local-data/data-expansion-20261010/prepared-candidates/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/prepared-candidates/verification.json>) |
| 1000 | local-data/data-expansion-20261010/prepared-tutorials/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/prepared-tutorials/verification.json>) |
| 1010 | local-data/data-expansion-20261010/review-delivery/delivery.json | signbridge-source-expansion-delivery-v1 | new_source_candidates_prepared_and_structurally_verified | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/review-delivery/delivery.json>) |
| 1015 | local-data/data-expansion-20261010/review-delivery/validation.json | signbridge-source-expansion-validation-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/data-expansion-20261010/review-delivery/validation.json>) |
| 1063 | local-data/full-sequence-20261009/archive.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/archive.json>) |
| 1067 | local-data/full-sequence-20261009/cpu-inference/pilot-greeting-hello-001/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/cpu-inference/pilot-greeting-hello-001/report.json>) |
| 1069 | local-data/full-sequence-20261009/cpu-inference/pilot-hospital-cough-003/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/cpu-inference/pilot-hospital-cough-003/report.json>) |
| 1078 | local-data/full-sequence-20261009/curated-motions/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/curated-motions/verification.json>) |
| 1087 | local-data/full-sequence-20261009/curated-motions-final/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/curated-motions-final/verification.json>) |
| 1096 | local-data/full-sequence-20261009/curated-motions-validated/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/curated-motions-validated/verification.json>) |
| 1107 | local-data/full-sequence-20261009/curated-verified/curated-motions/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/curated-verified/curated-motions/verification.json>) |
| 1108 | local-data/full-sequence-20261009/curated-verified/curated-status.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/curated-verified/curated-status.json>) |
| 1111 | local-data/full-sequence-20261009/curated-verified/training-curated/results/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/curated-verified/training-curated/results/report.json>) |
| 1120 | local-data/full-sequence-20261009/delivery-motions/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/delivery-motions/verification.json>) |
| 1129 | local-data/full-sequence-20261009/delivery-source-motions/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/delivery-source-motions/verification.json>) |
| 1130 | local-data/full-sequence-20261009/delivery.json | signbridge-full-sequence-delivery-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/delivery.json>) |
| 1137 | local-data/full-sequence-20261009/final-verified/final-status.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/final-verified/final-status.json>) |
| 1140 | local-data/full-sequence-20261009/final-verified/tokenizer-final-review/report.json | signbridge-tokenizer-native-review-v1 | in_sample_native_reconstruction_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/final-verified/tokenizer-final-review/report.json>) |
| 1142 | local-data/full-sequence-20261009/final-verified/training-final/results/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/final-verified/training-final/results/report.json>) |
| 1151 | local-data/full-sequence-20261009/motions-final-validated/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/motions-final-validated/verification.json>) |
| 1153 | local-data/full-sequence-20261009/plan.json | signbridge-stable-crop-plan-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/plan.json>) |
| 1158 | local-data/full-sequence-20261009/state.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/state.json>) |
| 1162 | local-data/full-sequence-20261009/tokenizer-render-verified/tokenizer-native-review/report.json | signbridge-tokenizer-native-review-v1 | in_sample_native_reconstruction_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/tokenizer-render-verified/tokenizer-native-review/report.json>) |
| 1167 | local-data/full-sequence-20261009/validation.json | signbridge-full-sequence-validation-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/validation.json>) |
| 1171 | local-data/full-sequence-20261009/verified/fusion-source/results/report.json | signbridge-mano-smplx-alignment-v1 | alignment_candidate_gate_failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/fusion-source/results/report.json>) |
| 1181 | local-data/full-sequence-20261009/verified/motions/verification.json | signbridge-full-fusion-export-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/motions/verification.json>) |
| 1183 | local-data/full-sequence-20261009/verified/plan.json | signbridge-stable-crop-plan-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/plan.json>) |
| 1185 | local-data/full-sequence-20261009/verified/post-status.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/post-status.json>) |
| 1189 | local-data/full-sequence-20261009/verified/stable-source/plan.json | signbridge-stable-crop-plan-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/stable-source/plan.json>) |
| 1578 | local-data/full-sequence-20261009/verified/stable-source/results/report.json | signbridge-stable-crop-pilot-v1 | inferred_pending_stable_crop_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/stable-source/results/report.json>) |
| 1580 | local-data/full-sequence-20261009/verified/status.json | signbridge-full-sequence-driver-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/status.json>) |
| 1582 | local-data/full-sequence-20261009/verified/training/results/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/training/results/report.json>) |
| 1584 | local-data/full-sequence-20261009/verified/wilor-source/results/report.json | signbridge-wilor-keyframe-pilot-v1 | missing_required_hand | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/full-sequence-20261009/verified/wilor-source/results/report.json>) |
| 1589 | local-data/hand-keyframe-runs/download-dl13uskz/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | keyframe_candidates_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-dl13uskz/verified/results/report.json>) |
| 1594 | local-data/hand-keyframe-runs/download-k99wh10f/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | saved_parameters_rerendered_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-k99wh10f/verified/results/report.json>) |
| 1599 | local-data/hand-keyframe-runs/download-ln9bx0j6/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-ln9bx0j6/verified/results/report.json>) |
| 1604 | local-data/hand-keyframe-runs/download-p7acq0ut/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-p7acq0ut/verified/results/report.json>) |
| 1609 | local-data/hand-keyframe-runs/download-pof7lsms/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-pof7lsms/verified/results/report.json>) |
| 1614 | local-data/hand-keyframe-runs/download-trkzf8dr/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | candidate_gate_failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-trkzf8dr/verified/results/report.json>) |
| 1619 | local-data/hand-keyframe-runs/download-uq0azu_4/verified/results/report.json | signbridge-hand-keyframe-pilot-v1 | candidate_gate_failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/download-uq0azu_4/verified/results/report.json>) |
| 1623 | local-data/hand-keyframe-runs/hand-keyframe-pilot-20261008-083758-cla3MU/state.json | signbridge-hand-pilot-launch-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261008-083758-cla3MU/state.json>) |
| 1625 | local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-063407-oE5eJX/state.json | signbridge-hand-pilot-launch-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-063407-oE5eJX/state.json>) |
| 1627 | local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-065007-8f5GgO/state.json | signbridge-hand-pilot-launch-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-065007-8f5GgO/state.json>) |
| 1629 | local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-071346-2mYWJC/state.json | signbridge-hand-pilot-launch-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-071346-2mYWJC/state.json>) |
| 1631 | local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-072730-m2RWFf/state.json | signbridge-hand-pilot-launch-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-072730-m2RWFf/state.json>) |
| 1633 | local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-073446-J4C8jT/state.json | signbridge-hand-pilot-launch-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/hand-keyframe-runs/hand-keyframe-pilot-20261009-073446-J4C8jT/state.json>) |
| 1638 | local-data/heldout-eval-20261009/archive.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-eval-20261009/archive.json>) |
| 1640 | local-data/heldout-eval-20261009/cpu-inference/fold-01/pilot-greeting-hello-001/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-eval-20261009/cpu-inference/fold-01/pilot-greeting-hello-001/report.json>) |
| 1642 | local-data/heldout-eval-20261009/cpu-inference/fold-02/pilot-hospital-cough-003/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-eval-20261009/cpu-inference/fold-02/pilot-hospital-cough-003/report.json>) |
| 1645 | local-data/heldout-eval-20261009/state.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-eval-20261009/state.json>) |
| 1650 | local-data/heldout-eval-20261009/verified/results/report.json | signbridge-leave-source-out-tokenizer-v1 | leave_source_out_experiments_complete_pending_quality_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-eval-20261009/verified/results/report.json>) |
| 1652 | local-data/heldout-review-20261010/report.json | signbridge-source-heldout-review-v1 | source_holdout_evidence_independently_recomputed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-review-20261010/report.json>) |
| 1655 | local-data/heldout-review-20261010-final/delivery.json | signbridge-heldout-delivery-v1 | train_holdout_infer_independent_review_complete | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-review-20261010-final/delivery.json>) |
| 1657 | local-data/heldout-review-20261010-final/report.json | signbridge-source-heldout-review-v1 | source_holdout_evidence_independently_recomputed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-review-20261010-final/report.json>) |
| 1659 | local-data/heldout-review-20261010-final/validation.json | signbridge-source-holdout-validation-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-review-20261010-final/validation.json>) |
| 1662 | local-data/heldout-review-20261010-validated/report.json | signbridge-source-heldout-review-v1 | source_holdout_evidence_independently_recomputed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/heldout-review-20261010-validated/report.json>) |
| 1668 | local-data/mano-smplx-alignment-20261009/verified/results/report.json | signbridge-mano-smplx-alignment-v1 | alignment_candidates_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/mano-smplx-alignment-20261009/verified/results/report.json>) |
| 1672 | local-data/mano-smplx-alignment-final-20261009/verified/results/report.json | signbridge-mano-smplx-alignment-v1 | alignment_candidates_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/mano-smplx-alignment-final-20261009/verified/results/report.json>) |
| 1679 | local-data/mano-smplx-fusion-windows-20261009/verified/results/report.json | signbridge-mano-smplx-alignment-v1 | alignment_candidates_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/mano-smplx-fusion-windows-20261009/verified/results/report.json>) |
| 1685 | local-data/mano-smplx-fusion-windows-final-20261009/verified/results/report.json | signbridge-mano-smplx-alignment-v1 | alignment_candidates_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/mano-smplx-fusion-windows-final-20261009/verified/results/report.json>) |
| 1686 | local-data/pilot-hand-targets-20261007-v1/report.json | signbridge-hand-keyframe-pilot-v1 | targets_pending_visual_check | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/pilot-hand-targets-20261007-v1/report.json>) |
| 1687 | local-data/pilot-hand-targets-20261007-v2/report.json | signbridge-hand-keyframe-pilot-v1 | targets_pending_visual_check | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/pilot-hand-targets-20261007-v2/report.json>) |
| 1697 | local-data/pilot-motion-review-20261007-151306-GgKn6b/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/pilot-motion-review-20261007-151306-GgKn6b/verification.json>) |
| 1706 | local-data/remaining14-eval-20261010/frozen-diagnostic/inference/pilot-greeting-hello-001/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-eval-20261010/frozen-diagnostic/inference/pilot-greeting-hello-001/report.json>) |
| 1708 | local-data/remaining14-eval-20261010/frozen-diagnostic/inference/pilot-hospital-cough-003/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-eval-20261010/frozen-diagnostic/inference/pilot-hospital-cough-003/report.json>) |
| 1709 | local-data/remaining14-eval-20261010/frozen-diagnostic/report.json | signbridge-frozen-clip-diagnostic-v1 | frozen_clip_diagnostic_complete_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-eval-20261010/frozen-diagnostic/report.json>) |
| 1719 | local-data/remaining14-eval-20261010/raw-reference-motions/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-eval-20261010/raw-reference-motions/verification.json>) |
| 1720 | local-data/remaining14-eval-20261010/validation.json | signbridge-remaining14-frozen-evaluation-validation-v1 | frozen_clip_evaluation_verified_not_promoted | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-eval-20261010/validation.json>) |
| 1757 | local-data/remaining14-hand-quality-20261010/audit/masked-motions/verification.json | signbridge-hand-observation-screen-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/audit/masked-motions/verification.json>) |
| 1758 | local-data/remaining14-hand-quality-20261010/audit/report.json | signbridge-hand-quality-audit-v1 | automatic_screen_complete | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/audit/report.json>) |
| 1792 | local-data/remaining14-hand-quality-20261010/audit-v2/masked-motions/verification.json | signbridge-hand-observation-screen-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/audit-v2/masked-motions/verification.json>) |
| 1793 | local-data/remaining14-hand-quality-20261010/audit-v2/report.json | signbridge-hand-quality-audit-v1 | automatic_screen_complete | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/audit-v2/report.json>) |
| 1795 | local-data/remaining14-hand-quality-20261010/comparison.json | signbridge-observation-mask-ablation-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/comparison.json>) |
| 1798 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-answer-002/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-answer-002/report.json>) |
| 1800 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-busy-005/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-busy-005/report.json>) |
| 1802 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-how-004/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-how-004/report.json>) |
| 1804 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-lunch-006/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-lunch-006/report.json>) |
| 1806 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-overtime-008/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-overtime-008/report.json>) |
| 1808 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-well-007/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-greeting-well-007/report.json>) |
| 1810 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-allergy-011/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-allergy-011/report.json>) |
| 1812 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-cold-009/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-cold-009/report.json>) |
| 1814 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-dose-012/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-dose-012/report.json>) |
| 1816 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-iv-016/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-iv-016/report.json>) |
| 1818 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-pay-013/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-pay-013/report.json>) |
| 1820 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-rest-010/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-rest-010/report.json>) |
| 1822 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-serious-015/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-serious-015/report.json>) |
| 1824 | local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-temperature-014/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/cpu-inference/pilot-hospital-temperature-014/report.json>) |
| 1827 | local-data/remaining14-hand-quality-20261010/evaluation-unmasked-reference/inference/pilot-greeting-hello-001/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/evaluation-unmasked-reference/inference/pilot-greeting-hello-001/report.json>) |
| 1829 | local-data/remaining14-hand-quality-20261010/evaluation-unmasked-reference/inference/pilot-hospital-cough-003/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/evaluation-unmasked-reference/inference/pilot-hospital-cough-003/report.json>) |
| 1830 | local-data/remaining14-hand-quality-20261010/evaluation-unmasked-reference/report.json | signbridge-frozen-clip-diagnostic-v1 | frozen_clip_diagnostic_complete_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/evaluation-unmasked-reference/report.json>) |
| 1832 | local-data/remaining14-hand-quality-20261010/paired-comparison.json | signbridge-paired-common-mask-comparison-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-comparison.json>) |
| 1835 | local-data/remaining14-hand-quality-20261010/paired-evaluation-original/inference/pilot-greeting-hello-001/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-evaluation-original/inference/pilot-greeting-hello-001/report.json>) |
| 1837 | local-data/remaining14-hand-quality-20261010/paired-evaluation-original/inference/pilot-hospital-cough-003/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-evaluation-original/inference/pilot-hospital-cough-003/report.json>) |
| 1838 | local-data/remaining14-hand-quality-20261010/paired-evaluation-original/report.json | signbridge-frozen-clip-diagnostic-v1 | frozen_clip_diagnostic_complete_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-evaluation-original/report.json>) |
| 1841 | local-data/remaining14-hand-quality-20261010/paired-evaluation-screened/inference/pilot-greeting-hello-001/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-evaluation-screened/inference/pilot-greeting-hello-001/report.json>) |
| 1843 | local-data/remaining14-hand-quality-20261010/paired-evaluation-screened/inference/pilot-hospital-cough-003/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-evaluation-screened/inference/pilot-hospital-cough-003/report.json>) |
| 1844 | local-data/remaining14-hand-quality-20261010/paired-evaluation-screened/report.json | signbridge-frozen-clip-diagnostic-v1 | frozen_clip_diagnostic_complete_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-evaluation-screened/report.json>) |
| 1852 | local-data/remaining14-hand-quality-20261010/paired-masked-reference/verification.json | signbridge-hand-observation-screen-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/paired-masked-reference/verification.json>) |
| 1860 | local-data/remaining14-hand-quality-20261010/verified/masked-training/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/verified/masked-training/report.json>) |
| 1863 | local-data/remaining14-hand-quality-20261010/verified/wilor-results/report.json | signbridge-wilor-keyframe-pilot-v1 | missing_required_hand | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-hand-quality-20261010/verified/wilor-results/report.json>) |
| 1867 | local-data/remaining14-research-20261010/completed.json | signbridge-remaining14-research-plan-v1 | research_training_completed_cpu_parity_verified | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/completed.json>) |
| 1870 | local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-answer-002/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-answer-002/report.json>) |
| 1872 | local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-busy-005/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-busy-005/report.json>) |
| 1874 | local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-how-004/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-how-004/report.json>) |
| 1876 | local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-lunch-006/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-lunch-006/report.json>) |
| 1878 | local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-overtime-008/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-overtime-008/report.json>) |
| 1880 | local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-well-007/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-greeting-well-007/report.json>) |
| 1882 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-allergy-011/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-allergy-011/report.json>) |
| 1884 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-cold-009/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-cold-009/report.json>) |
| 1886 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-dose-012/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-dose-012/report.json>) |
| 1888 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-iv-016/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-iv-016/report.json>) |
| 1890 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-pay-013/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-pay-013/report.json>) |
| 1892 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-rest-010/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-rest-010/report.json>) |
| 1894 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-serious-015/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-serious-015/report.json>) |
| 1896 | local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-temperature-014/report.json | signbridge-tokenizer-inference-v1 | motion_encoded_and_reconstructed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/cpu-inference/pilot-hospital-temperature-014/report.json>) |
| 1899 | local-data/remaining14-research-20261010/plan.json | signbridge-remaining14-research-plan-v1 | reconstruction_import_passed_pending_research_training | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/plan.json>) |
| 1901 | local-data/remaining14-research-20261010/validation.json | signbridge-remaining14-stage-validation-v1 | research_training_and_local_reload_complete | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/validation.json>) |
| 4652 | local-data/remaining14-research-20261010/verified/fits/run.json | signbridge-smplerx-run-v1 | inferred_pending_import_audit | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/verified/fits/run.json>) |
| 4683 | local-data/remaining14-research-20261010/verified/motions/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/verified/motions/verification.json>) |
| 4685 | local-data/remaining14-research-20261010/verified/training/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/remaining14-research-20261010/verified/training/report.json>) |
| 4721 | local-data/sign-language-candidates-v3/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-candidates-v3/verification.json>) |
| 4737 | local-data/sign-language-first-batch-v2/verification.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-first-batch-v2/verification.json>) |
| 4739 | local-data/sign-language-fit-plan-mac-v1/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-fit-plan-mac-v1/run.json>) |
| 4742 | local-data/sign-language-fit-plan-mac-v2/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-fit-plan-mac-v2/run.json>) |
| 4745 | local-data/sign-language-fit-plan-mac-v3/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-fit-plan-mac-v3/run.json>) |
| 4748 | local-data/sign-language-fit-plan-mac-v4/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-fit-plan-mac-v4/run.json>) |
| 4751 | local-data/sign-language-fit-plan-mac-v5/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-fit-plan-mac-v5/run.json>) |
| 4754 | local-data/sign-language-fit-plan-mac-v6/run.json | signbridge-smplerx-run-v1 | blocked | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-fit-plan-mac-v6/run.json>) |
| 4758 | local-data/sign-language-gpu-stage-v1/batch/review-decision.json | signbridge-content-review-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-gpu-stage-v1/batch/review-decision.json>) |
| 4780 | local-data/sign-language-gpu-stage-v2/batch/review-decision.json | signbridge-content-review-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-gpu-stage-v2/batch/review-decision.json>) |
| 4812 | local-data/sign-language-reviewed-v4/review-decision.json | signbridge-content-review-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-reviewed-v4/review-decision.json>) |
| 4817 | local-data/sign-language-smplx-input-v1/review-decision.json | signbridge-content-review-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/sign-language-smplx-input-v1/review-decision.json>) |
| 4837 | local-data/stable-crop-fusion-20261009/failed-start-evidence/results/report.json | signbridge-mano-smplx-alignment-v1 | failed | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-fusion-20261009/failed-start-evidence/results/report.json>) |
| 4840 | local-data/stable-crop-fusion-20261009/state.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-fusion-20261009/state.json>) |
| 4841 | local-data/stable-crop-fusion-20261009/validation.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-fusion-20261009/validation.json>) |
| 4845 | local-data/stable-crop-fusion-20261009/verified/results/report.json | signbridge-mano-smplx-alignment-v1 | alignment_candidates_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-fusion-20261009/verified/results/report.json>) |
| 4849 | local-data/stable-crop-pilot-20261009/plan.json | signbridge-stable-crop-plan-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-pilot-20261009/plan.json>) |
| 4850 | local-data/stable-crop-pilot-20261009/state.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-pilot-20261009/state.json>) |
| 4851 | local-data/stable-crop-pilot-20261009/validation.json | 未声明 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-pilot-20261009/validation.json>) |
| 4855 | local-data/stable-crop-pilot-20261009/verified/plan.json | signbridge-stable-crop-plan-v1 | 未声明 | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-pilot-20261009/verified/plan.json>) |
| 4874 | local-data/stable-crop-pilot-20261009/verified/results/report.json | signbridge-stable-crop-pilot-v1 | inferred_pending_stable_crop_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-pilot-20261009/verified/results/report.json>) |
| 4877 | local-data/stable-crop-review-20261009/report.json | signbridge-stable-crop-review-v1 | stable_crop_comparison_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-review-20261009/report.json>) |
| 4879 | local-data/stable-crop-review-20261009-validated/report.json | signbridge-stable-crop-review-v1 | stable_crop_comparison_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-crop-review-20261009-validated/report.json>) |
| 4881 | local-data/stable-fusion-review-20261009/report.json | signbridge-stable-fusion-review-v1 | stable_fusion_saved_parameters_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-fusion-review-20261009/report.json>) |
| 4883 | local-data/stable-fusion-review-20261009-validated/report.json | signbridge-stable-fusion-review-v1 | stable_fusion_saved_parameters_pending_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/stable-fusion-review-20261009-validated/report.json>) |
| 4884 | local-data/temporal-hand-audit-20261009/report.json | signbridge-temporal-hand-audit-v1 | audited_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/temporal-hand-audit-20261009/report.json>) |
| 4886 | local-data/temporal-hand-audit-20261009-final/report.json | signbridge-temporal-hand-audit-v1 | audited_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/temporal-hand-audit-20261009-final/report.json>) |
| 4888 | local-data/temporal-hand-audit-20261009-final-v2/report.json | signbridge-temporal-hand-audit-v1 | audited_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/temporal-hand-audit-20261009-final-v2/report.json>) |
| 4890 | local-data/temporal-hand-audit-20261009-v2/report.json | signbridge-temporal-hand-audit-v1 | audited_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/temporal-hand-audit-20261009-v2/report.json>) |
| 4892 | local-data/temporal-hand-audit-20261009-validated/report.json | signbridge-temporal-hand-audit-v1 | audited_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/temporal-hand-audit-20261009-validated/report.json>) |
| 4897 | local-data/tokenizer-smoke-20261009-074134-Q9JVxL/verified/results/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/tokenizer-smoke-20261009-074134-Q9JVxL/verified/results/report.json>) |
| 4901 | local-data/tokenizer-smoke-verified-20261009-074538-KncThF/verified/results/report.json | signbridge-tokenizer-smoke-v1 | research_smoke_trained_not_deployable | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/tokenizer-smoke-verified-20261009-074538-KncThF/verified/results/report.json>) |
| 4907 | local-data/wilor-keyframes-20261009/verified/results/report.json | signbridge-wilor-keyframe-pilot-v1 | inferred_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/wilor-keyframes-20261009/verified/results/report.json>) |
| 4910 | local-data/wilor-keyframes-rerender-20261009/verified/results/report.json | signbridge-wilor-rerender-v1 | rerendered_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/wilor-keyframes-rerender-20261009/verified/results/report.json>) |
| 4915 | local-data/wilor-keyframes-verified-20261009/verified/results/report.json | signbridge-wilor-keyframe-pilot-v1 | inferred_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/wilor-keyframes-verified-20261009/verified/results/report.json>) |
| 4923 | local-data/wilor-windows-20261009/verified/results/report.json | signbridge-wilor-keyframe-pilot-v1 | inferred_pending_visual_review | [全文](</Users/mac/Documents/ChatGPT/signbridge/local-data/training-master-report-20261010-v1/evidence/local-data/wilor-windows-20261009/verified/results/report.json>) |

