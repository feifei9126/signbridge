# SignBridge 架构

SignBridge 将“输入获取、文本转换、动作资产、模型适配和 3D 播放”拆成独立层，避免手语数据与某一个虚拟人的原始骨骼名称绑定。

## 运行时组件

```text
popup 控制面板
  ├─ 翻译开关、手动文字、浮窗尺寸
  ├─ 本地 Whisper / 云端 ASR 设置
  ├─ 姿势编辑器、录制器、帮助入口
  ├─ 词库覆盖分析 → 未覆盖词 → 动作工具预填元数据
  └─ 动作验收 → 只读动作目录 → 回放 / 三视图截图 → 独立视觉基准

Service Worker
  ├─ 扩展状态与配置
  ├─ tabCapture 音频会话
  ├─ offscreen 生命周期
  └─ 转写文本消息路由

Offscreen Document
  ├─ 保持标签页音频输出
  ├─ 混声与 16 kHz 单声道重采样
  ├─ 浏览器内 Whisper 推理
  └─ OpenAI-compatible 云端转写

Content Script + Page Agent
  ├─ 创建和管理 3D 浮窗
  ├─ 捕获 TextTrack 与 DOM 字幕
  └─ 在页面、扩展和 iframe 间路由消息

Three.js iframe
  ├─ 加载 glTF 虚拟人
  ├─ 文本到动作序列
  ├─ 读取已确认的本地自定义动作、监听动作库变更
  ├─ Humanoid 重定向
  └─ 动作插值与渲染

姿势编辑器 / 关键帧录制器
  ├─ 动作包 JSON ↔ 整库备份 / 只读预检 → 新草稿
  └─ 统一动作资产 → 草稿 → 预览 → 人工确认
       └─ chrome.storage.local 共享动作库 → Three.js iframe
```

## 翻译流水线

### 离线覆盖分析

`src/tools/coverage.js` 提供扩展内的按需分析页面；`src/avatar/coverage-analysis.js` 负责有限大小的纯文字/SRT/WebVTT 解析和统计。页面读取实际 GLB 创建同一 `HumanoidRig`，使用 `createMotionLibrary()` 校验骨骼绑定和确认状态，再将 `selectEnabledMotions()` 的结果交给同一个 `compileTranslationMatchers()` / `translateText()`。不另造一份容易偏离运行时的查找算法。

全段统计与每段 12 个动作的运行时截断分开计算。草稿、过期确认、冲突或无效条目不能增加有效覆盖。模型/存储无法核验时显示失败，不悄悄退回仅内置词库的报告。报告是当前快照，输入或动作库变化后禁止导出旧报告。

该页面不播放动画、不生成动作、不保存或上传分析语料。只在内存中处理，JSON 下载由用户主动触发，默认不含原文。工具跳转使用扩展 URL 的 fragment 传递一个词作为名称/匹配文字建议；不携带整段字幕，不写动作库。加载模型只用于同源校验，不创建渲染循环；读取后释放模型资源，离页移除存储监听并撤销下载 URL。详见[第三阶段流程与边界](phase3-coverage.md)。

### 小批量补词清单

覆盖页的 `src/tools/vocabulary-batch-ui.js` 将用户明确选择的缺词或完整词组交给 `src/avatar/vocabulary-batch.js`，仅在 `chrome.storage.local` 的独立键保存最多 8 个候选。写入使用同源 Web Lock 串行化；损坏记录不自动覆盖，锁不可用时不写入。它不保存分析原文、不保存或启用动作，也不修改视觉基准。

状态来自真实模型校验后的共享动作库和同一个运行时匹配器。草稿、失效确认及部分匹配不会被记为完全匹配；动作库变化会触发重算。导出前再次核验，模型或存储失败时禁用导出。完整匹配仍不等于手语含义正确，语言验收独立于程序检查。`npm run verify:release` 串行运行标准验证及六轮浏览器回归，记录源码/构建指纹；人工验收和发布始终需要单独批准。详见[第六阶段验收流程](phase6-acceptance.md)。

### 运行时转换

1. `SubtitleCapturer` 或 ASR 产生文本。
2. `normalizeText()` 统一标点和空白，`Intl.Segmenter` 进行分词。英文转为小写，但保留否定缩写中的单引号，避免把 `can't` 当作 `can`。
3. `translateText()` 从左到右按完整分词执行最长别名匹配，再跳过独立虚词、尝试已收录单字回退；不会先删除词语内部的虚词字符，也不会从未知英文单词内部截取短别名。
4. 每个命中词条提供 `humanoid-local-v1` 动作片段，句内多个词按原顺序连接。
5. `MotionPlayer` 对实时输入有界排队，使用四元数球面插值在帧间过渡；手动预览使用立即替换播放。
6. `HumanoidRig` 把标准动作映射到 Godette 模型，并以模型 REST A-Pose 为基准应用旋转增量。

`translateText()` 返回 `matches`、`unmatched`、`skipped`、`truncated` 和 `remainingText`，分别说明已匹配词、未知词、跳过的虚词、是否达到单段词条上限及尚未处理的文本。默认单段最多播放 12 个命中词条。运行时通过 `[SB] Translation coverage:` 日志输出命中、未知及截断信息。

完全未知的文本在数据 API 中仍返回中性帧以兼容旧调用方；浮窗运行时检查 `matches`，无命中时不启动动作、不打断当前播放。分词匹配不等于 CSL 语义翻译，现有词条及句意仍需人工验收。

## 输入与播放生命周期

- 普通字幕与 ASR 调用 `MotionPlayer.enqueue()`，按输入段播放，最多缓存 2 段待播动作；等待超过 6000 毫秒的待播段会丢弃，容量溢出时丢弃最旧待播段。当前段与待播段按规范化文本去重。
- 手动文字预览调用 `play()`，清除原队列并立即播放。`stop()` 清除队列、计时器和插值帧，可同时恢复 REST。
- 视频 `seeking` / `emptied` 触发 `PLAYBACK_RESET`，同时清除字幕去重状态，允许跳转后相同字幕重新处理。不会撤销已提交的 ASR 分片，严格的音视频时间戳对齐不属于本轮实现。
- Content Script 使用浮窗代次和 iframe 身份隔离异步加载。关闭旧浮窗后，其迟到的加载回调不能初始化新浮窗。
- 关闭浮窗或停止翻译先使内容侧失效并清理播放，再向 Service Worker 发送 `ASR_STOP_TAB`，只停止消息发送标签页所属的音频会话。
- 音频启动使用显式 `audioSessionStart`。普通 `audioTranscript` 必须同时匹配活动状态和会话 ID，不能自动重开已关闭的浮窗。
- Service Worker 和 Offscreen Document 都检查会话身份与代次，避免旧启动、状态查询、采集回调或转写结果覆盖新会话。Worker 唤醒后可从 Offscreen 状态恢复当前会话信息。

上述排队策略优先限制延迟，不保证每段字幕、每个已识别词都会播放，也不进行字幕和音频输入的语义合并。

## 关键目录

```text
signbridge/
├── src/
│   ├── asr/                  # ASR 配置、PCM、Whisper 和云端客户端
│   ├── avatar/               # 词典、动作、Humanoid rig 和 Three.js 运行时
│   ├── background/           # Service Worker
│   ├── content/              # 浮窗注入与页面消息桥
│   ├── offscreen/            # 标签页音频处理
│   ├── options/              # ASR 设置页面
│   ├── popup/                # 扩展控制面板
│   ├── tools/                # 录制器逻辑，共用运行时 rig/player
│   └── utils/                # 配置与字幕捕获
├── tools/                    # 工具页面 HTML、姿势编辑器入口
├── tests/                    # Node.js 自动测试
└── scripts/build.mjs         # 构建脚本
```

## 动作空间

动作数据使用标准 Humanoid 名称，例如：

```text
rightShoulder → rightUpperArm → rightLowerArm → rightHand
leftShoulder  → leftUpperArm  → leftLowerArm  → leftHand
```

每根手指映射 Metacarpal、Proximal、Intermediate、Distal 中可用的骨骼段。浮窗运行时通过 `src/avatar/humanoid-rig.js` 的 profile 适配当前模型实际节点名。更换模型时应新增 profile，不应批量改写词典动作。

运行时、编辑器和录制器的动作帧均保存相对于 REST 姿势的本地旋转增量，单位为弧度，不是 glTF 节点的绝对角度。录制器的骨骼滑块显示绝对本地旋转，但捕获时由 `rig.capturePose()` 转成 REST 增量。原有手工预设与骨骼标定数值保持不变。

## 共享动作资产与验收

- `motion-asset.js` 定义 `signbridge-motion` v1：稳定 ID、名称、匹配文字、标签、`humanoid-local-v1` 空间、弧度单位、骨骼/REST 绑定及 `{ value, duration }` 帧序列。旧度数文件只能通过显式转换入口进入，不猜测单位，不执行导入的代码。
- `motion-library.js` 以每个动作一个键存入 `chrome.storage.local`；保存一律撤销旧确认。工具页通过 Web Locks 串行化写入，避免跨页面确认覆盖刚保存的草稿。确认内容使用键排序后的完整 JSON 比较，避免存储重排键顺序导致误判。
- `motion-library-ui.js` 在两个工具页提供相同的保存、载入、预览、启用、停用、导入与下载入口。仅有预览后人工确认的条目可以进入翻译；导入文件不能携带可继承的启用资格。
- 浮窗监听动作库变更，仅将有效、已确认、没有别名冲突的条目加入匹配器。内置词条不可被自定义别名覆盖；别名冲突检查与翻译使用同一分词规则。损坏或模型不兼容的记录被跳过，不自动删除。
- 有效播放目录变化时取消旧播放及待播队列，下一次输入使用新目录；保存不参与翻译的草稿不打断正常播放。
- 工具预览与浮窗共用 `createMotionPlayer()`，避免录制器和运行时各自解释插值、单位和关键帧。

绑定校验比较 profile、标准骨骼对应节点、父节点、REST 旋转及局部位置/缩放；它不是整个 GLB、蒙皮权重或材质文件的加密指纹，更不是手语语言正确性认证。更换骨架或 REST 后不能绕过校验强行导入，仍需重新适配和人工验收。

详细操作、限制和复测方法见[第二阶段动作库文档](phase2-motion-library.md)。

### 动作包备份与安全导入

`motion-pack.js` 在统一动作资产外增加 `signbridge-motion-pack` v1 容器；复用相同模型/REST 校验，不再次变换角度。`motion-pack-ui.js` 在共享动作库内提供折叠式入口，不修改工具的姿势控制、当前编辑内容或播放引擎。

导出只读取已保存的动作；存在损坏或模型不兼容的记录时拒绝导出，避免无提示遗漏。`wasEnabled` 只是来源提示，不附带审核资格。候选文件只留在当前页面内存，未确认前不写入动作库。

导入先检查全包格式、模型、容量、重复 ID、已有 ID 和别名。已有相同 ID、相同规范化内容的动作跳过；同 ID 不同内容阻止整包写入。跨页面使用与保存/启用相同的 Web Lock，并在锁内重新检查全部动作记录快照；预检已过期或缺少锁支持时拒绝写入。新条目通过一次 `storage.local.set()` 批量写为草稿，既有条目及确认记录不重写。这减少逐条导入产生的中间状态，但不将浏览器存储宣称为通用事务数据库。

导入不会使草稿计入翻译或覆盖统计，仍需逐条预览和确认。别名冲突只提示，可以先保存为待整理素材；不能绕过既有启用检查。文件不会自动上传，下载 URL 和存储监听在工具销毁时清理。详见[第四阶段流程、限制与复测](phase4-motion-packs.md)。

## 动作可视化验收

`src/tools/motion-review.js` 组合只读目录、批量操作和本地报告；`review-stage.js` 加载真实 GLB，复用 `createHumanoidRig()`、`createMotionPlayer()` 和 `disposeModel()`，用固定相机生成最多 12 行的正面/右侧/左侧关键帧图。只在完整回放期间维持动画循环，空闲不持续渲染。

`src/avatar/motion-review.js` 负责动作校验、确定性采样、SHA-256 指纹和像素差异计算。内置目录按 SIGNS 去重；兼容自定义动作（包括草稿）来自共享动作库。验收入口不调用保存动作或启用翻译的方法，不改变 REST 或运行时姿态。

`review-store.js` 将 PNG 与指纹存入独立 IndexedDB，限定 100 条/64 MiB；更新在同一事务内检查上次读取的令牌，防止两个页面相互覆盖。动作库变更取消工作并清空结果；写入前重读自定义动作内容，加载、播放和存储事务支持取消，离页清理渲染器和监听。模型/渲染环境或动作哈希变化时拒绝直接算同条件差异，保留旧基准供人工复核。

基准、共享动作资产和语言审核是三件不同的事：保存图片不让草稿进入翻译，动作包也不包含图片。截图检查不覆盖所有过渡、穿模或手语含义。操作与边界见[第五阶段文档](phase5-motion-review.md)。

## ASR 数据边界

- 本地 Whisper：模型文件从 Hugging Face 或镜像下载，推理在扩展 offscreen document 中完成，音频不上传到 ASR 服务。
- 云端 ASR：音频分片会发送到用户配置的 OpenAI-compatible 端点。
- API Key：仅存储在 `chrome.storage.local`，不通过 Chrome Sync 同步。
- 输入音频：来自当前标签页的 `tabCapture`，不是系统麦克风。

## 资源生命周期

- Three.js 几何体、材质和纹理在 iframe 销毁时调用 `dispose()`。
- 动画循环在页面退出时使用 `cancelAnimationFrame()` 停止。
- Offscreen document 按需创建，可保留以复用已加载的本地模型；停止会话不等于关闭整个 document。
- 停止音频会话会释放媒体流、录制器、计时器和 AudioContext，并取消正在进行的云端转写请求。本地推理无法立即中断时，完成后的旧会话结果会被丢弃。
- 本地推理与云端转写使用单一处理队列；处理期间只保留最新待处理音频分片，避免无限积压。这也意味着高负载时可能丢失未处理分片。

## 当前边界

SignBridge 当前不执行完整自然语言到 CSL 语法的自动重排，也不会从任意视频直接生成未经审核的骨骼动作。推荐的发展顺序是：扩大标准动作资产、增加动作回归、完善模型重定向，再加入句法和非手控特征模型。
