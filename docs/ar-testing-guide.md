# SignBridge AR 模式 - 快速测试指南

## 当前开发状态

✅ **Phase 1 完成** - 基础 AR 框架
✅ **Phase 2 完成** - 深度估计集成
✅ **Phase 3 准备就绪** - 等待性能测试

## 已实现功能

### 1. 核心模块
- ✅ 摄像头流捕获 (`camera-capture.js`)
- ✅ AR 场景管理 (`ar-scene.js`)
- ✅ AR 控制器 (`ar-controller.js`)
- ✅ 深度估计 (`depth-estimation.js`)
- ✅ 深度自适应定位 (`depth-adaptive.js`)
- ✅ AR 入口页面 (`ar-frame.html`)

### 2. UI 集成
- ✅ Popup 添加 AR 开关
- ✅ AR 状态显示
- ✅ 事件处理完整

### 3. 权限配置
- ✅ manifest.json camera 权限
- ✅ web_accessible_resources 配置
- ✅ TensorFlow.js 依赖

## 快速测试步骤

### 步骤 1: 安装依赖并构建

```bash
cd /Users/mac/Documents/ChatGPT/signbridge/signbridge
npm install
npm run build
```

### 步骤 2: 加载扩展

1. 打开 Chrome 浏览器
2. 访问 `chrome://extensions/`
3. 开启"开发者模式"
4. 点击"加载已解压的扩展程序"
5. 选择 `signbridge` 目录

### 步骤 3: 测试 AR 模式

1. 点击扩展图标打开 popup
2. 找到 "🎥 AR 模式" 按钮
3. 点击启动 AR 模式
4. 允许摄像头权限
5. 应该看到：
   - 摄像头视频流作为背景
   - 3D 虚拟人叠加在画面右下角
   - 点击"测试手语: 你好"按钮播放动作

### 步骤 4: 测试深度自适应（可选）

修改 `ar-frame.html` 启动参数：
```javascript
await startARMode(container, { enableDepth: true });
```

重新构建后测试：
- 虚拟人应该根据场景深度自动调整位置和大小
- 控制台会显示深度调整日志

## 预期效果

### 基础模式（默认）
- 摄像头实时视频作为背景
- 虚拟人固定在右下角
- 可以播放手语动作

### 深度自适应模式
- 虚拟人根据场景深度自动调整
- 深度越远，虚拟人越小且越靠后
- 每 0.5 秒更新一次位置

## 性能考虑

### 当前配置
- 深度估计：256x256 分辨率
- 更新频率：500ms (每秒 2 次)
- 模型：MiDaS Small (~11MB)

### 如果性能不佳
1. 降低深度估计频率到 1000ms
2. 暂时禁用深度估计
3. 降低视频分辨率

## 故障排查

### AR 模式无法启动
- 检查摄像头权限是否允许
- 查看控制台错误信息
- 确认构建无错误

### 虚拟人不显示
- 检查 model.glb 文件是否存在
- 查看控制台是否有加载错误
- 确认 Three.js 正确加载

### 深度估计失败
- TensorFlow.js 可能需要较长加载时间
- 检查网络连接（模型从 TFHub 加载）
- 尝试禁用深度估计继续测试基础功能

## 下一步开发

如果基础测试通过：

1. **性能优化**
   - 本地托管深度估计模型
   - 可配置的性能模式
   - 降低分辨率选项

2. **用户体验**
   - 拖拽调整虚拟人位置
   - 缩放控制
   - 位置记忆

3. **功能增强**
   - 从 popup 发送文字到 AR 模式
   - 录制 AR 视频
   - 多场景预设

## 技术架构

```
SignBridge Extension
├─ manifest.json (camera 可选权限)
├─ popup/ (AR 开关 UI)
└─ src/ar/
   ├─ camera-capture.js (getUserMedia)
   ├─ ar-scene.js (Three.js 场景)
   ├─ ar-controller.js (状态管理)
   ├─ depth-estimation.js (TensorFlow.js)
   ├─ depth-adaptive.js (自动定位)
   └─ ar-frame.html (入口页面)
```

## 可复用 SignBridge 组件

- ✅ Three.js 渲染管线
- ✅ Humanoid-rig 骨骼系统
- ✅ Motion-player 动作播放器
- ✅ Godette 模型和动作库
- ✅ Chrome Extension 架构

## 许可与贡献

继承 SignBridge 的 MIT 许可证
