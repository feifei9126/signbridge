# 2026-10-19 审计整改（本地1.0.3）

本轮按照只读审计结果修复程序行为，不重新训练模型，不修改六批视频、原始动作、检查点或人工批准。当前代码在本地研究分支提交；没有自动推送、替换旧公开ZIP、修改仓库许可或撤回历史分发。

## 构建与交付范围

| 命令                     | 配置             | 打包内容                                       | 使用边界                                 |
| ------------------------ | ---------------- | ---------------------------------------------- | ---------------------------------------- |
| `npm run build`          | `public-demo`    | 已公开手工词典、角色与编辑／审阅工具           | 词典可提取；不自动读取local-data         |
| `npm run build:research` | `local-research` | 显式选择并通过SHA清单的T08／拟合动作／参考图片 | 本地核验，不能当保密公开包               |
| `npm run build:private`  | `private-client` | 轻量中文语义客户端                             | 无词库／动作／训练集／权重，需要本机服务 |

普通动作演示继续可用，默认不会因为本机偶然存在某个历史目录而把私有研究数据复制进产物。发布时查看 `BUILD.json` 的 profile、源码指纹、资产范围和逐文件SHA-256；配置声明不等于中国手语语言批准。仍需公开手工动作的演示就使用public-demo；要避免分发完整词库则使用private-client。客户端得到的结果仍可能被复制，既有公开MIT源码／旧ZIP无法通过本次本地改动撤回。

构建路径禁止指向仓库、源码、测试、工具、依赖或其祖先目录，并解析符号链接防止逃逸。自定义输出须为新目录；只有身份匹配的 `.signbridge-build.json` 产物目录允许重建。首次构建接管旧默认 `dist/` 时会先移到 `signbridge/backups/legacy-dist-*`，不删除旧动作证据；非默认、无标识的已有目录一律拒绝。研究输入预检在准备输出之前进行，摘要不符不会破坏旧产物。

### 显式本地研究构建

先选择来源资产并生成一个**新**的当前字节快照（不是补造历史run.json或原始JPEG摘要）：

```sh
# 从仓库根目录执行。输出父目录需已存在。
.venv-sign-data/bin/python signbridge/src/tools/sign-build-inputs.py \
  --demo local-data/demo-20261012 \
  --experimental local-data/six-batch-motion-audit-20261016-b3j952wo/display-fix-v2 \
  --output /absolute/path/to/new-research-inputs.json
```

从内层扩展项目执行（所有路径须为绝对路径）：

```sh
SIGNBRIDGE_BUILD_DIR=/absolute/path/to/new-local-demo \
SIGNBRIDGE_DEMO_ASSET_DIR=/absolute/path/to/demo-20261012 \
SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR=/absolute/path/to/display-fix-v2 \
SIGNBRIDGE_RESEARCH_ASSET_MANIFEST=/absolute/path/to/new-research-inputs.json \
npm run build:research
```

`local-research` 缺任何指定文件、哈希不符、原生字段／帧集不合约或输入符号链接逃逸都会失败；没有静默词库降级。沿用恢复版实验资产时原有两句防抖配置保持不变，不改原生姿态。`SIGNBRIDGE_BUILD_PROFILE` 也可显式指定配置，但不会自动发现本地数据。轻量客户端版本为0.1.1；private-client仍要求新输出目录，可用 `SIGNBRIDGE_PRIVATE_BUILD_DIR` 指定。

## 词项匹配和冗余整理

Demo和实时字幕的词典部分现在共享 `scanDictionaryText`，采用完整中文词边界，未知文本保留。`好久不见`、`不是`、`人民广场`、`了解一下`不再因子串碰巧命中而播放“好／不／见”“人”等残缺内容。参考动作跨度扫描放进独立模块，实时字幕无需带入语义规则模块。

在本次已固定浏览器／Node环境复查，原53条预设组合中只有28条能按共享边界完整匹配；另外25条从可播放目录隐藏，定义和历史证据仍保留。没有放宽词边界、添加猜测词条或改写旧统计。目录数量由实际匹配计算，变化不等于模型忘词／新增训练。

语义页只分析中文意思，返回 `analysis_only`、`items:[]`、`canPreview:false`。即使有整句拟合参考也只列作证据，不绕过语义／词级门禁。按钮、快捷键和导出报告一致；规则草案不再自动调用已有词典动作。auto、T08和词典模式明确保留参考动作预览。中文规则研究与已训练的私有角色模型仍是不同实验，界面标识不混用。

旧的一次性 `sign-source-catchup-audit.py` 未跟踪且硬编码76／380范围：本轮不删除、不修改、不自动调用，禁止用作来源4／6的通用审计。其他按批次保存的研究工具有不同数据契约，本轮只合并已经证实重复的匹配逻辑，不按文件数量盲删历史流程。

## ASR网络安全

设置保存和发送音频前共用端点校验：远程只能HTTPS；HTTP仅允许准确的127.0.0.1、localhost和[::1]。拒绝URL账号密码、fragment、其他协议和伪造本机后缀。发送设置为 `redirect:error`、`credentials:omit`，不跟随重定向把音频／Bearer发送到另一地址。旧远程HTTP配置需要手动改成HTTPS；本机开发端点仍可用。

## 本机研究服务

本机单服务进程、单随机口令，配额为所有连接共享60次／分钟，响应声明 `X-RateLimit-Scope: process`。满额返回429和Retry-After；忙碌返回503不占额度。2个推理并发、12个连接上限继续保留。测试覆盖不同连接共用额度与忙碌恢复；没有宣称多租户或独立用户会话隔离。私有客户端额外拒绝畸形roles响应，仍只以纯文本显示结果。

## 发布验证前置条件

Playwright固定为开发依赖，执行：

```sh
cd signbridge
npm ci
npx playwright install chromium
npm run verify:release
```

Linux CI使用 `npx playwright install --with-deps chromium`。缺浏览器时，验收在修改构建输出之前给出明确安装提示。测试默认使用本项目Playwright，仍允许通过已记录环境变量指定可用浏览器。验收保留按运行时间分隔的report，不通过删除上一轮失败报告判断成功；原有六阶段浏览器检查之外，加入本次词边界与语义禁播回归。

Python测试有统一入口，建议用项目环境：

```sh
.venv-sign-data/bin/python signbridge/src/tools/sign-test-suite.py
```

CI配置了Python3.12和numpy/scipy/Pillow/opencv测试依赖；这不是GPU训练环境。

## 依赖残余风险

本轮执行npm审计后更新了sharp和brace-expansion的兼容补丁，当前安装树的高危项从3降为0。仍有5个中危依赖链标记（Transformers.js3.x带来的onnxruntime-node／global-agent／roarr／sprintf-js链）；npm建议跨大版本升级到Transformers.js4.x。没有使用 `npm audit fix --force` 或顺手更换ASR大版本，因为需要单独做语音模型与运行时迁移验收。此处记录不等于宣称依赖审计全绿，也不把npm报告直接当作浏览器利用证明。

2026-10-18固定日期的研究打包器会拒绝把0.1.1客户端重新命名成旧0.1.0包；要发布新包必须另开版本。旧下载与历史素材未被覆盖。

## 本轮本地验证结果

| 验证范围               | 结果                                                            |
| ---------------------- | --------------------------------------------------------------- |
| 构建、ESLint、Prettier | 全部通过                                                        |
| JavaScript回归测试     | 216项通过，0失败                                                |
| Python回归测试         | 471项通过，0失败                                                |
| 原6阶段真实浏览器验收  | 63项检查通过                                                    |
| 审计专项浏览器回归     | public-demo与local-research均通过，语义按钮／快捷键禁播生效     |
| 私有客户端真实模型推理 | 0.1.1客户端通过角色交换、语序、否定、疑问、拒答与纯文本渲染检查 |
| T08检查点摘要          | 与既有预期SHA-256一致                                           |

发布验收记录为 `signbridge/test-results/releases/2026-10-19T05-15-50.842Z/release-acceptance.json`；本次汇总和内部摘要保存在忽略目录 `local-data/audit-remediation-20261019-v1/verification-final.json` 与 `evidence-final-v1/SHA256SUMS`。CI配置已修改，远端CI尚未运行；本次浏览器私有客户端在本机网页上下文验证。`publishReady`仍为false，自动化结果不代替中国手语人工质量验收。没有新模型训练或公网发布。
