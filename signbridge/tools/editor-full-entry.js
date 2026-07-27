import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  canonicalizePose,
  createHumanoidRig,
} from "../src/avatar/humanoid-rig.js";
import { handShape } from "../src/avatar/sign-language-data.js";

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
  boneMap = {},
  REST = {};
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
  requestAnimationFrame(anim);
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
  REST = Object.fromEntries(
    Object.entries(rig.rest).map(([name, value]) => [name, value.rotation]),
  );
  if (!rig.isSigningReady) {
    throw new Error(`缺少手语骨骼: ${rig.missing.join(", ")}`);
  }
}

function handleSliderInput(e) {
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
  rig?.applyPose(canonicalizePose(delta));
  syncSliders();
}

function applyAbs(obj) {
  for (const n in obj) {
    const b = boneMap[n];
    if (!b) continue;
    const r = obj[n];
    if (r && "x" in r) b.rotation.set(r.x || 0, r.y || 0, r.z || 0);
  }
  rig?.update();
  syncSliders();
}
function getPose() {
  const p = {};
  for (const k in boneMap)
    p[k] = {
      x: boneMap[k].rotation.x,
      y: boneMap[k].rotation.y,
      z: boneMap[k].rotation.z,
    };
  return p;
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
    const j = JSON.stringify(getPose(), null, 2);
    document.getElementById("output-text").textContent = j;
    navigator.clipboard
      .writeText(j)
      .then(() => toast("JSON已复制"))
      .catch(() => toast("请从输出框复制"));
  },
  exportAsCode() {
    const lines = [];
    const delta = {};
    for (const b of EDIT_BONES) {
      if (!boneMap[b.name]) continue;
      const cur = boneMap[b.name].rotation;
      const r = REST[b.name] || { x: 0, y: 0, z: 0 };
      const dx = +(cur.x - r.x) / D,
        dy = +(cur.y - r.y) / D,
        dz = +(cur.z - r.z) / D;
      if (Math.abs(dx) < 0.3 && Math.abs(dy) < 0.3 && Math.abs(dz) < 0.3)
        continue;
      lines.push(
        b.name +
          ": dg(" +
          dx.toFixed(1) +
          "," +
          dy.toFixed(1) +
          "," +
          dz.toFixed(1) +
          "),",
      );
      delta[b.name] = { x: dx, y: dy, z: dz };
    }
    const code = "applyDelta({\n  " + lines.join("\n  ") + "\n});";
    document.getElementById("output-text").textContent = code;
    navigator.clipboard
      .writeText(code)
      .then(() => toast("代码已复制"))
      .catch(() => toast("请从输出框复制"));
    const lib = document.getElementById("lib-name")?.value || "default";
    const name = prompt("手势名称？(库: " + lib + ")", "");
    if (name) {
      const existing = JSON.parse(localStorage.getItem("sb_gestures") || "{}");
      existing[name] = {
        library: lib,
        delta: delta,
        timestamp: new Date().toISOString(),
      };
      localStorage.setItem("sb_gestures", JSON.stringify(existing, null, 2));
      const libs = {};
      for (const [k, v] of Object.entries(existing)) {
        const l = v.library || "default";
        if (!libs[l]) libs[l] = [];
        libs[l].push(k);
      }
      let txt = "✅ " + name + " [" + lib + "]\n" + code + "\n";
      for (const [l, names] of Object.entries(libs)) {
        txt += "\n📁 " + l + " (" + names.length + "): " + names.join(", ");
      }
      document.getElementById("output-text").textContent = txt;
      API.refreshLib();
      toast("✅ 已保存: " + name + " → " + lib);
    }
  },
  importPose() {
    const t = prompt("粘贴JSON:");
    if (!t) return;
    try {
      applyAbs(JSON.parse(t));
      toast("已导入");
    } catch (e) {
      toast("JSON错误:" + e.message);
    }
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
  showGestures() {
    const g = JSON.parse(localStorage.getItem("sb_gestures") || "{}");
    const libs = {};
    for (const [k, v] of Object.entries(g)) {
      const l = v.library || "default";
      if (!libs[l]) libs[l] = [];
      libs[l].push(k);
    }
    let txt = "全部 " + Object.keys(g).length + " 个手势:\n";
    for (const [l, names] of Object.entries(libs)) {
      txt += "\n📁 " + l + " (" + names.length + "): " + names.join(", ");
    }
    document.getElementById("output-text").textContent = txt;
    toast("共 " + Object.keys(g).length + " 个手势");
  },
  downloadGestures() {
    const g = JSON.parse(localStorage.getItem("sb_gestures") || "{}");
    const blob = new Blob([JSON.stringify(g, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    const url = URL.createObjectURL(blob);
    a.href = url;
    a.download = "signbridge-gestures.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    toast("已下载");
  },
  onSymToggle() {
    toast(
      document.getElementById("sym-mode").checked ? "对称模式开" : "对称模式关",
    );
  },
  refreshLib() {
    const g = JSON.parse(localStorage.getItem("sb_gestures") || "{}");
    const libs = {};
    for (const [k, v] of Object.entries(g)) {
      const l = v.library || "default";
      if (!libs[l]) libs[l] = [];
      libs[l].push(k);
    }
    let h = "";
    for (const [l, names] of Object.entries(libs)) {
      h += '<div style="color:#ff0;margin:4px 0 2px;">📁 ' + l + "</div>";
      names.forEach((n) => {
        h +=
          '<div style="display:flex;align-items:center;gap:4px;margin:1px 0;padding:2px 4px;background:#1a1a3a;border-radius:3px;cursor:pointer;" class="lib-item" data-gname="' +
          n +
          '" title="点击应用">';
        h += '<span style="flex:1;">' + n + "</span>";
        h +=
          '<button style="font-size:9px;padding:1px 4px;background:#933;color:#fff;border:none;border-radius:2px;cursor:pointer;" class="lib-del" data-gname="' +
          n +
          '">🗑</button>';
        h += "</div>";
      });
    }
    if (!Object.keys(g).length)
      h = '<div style="color:#888;">暂无，摆好姿势后点导出代码保存</div>';
    const list = document.getElementById("lib-list");
    if (!list) return;
    list.innerHTML = h;
    list.querySelectorAll(".lib-item").forEach((el) => {
      el.addEventListener("click", () => {
        API.applyLib(el.dataset.gname);
      });
    });
    list.querySelectorAll(".lib-del").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        API.delLib(el.dataset.gname);
      });
    });
  },
  applyLib(name) {
    const g = JSON.parse(localStorage.getItem("sb_gestures") || "{}");
    if (!g[name]) {
      toast("❌ 未找到: " + name);
      return;
    }
    applyDelta(g[name].delta);
    toast("✅ " + name);
    document.getElementById("pose-label").textContent = name;
  },
  delLib(name) {
    if (!confirm("删除 " + name + "?")) return;
    const g = JSON.parse(localStorage.getItem("sb_gestures") || "{}");
    delete g[name];
    localStorage.setItem("sb_gestures", JSON.stringify(g, null, 2));
    this.refreshLib();
    toast("🗑 已删除: " + name);
  },
};

function bindUI() {
  const on = (id, event, handler) =>
    document.getElementById(id)?.addEventListener(event, handler);
  on("btn-reset", "click", API.resetAll);
  on("btn-export-json", "click", API.exportPose);
  on("btn-export-code", "click", API.exportAsCode);
  on("btn-import", "click", API.importPose);
  on("btn-show-all", "click", API.showGestures);
  on("btn-dl", "click", API.downloadGestures);
  on("preset-dd", "change", (event) => API.loadPreset(event.target.value));
  on("sym-mode", "change", API.onSymToggle);
  on("btn-refresh-lib", "click", API.refreshLib);
}

(async () => {
  window.__PE = API;
  window.addEventListener("resize", resize);
  resize();
  anim();
  bindUI();

  try {
    const poseLabel = document.getElementById("pose-label");
    poseLabel.textContent = "加载模型...";
    const gltf = await loadModel();
    poseLabel.textContent = "解析骨骼...";
    mapBones(gltf);
    modelRoot = gltf.scene;
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
    API.refreshLib();
  } catch (e) {
    const poseLabel = document.getElementById("pose-label");
    poseLabel.textContent = "加载失败: " + e.message;
    poseLabel.style.color = "#f44";
    console.error(e);
  }
})();
