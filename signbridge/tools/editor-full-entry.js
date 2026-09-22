import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  canonicalizePose,
  createHumanoidRig,
} from "../src/avatar/humanoid-rig.js";
import { handShape } from "../src/avatar/sign-language-data.js";
import { createMotionPlayer } from "../src/avatar/motion-player.js";
import { mountMotionLibrary } from "../src/avatar/motion-library-ui.js";
import { disposeModel } from "../src/avatar/dispose-model.js";
import { t } from "../src/i18n/locales.js";

const D = Math.PI / 180;
function dg(x, y, z) {
  return { x: (x || 0) * D, y: (y || 0) * D, z: (z || 0) * D };
}

const EDIT_BONES = [
  { name: "head", label: "头", keys: ["x", "y", "z"] },
  {
    name: "rightShoulder",
    label: "右肩",
    keys: ["x", "y", "z"],
    mirror: "leftShoulder",
  },
  {
    name: "rightUpperArm",
    label: "右上臂",
    keys: ["x", "y", "z"],
    mirror: "leftUpperArm",
  },
  {
    name: "rightLowerArm",
    label: "右前臂",
    keys: ["x", "y", "z"],
    mirror: "leftLowerArm",
  },
  {
    name: "rightHand",
    label: "右手",
    keys: ["x", "y", "z"],
    mirror: "leftHand",
  },
  {
    name: "rightThumbMetacarpal",
    label: "右拇指根",
    keys: ["x", "y", "z"],
    mirror: "leftThumbMetacarpal",
  },
  {
    name: "rightThumbProximal",
    label: "右拇指中",
    keys: ["x", "y", "z"],
    mirror: "leftThumbProximal",
  },
  {
    name: "rightThumbDistal",
    label: "右拇指尖",
    keys: ["x", "y", "z"],
    mirror: "leftThumbDistal",
  },
  ...["Index", "Middle", "Ring", "Little"].flatMap((finger) =>
    ["Proximal", "Intermediate", "Distal"].map((segment) => ({
      name: `right${finger}${segment}`,
      label: `右${{ Index: "食指", Middle: "中指", Ring: "无名指", Little: "小指" }[finger]}${{ Proximal: "根", Intermediate: "中", Distal: "尖" }[segment]}`,
      keys: ["x", "y", "z"],
      mirror: `left${finger}${segment}`,
    })),
  ),
  { name: "leftShoulder", label: "左肩", keys: ["x", "y", "z"] },
  { name: "leftUpperArm", label: "左上臂", keys: ["x", "y", "z"] },
  { name: "leftLowerArm", label: "左前臂", keys: ["x", "y", "z"] },
  { name: "leftHand", label: "左手", keys: ["x", "y", "z"] },
  {
    name: "leftThumbMetacarpal",
    label: "左拇指根",
    keys: ["x", "y", "z"],
  },
  {
    name: "leftThumbProximal",
    label: "左拇指中",
    keys: ["x", "y", "z"],
  },
  {
    name: "leftThumbDistal",
    label: "左拇指尖",
    keys: ["x", "y", "z"],
  },
  ...["Index", "Middle", "Ring", "Little"].flatMap((finger) =>
    ["Proximal", "Intermediate", "Distal"].map((segment) => ({
      name: `left${finger}${segment}`,
      label: `左${{ Index: "食指", Middle: "中指", Ring: "无名指", Little: "小指" }[finger]}${{ Proximal: "根", Intermediate: "中", Distal: "尖" }[segment]}`,
      keys: ["x", "y", "z"],
    })),
  ),
];
const MIRROR_MAP = {};
EDIT_BONES.forEach((b) => {
  if (b.mirror) MIRROR_MAP[b.name] = b.mirror;
});

const container = document.getElementById("viewer");
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xdce8f5);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(0, 1.05, 2.25);
camera.lookAt(0, 0.75, 0);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
container.appendChild(renderer.domElement);
const ctrl = new OrbitControls(camera, renderer.domElement);
ctrl.target.set(0, 0.75, 0);
ctrl.enableDamping = true;
ctrl.dampingFactor = 0.08;
ctrl.update();
scene.add(new THREE.AmbientLight(0xffffff, 1.2));
const l1 = new THREE.DirectionalLight(0xffffff, 1.5);
l1.position.set(2, 4, 3);
scene.add(l1);
const l2 = new THREE.DirectionalLight(0x8888ff, 0.6);
l2.position.set(-2, 1, -1);
scene.add(l2);

let modelRoot = null,
  rig = null,
  boneMap = {};
let player = null;
let libraryUI = null;
let poseDuration = 0.8;
let animationFrame = null;
let disposed = false;
let _lt = 0;

function resize() {
  const w = container.clientWidth,
    h = container.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
function anim() {
  animationFrame = requestAnimationFrame(anim);
  ctrl.update();
  renderer.render(scene, camera);
  const n = performance.now();
  document.getElementById("status-bar").textContent =
    "骨骼:" +
    Object.keys(boneMap).length +
    " FPS:" +
    (1000 / (n - _lt || 16)).toFixed(0);
  _lt = n;
}

async function loadModel() {
  const loader = new GLTFLoader();
  const resp = await fetch("./model.glb");
  if (!resp.ok) throw new Error("model.glb HTTP " + resp.status);
  const buf = await resp.arrayBuffer();
  return new Promise((resolve, reject) => {
    loader.parse(buf, "", resolve, reject);
  });
}

function mapBones(gltf) {
  rig = createHumanoidRig(gltf.scene);
  boneMap = rig.bones;
  player = createMotionPlayer(rig);
  if (!rig.isSigningReady) {
    throw new Error(`缺少手语骨骼: ${rig.missing.join(", ")}`);
  }
}

function handleSliderInput(e) {
  player?.stop();
  const bn = e.target.dataset.bone,
    k = e.target.dataset.key,
    v = parseFloat(e.target.value);
  const b = boneMap[bn];
  if (!b) return;
  b.rotation[k] = v;
  rig?.update();
  const ve = document.getElementById("sl_" + bn + "_" + k + "_v");
  if (ve) ve.textContent = v.toFixed(2);
  if (document.getElementById("sym-mode")?.checked && MIRROR_MAP[bn]) {
    const mn = MIRROR_MAP[bn],
      mb = boneMap[mn];
    if (!mb) return;
    const mv = k === "y" ? -v : v;
    mb.rotation[k] = mv;
    rig?.update();
    const ms = document.getElementById("sl_" + mn + "_" + k),
      mv2 = document.getElementById("sl_" + mn + "_" + k + "_v");
    if (ms) ms.value = mv;
    if (mv2) mv2.textContent = mv.toFixed(2);
  }
}

function buildSliders() {
  const scroll = document.getElementById("bones-scroll");
  let html = "";
  EDIT_BONES.forEach((b) => {
    const bm = boneMap[b.name];
    if (!bm) {
      html +=
        '<div class="bone-group"><div class="bone-label" style="color:#f44">❌ ' +
        b.label +
        "</div></div>";
      return;
    }
    html +=
      '<div class="bone-group"><div class="bone-label">' + b.label + "</div>";
    b.keys.forEach((k) => {
      const id = "sl_" + b.name + "_" + k;
      html +=
        '<div class="slider-row">' +
        '<span class="axis">' +
        k.toUpperCase() +
        "</span>" +
        '<input type="range" id="' +
        id +
        '" data-bone="' +
        b.name +
        '" data-key="' +
        k +
        '" min="-3.2" max="3.2" step="0.01" value="' +
        (bm.rotation[k] || 0) +
        '">' +
        '<span class="val" id="' +
        id +
        '_v">' +
        (bm.rotation[k] || 0).toFixed(2) +
        "</span>" +
        "</div>";
    });
    html += "</div>";
  });
  scroll.innerHTML = html;
  scroll
    .querySelectorAll("input[type=range]")
    .forEach((inp) => inp.addEventListener("input", handleSliderInput));
}

function syncSliders() {
  EDIT_BONES.forEach((b) => {
    const bm = boneMap[b.name];
    if (!bm) return;
    b.keys.forEach((k) => {
      const s = document.getElementById("sl_" + b.name + "_" + k),
        v = document.getElementById("sl_" + b.name + "_" + k + "_v"),
        val = bm.rotation[k] || 0;
      if (s) s.value = val;
      if (v) v.textContent = val.toFixed(2);
    });
  });
}

function applyDelta(delta) {
  player?.stop();
  rig?.applyPose(canonicalizePose(delta));
  syncSliders();
}

let tt;
function toast(m) {
  const e = document.getElementById("toast");
  e.textContent = m;
  e.classList.add("show");
  if (tt) clearTimeout(tt);
  tt = setTimeout(() => e.classList.remove("show"), 2000);
}

const PRESETS = {
  apose: () => {
    applyDelta({});
    toast("A-Pose");
  },
  fist: () => {
    applyDelta(handShape("fist", "right"));
    toast("握拳");
  },
  flat: () => {
    applyDelta(handShape("flat", "right"));
    toast("平掌");
  },
  point: () => {
    applyDelta(handShape("point", "right"));
    toast("食指指");
  },
  thumbUp: () => {
    applyDelta(handShape("thumbUp", "right"));
    toast("拇指竖");
  },
  抬头: () => {
    applyDelta({ head: dg(-43.9, 0, 0) });
    toast("抬头");
  },
  低头: () => {
    applyDelta({ head: dg(38.6, 0, 0) });
    toast("低头");
  },
  左转头: () => {
    applyDelta({ head: dg(1.4, -44.6, 0) });
    toast("左转头");
  },
  右转头: () => {
    applyDelta({ head: dg(1.4, 64.3, 0) });
    toast("右转头");
  },
  左歪头: () => {
    applyDelta({ head: dg(1.4, -1.0, 33.4) });
    toast("左歪头");
  },
  右歪头: () => {
    applyDelta({ head: dg(1.4, -1.0, -47.4) });
    toast("右歪头");
  },
};

const API = {
  resetAll() {
    applyDelta({});
    toast("A-Pose");
  },
  exportPose() {
    libraryUI?.exportJson();
  },
  exportAsCode() {
    if (!rig) throw new Error("motionModelNotReady");
    const code =
      "applyDelta(" + JSON.stringify(rig.capturePose(), null, 2) + ");";
    document.getElementById("output-text").textContent = code;
  },
  importPose() {
    libraryUI?.importFile();
  },
  loadPreset(name) {
    if (PRESETS[name]) {
      PRESETS[name]();
      const select = document.getElementById("preset-dd");
      document.getElementById("pose-label").textContent =
        select?.selectedOptions[0]?.textContent || name;
    } else {
      toast("❌ 未知: " + name);
    }
  },
  onSymToggle() {
    toast(
      document.getElementById("sym-mode").checked ? "对称模式开" : "对称模式关",
    );
  },
};

function bindUI() {
  const on = (id, event, handler) =>
    document.getElementById(id)?.addEventListener(event, () => {
      try {
        handler();
      } catch (error) {
        libraryUI?.report(error);
      }
    });
  on("btn-reset", "click", API.resetAll);
  on("btn-export-json", "click", API.exportPose);
  on("btn-export-code", "click", API.exportAsCode);
  on("btn-import", "click", API.importPose);
  on("preset-dd", "change", () =>
    API.loadPreset(document.getElementById("preset-dd").value),
  );
  on("sym-mode", "change", API.onSymToggle);
}

(async () => {
  window.__PE = API;
  window.addEventListener("resize", resize);
  resize();
  anim();
  bindUI();
  document.getElementById("btn-export-code").textContent =
    t("motionExportCode");

  try {
    const poseLabel = document.getElementById("pose-label");
    poseLabel.textContent = "加载模型...";
    const gltf = await loadModel();
    if (disposed) {
      disposeModel(gltf.scene);
      return;
    }
    modelRoot = gltf.scene;
    poseLabel.textContent = "解析骨骼...";
    mapBones(gltf);
    scene.add(modelRoot);
    camera.position.set(0, 1.05, 2.25);
    ctrl.target.set(0, 0.75, 0);
    ctrl.update();

    poseLabel.textContent = "A-Pose (" + Object.keys(boneMap).length + " 骨骼)";

    const dd = document.getElementById("preset-dd");
    dd.innerHTML =
      '<option value="apose">A-Pose</option>' +
      '<optgroup label="手形">' +
      '<option value="fist">握拳</option>' +
      '<option value="flat">平掌</option>' +
      '<option value="point">食指指</option>' +
      '<option value="thumbUp">拇指竖</option>' +
      "</optgroup>" +
      '<optgroup label="头部">' +
      '<option value="抬头">抬头</option>' +
      '<option value="低头">低头</option>' +
      '<option value="左转头">左转头</option>' +
      '<option value="右转头">右转头</option>' +
      '<option value="左歪头">左歪头</option>' +
      '<option value="右歪头">右歪头</option>' +
      "</optgroup>";
    buildSliders();
    libraryUI = mountMotionLibrary({
      container: document.getElementById("motion-library"),
      rig,
      getFrames: () => [{ value: rig.capturePose(), duration: poseDuration }],
      load: (asset) => {
        if (asset.frames.length !== 1)
          throw new Error("motionEditorSingleFrame");
        applyDelta(asset.frames[0].value);
        poseDuration = asset.frames[0].duration;
      },
      preview: (asset) => {
        player.stop({ reset: true });
        player.play(asset);
      },
      output: (text) => {
        document.getElementById("output-text").textContent = text;
      },
    });
  } catch (e) {
    if (disposed) return;
    const poseLabel = document.getElementById("pose-label");
    poseLabel.textContent = "加载失败: " + e.message;
    poseLabel.style.color = "#f44";
    console.error(e);
  }
})();

window.addEventListener(
  "pagehide",
  () => {
    disposed = true;
    player?.stop();
    libraryUI?.dispose();
    cancelAnimationFrame(animationFrame);
    clearTimeout(tt);
    window.removeEventListener("resize", resize);
    ctrl.dispose();
    disposeModel(modelRoot);
    renderer.dispose();
  },
  { once: true },
);
