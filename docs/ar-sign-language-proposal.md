# AR 手语演示系统 - 完整技术方案

## 一、项目概述

### 1.1 目标
在 SignBridge 现有基础上，开发轻量级 AR 手语演示系统，实现摄像头视频流与 3D 虚拟人的实时融合渲染。

### 1.2 核心特性
- 摄像头实时视频流捕获
- 简单深度估计（MiDaS Small）
- 虚拟手语人物与真实场景融合
- 保持现有手语翻译能力

---

## 二、SignBridge 可复用组件分析

### 2.1 Three.js 渲染系统 ✅
**位置**: `src/avatar/iframe-bundle.js`
**能力**:
- 完整的 Three.js 场景管理
- GLTFLoader 模型加载
- 动画循环渲染
- 相机和光照系统

**复用度**: 95% - 可直接作为 AR 渲染基础

### 2.2 虚拟人系统 ✅
**位置**: `src/avatar/humanoid-rig.js`
**能力**:
- Godette 3D 模型（227 骨骼）
- 标准化的 humanoid-local-v1 动作空间
- 50+ 标准骨骼映射
- 手指精细动作支持

**复用度**: 100% - 无需修改

### 2.3 动作播放系统 ✅
**位置**: `src/avatar/motion-player.js`
**能力**:
- 四元数插值
- 动作队列管理
- 缓动函数
- 实时动作切换

**复用度**: 100% - 无需修改

### 2.4 Chrome Extension 架构 ✅
**能力**:
- Service Worker
- Content Script 注入
- iframe 隔离渲染
- chrome.storage 数据管理

**复用度**: 80% - 需添加摄像头权限

---

## 三、技术架构设计

### 3.1 系统架构图
```
┌─────────────────────────────────────────┐
│       Chrome Extension (MV3)            │
├─────────────────────────────────────────┤
│  Popup UI                               │
│  ├─ 摄像头开关                          │
│  ├─ AR 模式切换                         │
│  └─ 手语翻译控制                        │
├─────────────────────────────────────────┤
│  Content Script                         │
│  ├─ 创建 AR Canvas Overlay              │
│  ├─ 管理摄像头流                        │
│  └─ 消息路由                            │
├─────────────────────────────────────────┤
│  AR Rendering iframe                    │
│  ├─ 摄像头视频背景层                    │
│  ├─ 深度估计模型 (TensorFlow.js)       │
│  ├─ Three.js 场景                       │
│  │  ├─ 虚拟人模型                       │
│  │  └─ 动作播放器                       │
│  └─ 深度混合渲染                        │
└─────────────────────────────────────────┘
```

### 3.2 渲染流程
```
摄像头输入 → 深度估计 → 虚拟人定位 → 合成渲染
   ↓            ↓           ↓           ↓
MediaStream  MiDaS      Three.js    Canvas2D
  (640×480)  (11MB)    (Godette)   (Output)
```

---

## 四、核心技术实现

### 4.1 摄像头集成

#### 4.1.1 权限配置
**文件**: `signbridge/manifest.json`
```json
{
  "permissions": [
    "storage",
    "activeTab",
    "tabCapture"
  ],
  "host_permissions": [
    "<all_urls>"
  ],
  "optional_permissions": [
    "camera"  // 新增
  ]
}
```

#### 4.1.2 视频流捕获
**新建文件**: `src/ar/camera-capture.js`
```javascript
export async function initCameraStream() {
  const constraints = {
    video: {
      width: { ideal: 640 },
      height: { ideal: 480 },
      frameRate: { ideal: 30 }
    }
  };
  
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  return stream;
}

export function createVideoTexture(renderer, stream) {
  const video = document.createElement('video');
  video.srcObject = stream;
  video.play();
  
  const texture = new THREE.VideoTexture(video);
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  
  return { video, texture };
}
```

### 4.2 深度估计

#### 4.2.1 模型选择
| 模型 | 大小 | 速度 | 精度 | 推荐 |
|------|------|------|------|------|
| MiDaS Small | 11MB | 30fps+ | 中 | ✅ 推荐 |
| MiDaS v2.1 | 100MB | 15fps | 高 | ❌ 太大 |
| ZoeDepth | 350MB | 10fps | 极高 | ❌ 过重 |

#### 4.2.2 实现代码
**新建文件**: `src/ar/depth-estimation.js`
```javascript
import * as tf from '@tensorflow/tfjs';

let model = null;

export async function loadDepthModel() {
  if (model) return model;
  
  // 从 CDN 加载预训练的 MiDaS Small
  const modelUrl = 'https://tfhub.dev/intel/midas/v2_1_small/1';
  model = await tf.loadGraphModel(modelUrl, { fromTFHub: true });
  
  return model;
}

export async function estimateDepth(videoElement) {
  const inputTensor = tf.browser.fromPixels(videoElement)
    .resizeBilinear([256, 256])
    .expandDims(0)
    .div(255.0);
  
  const depthMap = await model.predict(inputTensor);
  
  // 归一化到 0-1
  const normalized = depthMap.sub(depthMap.min())
    .div(depthMap.max().sub(depthMap.min()));
  
  inputTensor.dispose();
  
  return normalized;
}
```

### 4.3 AR 场景渲染

#### 4.3.1 场景初始化
**新建文件**: `src/ar/ar-scene.js`
```javascript
import * as THREE from 'three';
import { createHumanoidRig } from '../avatar/humanoid-rig.js';
import { createMotionPlayer } from '../avatar/motion-player.js';
import { createVideoTexture } from './camera-capture.js';
import { loadDepthModel, estimateDepth } from './depth-estimation.js';

export async function createARScene(container, cameraStream) {
  // 1. 创建渲染器
  const renderer = new THREE.WebGLRenderer({ 
    alpha: true,
    antialias: true 
  });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);
  
  // 2. 创建场景
  const scene = new THREE.Scene();
  
  // 3. 摄像头背景
  const { video, texture } = createVideoTexture(renderer, cameraStream);
  const bgGeometry = new THREE.PlaneGeometry(2, 2);
  const bgMaterial = new THREE.MeshBasicMaterial({ 
    map: texture,
    depthTest: false,
    depthWrite: false
  });
  const bgMesh = new THREE.Mesh(bgGeometry, bgMaterial);
  bgMesh.renderOrder = -1;
  scene.add(bgMesh);
  
  // 4. 创建相机（固定视角）
  const camera = new THREE.PerspectiveCamera(
    50, 
    container.clientWidth / container.clientHeight,
    0.1,
    1000
  );
  camera.position.set(0, 1.5, 3);
  camera.lookAt(0, 1, 0);
  
  // 5. 加载虚拟人模型（复用 SignBridge）
  const gltfUrl = chrome.runtime.getURL('assets/model.glb');
  const gltf = await loadGLTF(gltfUrl);
  const modelRoot = gltf.scene;
  
  // 默认位置：屏幕右下角
  modelRoot.position.set(1.5, -0.5, 0);
  modelRoot.scale.setScalar(1.2);
  scene.add(modelRoot);
  
  // 6. 创建 HumanoidRig（复用）
  const rig = createHumanoidRig(modelRoot);
  
  // 7. 创建动作播放器（复用）
  const motionPlayer = createMotionPlayer(rig);
  
  // 8. 加载深度估计模型
  await loadDepthModel();
  
  // 9. 光照
  const light = new THREE.DirectionalLight(0xffffff, 1.0);
  light.position.set(5, 10, 5);
  scene.add(light);
  scene.add(new THREE.AmbientLight(0xffffff, 0.5));
  
  return {
    scene,
    camera,
    renderer,
    rig,
    motionPlayer,
    modelRoot,
    video
  };
}
```

#### 4.3.2 渲染循环
```javascript
export function startARLoop(arScene) {
  const { scene, camera, renderer, video, modelRoot } = arScene;
  
  let depthUpdateCounter = 0;
  const DEPTH_UPDATE_INTERVAL = 10; // 每10帧更新一次深度
  
  function animate() {
    requestAnimationFrame(animate);
    
    // 每10帧估计一次深度（降低性能开销）
    if (depthUpdateCounter++ % DEPTH_UPDATE_INTERVAL === 0) {
      estimateDepth(video).then(depthMap => {
        // 简单策略：根据中心深度调整虚拟人大小
        const centerDepth = getDepthAtCenter(depthMap);
        const scale = 1.0 + (1.0 - centerDepth) * 0.5;
        modelRoot.scale.setScalar(scale);
        
        depthMap.dispose();
      });
    }
    
    renderer.render(scene, camera);
  }
  
  animate();
}

function getDepthAtCenter(depthMap) {
  // 提取深度图中心点的值
  const centerX = Math.floor(depthMap.shape[2] / 2);
  const centerY = Math.floor(depthMap.shape[1] / 2);
  const value = depthMap.dataSync()[centerY * depthMap.shape[2] + centerX];
  return value;
}
```

### 4.4 集成手语翻译

**修改文件**: `src/ar/ar-scene.js`
```javascript
// 添加到 createARScene 返回对象
return {
  // ... 现有属性
  
  // 新增：手语翻译接口
  translateAndPlay: async (text) => {
    // 复用 SignBridge 的翻译逻辑
    const { translateText } = await import('../avatar/sign-language-data.js');
    const result = translateText(text);
    
    if (result.matches.length > 0) {
      const motions = result.matches.map(m => m.motion);
      motionPlayer.enqueue({
        frames: motions.flat(),
        key: text
      });
    }
  }
};
```

---

## 五、竞品分析

### 5.1 国际主流产品

#### 5.1.1 Simulon（参考视频）
**定位**: 现实感知 AR 内容创作工具

**核心技术**:
- 深度估计：基于 DepthAnything v2（神经网络）
- 平面检测：RANSAC + 持久化追踪
- 手势识别：MediaPipe Hands
- 渲染引擎：Unity/Unreal

**优势**:
- ✅ 精确的遮挡关系
- ✅ 实时物理碰撞
- ✅ 多人协作

**劣势**:
- ❌ 需要专业硬件（高端 GPU）
- ❌ 本地应用，无法网页运行
- ❌ 不开源

#### 5.1.2 Niantic Lightship ARDK
**定位**: 移动端 AR 开发框架

**核心技术**:
- 深度估计：Lightship Depth API
- 平面检测：ARCore/ARKit
- 场景理解：语义分割

**优势**:
- ✅ 移动端优化好
- ✅ 大规模验证（Pokemon GO）

**劣势**:
- ❌ 移动端专用，不支持网页
- ❌ 商业化收费

#### 5.1.3 8th Wall
**定位**: WebAR 平台

**核心技术**:
- 无需深度估计（简单叠加）
- 平面追踪：WebXR Device API
- 图像识别：自研

**优势**:
- ✅ 纯网页技术
- ✅ 跨平台

**劣势**:
- ❌ 无真实遮挡关系
- ❌ 按月收费（$99+）

### 5.2 手语相关产品

#### 5.2.1 SignAll（美国）
**定位**: 手语翻译硬件

**技术方案**:
- 摄像头手势识别 → 文字
- 文字 → 2D 手语视频播放

**劣势**:
- ❌ 2D 视频，非 3D 实时渲染
- ❌ 硬件设备，价格高

#### 5.2.2 Signapse（已倒闭）
**定位**: AI 手语翻译

**技术方案**:
- GAN 生成手语视频
- 无 3D 模型

**失败原因**:
- 精度不够
- 商业化困难

### 5.3 差异化优势分析

| 产品 | 3D 实时 | WebAR | 手语专业 | 轻量级 | 开源 |
|------|---------|-------|----------|--------|------|
| **我们的方案** | ✅ | ✅ | ✅ | ✅ | ✅ |
| Simulon | ✅ | ❌ | ❌ | ❌ | ❌ |
| 8th Wall | ✅ | ✅ | ❌ | ✅ | ❌ |
| SignAll | ❌ | ❌ | ✅ | ❌ | ❌ |
| SignBridge (现有) | ✅ | ❌ | ✅ | ✅ | ✅ |

**核心竞争力**:
1. **全球首个** WebAR + 3D 手语的开源方案
2. **浏览器内运行**，无需安装应用
3. **轻量级模型**（<20MB），普通笔记本可运行
4. **真实场景融合**，比单纯浮窗更有沉浸感

---

## 六、实现路线图

### Phase 1: 基础框架（Week 1）
- [x] 分析 SignBridge 可复用组件
- [ ] 添加摄像头权限
- [ ] 实现视频流捕获
- [ ] 创建 AR 场景基础架构
- [ ] 虚拟人叠加到视频流

**验证目标**: 虚拟人显示在摄像头画面上

### Phase 2: 深度估计（Week 2）
- [ ] 集成 TensorFlow.js
- [ ] 加载 MiDaS Small 模型
- [ ] 实现深度估计推理
- [ ] 根据深度调整虚拟人位置/大小

**验证目标**: 虚拟人会随场景深度变化

### Phase 3: 优化与集成（Week 3）
- [ ] 性能优化（降帧、缓存）
- [ ] 集成手语翻译功能
- [ ] UI 交互（摄像头开关、位置调整）
- [ ] 边界情况处理

**验证目标**: 流畅运行，手语翻译正常

---

## 七、技术风险与应对

### 7.1 性能风险
**风险**: 浏览器内 ML 推理可能卡顿

**应对**:
1. 降低深度估计频率（10帧/次 → 20帧/次）
2. 降低输入分辨率（640×480 → 320×240）
3. 使用 WebGL 加速
4. 提供"性能模式"开关

### 7.2 兼容性风险
**风险**: 旧设备/浏览器不支持

**应对**:
1. 检测 WebGL 支持
2. 降级方案：关闭深度估计，固定位置显示
3. 最低要求：Chrome 90+

### 7.3 用户体验风险
**风险**: 虚拟人"飘"的感觉

**应对**:
1. 添加简单阴影
2. 使用缓动动画过渡位置变化
3. 让用户手动调整初始位置

---

## 八、依赖项清单

### 新增 npm 依赖
```json
{
  "dependencies": {
    "three": "^0.170.0",  // 已有
    "@tensorflow/tfjs": "^4.20.0",  // 新增
    "@tensorflow/tfjs-backend-webgl": "^4.20.0"  // 新增
  }
}
```

### CDN 资源
- MiDaS Small 模型：~11MB
- TensorFlow.js Runtime：~1.2MB

**总增量**: ~12MB

---

## 九、开发时间估算

| 阶段 | 工作量 | 风险系数 | 预计时间 |
|------|--------|----------|----------|
| Phase 1 基础框架 | 中 | 低 | 5 天 |
| Phase 2 深度估计 | 高 | 中 | 7 天 |
| Phase 3 优化集成 | 中 | 低 | 5 天 |
| **总计** | | | **17 天** |

**建议迭代**:
- Week 1: 完成 Phase 1，内部测试
- Week 2: 完成 Phase 2，性能测试
- Week 3: 完成 Phase 3，用户测试

---

## 十、下一步行动

### 立即可做
1. ✅ 创建技术方案文档（本文档）
2. [ ] 搭建开发分支 `feature/ar-mode`
3. [ ] 添加摄像头权限到 manifest.json
4. [ ] 创建 `src/ar/` 目录结构

### 需要决策
1. **是否保留原有浮窗模式？**
   - 建议：保留，让用户切换
   
2. **虚拟人初始位置？**
   - 建议：屏幕右下角，用户可拖拽

3. **是否开源此 AR 功能？**
   - 建议：是，符合 SignBridge 开源定位

---

**文档版本**: v1.0  
**创建时间**: 2026-11-09  
**作者**: Claude & User  
**项目**: SignBridge AR Extension
