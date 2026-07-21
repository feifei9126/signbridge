# SignBridge —— 实时手语翻译浏览器扩展

> 让每一个视频都能被"听"见。

SignBridge 是一个开源的 Chrome 浏览器扩展，将网页视频的字幕（或语音）实时转换为 **3D 虚拟人手语动画**。通过一个可拖拽的叠加窗口，在任何视频网站的角落展示虚拟人翻译，让听障用户也能无障碍观看视频内容。
<img width="1920" height="1080" alt="ScreenShot_2026-07-21_102027_932_副本_副本_副本" src="https://github.com/user-attachments/assets/cfc48e89-a50f-4bc3-a0bc-2224611cf351" />
<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License MIT">
  <img src="https://img.shields.io/badge/platform-Chrome%20Extension-brightgreen" alt="Platform">
  <img src="https://img.shields.io/badge/language-JavaScript-yellow" alt="JavaScript">
  <img src="https://img.shields.io/badge/sign%20language-CSL-red" alt="CSL">
</p>

---

## 🎯 项目目标

1. **实时字幕→手语翻译**：从 B站、YouTube、Netflix 等主流视频平台捕获字幕，毫秒级转换为手语
2. **低门槛接入**：用户安装扩展即可使用，无需任何配置
3. **开源可扩展**：任何人都可以添加新的手语词汇、支持新的手语类型（ASL、LIBRAS 等）
4. **开发者友好**：内置姿势编辑器和录制工具，可视化创建手语动画
5. **多模态输入**：同时支持字幕识别和语音识别两种输入方式

---

## 🏗 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      Chrome 扩展环境                       │
│                                                           │
│  ┌──────────────┐     chrome.runtime     ┌─────────────┐ │
│  │  popup/       │◀─────────────────────▶│ background/  │ │
│  │  控制面板      │     sendMessage       │  Service     │ │
│  │  - 开关翻译    │                       │  Worker      │ │
│  │  - 大小/位置   │                       │  - 状态同步   │ │
│  │  - 麦克风      │                       │  - 配置存储   │ │
│  │  - 工具入口    │                       └─────────────┘ │
│  └──────────────┘                                         │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │                   网页 (B站/YouTube/Netflix...)     │    │
│  │                                                    │    │
│  │  ┌─────────────────┐     window.postMessage       │    │
│  │  │  page-agent.js   │──────────────────────┐       │    │
│  │  │  (注入到页面)     │                      │       │    │
│  │  │  ├ SubtitleCapturer 字幕捕获             │       │    │
│  │  │  └ SpeechRecognizer 语音识别             │       │    │
│  │  └─────────────────┘                      │       │    │
│  │                                            ▼       │    │
│  │  ┌──────────────────────────────────────────────┐  │    │
│  │  │  injector.js (Content Script)                 │  │    │
│  │  │  ├ 创建叠加层 div                              │  │    │
│  │  │  ├ 注入 iframe (3D渲染)                       │  │    │
│  │  │  ├ 拖拽 + 关闭按钮                             │  │    │
│  │  │  ├ 站点检测 (仅视频网站显示)                    │  │    │
│  │  │  └ 消息路由 (popup ↔ page-agent ↔ iframe)     │  │    │
│  │  └──────────────────────┬───────────────────────┘  │    │
│  │                         │ postMessage              │    │
│  │  ┌──────────────────────▼───────────────────────┐  │    │
│  │  │  iframe-bundle.js (3D 渲染引擎)               │  │    │
│  │  │  ├ Three.js 场景 + Godette 3D模型              │  │    │
│  │  │  ├ 手语词典 (sign-language-data.js)            │  │    │
│  │  │  ├ 骨骼动画 (slerp 插值 + REST delta)          │  │    │
│  │  │  ├ 面部表情 (眨眼 + 呼吸微动)                   │  │    │
│  │  │  ├ 鼠标交互 (拖拽旋转 + 滚轮缩放 + 平移)        │  │    │
│  │  │  └ 调试面板 (🔧 实时骨骼调参)                   │  │    │
│  │  └──────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 翻译流水线

```
字幕/语音文本
  │
  ├─ normalizeText()          → 规范化：去标点、统一空格
  ├─ stripFunctionWords()     → 虚词过滤：跳过 的/了/吗/呢 等 19 个虚词
  │
  ▼
findGesture()
  ├─ 第1层：SIGNS 词典查找    → 52 条结构化词条（gloss + meta + tags）
  │   最长优先匹配              → 支持中英文多别名
  ├─ 第2层：CHARS 单字查找     → 16 个高频单字手势
  └─ 第3层：默认空闲姿态       → A-Pose 归位
  │
  ▼
playFrames(frames)
  ├─ frm(gesture(arm, shape), duration)
  │   ├ gesture()  → 构建骨骼姿态 {rUpperArm: deg(35,50,-15), ...}
  │   ├ handShape() → 7 种手形原子 (fist/flat/point/thumbUp/peace/ok/relax)
  │   └ arm shorthand → 6 种手臂参数简写 (A/AH/AL/AT/AW/AWL)
  │
  ▼
lerpPose(from, to, t)
  ├─ 缓入缓出 (ease-in-out)       → 帧间平滑过渡
  └─ REST delta 叠加              → A-Pose 基准 + 手势增量
  │
  ▼
skinnedMesh.skeleton.update()
  └─ Three.js 骨骼变形 → 60fps 渲染
```

### 数据流

```
弹窗(popup) ──chrome.tabs.sendMessage──▶ 注入器(injector)
                                              │
                     ┌────────────────────────┼────────────────────────┐
                     │                        │                        │
                     ▼                        ▼                        ▼
              page-agent                 iframe-bundle           浮窗拖动/关闭
              (页面上下文)                (3D渲染上下文)
                     │                        │
                     │ postMessage            │
                     └────────────────────────┘
```

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/yourname/signbridge.git
cd signbridge
npm install
npm run build
```

然后：
1. 打开 Chrome → `chrome://extensions`
2. 开启右上角"开发者模式"
3. 点击"加载已解压的扩展程序"
4. 选择项目中的 `dist/` 目录
5. 完成！

### 使用

1. 打开 B站 / YouTube 任意视频
2. 右下角出现蓝色 3D 虚拟人浮窗
3. **确保视频已开启 CC 字幕**
4. 虚拟人自动翻译字幕内容
5. 如需语音识别：点击扩展图标 → 点击 🎤 麦克风按钮授权

### 鼠标交互

| 操作 | 效果 |
|---|---|
| 🖱 拖拽左右 | 旋转虚拟人 |
| 🖱 拖拽上下 | 上下平移虚拟人 |
| 🖱 滚轮 | 缩放虚拟人 |
| 🖱 拖拽标题栏 | 移动浮窗位置 |
| 🖱 点击 × | 关闭浮窗 |

### 弹窗控制

| 按钮 | 功能 |
|---|---|
| ▶/⏹ 开始/停止 | 开关翻译 |
| 🎤 麦克风 | 开关语音识别（需授权） |
| 🎬 姿势编辑器 | 打开骨骼调试+姿势导出页面 |
| 🎥 录制工具 | 打开关键帧录制+动画导出页面 |
| 📖 帮助文档 | 打开内置帮助页面 |
| 大小滑块 | 调整浮窗尺寸（实时生效） |
| 位置选择 | 浮窗置于屏幕四角 |

---

## 🦴 骨骼系统详解

### 模型

使用 **Godette** 自由 3D 模型（227 根骨骼，76K 三角面，1.6MB glTF 格式）。
模型处于 **A-Pose**（手臂微张 45°），所有手势以 REST（A-Pose）为基准叠加旋转增量。

### 骨骼映射 (33 根关键骨骼)

```
手臂链:  rShoulder → rUpperArm → rForearm → rHand
         lShoulder → lUpperArm → lForearm → lHand

手指:   rthumb  rindex  rmiddle  rring  rpinky  (每指控制末端指节,
        lthumb  lindex  lmiddle  lring  lpinky    手指弯曲用 X 轴旋转)

头部:   head, jaw

面部:   lUpperEyelid  rUpperEyelid  lLowerEyelid  rLowerEyelid

躯干:   root → spine → chest → upperChest → neck → neck2 → neck3 → head
        hip (骨盆)
```

### 旋转轴约定

| 轴 | 手臂 | 手指 |
|---|---|---|
| **X** | 前后摆动（正=后/上抬） | **弯曲**（负=握拳方向） |
| **Y** | 外展（正=外推远离身体） | 左右摆动 |
| **Z** | 扭转（正=内旋） | 扭转 |

---

## 🎨 手形原子 (Handshape Primitives)

7 种可复用手形，通过 `handShape(name)` 调用。所有手形以 REST A-Pose 为基准。

| 手形 | 键名 | 骨骼角度 | 用途示例 |
|---|---|---|---|
| ✊ 握拳 | `fist` | 拇指 X-40°, 其余 X-110° | 谢谢、爱、做 |
| ✋ 平掌 | `flat` | 全部 X+30° | 欢迎、来、去、帮助 |
| ☝ 食指指 | `point` | 食指 X0°, 其余弯曲 | 我、你、他、是、不 |
| 👍 拇指竖 | `thumbUp` | 拇指 Y63° Z30°, 其余 X-110° | 好、棒、可以、有 |
| ✌ 胜利V | `peace` | 食指+中指 X0° | 数字二 |
| 👌 OK | `ok` | 拇指+食指捏合 | 可以、三 |
| 👐 放松 | `relax` | 全零 (REST) | 空闲/过渡 |

---

## 📝 手语词典结构

### 词条格式

```javascript
csl_hello: {
  id: "csl_hello",              // 唯一标识 (csl_ 前缀=中国手语)
  gloss: "你好",                 // 标准词条名
  texts: ["你好", "hello", "hi"], // 匹配文字（支持中英文，自动最长匹配）
  tags: ["greeting"],           // 分类标签 (可检索/筛选)
  frames: [                     // 动画帧序列
    frm(gesture(A, "point"), 0.6),
    frm(gesture(A, "thumbUp"), 0.7),
  ],
  meta: {                       // 手语参数元数据
    handshape: "point→thumbUp", // 手形序列
    location: "chest",          // 位置 (chest/side/forward/forehead/chin)
    movement: "none"            // 运动类型 (none/arc/wave/nod/repeat)
  }
}
```

### 手势构建 API

```javascript
// gesture(手臂参数, 右手形, 左手臂参数, 左手形)
gesture(A, "point")                       // 右臂胸前 + 食指指
gesture(A, "flat", null, null)            // 右臂胸前 + 平掌
gesture(AW, "flat", AWL, "flat")          // 双手欢迎手势
gesture([0,0,0, 40,60,-15, 25,0,0, 5,0,0], "point")  // 自定义手臂 + 食指
```

### 手臂参数简写

```javascript
// [shX,shY,shZ, uaX,uaY,uaZ, faX,faY,faZ, hX,hY,hZ]
const A   = [0,0,0, 35,50,-15, 15,0,0, 0,0,0];  // 默认胸前
const AH  = [0,0,0, 40,50,-15, 20,0,0, -90,0,0]; // 高位
const AL  = [0,0,0, 30,50,-10, 10,0,0, 0,0,0];   // 低位
const AT  = [0,0,0, 55,5,-10, 20,0,0, 0,10,10];  // 谢谢位
const AW  = [10,20,0, 35,20,0, 15,5,0, 10,0,0];  // 欢迎右手
const AWL = [10,-20,0, 35,-5,0, 15,-5,0, 10,0,0]; // 欢迎左手
```

---

## ✨ 添加新词条

### 方式1：使用简写（最快）

```javascript
// 在 src/avatar/sign-language-data.js 的 SIGNS 对象中添加
csl_mysign: {
  id: "csl_mysign",
  gloss: "新词",
  texts: ["新词", "别名"],
  tags: ["custom"],
  frames: [frm(gesture(A, "flat"), 0.7)],
  meta: { handshape: "flat", location: "chest", movement: "none" }
}
```

### 方式2：自定手臂位置

```javascript
frames: [frm(gesture([0,0,0, 40,60,-15, 25,0,0, 10,0,0], "point"), 0.7)]
//                   shX shY shZ uaX uaY uaZ faX faY faZ  hX  hY  hZ
```

### 方式3：姿势编辑器导出

1. 打开 🎬 姿势编辑器
2. 拖滑块调整骨骼角度
3. 点击"导出代码"复制 `applyDelta({...})`
4. 转换为 `frm(gesture(...))` 格式加入词典

### 方式4：录制工具导出动画序列

1. 打开 🎥 录制工具
2. "开始录制" → 手动调骨骼 → "📸 抓关键帧" (重复)
3. "预览" → "导出为代码"
4. 粘贴到 SIGNS 词典

---

## 🛠 开发

### 命令

```bash
npm run build       # 构建到 dist/
npm run dev         # 持续构建（监视模式）
npm run lint        # ESLint 检查
npx prettier --check src/  # 格式检查
npx prettier --write src/  # 自动格式化
```

### 目录结构

```
signbridge/
├── src/                        # 源代码
│   ├── avatar/
│   │   ├── iframe-bundle.js    # 3D 渲染引擎 (~800行)
│   │   ├── sign-language-data.js # 手语词典 (~900行)
│   │   ├── pose-engine.js      # 姿态工具函数
│   │   ├── page-agent.js       # 页面代理(字幕+语音)
│   │   └── avatar-frame.html   # iframe HTML
│   ├── content/
│   │   ├── injector.js         # 注入器
│   │   └── overlay.css         # 浮窗样式
│   ├── popup/
│   │   ├── popup.js            # 弹窗逻辑
│   │   ├── index.html          # 弹窗界面
│   │   └── popup.css           # 弹窗样式
│   ├── background/worker.js    # Service Worker
│   ├── utils/
│   │   ├── subtitle-capturer.js # 字幕捕获
│   │   ├── speech-recognizer.js # 语音识别
│   │   └── config.js           # 配置管理
│   └── i18n/locales.js         # 国际化
├── dist/                       # 构建输出(不提交Git)
│   └── avatar/
│       ├── model.glb           # Godette 3D 模型
│       ├── three.module.js     # Three.js
│       ├── pose-editor.html    # 姿势编辑器
│       ├── record-mode.html    # 录制工具
│       └── help.html           # 帮助页面
├── tools/                      # 开发工具
│   ├── pose-editor.html        # 姿势编辑器(工具版)
│   ├── record-mode.html        # 录制工具(工具版)
│   └── editor-full-entry.js    # 编辑器入口
├── backups/                    # 备份
│   ├── stable/                 # 稳定版本
│   └── v*/                     # 版本快照
├── scripts/build.mjs           # 构建脚本
└── README.md                   # 本文档
```

### 开发约定

- ✅ **编辑 `src/`** → 构建 → 输出到 `dist/`
- ❌ **不要直接改 `dist/`**（构建会覆盖）
- ✅ ES Module (`import`/`export`)
- ✅ `deg(x,y,z)` 函数：度→弧度
- ✅ Manifest V3，权限最小化
- ✅ 备份在 `backups/`，出问题可直接恢复

---

## 📊 技术栈

| 层 | 技术 |
|---|---|
| 3D 渲染 | Three.js (软件光栅化，无 WebGL 依赖) |
| 3D 模型 | Godette (227 骨骼, 76K 三角面, glTF) |
| 构建 | esbuild (打包) + Prettier (格式化) |
| 平台 | Chrome Extension Manifest V3 |
| 字幕捕获 | TextTrack API + MutationObserver + DOM 选择器 |
| 语音识别 | Web Speech API (SpeechRecognition) |
| 动画 | 骨骼动画 + slerp 插值 + REST delta 叠加 |

---

## 🗺 路线图

- [x] 骨骼动画 + slerp 插值过渡
- [x] 结构化手语词典 (52条)
- [x] 7 种手形原子系统
- [x] 虚词自动过滤
- [x] 面部表情 (眨眼 + 呼吸微动)
- [x] 鼠标交互相机控制
- [x] 姿势编辑器 (可视化调参)
- [x] 录制工具 (关键帧动画)
- [x] 多站点支持 (B站/YouTube/Netflix等)
- [x] 语音识别 (麦克风)
- [x] 弹窗控制面板
- [ ] glTF 动画剪辑播放
- [ ] ASL (美国手语) 支持
- [ ] 句级动画流程优化
- [ ] 更多手语词汇 (目标 200+)
- [ ] 双手手势系统

---

## ❓ 常见问题

| 问题 | 解决 |
|---|---|
| 虚拟人不加载 | 1) 重新加载扩展 2) 刷新页面 3) 看控制台 `[SB] ✅ Ready` |
| 字幕翻译不触发 | 确认视频**已开启 CC 字幕**；看控制台 `[SB] Sign match` |
| 手势不正确 | 用 🔧 调试面板调参，用 🎬 姿势编辑器导出正确值 |
| 手掌方向反 | 调整 `gesture()` 中 `hZ` 值 (第12个参数) |
| 手臂穿透身体 | 增大 `uaY` (第5个参数) 到 50+ 外推手臂 |
| 页面卡顿 | Godette 模型较重(76K三角面)，可考虑后续换轻量模型 |
| 麦克风不工作 | 点击弹窗 🎤 按钮授权；需 HTTPS 或 localhost |

---

## 📄 License

MIT © SignBridge Contributors

---

<p align="center">
  <sub>让每一个视频都能被"听"见 👐</sub>
</p>
