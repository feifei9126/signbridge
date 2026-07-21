// editor-entry.js
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
var D = Math.PI / 180;
var BONE_SHORT = {
  "mixamorig6Hips": "hip",
  "mixamorig6Spine": "spine",
  "mixamorig6Spine1": "spine1",
  "mixamorig6Spine2": "spine2",
  "mixamorig6Neck": "neck",
  "mixamorig6Head": "head",
  "mixamorig6RightShoulder": "rShoulder",
  "mixamorig6RightArm": "rUpperArm",
  "mixamorig6RightForeArm": "rForearm",
  "mixamorig6RightHand": "rHand",
  "mixamorig6RightHandThumb1": "rthumb1",
  "RightHandThumb2": "rthumb2",
  "RightHandThumb3": "rthumb3",
  "RightHandThumb4": "rthumb4",
  "mixamorig6RightHandIndex1": "rindex1",
  "mixamorig6RightHandIndex2": "rindex2",
  "mixamorig6RightHandIndex3": "rindex3",
  "mixamorig6RightHandIndex4": "rindex4",
  "mixamorig6RightHandMiddle1": "rmiddle1",
  "mixamorig6RightHandMiddle2": "rmiddle2",
  "mixamorig6RightHandMiddle3": "rmiddle3",
  "mixamorig6RightHandMiddle4": "rmiddle4",
  "mixamorig6RightHandRing1": "rring1",
  "mixamorig6RightHandRing2": "rring2",
  "mixamorig6RightHandRing3": "rring3",
  "mixamorig6RightHandRing4": "rring4",
  "mixamorig6RightHandPinky1": "rpinky1",
  "mixamorig6RightHandPinky2": "rpinky2",
  "mixamorig6RightHandPinky3": "rpinky3",
  "mixamorig6RightHandPinky4": "rpinky4",
  "mixamorig6LeftShoulder": "lShoulder",
  "mixamorig6LeftArm": "lUpperArm",
  "mixamorig6LeftForeArm": "lForearm",
  "mixamorig6LeftHand": "lHand",
  "mixamorig6LeftHandThumb1": "lthumb1",
  "LeftHandThumb2": "lthumb2",
  "LeftHandThumb3": "lthumb3",
  "LeftHandThumb4": "lthumb4",
  "mixamorig6LeftHandIndex1": "lindex1",
  "mixamorig6LeftHandIndex2": "lindex2",
  "mixamorig6LeftHandIndex3": "lindex3",
  "mixamorig6LeftHandIndex4": "lindex4",
  "mixamorig6LeftHandMiddle1": "lmiddle1",
  "mixamorig6LeftHandMiddle2": "lmiddle2",
  "mixamorig6LeftHandMiddle3": "lmiddle3",
  "mixamorig6LeftHandMiddle4": "lmiddle4",
  "mixamorig6LeftHandRing1": "lring1",
  "mixamorig6LeftHandRing2": "lring2",
  "mixamorig6LeftHandRing3": "lring3",
  "mixamorig6LeftHandRing4": "lring4",
  "mixamorig6LeftHandPinky1": "lpinky1",
  "mixamorig6LeftHandPinky2": "lpinky2",
  "mixamorig6LeftHandPinky3": "lpinky3",
  "mixamorig6LeftHandPinky4": "lpinky4"
};
var EDIT_BONES = [
  { name: "head", label: "\u5934", keys: ["x", "y", "z"] },
  { name: "rShoulder", label: "\u53F3\u80A9", keys: ["x", "y", "z"], mirror: "lShoulder" },
  { name: "rUpperArm", label: "\u53F3\u4E0A\u81C2", keys: ["x", "y", "z"], mirror: "lUpperArm" },
  { name: "rForearm", label: "\u53F3\u524D\u81C2", keys: ["x", "y", "z"], mirror: "lForearm" },
  { name: "rHand", label: "\u53F3\u624B", keys: ["x", "y", "z"], mirror: "lHand" },
  { name: "lShoulder", label: "\u5DE6\u80A9", keys: ["x", "y", "z"] },
  { name: "lUpperArm", label: "\u5DE6\u4E0A\u81C2", keys: ["x", "y", "z"] },
  { name: "lForearm", label: "\u5DE6\u524D\u81C2", keys: ["x", "y", "z"] },
  { name: "lHand", label: "\u5DE6\u624B", keys: ["x", "y", "z"] },
  { name: "rthumb1", label: "\u53F3\u62C7\u63071", keys: ["x"], mirror: "lthumb1" },
  { name: "rindex1", label: "\u53F3\u98DF\u63071", keys: ["x"], mirror: "lindex1" },
  { name: "rmiddle1", label: "\u53F3\u4E2D\u63071", keys: ["x"], mirror: "lmiddle1" },
  { name: "rring1", label: "\u53F3\u65E0\u540D\u63071", keys: ["x"], mirror: "lring1" },
  { name: "rpinky1", label: "\u53F3\u5C0F\u63071", keys: ["x"], mirror: "lpinky1" },
  { name: "lthumb1", label: "\u5DE6\u62C7\u63071", keys: ["x"] },
  { name: "lindex1", label: "\u5DE6\u98DF\u63071", keys: ["x"] },
  { name: "lmiddle1", label: "\u5DE6\u4E2D\u63071", keys: ["x"] },
  { name: "lring1", label: "\u5DE6\u65E0\u540D\u63071", keys: ["x"] },
  { name: "lpinky1", label: "\u5DE6\u5C0F\u63071", keys: ["x"] }
];
var MIRROR_MAP = {};
EDIT_BONES.forEach((b) => {
  if (b.mirror) MIRROR_MAP[b.name] = b.mirror;
});
var container = document.getElementById("viewer");
var scene = new THREE.Scene();
scene.background = new THREE.Color(14477557);
var camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(1.2, 0.8, 2.2);
camera.lookAt(0, 0.7, 0);
var renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);
var ctrl = new OrbitControls(camera, renderer.domElement);
ctrl.target.set(0, 0.7, 0);
ctrl.enableDamping = true;
ctrl.dampingFactor = 0.08;
ctrl.update();
scene.add(new THREE.AmbientLight(16777215, 1.2));
var l1 = new THREE.DirectionalLight(16777215, 1.5);
l1.position.set(2, 4, 3);
scene.add(l1);
var l2 = new THREE.DirectionalLight(8947967, 0.6);
l2.position.set(-2, 1, -1);
scene.add(l2);
var grid = new THREE.GridHelper(3, 20, 13421772, 14540253);
grid.position.y = -0.5;
scene.add(grid);
var skinnedMesh = null;
var modelRoot = null;
var boneMap = {};
var animTimer = null;
var animFrames = [];
var animIdx = 0;
var _lastTime = 0;
function resize() {
  const w = container.clientWidth, h = container.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
function anim() {
  requestAnimationFrame(anim);
  ctrl.update();
  renderer.render(scene, camera);
  const now = performance.now();
  document.getElementById("status-bar").textContent = "\u9AA8\u9ABC: " + Object.keys(boneMap).length + " | FPS: " + (1e3 / (now - _lastTime || 16)).toFixed(0);
  _lastTime = now;
}
async function loadModel() {
  const loader = new GLTFLoader();
  try {
    const gltf = await loader.loadAsync("./model.glb");
    modelRoot = gltf.scene;
    scene.add(modelRoot);
    modelRoot.traverse((obj) => {
      if (obj.isSkinnedMesh && !skinnedMesh) skinnedMesh = obj;
    });
    modelRoot.traverse((obj) => {
      if (obj.isBone) {
        const n = obj.name;
        if (BONE_SHORT[n]) boneMap[BONE_SHORT[n]] = obj;
        const c = n.replace(/^mixamorig6/, "");
        if (c !== n && BONE_SHORT[c]) boneMap[BONE_SHORT[c]] = obj;
      }
    });
    modelRoot.position.set(0, -0.15, 0);
    modelRoot.scale.set(0.85, 0.85, 0.85);
    console.log("[PE] Loaded, bones:", Object.keys(boneMap).length);
    document.getElementById("pose-label").textContent = "\u5C31\u7EEA - \u9009\u9884\u8BBE\u6216\u62D6\u6ED1\u5757";
    buildSliders();
    resetAll();
  } catch (err) {
    console.error("[PE] Load failed:", err);
    document.getElementById("pose-label").textContent = "\u52A0\u8F7D\u5931\u8D25: " + err.message;
  }
}
function syncSliders() {
  EDIT_BONES.forEach((b) => {
    const bm = boneMap[b.name];
    if (!bm) return;
    b.keys.forEach((k) => {
      const s = document.getElementById("sl_" + b.name + "_" + k);
      const v = document.getElementById("sl_" + b.name + "_" + k + "_v");
      const val = bm.rotation[k] || 0;
      if (s) s.value = val;
      if (v) v.textContent = val.toFixed(2);
    });
  });
}
function applyPoseObj(pose) {
  for (const name in pose) {
    const b = boneMap[name];
    if (!b) continue;
    const rot = pose[name];
    if (rot && "x" in rot) b.rotation.set(rot.x || 0, rot.y || 0, rot.z || 0);
  }
  if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
  syncSliders();
}
function getCurrentPose() {
  const p = {};
  for (const k in boneMap) p[k] = { x: boneMap[k].rotation.x, y: boneMap[k].rotation.y, z: boneMap[k].rotation.z };
  return p;
}
var toastT;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  if (toastT) clearTimeout(toastT);
  toastT = setTimeout(() => el.classList.remove("show"), 2e3);
}
var API = {};
window.__PE = API;
API.resetAll = function() {
  for (const k in boneMap) boneMap[k].rotation.set(0, 0, 0);
  if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
  syncSliders();
  document.getElementById("pose-label").textContent = "T-Pose";
};
API.exportPose = function() {
  const json = JSON.stringify(getCurrentPose(), null, 2);
  document.getElementById("output-text").textContent = json;
  navigator.clipboard.writeText(json).then(() => toast("JSON \u5DF2\u590D\u5236"));
};
API.exportAsCode = function() {
  const pose = getCurrentPose();
  const lines = [];
  for (const b of EDIT_BONES) {
    if (!boneMap[b.name]) continue;
    const bm = boneMap[b.name];
    const vals = b.keys.map((k) => ((bm.rotation[k] || 0) / D).toFixed(1));
    if (vals.every((v) => parseFloat(v) === 0)) continue;
    lines.push("  " + b.name + ": deg(" + vals.join(", ") + "),");
  }
  const code = "const pose = makePose({\n" + lines.join("\n") + "\n});";
  document.getElementById("output-text").textContent = code;
  navigator.clipboard.writeText(code).then(() => toast("\u4EE3\u7801\u5DF2\u590D\u5236"));
};
API.importPose = function() {
  const text = prompt("\u7C98\u8D34 JSON \u59FF\u52BF\u6570\u636E:");
  if (!text) return;
  try {
    applyPoseObj(JSON.parse(text));
    document.getElementById("pose-label").textContent = "\u5BFC\u5165\u7684\u59FF\u52BF";
    toast("\u5DF2\u5BFC\u5165");
  } catch (e) {
    toast("JSON \u9519\u8BEF: " + e.message);
  }
};
var PRESETS = {
  tpose: () => {
    for (const k in boneMap) boneMap[k].rotation.set(0, 0, 0);
    if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    syncSliders();
  },
  idle: () => applyPoseObj({ lUpperArm: { x: -5 * D, y: 5 * D, z: 0 }, rUpperArm: { x: -5 * D, y: -5 * D, z: 0 }, lForearm: { x: -10 * D, y: 0, z: 0 }, rForearm: { x: -10 * D, y: 0, z: 0 } }),
  hello: () => applyPoseObj({ rShoulder: { x: 0, y: 0, z: -5 * D }, rUpperArm: { x: 35 * D, y: 10 * D, z: 0 }, rForearm: { x: -60 * D, y: 5 * D, z: -10 * D }, rHand: { x: 10 * D, y: 0, z: 5 * D } }),
  thanks: () => applyPoseObj({ rShoulder: { x: 0, y: 5 * D, z: -5 * D }, rUpperArm: { x: 25 * D, y: 15 * D, z: 0 }, rForearm: { x: -50 * D, y: 5 * D, z: -10 * D }, rHand: { x: 0, y: 10 * D, z: -15 * D }, head: { x: 8 * D, y: 0, z: 0 } }),
  welcome: () => applyPoseObj({ rUpperArm: { x: 30 * D, y: 20 * D, z: 0 }, rForearm: { x: -60 * D, y: -5 * D, z: 25 * D }, lUpperArm: { x: 30 * D, y: -20 * D, z: 0 }, lForearm: { x: -60 * D, y: 5 * D, z: -25 * D } }),
  yes: () => applyPoseObj({ rUpperArm: { x: 20 * D, y: 5 * D, z: 0 }, rForearm: { x: -45 * D, y: 0, z: 5 * D }, rHand: { x: 0, y: -15 * D, z: -5 * D } }),
  no: () => applyPoseObj({ head: { x: -10 * D, y: 0, z: 0 }, rUpperArm: { x: 20 * D, y: 10 * D, z: 0 }, rForearm: { x: -40 * D, y: 0, z: 10 * D }, rHand: { x: 0, y: -15 * D, z: 0 } }),
  ok: () => applyPoseObj({ rShoulder: { x: 0, y: 0, z: -5 * D }, rUpperArm: { x: 30 * D, y: 15 * D, z: 0 }, rForearm: { x: -55 * D, y: 5 * D, z: -10 * D }, rHand: { x: 10 * D, y: -5 * D, z: 15 * D }, rthumb1: { x: 20 * D }, rindex1: { x: 30 * D }, rmiddle1: { x: 40 * D }, lthumb1: { x: 20 * D }, lindex1: { x: 30 * D }, lmiddle1: { x: 40 * D } }),
  help: () => applyPoseObj({ rUpperArm: { x: 50 * D, y: 25 * D, z: 0 }, rForearm: { x: -75 * D, y: 15 * D, z: 20 * D }, lUpperArm: { x: 40 * D, y: -20 * D, z: 0 }, lForearm: { x: -60 * D, y: -10 * D, z: 15 * D } }),
  point_r: () => applyPoseObj({ rUpperArm: { x: 35 * D, y: 10 * D, z: 0 }, rForearm: { x: -55 * D, y: 0, z: 0 }, rHand: { x: 0, y: 0, z: 0 }, rindex1: { x: 0 }, rmiddle1: { x: 40 * D }, rring1: { x: 50 * D }, rpinky1: { x: 60 * D } }),
  fist_r: () => applyPoseObj({ rthumb1: { x: 40 * D }, rindex1: { x: 70 * D }, rmiddle1: { x: 70 * D }, rring1: { x: 70 * D }, rpinky1: { x: 70 * D } }),
  open_r: () => applyPoseObj({ rthumb1: { x: 0 }, rindex1: { x: 0 }, rmiddle1: { x: 0 }, rring1: { x: 0 }, rpinky1: { x: 0 } })
};
API.loadPreset = function(name) {
  if (PRESETS[name]) {
    PRESETS[name]();
    document.getElementById("pose-label").textContent = document.getElementById("preset-dd").selectedOptions[0].text;
  }
};
API.playSequence = function() {
  const sel = document.getElementById("preset-dd").value;
  if (sel === "hello") {
    animFrames = [
      { pose: { rShoulder: { x: 0, y: 0, z: -5 * D }, rUpperArm: { x: 35 * D, y: 10 * D, z: 0 }, rForearm: { x: -60 * D, y: 5 * D, z: -10 * D }, rHand: { x: 10 * D, y: 0, z: 5 * D } }, dur: 0.4 },
      { pose: { rShoulder: { x: 0, y: 0, z: -5 * D }, rUpperArm: { x: 40 * D, y: 15 * D, z: 0 }, rForearm: { x: -65 * D, y: 10 * D, z: -5 * D }, rHand: { x: 12 * D, y: 5 * D, z: 10 * D } }, dur: 0.4 },
      { pose: { rShoulder: { x: 0, y: 0, z: -5 * D }, rUpperArm: { x: 35 * D, y: 10 * D, z: 0 }, rForearm: { x: -60 * D, y: 5 * D, z: -10 * D }, rHand: { x: 10 * D, y: 0, z: 5 * D } }, dur: 0.4 }
    ];
  } else {
    animFrames = [{ pose: getCurrentPose(), dur: 0.5 }, { pose: {}, dur: 0.3 }];
  }
  animIdx = 0;
  playNextFrame();
  document.getElementById("pose-label").textContent = "\u64AD\u653E\u4E2D...";
};
function playNextFrame() {
  if (animIdx >= animFrames.length) {
    document.getElementById("pose-label").textContent = "\u64AD\u653E\u5B8C\u6210";
    return;
  }
  applyPoseObj(animFrames[animIdx].pose || {});
  animIdx++;
  animTimer = setTimeout(playNextFrame, (animFrames[animIdx - 1]?.dur || 0.3) * 1e3);
}
API.stopSequence = function() {
  if (animTimer) clearTimeout(animTimer);
  animFrames = [];
  animIdx = 0;
  document.getElementById("pose-label").textContent = "\u5DF2\u505C\u6B62";
};
API.onSymToggle = function() {
  toast(document.getElementById("sym-mode").checked ? "\u5BF9\u79F0\u6A21\u5F0F\u5F00" : "\u5BF9\u79F0\u6A21\u5F0F\u5173");
};
window.onSlider = function(boneName, key, valStr) {
  const val = parseFloat(valStr);
  const b = boneMap[boneName];
  if (!b) return;
  b.rotation[key] = val;
  if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
  const vEl = document.getElementById("sl_" + boneName + "_" + key + "_v");
  if (vEl) vEl.textContent = val.toFixed(2);
  if (document.getElementById("sym-mode")?.checked && MIRROR_MAP[boneName]) {
    const mName = MIRROR_MAP[boneName], mb = boneMap[mName];
    if (!mb) return;
    const mVal = key === "y" ? -val : val;
    mb.rotation[key] = mVal;
    if (skinnedMesh?.skeleton) skinnedMesh.skeleton.update();
    const ms = document.getElementById("sl_" + mName + "_" + key);
    const mv = document.getElementById("sl_" + mName + "_" + key + "_v");
    if (ms) ms.value = mVal;
    if (mv) mv.textContent = mVal.toFixed(2);
  }
};
function buildSliders() {
  const scroll = document.getElementById("bones-scroll");
  let html = "";
  EDIT_BONES.forEach((b) => {
    const bm = boneMap[b.name];
    if (!bm) {
      html += '<div class="bone-group"><div class="bone-label">' + b.label + ' <span style="color:#f00">\u672A\u6620\u5C04</span></div></div>';
      return;
    }
    html += '<div class="bone-group"><div class="bone-label">' + b.label + " (" + b.name + ")</div>";
    b.keys.forEach((k) => {
      const id = "sl_" + b.name + "_" + k;
      const val = bm.rotation[k] || 0;
      html += '<div class="slider-row"><span class="axis">' + k + '</span><input type="range" id="' + id + '" min="-3.2" max="3.2" step="0.01" value="' + val + `" oninput="onSlider('` + b.name + "','" + k + `',this.value)"><span class="val" id="` + id + '_v">' + val.toFixed(2) + "</span></div>";
    });
    html += "</div>";
  });
  scroll.innerHTML = html;
}
window.addEventListener("resize", resize);
resize();
anim();
loadModel();
