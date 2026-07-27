# SignBridge 架构

SignBridge 将“输入获取、文本转换、动作资产、模型适配和 3D 播放”拆成独立层，避免手语数据与某一个虚拟人的原始骨骼名称绑定。

## 运行时组件

```text
popup 控制面板
  ├─ 翻译开关、手动文字、浮窗尺寸
  ├─ 本地 Whisper / 云端 ASR 设置
  └─ 姿势编辑器、录制器、帮助入口

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
  ├─ Humanoid 重定向
  └─ 动作插值与渲染
```

## 翻译流水线

1. `SubtitleCapturer` 或 ASR 产生文本。
2. `normalizeText()` 统一标点和空白，虚词过滤器跳过没有独立动作的功能词。
3. `translateText()` 从左到右执行最长词组匹配，并使用已收录单字回退。
4. 每个命中词条提供 `humanoid-local-v1` 动作片段，句内多个词按原顺序连接。
5. `MotionPlayer` 使用四元数球面插值在帧间过渡。
6. `HumanoidRig` 把标准动作映射到 Godette 模型，并以模型 REST A-Pose 为基准应用旋转增量。

未知文本返回中性帧，不用无关动作冒充翻译。

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
│   └── utils/                # 配置与字幕捕获
├── tools/                    # 姿势编辑器和录制器源码
├── tests/                    # Node.js 自动测试
└── scripts/build.mjs         # 构建脚本
```

## 动作空间

动作数据使用标准 Humanoid 名称，例如：

```text
rightShoulder → rightUpperArm → rightLowerArm → rightHand
leftShoulder  → leftUpperArm  → leftLowerArm  → leftHand
```

每根手指映射 Metacarpal、Proximal、Intermediate、Distal 中可用的骨骼段。当前模型的实际节点名只出现在 `src/avatar/humanoid-rig.js` 的 profile 中。更换模型时应新增 profile，不应批量改写词典动作。

每帧保存相对于 REST 姿势的本地旋转增量，而不是 glTF 节点的绝对角度。这个约定由浮窗、姿势编辑器和录制器共同使用。

## ASR 数据边界

- 本地 Whisper：模型文件从 Hugging Face 或镜像下载，推理在扩展 offscreen document 中完成，音频不上传到 ASR 服务。
- 云端 ASR：音频分片会发送到用户配置的 OpenAI-compatible 端点。
- API Key：仅存储在 `chrome.storage.local`，不通过 Chrome Sync 同步。
- 输入音频：来自当前标签页的 `tabCapture`，不是系统麦克风。

## 资源生命周期

- Three.js 几何体、材质和纹理在 iframe 销毁时调用 `dispose()`。
- 动画循环在页面退出时使用 `cancelAnimationFrame()` 停止。
- Offscreen document 由 Service Worker 按音频会话创建和关闭。

## 当前边界

SignBridge 当前不执行完整自然语言到 CSL 语法的自动重排，也不会从任意视频直接生成未经审核的骨骼动作。推荐的发展顺序是：扩大标准动作资产、增加动作回归、完善模型重定向，再加入句法和非手控特征模型。
