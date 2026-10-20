# 现有资源优化实验（本地 1.0.5）

本轮只复用本机已有中文语义模型、六批动作、教程词句和 Godette 骨骼，没有引入视频、外部语料或 GPU 训练。输出位于忽略目录 `local-data/existing-resources-optimization-20261019-v1/`。T08 检查点、SMPL-X 参数、原片、旧模型和批准状态保持不变。

## 总览

| 工作             |                                                           结果 | 解释                                                                                               |
| ---------------- | -------------------------------------------------------------: | -------------------------------------------------------------------------------------------------- |
| 冻结中文对照     |                    76例；3例与旧训练文本归一化后重叠并单独排除 | 开发者合成结构测试，不是独立自然语言评测                                                           |
| 无重叠的结构留出 |                                     46例，其中22个预期支持结构 | 旧解析器正确覆盖6/22；作用域实验覆盖22/22、误接受0/24                                              |
| 无重叠全套       | 73例；作用域实验正确解析42/42个支持项，正确拒绝31/31个不支持项 | 100%只说明符合冻结的合成契约，不说明现实中文／CSL准确率                                            |
| 教程单元候选     |                                          20项，完整解码3,516帧 | 观测活动区间是边界线索；人工核验词单元数仍为0                                                      |
| 虚拟人轨迹比较   |                                                           95段 | 自适应过滤0段通过共同数值门槛，不晋级默认显示                                                      |
| 有界动作缓存     |                              最多12条、500,000个四元数分量预算 | 本机冷编译均值约20.5 ms，热查找约0.0019 ms；峰值数值载荷约768 KB，不含 JS 对象、活动轨迹和显卡资源 |

## 中文作用域实验

`tests/fixtures/semantic-contrast-v1.json` 在结构约束代码之前冻结，覆盖人物互换、时间语序、否定／情态辖域、体貌、句内边界和超出范围句。按模板组切分，报告同时列完整结果和排除训练文本重叠后的指标。

例如“我不想去”解析为 `不(想(去))`，“我想不去”解析为 `想(不(去))`。实现复用 `learned-roles-v3` 权重与标签，只对很窄的作用域组合、体貌组合施加新约束；未知组合、重复操作符、不完整或复杂分句仍拒答。没有新增学习参数，也没有置信度。

基线默认未改变。只有启动时显式加入 `--scope-experiment` 才启用，候选证据可选：

```sh
.venv-sign-data/bin/python signbridge/src/tools/sign-private-serve.py \
  --model local-data/csl-understanding-20261017-rLaeiN/learned-roles-v3 \
  --client local-data/existing-resources-optimization-20261019-v1/thin-client-v1.0.5 \
  --port 8770 --scope-experiment \
  --unit-candidates local-data/existing-resources-optimization-20261019-v1/unit-candidates-final/candidates.json
```

按终端当次提示输入短期口令。工作台“意思分析”链接进入作用域对照。服务仍只绑定本机，静态页面仅有一个固定 `scope=1` 查询变体，不能将口令或待分析文字放入 URL。事件树和表达计划通过输入／角色类型校验；计划恒为 `review_required`、`can_play=false`、`motion_items=[]`。已有教程单元只有文字精确相同时作为证据候选；否则明确显示缺口。

未从扩展工作台启动时，对照页地址是 `http://127.0.0.1:8770/private/index.html?scope=1`（按终端实际端口替换）。独立轻客户端 0.1.3 不附动作库或权重。

完整测量在 `semantic-contrast-v4/report.json`。报告分开计算所有接受内容和预期支持内容的覆盖／正确率。3个重叠项为“你能去”“你没去”和标点归一化后的“她去学校”，已从泄漏排除结果中移走。保留测试仍是已知模板集，不是由独立专家设计／标注，所以即使契约分数满分也不能宣称“真正理解中文”，更不能宣称理解中国手语。

## 旧视频候选单元

复用教程索引中问候、常用动作和时间参考各一组，打包20条原片窗口与已有采样联系表。工具重新核对索引、原视频及已登记的片段／2D观测／注释／质量文件摘要，并用 OpenCV 对20段逐帧完整解码。候选页：[unit-candidates-final/index.html](../local-data/existing-resources-optimization-20261019-v1/unit-candidates-final/index.html)。

每项保留原始教程说明、名义时间窗口、估计器左右槽观测及缺失／排除帧。由连续可用观测提出至多3个速度高点窗口，仅供人寻找视频位置；快速运动和教学过渡也会产生活动峰，因此明确**不等于词起止、手语相位或边界建议**。教程系列相同且 `split=unassigned`，没有训练划分。总候选20、`verified_word_units=0`，所有 `text_verified` 为空，`human_approved/training_ready/model_training_ready=false`。

## 动作稳定与缓存

在完整六批 Demo 实验动作和来源6预览动作上，以实际 Godette 骨架全帧比较原始、现有资产配置与“孤立尖峰”研究过滤。指标包含局部旋转中点残差、腕部中点残差、腕部范围、手指末端**骨骼原点**位移和原轨迹手部骨端小于3 cm帧的距离变化。骨端／近手数据是模型上的风险筛查代理，不是皮肤碰撞、接触真值或手语语义。

本轮95段上，新实验的平均腕部P95代理为3.85 cm，现有配置约1.00 cm；新实验最小腕部范围保留约85.9%。即使逐段应用“腕部残差不高于现有、腕部范围至少保留90%、手指末端骨端位移不比现有多0.2 cm”的门槛，**0/95通过**。因此只开放为收起的研究对照，绝不默认或批量推广；核对原片时仍以原始姿态及既有恢复配置为主。报告含每段的前后指标与所有输入／工具摘要：`motion-comparison-v4/report.json`。

代码提供一个至多每关节修正3度的孤立单帧尖峰实验，不会改写原姿态、加帧或改变时间轴。复核显示其在当前实现上对整体腕部代理过度修正，未达推广门槛，保留代码只为重复试验和显式预览。现有资产配置保持不变。

动作轨迹编译使用按来源／ID／滤镜的 LRU 缓存，限制为12条或500,000个四元数分量，页面卸载时清空。编译耗时、缓存命中和数值载荷统计不记录字幕原文，不计对象开销和活动轨迹。当前测量支持“可用缓存减少重复编译时间”，并不单独说明它改善了用户可感知首帧延迟；需要实机端到端启动测试时再单独测量。

## 本地总览与复现

综合表格：[dashboard-v6/index.html](../local-data/existing-resources-optimization-20261019-v1/dashboard-v6/index.html)。页面链接逐项原视频／联系表、语义和运动 JSON，并附同一动作暂停时刻的既有／实验人物截图。候选视频从本地静态页播放。综合报告已通过桌面／手机浏览器检查及20条视频实际解码帧检查，见 [浏览器验证记录](../local-data/existing-resources-optimization-20261019-v1/dashboard-browser-final/report.json)。每份底层报告含自己的输入摘要；T08检查点哈希另对照既有验证记录。所有报告都标记未人工批准和未训练。

```sh
.venv-sign-data/bin/python signbridge/src/tools/sign-semantic-contrast.py \
  --model local-data/csl-understanding-20261017-rLaeiN/learned-roles-v3 \
  --fixture signbridge/tests/fixtures/semantic-contrast-v1.json \
  --output /new/path/semantic-contrast

.venv-sign-data/bin/python signbridge/src/tools/sign-unit-candidates.py \
  --tutorial local-data/tutorial-hand-reference-20261010-v2 \
  --output /new/path/unit-candidates

node signbridge/src/tools/sign-motion-optimization.mjs \
  --assets local-data/six-batch-motion-audit-20261016-b3j952wo/display-fix-v2 \
  --extra local-data/data-expansion-20261015/source-6/avatar-preview-20261016-hjzppz64/motions-v1 \
  --output /new/path/motion-comparison
```

真实测量结果隔离在 ignored `local-data`。没有生成新 T08 权重或训练输出，不推送、不改旧发布件。

## 2026-10-19 第二轮工程优化

本轮继续复用同一批本地模型、95段可播放拟合动作和现有运行环境；没有增加训练数据、改权重、改源姿态或生成新语义标签。输出在新目录 `local-data/existing-resources-optimization-20261019-v2/`。

### 验证与服务边界

- `npm run verify` 现在只构建一次，之后运行 ESLint、JavaScript 测试、Python 全套测试与 Prettier；Python runner 优先采用仓库根 `.venv-sign-data`，也支持 `SIGNBRIDGE_PYTHON`。
- 发布报告目录和 `startedAt` 使用同一时间戳，避免之前目录名与报告相差毫秒。新建的纯函数单测覆盖该约束。
- 私有语义服务对候选证据文件限制为普通文件、5 MB、1000项；每条 ID 限128字符且唯一、候选文本限80字符、同一文本最多8条。遇到冲突的人工批准／训练状态会拒绝启动。传给浏览器的证据只含 ID 与候选文本，仍全部标为未批准、未核边界、不可训练、不可播放；客户端另行限制 ID 长度。

### 全量动作滤镜对照

在之前95段基线上新增“所有片段统一使用100 ms恢复滤镜”的研究对照，联合门槛仍为：腕部残差不高于当前资产配置、最小腕部范围保留至少90%、手指末端骨骼原点位移不超过当前配置0.2 cm。结果：

| 配置                   | 平均腕部中点残差P95 | 最小腕部范围保留 | 通过联合门槛 |
| ---------------------- | ------------------: | ---------------: | -----------: |
| 当前逐片段资产配置     |            0.997 cm |            69.8% |         基线 |
| 所有片段统一100 ms恢复 |            0.316 cm |            62.2% |         0/95 |
| 孤立尖峰实验           |            3.845 cm |            85.9% |         0/95 |

100 ms滤镜确实压低腕部残差代理，但动作范围损失更大；不能因此自动推广。原始轨迹、两条既有恢复配置和失败实验均保留，产品默认未改变。报告：`motion-comparison-v1/report.json`；工具不再用彼此独立的句子索引顺序伪算“跨片段跳变”。它仍是 Godette 骨架上的稳定性代理，没有专业手语动作质量/接触真值。

### 播放启动测量

本地研究构建在无头 Chromium 中实际点击扩展 Demo，测量点击到首个姿态更新消息（姿态应用及渲染调用之后），并检查缓存重播：冷启动样例约64.4 ms，三次暖重播约31.0、31.6、31.3 ms，缓存命中为真。记录：`browser-local-v2/report.json`。这只覆盖一条动作和一台本地软件渲染环境，是首个更新代理，不是物理屏幕显示时延或总体P95；足以说明同一动作缓存减少重复编译等待，但不足以据此调整缓存上限或宣称所有设备更快。

上述两份报告在各自的新目录生成，旧 v1 报告未覆盖。中文模型仍只在受限合成结构上验证；没有已核准词级 CSL 对齐和动作质量人工标签。因此本轮能完成工程验证、资源保护和播放性能优化，但无法仅靠当前素材把动作是否符合中国手语、镜像／手别或词界“优化通过”。`human_approved/training_ready/model_training_ready` 保持 false。

### 最终验收

修复验收指纹把 Python 测试生成的 `__pycache__` 字节码误认为源码变化后，单独保留失败记录在 `release-evidence-v1/releases/2026-10-19T13-53-40.485Z/release-acceptance.json`。测试启动器现在禁写 `.pyc`，源码指纹也明确跳过 `__pycache__`；增加候选文件符号链接和超长文本回归后，最终复跑结果位于 `release-evidence-v3/releases/2026-10-19T14-03-16.877Z/release-acceptance.json`。

最终记录为 1.0.5 `public-demo`，282个源文件指纹稳定；构建、Lint、233项 JavaScript 测试、492项 Python 测试和 Prettier 检查通过；六个浏览器阶段63项检查，以及语义/词边界审计和功能浏览器回归均通过。阶段截图、脚本输出和总报告全部写入 `release-evidence-v3/`，没有覆盖原固定 `test-results/`。`publishReady:false` 及五项人工检查仍待处理；没有对外发布。

## 2026-10-20 本机服务与来源模式修正

- 来源模式保持同一工作台，但各模式显示不同说明和实际目录：自动匹配、T08参考/拟合动作、内置词条、规则语义分析。切换到“内置词库”会自动切换到词条目录；规则语义模式隐藏动作播放和动作目录。
- 本机分析跳转在普通 `127.0.0.1` / `localhost` 工作台先请求无凭据、无用户文本的 `/health`。服务未运行时留在当前页，显示可直接运行的本地启动命令；服务启动后重试再打开分析页。健康端点只返回 `{"status":"ok"}`，不放宽带口令的推理接口来源校验。
- 本机页面浏览器回归覆盖服务关闭提示、服务启动后的作用域页面跳转、四种模式内容差异；服务启动命令显式带 `--scope-experiment`，避免规则研究标签与实际解析器配置不一致。
- 验收：`npm run verify:release` 通过，235项 JavaScript、493项 Python、Lint/Prettier、六阶段浏览器65项和新增长的服务交接2项检查通过。报告：`local-data/service-mode-fix-20261020-v1/release-evidence-v2/releases/2026-10-20T10-31-40.514Z/release-acceptance.json`。本机服务当前不会由网页自动启动；页面在检测不到服务时提供了仓库根目录启动命令。
