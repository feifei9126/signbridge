// BUILD: 1784252939651
/**
 * SignBridge v17 — Multi-site + structured gestures + slerp
 * Godette模型: 227骨骼, 正确骨骼名映射
 */
import * as THREE from "./three.module.js";
import { GLTFLoader } from "./jsm/loaders/GLTFLoader.js";
import { deg, frm } from "./pose-engine.js";
import {
  GESTURES,
  CHARS,
  findGesture,
  normalizeText,
} from "./sign-language-data.js";

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
let modelReady = false;

// ===== 动画系统 =====
let animQueue = [],
  animTimer = null,
  animPlaying = false,
  _slerpRaf = null;

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
    cancelAnimationFrame(_slerpRaf);
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
    if (t < 1.0) _slerpRaf = requestAnimationFrame(step);
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
  cancelAnimationFrame(_slerpRaf);
}

// ===== Pose 应用 =====
function lerpPose(fromPose, toPose, t) {
  if (Object.keys(toPose || {}).length > 0) {
    console.log(
      "[SB-DIAG] First gesture target pose keys:",
      Object.keys(toPose || {}).slice(0, 10),
    );
    if (toPose && toPose.rUpperArm)
      console.log(
        "[SB-DIAG] rUpperArm delta:",
        JSON.stringify(toPose.rUpperArm),
      );
    if (toPose && toPose.rForearm)
      console.log("[SB-DIAG] rForearm delta:", JSON.stringify(toPose.rForearm));
    if (toPose && toPose.rHand)
      console.log("[SB-DIAG] rHand delta:", JSON.stringify(toPose.rHand));
    console.log("[SB-DIAG] REST rUpperArm:", JSON.stringify(REST.rUpperArm));
    console.log("[SB-DIAG] REST rForearm:", JSON.stringify(REST.rForearm));
  }
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

// ===== glTF Animation Clip Support =====
window._sbClips = {};
window._sbLoadClip = function (name, url) {
  if (window._sbClips[name]) return Promise.resolve(window._sbClips[name]);
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader();
    loader.load(
      url,
      (gltf) => {
        if (gltf.animations && gltf.animations.length > 0) {
          window._sbClips[name] = gltf.animations[0];
          console.log("[SB] Clip loaded:", name);
          resolve(gltf.animations[0]);
        } else {
          reject(new Error("No animations in " + url));
        }
      },
      undefined,
      reject,
    );
  });
};
window._sbMixer = null;
window._sbCurrentClip = null;

function loadClip(name, url) {
  if (window._sbClips[name]) return Promise.resolve(window._sbClips[name]);
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader();
    loader.load(
      url,
      (gltf) => {
        if (gltf.animations && gltf.animations.length > 0) {
          window._sbClips[name] = gltf.animations[0];
          console.log("[SB] Clip loaded:", name);
          resolve(gltf.animations[0]);
        } else {
          reject(new Error("No animations in " + url));
        }
      },
      undefined,
      reject,
    );
  });
}

function playClip(name) {
  const clip = window._sbClips[name];
  if (!clip || !skinnedMesh) return false;
  stopAnimation();
  if (window._sbMixer) window._sbMixer.stopAllAction();
  window._sbMixer = new THREE.AnimationMixer(skinnedMesh);
  window._sbCurrentClip = window._sbMixer.clipAction(clip);
  window._sbCurrentClip.setLoop(THREE.LoopOnce);
  window._sbCurrentClip.clampWhenFinished = true;
  window._sbCurrentClip.play();
  console.log("[SB] Playing clip:", name);
  return true;
}

function textToAnimation(text) {
  // DIAGNOSTIC: log the gesture data being used
  console.log(
    "[SB-DIAG] textToAnimation called with:",
    JSON.stringify(text).substring(0, 80),
  );
  console.log("[SB-DIAG] GESTURES count:", Object.keys(GESTURES).length);
  console.log("[SB-DIAG] CHARS count:", Object.keys(CHARS).length);
  if (!text) return false;
  const result = findGesture(text);
  if (!result) return false;
  if (result.clip) {
    playClip(result.clip);
    return true;
  }
  if (!result.frames) return false;
  playFrames(result.frames);
  const out = document.getElementById("dbg-out");
  if (out && result.meta) {
    out.textContent = (result.meta.gloss || "") + " | " + text;
  }
  return true;
}

// ===== 初始化 =====
function init(modelUrl) {
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
      window._sbModel = gltf.scene;

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
      startIdleAnimations();
      createDebugPanel();
      setupMouseControls();
      notify("READY", {});
      console.log("[SB] ✅ Ready");
    },
    undefined,
    (err) => {
      console.error("[SB] Load error:", err);
      notify("ERROR", { message: err.message || String(err) });
    },
  );

  animate();
}

function animate() {
  requestAnimationFrame(animate);
  try {
    if (window._sbMixer) window._sbMixer.update(0.016);
    if (scene) scene.updateMatrixWorld(true);
    if (renderer && scene && camera) renderer.render(scene, camera);
  } catch (e) {}
}

function notify(type, data) {
  try {
    parent.postMessage(
      { source: "signbridge-iframe", type, ...(data || {}) },
      "*",
    );
  } catch (e) {}
}

// ===== 面部表情动画 =====
function startIdleAnimations() {
  // Blink timer: random 2-5 second intervals
  function scheduleBlink() {
    const delay = 2000 + Math.random() * 3000;
    setTimeout(() => {
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
  window._sbBaseY = -0.85;
  function breathingLoop() {
    if (!modelReady || !window._sbModel || window._sbCurrentClip) {
      requestAnimationFrame(breathingLoop);
      return;
    }
    breathTime += 0.016;
    const breathe = Math.sin(breathTime * 0.8) * 0.003;
    if (window._sbModel && !animPlaying) {
      window._sbModel.position.y = window._sbBaseY + breathe;
    }
    requestAnimationFrame(breathingLoop);
  }
  breathingLoop();
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
function createDebugPanel() {
  const el = document.getElementById("c");
  if (!el) return;
  const toggleBtn = document.createElement("button");
  toggleBtn.textContent = "🔧";
  toggleBtn.title = "骨骼调参";
  toggleBtn.style.cssText =
    "position:absolute;top:4px;left:4px;width:28px;height:28px;border:none;border-radius:4px;background:rgba(0,0,0,0.65);color:#ff0;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;z-index:31;";
  const panel = document.createElement("div");
  panel.id = "sb-debug";
  panel.style.cssText =
    "position:absolute;top:32px;left:4px;width:260px;max-height:80%;overflow-y:auto;background:rgba(0,0,0,0.88);color:#0f0;font-size:10px;font-family:monospace;padding:6px;border-radius:6px;z-index:30;display:none;";
  toggleBtn.onclick = (e) => {
    e.stopPropagation();
    panel.style.display = panel.style.display === "none" ? "block" : "none";
  };
  el.appendChild(toggleBtn);

  const bones = [
    { name: "rUpperArm", label: "右上臂", keys: ["x", "y", "z"] },
    { name: "rForearm", label: "右前臂", keys: ["x", "y", "z"] },
    { name: "rHand", label: "右手", keys: ["x", "y", "z"] },
    { name: "rShoulder", label: "右肩", keys: ["x", "y", "z"] },
    { name: "lUpperArm", label: "左上臂", keys: ["x", "y", "z"] },
    { name: "lForearm", label: "左前臂", keys: ["x", "y", "z"] },
    { name: "lHand", label: "左手", keys: ["x", "y", "z"] },
    { name: "lShoulder", label: "左肩", keys: ["x", "y", "z"] },
    { name: "head", label: "头", keys: ["x", "y", "z"] },
    { name: "rthumb", label: "右拇指", keys: ["x", "y", "z"] },
    { name: "rindex", label: "右食指", keys: ["x", "y", "z"] },
    { name: "rmiddle", label: "右中指", keys: ["x", "y", "z"] },
    { name: "rring", label: "右无名指", keys: ["x", "y", "z"] },
    { name: "rpinky", label: "右小指", keys: ["x", "y", "z"] },
  ];

  let html =
    '<div style="margin-bottom:4px;font-weight:bold;color:#ff0;">骨骼调参 (弧度)</div>';
  bones.forEach((b) => {
    html +=
      '<div style="margin:2px 0;padding:2px;border:1px solid #333;border-radius:2px;">';
    html += '<div style="color:#ff0;margin-bottom:1px;">' + b.label + "</div>";
    const bm = boneMap[b.name];
    if (!bm) {
      html += '<span style="color:#f00;">未映射</span>';
    } else {
      b.keys.forEach((k) => {
        const id = "dbg_" + b.name + "_" + k;
        const val = bm.rotation[k] || 0;
        html +=
          k +
          ': <input id="' +
          id +
          '" type="range" min="-3.2" max="3.2" step="0.01" value="' +
          val +
          '" oninput="window._dbgSet(\'' +
          b.name +
          "','" +
          k +
          '\',this.value)" style="width:45px;vertical-align:middle;">';
        html +=
          '<span id="' +
          id +
          '_v" style="display:inline-block;width:32px;text-align:right;">' +
          val.toFixed(2) +
          "</span> ";
      });
    }
    html += "</div>";
  });
  html +=
    '<button onclick="window._dbgExport()" style="margin-top:6px;width:100%;padding:4px;background:#393;color:#fff;border:none;border-radius:3px;cursor:pointer;">📋 导出姿势</button>';
  html +=
    '<button onclick="window._dbgReset()" style="margin-top:2px;width:100%;padding:4px;background:#933;color:#fff;border:none;border-radius:3px;cursor:pointer;">🔄 重置全部</button>';
  html +=
    '<pre id="dbg-out" style="margin-top:4px;color:#ff0;font-size:9px;white-space:pre-wrap;word-break:break-all;max-height:80px;overflow-y:auto;"></pre>';
  panel.innerHTML = html;
  el.appendChild(panel);

  window._dbgSet = function (boneName, key, valStr) {
    const b = boneMap[boneName];
    if (!b) return;
    b.rotation[key] = parseFloat(valStr);
    if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    const vEl = document.getElementById("dbg_" + boneName + "_" + key + "_v");
    if (vEl) vEl.textContent = parseFloat(valStr).toFixed(2);
  };
  window._dbgExport = function () {
    const lines = [];
    for (const b of bones) {
      const bm = boneMap[b.name];
      if (!bm) continue;
      const rots = b.keys.map((k) => bm.rotation[k].toFixed(2)).join(", ");
      lines.push(b.name + ": deg(" + rots + ")");
    }
    const text = lines.join(",\n");
    document.getElementById("dbg-out").textContent = text;
    navigator.clipboard.writeText(text).catch(() => {});
    console.log("[SB] Exported:\n" + text);
  };
  window._dbgReset = function () {
    for (const k in boneMap) {
      const r = REST[k] || { x: 0, y: 0, z: 0 };
      boneMap[k].rotation.set(r.x, r.y, r.z);
    }
    if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    for (const b of bones) {
      const bm = boneMap[b.name];
      if (!bm) continue;
      for (const k of b.keys) {
        const inp = document.getElementById("dbg_" + b.name + "_" + k);
        const sp = document.getElementById("dbg_" + b.name + "_" + k + "_v");
        if (inp) inp.value = bm.rotation[k].toFixed(2);
        if (sp) sp.textContent = bm.rotation[k].toFixed(2);
      }
    }
  };
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
    if (
      e.target.tagName === "BUTTON" ||
      e.target.closest("#sb-debug") ||
      e.target.closest("#sb-tools")
    )
      return;
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
    if (!isDragging || !window._sbModel) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    if (shiftKey) {
      window._sbModel.position.y -= dy * 0.008;
      window._sbBaseY = window._sbModel.position.y;
      console.log(
        "[SB-DRAG] SHIFT dy:",
        dy.toFixed(1),
        "posY:",
        window._sbModel.position.y.toFixed(3),
      );
      window._sbBaseY = window._sbModel.position.y;
    } else {
      window._sbModel.rotation.y += dx * 0.01;
      window._sbModel.position.y -= dy * 0.008;
      console.log(
        "[SB-DRAG] dy:",
        dy.toFixed(1),
        "posY:",
        window._sbModel.position.y.toFixed(3),
      );
      window._sbBaseY = window._sbModel.position.y;
    }
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
      if (!window._sbModel) return;
      e.preventDefault();
      const s = window._sbModel.scale.x;
      const ns = Math.max(
        0.2,
        Math.min(2.5, s * (e.deltaY > 0 ? 0.985 : 1.015)),
      );
      window._sbModel.scale.set(ns, ns, ns);
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
  if (!ev.data || ev.data.source !== "signbridge-page") return;
  console.log("[SB] iframe rx:", ev.data.type, ev.data.text || "");
  switch (ev.data.type) {
    case "INIT":
      init(ev.data.modelUrl);
      break;
    case "SUBTITLE_TEXT":
      if (modelReady && ev.data.text) {
        clearTimeout(window._sbSubDebounce);
        window._sbSubDebounce = setTimeout(
          () => textToAnimation(ev.data.text),
          250,
        );
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
console.log("[SB] v17 — multi-site + structured gestures + slerp");
