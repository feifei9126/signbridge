/**
 * AR 模式深度自适应定位
 * 根据场景深度自动调整虚拟人位置和缩放
 */

import {
  loadDepthModel,
  estimateDepth,
  getDepthAtCenter,
  disposeDepthModel,
} from "./depth-estimation.js";

let depthEstimationEnabled = false;
let depthUpdateInterval = null;

/**
 * 启用深度自适应定位
 * @param {Object} arScene - AR 场景对象
 * @param {Object} options - 配置选项
 * @param {number} options.updateFrequency - 更新频率（毫秒），默认 500ms
 * @param {number} options.minScale - 最小缩放，默认 0.8
 * @param {number} options.maxScale - 最大缩放，默认 2.0
 * @param {number} options.minZ - 最近距离，默认 -1
 * @param {number} options.maxZ - 最远距离，默认 2
 */
export async function enableDepthAdaptive(arScene, options = {}) {
  const {
    updateFrequency = 500,
    minScale = 0.8,
    maxScale = 2.0,
    minZ = -1,
    maxZ = 2,
  } = options;

  if (depthEstimationEnabled) {
    console.warn("[AR Depth] 深度估计已启用");
    return;
  }

  try {
    // 1. 加载深度模型
    console.log("[AR Depth] 正在加载深度估计模型...");
    await loadDepthModel();

    // 2. 启动定期更新
    depthUpdateInterval = setInterval(async () => {
      try {
        const { video, modelRoot } = arScene;

        if (!video || video.readyState < 2) {
          return; // 视频未就绪
        }

        // 估计深度
        const depthMap = await estimateDepth(video, {
          targetWidth: 256,
          targetHeight: 256,
        });

        // 获取中心深度值 (0-1，越接近 1 越远)
        const centerDepth = await getDepthAtCenter(depthMap);

        // 释放深度图张量
        depthMap.dispose();

        // 根据深度调整虚拟人位置和缩放
        // 深度越远，虚拟人越小且越靠后
        const scale = minScale + (maxScale - minScale) * (1 - centerDepth);
        const zPos = minZ + (maxZ - minZ) * centerDepth;

        modelRoot.scale.setScalar(scale);
        modelRoot.position.z = zPos;

        console.log("[AR Depth] 深度调整:", {
          depth: centerDepth.toFixed(3),
          scale: scale.toFixed(2),
          z: zPos.toFixed(2),
        });
      } catch (error) {
        console.error("[AR Depth] 深度估计失败:", error);
      }
    }, updateFrequency);

    depthEstimationEnabled = true;
    console.log("[AR Depth] 深度自适应定位已启用");
  } catch (error) {
    console.error("[AR Depth] 深度模型加载失败:", error);
    throw error;
  }
}

/**
 * 禁用深度自适应定位
 */
export function disableDepthAdaptive() {
  if (depthUpdateInterval) {
    clearInterval(depthUpdateInterval);
    depthUpdateInterval = null;
  }

  depthEstimationEnabled = false;
  console.log("[AR Depth] 深度自适应定位已禁用");
}

/**
 * 卸载深度估计资源
 */
export function cleanupDepthEstimation() {
  disableDepthAdaptive();
  disposeDepthModel();
  console.log("[AR Depth] 深度估计资源已清理");
}

/**
 * 获取深度估计状态
 * @returns {boolean}
 */
export function isDepthAdaptiveEnabled() {
  return depthEstimationEnabled;
}
