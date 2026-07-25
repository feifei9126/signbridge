// BUILD: 1784252939651
/**
 * SignBridge v17 — Multi-site + structured gestures + eased blending
 * Godette模型: 227骨骼, 正确骨骼名映射
 */
import * as THREE from "./three.module.js";
import { GLTFLoader } from "./jsm/loaders/GLTFLoader.js";
import { translateText } from "./sign-language-data.js";

// Godette骨骼映射 — 使用GLB中的实际骨骼名称
const BONE_SHORT = {
  Root_225: "root",
  Body_220: "body",
  Hip_218: "hip",
  Spine_1_199: "spine",
  Spine_2_198: "chest",
  Ribcage_197: "upperChest",
  Neck_1_132: "neck",
  Neck_2_131: "neck2",
  Neck_3_130: "neck3",
  Head_129: "head",
  ClavicR_192: "rShoulder",
  Arm_Upper_1R_187: "rUpperArm",
  Arm_Lower_1R_185: "rForearm",
  HandR_184: "rHand",
  ClavicL_162: "lShoulder",
  Arm_Upper_1L_157: "lUpperArm",
  Arm_Lower_1L_155: "lForearm",
  HandL_154: "lHand",
  ThumbR_178: "rthumb",
  Finger_1R002_165: "rindex",
  Finger_2R002_168: "rmiddle",
  Finger_3R002_171: "rring",
  Finger_4R002_174: "rpinky",
  ThumbL_148: "lthumb",
  Finger_1L002_135: "lindex",
  Finger_2L002_138: "lmiddle",
  Finger_3L002_141: "lring",
  Finger_4L002_144: "lpinky",
  Jaw_4: "jaw",
  Eyelid_Control_UpperL_14: "lUpperEyelid",
  Eyelid_Control_UpperR_15: "rUpperEyelid",
  Eyelid_Control_LowerL_16: "lLowerEyelid",
  Eyelid_Control_LowerR_17: "rLowerEyelid",
};

let renderer,
  scene,
  camera,
  skinnedMesh = null;
let boneMap = {},
  REST = {};
let modelRoot = null;
let baseModelY = -0.65;
let modelReady = false;
let modelLoading = false;
let renderFrameId = null;
let breathingFrameId = null;
let blinkTimerId = null;
let subtitleTimerId = null;

// ===== 动画系统 =====
let animQueue = [],
  animTimer = null,
  animPlaying = false,
  blendFrameId = null;

function playFrames(frames) {
  if (!frames || frames.length === 0) return;
  stopAnimation();
  animQueue = [...frames];
  animPlaying = true;
  playNextFrame();
}

function playNextFrame() {
  if (!animPlaying || animQueue.length === 0) {
    animPlaying = false;
    cancelAnimationFrame(blendFrameId);
    return;
  }
  const frame = animQueue.shift();
  const durMs = (frame.duration || 0.8) * 1000;
  const blendMs = Math.min(durMs * 0.35, 150);

  // Save current absolute rotations as 'from'
  const from = {};
  for (const k in boneMap) {
    const b = boneMap[k];
    from[k] = { x: b.rotation.x, y: b.rotation.y, z: b.rotation.z };
  }

  const startTime = performance.now();
  function step() {
    let t = Math.min((performance.now() - startTime) / blendMs, 1.0);
    t = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; // ease in-out
    lerpPose(from, frame.value, t);
    if (t < 1.0) blendFrameId = requestAnimationFrame(step);
  }
  step();

  animTimer = setTimeout(playNextFrame, durMs);
}

function stopAnimation() {
  animPlaying = false;
  if (animTimer) {
    clearTimeout(animTimer);
    animTimer = null;
  }
  if (blendFrameId) cancelAnimationFrame(blendFrameId);
  blendFrameId = null;
  animQueue = [];
}

// ===== Pose 应用 =====
function lerpPose(fromPose, toPose, t) {
  if (!skinnedMesh?.skeleton) return;
  for (const k in boneMap) {
    const r = REST[k];
    if (!r) continue;
    const target = toPose[k]
      ? {
          x: r.x + (toPose[k].x || 0),
          y: r.y + (toPose[k].y || 0),
          z: r.z + (toPose[k].z || 0),
        }
      : { x: r.x, y: r.y, z: r.z };
    const current = fromPose[k] || { x: r.x, y: r.y, z: r.z };
    boneMap[k].rotation.set(
      current.x + (target.x - current.x) * t,
      current.y + (target.y - current.y) * t,
      current.z + (target.z - current.z) * t,
    );
  }
  skinnedMesh.skeleton.update();
}

// ===== 字幕 → 手语 =====

function textToAnimation(text) {
  if (!text) return false;
  const result = translateText(text);
  if (!result) return false;
  if (!result.frames) return false;
  playFrames(result.frames);
  return true;
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
      skinnedMesh = null;
      boneMap = {};
      gltf.scene.traverse((child) => {
        if (child.isSkinnedMesh && !skinnedMesh) {
          skinnedMesh = child;
          console.log(
            "[SB] Mesh:",
            child.name,
            "tri:",
            child.geometry?.index?.count || "?",
          );
        }
      });
      if (skinnedMesh?.skeleton) {
        const bones = skinnedMesh.skeleton.bones;
        console.log("[SB] Bones:", bones.length);
        for (const b of bones) {
          if (BONE_SHORT[b.name]) boneMap[BONE_SHORT[b.name]] = b;
        }
        const crit = [
          "rUpperArm",
          "rForearm",
          "rHand",
          "lUpperArm",
          "lForearm",
          "lHand",
          "head",
        ];
        const st = {};
        for (const k of crit) st[k] = !!boneMap[k];
        console.log("[SB] BoneMap status:", JSON.stringify(st));
        if (!boneMap.rUpperArm) {
          console.warn(
            "[SB] rUpperArm not mapped! Available:",
            bones
              .map((b) => b.name)
              .filter(
                (n) =>
                  n.includes("Arm") ||
                  n.includes("Hand") ||
                  n.includes("Clavic"),
              ),
          );
        }
      }
      scene.add(gltf.scene);
      gltf.scene.scale.set(0.984, 0.984, 0.984);
      gltf.scene.position.y = -0.65;
      modelRoot = gltf.scene;
      baseModelY = gltf.scene.position.y;

      // Save REST rotations (A-Pose)
      REST = {};
      for (const k in boneMap) {
        REST[k] = {
          x: boneMap[k].rotation.x,
          y: boneMap[k].rotation.y,
          z: boneMap[k].rotation.z,
        };
      }
      console.log("[SB] REST saved for", Object.keys(REST).length, "bones");

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
      if (!modelReady || animPlaying) {
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
    if (modelRoot && !animPlaying) {
      modelRoot.position.y = baseModelY + breathe;
    }
    breathingFrameId = requestAnimationFrame(breathingLoop);
  }
  breathingFrameId = requestAnimationFrame(breathingLoop);
}

function blink() {
  const le = boneMap.lUpperEyelid,
    re = boneMap.rUpperEyelid;
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
      if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
      return;
    }
    if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
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
  stopAnimation();
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
  modelRoot = null;
  renderer?.dispose();
}
console.log("[SB] v17 — multi-site + structured gestures + eased blending");
