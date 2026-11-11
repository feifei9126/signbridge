/**
 * AR 场景管理器
 * 整合摄像头视频流、3D 虚拟人渲染和深度估计
 */

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createMotionPlayer } from "../avatar/motion-player.js";
import { createVideoTexture } from "./camera-capture.js";

/**
 * 创建 AR 场景
 * @param {HTMLElement} container - 容器元素
 * @param {MediaStream} cameraStream - 摄像头流
 * @returns {Promise<Object>} AR 场景对象
 */
export async function createARScene(container, cameraStream) {
  console.log("[AR Scene] 开始创建 AR 场景");

  // 1. 创建渲染器
  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: true,
    powerPreference: "high-performance",
  });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // 限制像素比，优化性能
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);

  // 2. 创建场景
  const scene = new THREE.Scene();

  // 3. 摄像头视频背景
  const { video, texture } = await createVideoTexture(cameraStream);

  // 创建全屏背景平面
  const aspectRatio = video.videoWidth / video.videoHeight;
  const bgGeometry = new THREE.PlaneGeometry(2, 2 / aspectRatio);
  const bgMaterial = new THREE.MeshBasicMaterial({
    map: texture,
    depthTest: false,
    depthWrite: false,
  });
  const bgMesh = new THREE.Mesh(bgGeometry, bgMaterial);
  bgMesh.position.z = -5; // 放在最后面
  bgMesh.renderOrder = -999; // 最先渲染
  scene.add(bgMesh);

  // 4. 创建相机
  const camera = new THREE.PerspectiveCamera(
    50,
    container.clientWidth / container.clientHeight,
    0.1,
    1000,
  );
  camera.position.set(0, 1.5, 3);
  camera.lookAt(0, 1, 0);

  // 5. 加载虚拟人模型（复用 SignBridge 的 Godette 模型）
  const gltfUrl = chrome.runtime.getURL("avatar/model.glb");
  const loader = new GLTFLoader();

  const gltf = await new Promise((resolve, reject) => {
    loader.load(gltfUrl, resolve, undefined, reject);
  });

  const modelRoot = gltf.scene;

  // 默认位置：屏幕右下角
  modelRoot.position.set(1.5, -0.5, 0);
  modelRoot.scale.setScalar(1.2);
  scene.add(modelRoot);

  console.log("[AR Scene] 虚拟人模型已加载");

  // 6. 创建 HumanoidRig（复用 SignBridge）
  const rig = createHumanoidRig(modelRoot);

  // 7. 创建动作播放器（复用 SignBridge）
  const motionPlayer = createMotionPlayer(rig);

  // 8. 光照
  const directionalLight = new THREE.DirectionalLight(0xffffff, 1.0);
  directionalLight.position.set(5, 10, 5);
  scene.add(directionalLight);

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
  scene.add(ambientLight);

  console.log("[AR Scene] AR 场景创建完成");

  return {
    scene,
    camera,
    renderer,
    rig,
    motionPlayer,
    modelRoot,
    video,
    texture,
    bgMesh,

    // 辅助方法
    updateAspectRatio: () => {
      const newAspectRatio = container.clientWidth / container.clientHeight;
      camera.aspect = newAspectRatio;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    },

    // 调整虚拟人位置
    setAvatarPosition: (x, y, z) => {
      modelRoot.position.set(x, y, z);
    },

    // 调整虚拟人缩放
    setAvatarScale: (scale) => {
      modelRoot.scale.setScalar(scale);
    },

    // 销毁场景
    dispose: () => {
      renderer.dispose();
      texture.dispose();
      bgGeometry.dispose();
      bgMaterial.dispose();
      motionPlayer.stop({ reset: true });
    },
  };
}

/**
 * 启动 AR 渲染循环
 * @param {Object} arScene - AR 场景对象
 * @returns {Function} 停止函数
 */
export function startARLoop(arScene) {
  const { scene, camera, renderer } = arScene;

  let animationId = null;
  let isRunning = true;

  function animate() {
    if (!isRunning) return;

    animationId = requestAnimationFrame(animate);
    renderer.render(scene, camera);
  }

  animate();
  console.log("[AR Scene] 渲染循环已启动");

  // 返回停止函数
  return () => {
    isRunning = false;
    if (animationId !== null) {
      cancelAnimationFrame(animationId);
    }
    console.log("[AR Scene] 渲染循环已停止");
  };
}

/**
 * 集成手语翻译功能
 * @param {Object} arScene - AR 场景对象
 * @param {string} text - 要翻译的文字
 */
export async function translateAndPlay(arScene, text) {
  const { motionPlayer } = arScene;

  // 动态导入翻译模块
  const { translateText } = await import("../avatar/sign-language-data.js");

  const result = translateText(text);

  if (!result) {
    console.warn("[AR Scene] 空文本，跳过播放");
    return null;
  }

  console.log("[AR Scene] 翻译匹配:", {
    text,
    matchCount: result.matches.length,
    unmatched: result.unmatched,
  });

  // result.frames 已是可直接播放的 motion frame 序列（含结尾中性帧）
  motionPlayer.enqueue({ frames: result.frames, key: text });

  return result;
}
