/**
 * 摄像头视频流捕获模块
 * 负责获取用户摄像头并创建 Three.js 视频纹理
 */

import * as THREE from "three";

/**
 * 初始化摄像头流
 * @returns {Promise<MediaStream>}
 */
export async function initCameraStream() {
  try {
    const constraints = {
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        frameRate: { ideal: 30 },
        facingMode: "user", // 前置摄像头
      },
    };

    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    console.log(
      "[AR Camera] 摄像头已启动",
      stream.getVideoTracks()[0].getSettings(),
    );
    return stream;
  } catch (error) {
    console.error("[AR Camera] 摄像头获取失败:", error);
    throw new Error(`摄像头访问失败: ${error.message}`);
  }
}

/**
 * 检查摄像头权限状态
 * camera 不是有效的 Chrome 扩展权限，无法用 chrome.permissions.request 申请；
 * 实际授权发生在 getUserMedia（iframe 需带 allow="camera"）。
 * @returns {Promise<boolean>}
 */
export async function requestCameraPermission() {
  try {
    if (!navigator.permissions?.query) return true;
    const status = await navigator.permissions.query({ name: "camera" });
    if (status.state === "denied") return false;
    return true;
  } catch {
    // 未实现 camera 查询的浏览器交给 getUserMedia 判定
    return true;
  }
}

/**
 * 创建 Three.js 视频纹理
 * @param {MediaStream} stream
 * @returns {{ video: HTMLVideoElement, texture: THREE.VideoTexture }}
 */
export function createVideoTexture(stream) {
  const video = document.createElement("video");
  video.srcObject = stream;
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;

  // 等待视频元数据加载
  return new Promise((resolve, reject) => {
    video.onloadedmetadata = () => {
      video
        .play()
        .then(() => {
          const texture = new THREE.VideoTexture(video);
          texture.minFilter = THREE.LinearFilter;
          texture.magFilter = THREE.LinearFilter;

          console.log("[AR Camera] 视频纹理已创建", {
            width: video.videoWidth,
            height: video.videoHeight,
          });

          resolve({ video, texture });
        })
        .catch(reject);
    };

    video.onerror = reject;
  });
}

/**
 * 停止摄像头流
 * @param {MediaStream} stream
 */
export function stopCameraStream(stream) {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    console.log("[AR Camera] 摄像头已停止");
  }
}

/**
 * 获取摄像头可用状态
 * @returns {Promise<boolean>}
 */
export async function isCameraAvailable() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.some((device) => device.kind === "videoinput");
  } catch (error) {
    console.error("[AR Camera] 设备枚举失败:", error);
    return false;
  }
}
