// BUILD: 1784252939651
/**
 * SignBridge v17 — Multi-site + structured gestures + eased blending
 * Godette模型: 227骨骼, 正确骨骼名映射
 */
import * as THREE from "./three.module.js";
import { GLTFLoader } from "./jsm/loaders/GLTFLoader.js";
import { createHumanoidRig } from "./humanoid-rig.js";
import { createMotionPlayer } from "./motion-player.js";
import { translateText } from "./sign-language-data.js";

let renderer, scene, camera;
let rig = null;
let motionPlayer = null;
let modelRoot = null;
let baseModelY = -0.65;
let modelReady = false;
let modelLoading = false;
let renderFrameId = null;
let breathingFrameId = null;
let blinkTimerId = null;
let subtitleTimerId = null;

// ===== 字幕 → 手语 =====

function textToAnimation(text) {
  if (!text) return false;
  const result = translateText(text);
  if (!result) return false;
  if (!result.frames) return false;
  return motionPlayer?.play(result) || false;
}

// ===== 初始化 =====
function init(modelUrl) {
  if (modelReady) {
    notify("READY", {});
    return;
  }
  if (modelLoading) return;
  modelLoading = true;
  console.log("[SB] Loading:", modelUrl);
  const container = document.getElementById("c");
  if (!container) return;

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xdce8f5);
  scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const dl = new THREE.DirectionalLight(0xffffff, 1.0);
  dl.position.set(2, 5, 3);
  scene.add(dl);
  const dl2 = new THREE.DirectionalLight(0xffffff, 0.6);
  dl2.position.set(-1, 2, -1);
  scene.add(dl2);

  camera = new THREE.PerspectiveCamera(
    45,
    container.clientWidth / container.clientHeight,
    0.1,
    100,
  );
  camera.position.set(0, 0.65, 1.5);
  camera.lookAt(0, 0.5, 0);

  const loader = new GLTFLoader();
  loader.load(
    modelUrl,
    (gltf) => {
      console.log("[SB] Model loaded");
      let primaryMesh = null;
      gltf.scene.traverse((child) => {
        if (child.isSkinnedMesh && !primaryMesh) {
          primaryMesh = child;
          console.log(
            "[SB] Mesh:",
            child.name,
            "tri:",
            child.geometry?.index?.count || "?",
          );
        }
      });
      const boneCount = primaryMesh?.skeleton?.bones.length || 0;
      console.log("[SB] Bones:", boneCount);
      rig = createHumanoidRig(gltf.scene);
      motionPlayer = createMotionPlayer(rig);
      console.log(
        "[SB] Humanoid profile:",
        rig.profile.id,
        `${Object.keys(rig.bones).length} mapped`,
      );
      if (!rig.isSigningReady) {
        console.error("[SB] Missing signing bones:", rig.missing);
        modelLoading = false;
        notify("ERROR", {
          message: `Missing signing bones: ${rig.missing.join(", ")}`,
        });
        return;
      }
      scene.add(gltf.scene);
      gltf.scene.scale.set(0.984, 0.984, 0.984);
      gltf.scene.position.y = -0.65;
      modelRoot = gltf.scene;
      baseModelY = gltf.scene.position.y;
      console.log("[SB] REST saved for", Object.keys(rig.rest).length, "bones");

      modelReady = true;
      modelLoading = false;
      startIdleAnimations();
      setupMouseControls();
      notify("READY", {});
      console.log("[SB] ✅ Ready");
    },
    undefined,
    (err) => {
      modelLoading = false;
      console.error("[SB] Load error:", err);
      notify("ERROR", { message: err.message || String(err) });
    },
  );

  if (!renderFrameId) animate();
}

function animate() {
  renderFrameId = requestAnimationFrame(animate);
  try {
    if (scene) scene.updateMatrixWorld(true);
    if (renderer && scene && camera) renderer.render(scene, camera);
  } catch {}
}

function notify(type, data) {
  try {
    parent.postMessage(
      { source: "signbridge-iframe", type, ...(data || {}) },
      "*",
    );
  } catch {}
}

// ===== 面部表情动画 =====
function startIdleAnimations() {
  // Blink timer: random 2-5 second intervals
  function scheduleBlink() {
    const delay = 2000 + Math.random() * 3000;
    blinkTimerId = setTimeout(() => {
      if (!modelReady || motionPlayer?.isPlaying) {
        scheduleBlink();
        return;
      }
      blink();
      scheduleBlink();
    }, delay);
  }
  scheduleBlink();

  // Subtle breathing/idle motion
  let breathTime = 0;
  baseModelY = modelRoot?.position.y ?? -0.65;
  function breathingLoop() {
    if (!modelReady || !modelRoot) {
      breathingFrameId = requestAnimationFrame(breathingLoop);
      return;
    }
    breathTime += 0.016;
    const breathe = Math.sin(breathTime * 0.8) * 0.003;
    if (modelRoot && !motionPlayer?.isPlaying) {
      modelRoot.position.y = baseModelY + breathe;
    }
    breathingFrameId = requestAnimationFrame(breathingLoop);
  }
  breathingFrameId = requestAnimationFrame(breathingLoop);
}

function blink() {
  const le = rig?.bones.leftUpperEyelid,
    re = rig?.bones.rightUpperEyelid;
  if (!le || !re) return;
  const startY = le.rotation.x;
  const dur = 150;
  let start;

  function step(ts) {
    if (!start) start = ts;
    const t = (ts - start) / dur;
    if (t < 0.4) {
      const v = t / 0.4;
      le.rotation.x = startY + v * 0.3;
      re.rotation.x = startY + v * 0.3;
    } else if (t < 0.6) {
      le.rotation.x = startY + 0.3;
      re.rotation.x = startY + 0.3;
    } else if (t < 1.0) {
      const v = 1 - (t - 0.6) / 0.4;
      le.rotation.x = startY + v * 0.3;
      re.rotation.x = startY + v * 0.3;
    } else {
      le.rotation.x = startY;
      re.rotation.x = startY;
      rig?.update();
      return;
    }
    rig?.update();
    requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
// ===== 鼠标交互控制 =====
function setupMouseControls() {
  const canvas = renderer.domElement;
  if (!canvas) return;
  let isDragging = false,
    lastX = 0,
    lastY = 0,
    shiftKey = false;

  canvas.style.cursor = "grab";

  canvas.addEventListener("pointerdown", (e) => {
    isDragging = true;
    shiftKey = e.shiftKey;
    lastX = e.clientX;
    lastY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
    canvas.style.cursor = shiftKey ? "grabbing" : "grabbing";
    e.preventDefault();
    e.stopPropagation();
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!isDragging || !modelRoot) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    if (!shiftKey) modelRoot.rotation.y += dx * 0.01;
    modelRoot.position.y -= dy * 0.008;
    baseModelY = modelRoot.position.y;
    lastX = e.clientX;
    lastY = e.clientY;
  });

  canvas.addEventListener("pointerup", () => {
    isDragging = false;
    canvas.style.cursor = "grab";
  });

  canvas.addEventListener("pointerleave", () => {
    if (!isDragging) canvas.style.cursor = "grab";
  });

  // Scroll wheel to zoom
  canvas.addEventListener(
    "wheel",
    (e) => {
      if (!modelRoot) return;
      e.preventDefault();
      const s = modelRoot.scale.x;
      const ns = Math.max(
        0.2,
        Math.min(2.5, s * (e.deltaY > 0 ? 0.985 : 1.015)),
      );
      modelRoot.scale.set(ns, ns, ns);
    },
    { passive: false },
  );

  // Key tracking for shift
  window.addEventListener("keydown", (e) => {
    if (e.key === "Shift") shiftKey = true;
  });
  window.addEventListener("keyup", (e) => {
    if (e.key === "Shift") shiftKey = false;
  });
}

// ===== 消息处理 =====
notify("LOADED", {});
window.addEventListener("message", (ev) => {
  if (ev.source !== parent || !ev.data || ev.data.source !== "signbridge-page")
    return;
  if (ev.data.type !== "SUBTITLE_TEXT") {
    console.log("[SB] iframe rx:", ev.data.type);
  }
  switch (ev.data.type) {
    case "INIT":
      init(ev.data.modelUrl);
      break;
    case "SUBTITLE_TEXT":
      if (modelReady && ev.data.text) {
        clearTimeout(subtitleTimerId);
        subtitleTimerId = setTimeout(() => textToAnimation(ev.data.text), 250);
      }
      break;
    case "RESIZE":
      if (renderer) {
        renderer.setSize(ev.data.width, ev.data.height);
        camera.aspect = ev.data.width / ev.data.height;
        camera.updateProjectionMatrix();
      }
      break;
  }
});
window.addEventListener("pagehide", disposeAvatar, { once: true });

function disposeAvatar() {
  motionPlayer?.stop();
  if (renderFrameId) cancelAnimationFrame(renderFrameId);
  if (breathingFrameId) cancelAnimationFrame(breathingFrameId);
  if (blinkTimerId) clearTimeout(blinkTimerId);
  clearTimeout(subtitleTimerId);
  modelRoot?.traverse((object) => {
    object.geometry?.dispose?.();
    const materials = Array.isArray(object.material)
      ? object.material
      : [object.material];
    for (const material of materials) {
      if (!material) continue;
      for (const value of Object.values(material)) {
        if (value?.isTexture) value.dispose();
      }
      material.dispose?.();
    }
  });
  motionPlayer = null;
  rig = null;
  modelRoot = null;
  renderer?.dispose();
}
console.log("[SB] v17 — multi-site + structured gestures + eased blending");
