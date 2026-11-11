/**
 * AR 模式控制器
 * 管理 AR 模式的启动、停止、深度估计和状态
 */

import {
  requestCameraPermission,
  initCameraStream,
  stopCameraStream,
  isCameraAvailable,
} from "./camera-capture.js";
import { createARScene, startARLoop, translateAndPlay } from "./ar-scene.js";
import {
  enableDepthAdaptive,
  disableDepthAdaptive,
  isDepthAdaptiveEnabled,
} from "./depth-adaptive.js";

let arState = {
  enabled: false,
  scene: null,
  stopLoop: null,
  stream: null,
};

/**
 * 启动 AR 模式
 * @param {HTMLElement} container - 渲染容器
 * @param {Object} options - 配置选项
 * @param {boolean} options.enableDepth - 是否启用深度估计，默认 false
 * @returns {Promise<boolean>} 是否成功启动
 */
export async function startARMode(container, options = {}) {
  const { enableDepth = false } = options;

  if (arState.enabled) {
    console.warn("[AR Controller] AR 模式已经启动");
    return true;
  }

  try {
    // 1. 检查摄像头可用性
    const available = await isCameraAvailable();
    if (!available) {
      throw new Error("未检测到摄像头设备");
    }

    // 2. 请求摄像头权限
    const hasPermission = await requestCameraPermission();
    if (!hasPermission) {
      throw new Error("摄像头权限被拒绝");
    }

    // 3. 初始化摄像头流
    const stream = await initCameraStream();

    // 4. 创建 AR 场景
    const scene = await createARScene(container, stream);

    // 5. 启动渲染循环
    const stopLoop = startARLoop(scene);

    // 6. （可选）启用深度自适应
    if (enableDepth) {
      try {
        await enableDepthAdaptive(scene, {
          updateFrequency: 500, // 0.5 秒更新一次
          minScale: 0.8,
          maxScale: 2.0,
          minZ: -1,
          maxZ: 2,
        });
        console.log("[AR Controller] 深度自适应已启用");
      } catch (depthError) {
        console.warn(
          "[AR Controller] 深度估计启动失败，继续使用默认定位:",
          depthError,
        );
      }
    }

    // 7. 保存状态
    arState = {
      enabled: true,
      scene,
      stopLoop,
      stream,
    };

    console.log("[AR Controller] AR 模式已启动", { enableDepth });
    return true;
  } catch (error) {
    console.error("[AR Controller] AR 模式启动失败:", error);

    // 清理资源
    if (arState.stream) {
      stopCameraStream(arState.stream);
    }
    if (arState.scene) {
      arState.scene.dispose();
    }

    arState = { enabled: false, scene: null, stopLoop: null, stream: null };
    throw error;
  }
}

/**
 * 停止 AR 模式
 */
export function stopARMode() {
  if (!arState.enabled) {
    console.warn("[AR Controller] AR 模式未启动");
    return;
  }

  try {
    // 停止深度估计
    if (isDepthAdaptiveEnabled()) {
      disableDepthAdaptive();
    }

    // 停止渲染循环
    if (arState.stopLoop) {
      arState.stopLoop();
    }

    // 停止摄像头
    if (arState.stream) {
      stopCameraStream(arState.stream);
    }

    // 销毁场景
    if (arState.scene) {
      arState.scene.dispose();
    }

    console.log("[AR Controller] AR 模式已停止");
  } finally {
    arState = { enabled: false, scene: null, stopLoop: null, stream: null };
  }
}

/**
 * 获取 AR 状态
 * @returns {boolean}
 */
export function isAREnabled() {
  return arState.enabled;
}

/**
 * 在 AR 模式下播放手语
 * @param {string} text - 要翻译的文字
 */
export async function playSignLanguageInAR(text) {
  if (!arState.enabled || !arState.scene) {
    throw new Error("AR 模式未启动");
  }

  return await translateAndPlay(arState.scene, text);
}

/**
 * 调整虚拟人位置
 * @param {number} x
 * @param {number} y
 * @param {number} z
 */
export function setAvatarPosition(x, y, z) {
  if (arState.scene) {
    arState.scene.setAvatarPosition(x, y, z);
  }
}

/**
 * 调整虚拟人缩放
 * @param {number} scale
 */
export function setAvatarScale(scale) {
  if (arState.scene) {
    arState.scene.setAvatarScale(scale);
  }
}

/**
 * 获取当前 AR 场景对象（用于高级操作）
 * @returns {Object|null}
 */
export function getARScene() {
  return arState.scene;
}
