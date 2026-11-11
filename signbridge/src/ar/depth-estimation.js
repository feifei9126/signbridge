/**
 * 深度估计模块 - 使用 MiDaS Small
 * 轻量级深度估计，用于调整虚拟人在场景中的位置
 */

import * as tf from "@tensorflow/tfjs";
import "@tensorflow/tfjs-backend-webgl";

let model = null;
let modelLoading = false;

/**
 * 加载 MiDaS Small 深度估计模型
 * @returns {Promise<void>}
 */
export async function loadDepthModel() {
  if (model) {
    return model;
  }

  if (modelLoading) {
    // 等待正在加载的模型
    return new Promise((resolve) => {
      const checkInterval = setInterval(() => {
        if (model) {
          clearInterval(checkInterval);
          resolve(model);
        }
      }, 100);
    });
  }

  try {
    modelLoading = true;
    console.log("[Depth Estimation] 开始加载 MiDaS Small 模型...");

    // 设置 WebGL 后端
    await tf.setBackend("webgl");
    await tf.ready();

    // 从 TensorFlow Hub 加载 MiDaS Small 模型
    // 注意：实际部署时需要本地托管模型文件
    const modelUrl = "https://tfhub.dev/intel/midas/v2_1_small/1";

    model = await tf.loadGraphModel(modelUrl, { fromTFHub: true });

    console.log("[Depth Estimation] MiDaS Small 模型加载成功");
    return model;
  } catch (error) {
    console.error("[Depth Estimation] 模型加载失败:", error);
    model = null;
    throw new Error(`深度估计模型加载失败: ${error.message}`);
  } finally {
    modelLoading = false;
  }
}

/**
 * 估计视频帧的深度图
 * @param {HTMLVideoElement} videoElement - 视频元素
 * @param {Object} options - 选项
 * @param {number} options.targetWidth - 目标宽度（默认 256）
 * @param {number} options.targetHeight - 目标高度（默认 256）
 * @returns {Promise<tf.Tensor>} 归一化的深度图张量
 */
export async function estimateDepth(videoElement, options = {}) {
  const { targetWidth = 256, targetHeight = 256 } = options;

  if (!model) {
    throw new Error("深度估计模型未加载，请先调用 loadDepthModel()");
  }

  if (!videoElement || videoElement.videoWidth === 0) {
    throw new Error("视频元素无效或未加载");
  }

  return tf.tidy(() => {
    // 1. 从视频元素创建张量
    const inputTensor = tf.browser.fromPixels(videoElement);

    // 2. 调整大小到模型输入尺寸
    const resized = tf.image.resizeBilinear(inputTensor, [
      targetHeight,
      targetWidth,
    ]);

    // 3. 归一化到 [0, 1]
    const normalized = resized.div(255.0);

    // 4. 添加 batch 维度 [1, H, W, 3]
    const batched = normalized.expandDims(0);

    // 5. 执行推理
    const depthMap = model.predict(batched);

    // 6. 移除 batch 维度并归一化深度值
    const squeezed = depthMap.squeeze();
    const min = squeezed.min();
    const max = squeezed.max();
    const normalizedDepth = squeezed.sub(min).div(max.sub(min));

    return normalizedDepth;
  });
}

/**
 * 从深度图提取中心点深度值
 * @param {tf.Tensor} depthMap - 深度图张量
 * @returns {Promise<number>} 中心点深度值 (0-1)
 */
export async function getDepthAtCenter(depthMap) {
  const shape = depthMap.shape;
  const centerY = Math.floor(shape[0] / 2);
  const centerX = Math.floor(shape[1] / 2);

  // 提取中心区域 (5x5) 的平均深度
  const centerRegion = depthMap.slice([centerY - 2, centerX - 2], [5, 5]);

  const meanDepth = await centerRegion.mean().data();
  centerRegion.dispose();

  return meanDepth[0];
}

/**
 * 从深度图提取指定区域的平均深度
 * @param {tf.Tensor} depthMap - 深度图张量
 * @param {Object} region - 区域 { x, y, width, height }
 * @returns {Promise<number>} 区域平均深度值 (0-1)
 */
export async function getDepthAtRegion(depthMap, region) {
  const { x, y, width, height } = region;

  const slice = depthMap.slice([y, x], [height, width]);
  const meanDepth = await slice.mean().data();
  slice.dispose();

  return meanDepth[0];
}

/**
 * 将深度图转换为可视化图像（用于调试）
 * @param {tf.Tensor} depthMap - 深度图张量
 * @returns {Promise<ImageData>} 可视化深度图
 */
export async function visualizeDepthMap(depthMap) {
  // 将深度值映射到灰度图
  const grayscale = tf.tidy(() => {
    const scaled = depthMap.mul(255);
    const stacked = tf.stack([scaled, scaled, scaled], 2);
    return stacked;
  });

  const imageData = await tf.browser.toPixels(grayscale);
  grayscale.dispose();

  return imageData;
}

/**
 * 卸载深度估计模型，释放资源
 */
export function disposeDepthModel() {
  if (model) {
    model.dispose();
    model = null;
    console.log("[Depth Estimation] 模型已卸载");
  }
}

/**
 * 获取模型加载状态
 * @returns {boolean}
 */
export function isDepthModelLoaded() {
  return model !== null;
}
