import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";

import { createMotionPlayer } from "../avatar/motion-player.js";
import { mountMotionLibrary } from "../avatar/motion-library-ui.js";
import { MAX_MOTION_FRAMES } from "../avatar/motion-asset.js";
import { disposeModel } from "../avatar/dispose-model.js";
import { t } from "../i18n/locales.js";

// State
let scene,
  camera,
  renderer,
  controls,
  rig,
  boneMap = {};
const keyframes = [];
let isRecording = false;
let recordTimer = null;
let player = null;
let libraryUI = null;
let modelRoot = null;
let animationFrame = null;
let disposed = false;
let currentFrame = -1;

// Bones to expose
const BONE_LIST = [
  "rightShoulder",
  "rightUpperArm",
  "rightLowerArm",
  "rightHand",
  "leftShoulder",
  "leftUpperArm",
  "leftLowerArm",
  "leftHand",
  "rightThumbMetacarpal",
  "rightThumbProximal",
  "rightThumbDistal",
  "rightIndexProximal",
  "rightIndexIntermediate",
  "rightIndexDistal",
  "rightMiddleProximal",
  "rightMiddleIntermediate",
  "rightMiddleDistal",
  "rightRingProximal",
  "rightRingIntermediate",
  "rightRingDistal",
  "rightLittleProximal",
  "rightLittleIntermediate",
  "rightLittleDistal",
  "leftThumbMetacarpal",
  "leftThumbProximal",
  "leftThumbDistal",
  "leftIndexProximal",
  "leftIndexIntermediate",
  "leftIndexDistal",
  "leftMiddleProximal",
  "leftMiddleIntermediate",
  "leftMiddleDistal",
  "leftRingProximal",
  "leftRingIntermediate",
  "leftRingDistal",
  "leftLittleProximal",
  "leftLittleIntermediate",
  "leftLittleDistal",
  "head",
];

// Init
const container = document.getElementById("c");
renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(container.clientWidth, container.clientHeight);
container.appendChild(renderer.domElement);

scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);
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
camera.position.set(0, 0.65, 2.0);
camera.lookAt(0, 0.3, 0);
controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.55, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enablePan = true;
controls.minDistance = 0.8;
controls.maxDistance = 5;
controls.update();

// Load model
const loader = new GLTFLoader();
const modelUrl = "./model.glb";
function modelError(error) {
  if (disposed) return;
  document.getElementById("rec-status").textContent = t("motionLoadingFailed", {
    detail: error.message,
  });
}
console.log("Loading:", modelUrl);
loader.load(
  modelUrl,
  (gltf) => {
    if (disposed) {
      disposeModel(gltf.scene);
      return;
    }
    modelRoot = gltf.scene;
    try {
      rig = createHumanoidRig(gltf.scene);
      if (!rig.isSigningReady) {
        throw new Error("Missing signing bones: " + rig.missing.join(", "));
      }
      boneMap = rig.bones;
      player = createMotionPlayer(rig, {
        onComplete: () => {
          currentFrame = -1;
          buildSliders();
          renderKeyframes();
        },
      });
      scene.add(gltf.scene);
      gltf.scene.scale.set(0.984, 0.984, 0.984);
      gltf.scene.position.y = -0.65;
      console.log("Model loaded. Bones:", Object.keys(boneMap).length);
      buildSliders();
      libraryUI = mountMotionLibrary({
        container: document.getElementById("motion-library"),
        rig,
        getFrames: () => {
          if (isRecording) window.toggleRecord();
          return keyframes;
        },
        load: (asset) => {
          if (isRecording) window.toggleRecord();
          stopPreview();
          keyframes.splice(
            0,
            keyframes.length,
            ...globalThis.structuredClone(asset.frames),
          );
          window.selectKeyframe(0);
        },
        preview: (asset) => {
          stopPreview();
          player.stop({ reset: true });
          player.play(asset);
        },
        output: (text) => {
          document.getElementById("export-box").value = text;
        },
      });
    } catch (error) {
      player?.stop();
      scene.remove(modelRoot);
      disposeModel(modelRoot);
      modelRoot = null;
      rig = null;
      modelError(error);
    }
  },
  undefined,
  modelError,
);

function animate() {
  animationFrame = requestAnimationFrame(animate);
  controls?.update();
  if (renderer && scene && camera) renderer.render(scene, camera);
}
animate();

// Bone sliders
function compactBoneName(name) {
  return name
    .replace(/^right/, "R.")
    .replace(/^left/, "L.")
    .replace("Metacarpal", ".0")
    .replace("Proximal", ".1")
    .replace("Intermediate", ".2")
    .replace("Distal", ".3");
}

function buildSliders() {
  const div = document.getElementById("bone-sliders");
  let html = "";
  BONE_LIST.forEach((name) => {
    const bm = boneMap[name];
    if (!bm) {
      html +=
        '<div class="bone-row"><span class="bone-name" style="color:#f00">' +
        name +
        " MISS</span></div>";
      return;
    }
    ["x", "y", "z"].forEach((k) => {
      const id = "sl_" + name + "_" + k;
      html += '<div class="bone-row">';
      html +=
        '<span class="bone-name">' +
        compactBoneName(name) +
        "." +
        k +
        "</span>";
      html +=
        '<input type="range" id="' +
        id +
        '" data-bone="' +
        name +
        '" data-key="' +
        k +
        '" min="-3.2" max="3.2" step="0.01" value="' +
        bm.rotation[k].toFixed(2) +
        '">';
      html +=
        '<span id="' + id + '_v">' + bm.rotation[k].toFixed(2) + "</span>";
      html += "</div>";
    });
  });
  div.innerHTML = html;
  div.querySelectorAll('input[type="range"]').forEach((input) => {
    input.addEventListener("input", (event) => {
      window._slide(
        event.target.dataset.bone,
        event.target.dataset.key,
        event.target.value,
      );
    });
  });
}

window._slide = function (name, key, val) {
  player?.stop();
  const b = boneMap[name];
  if (!b) return;
  b.rotation[key] = parseFloat(val);
  rig?.update();
  const vEl = document.getElementById("sl_" + name + "_" + key + "_v");
  if (vEl) vEl.textContent = parseFloat(val).toFixed(2);
};

function resetBones() {
  stopPreview();
  rig?.reset();
  buildSliders();
}
window.resetBones = resetBones;

// Recording
window.toggleRecord = function () {
  if (!rig) {
    document.getElementById("rec-status").textContent = t(
      "motionModelNotReady",
    );
    return;
  }
  player?.stop();
  const btn = document.getElementById("btn-record");
  isRecording = !isRecording;
  if (isRecording) {
    btn.textContent = "⏺ 录制中... (每0.3s自动抓帧)";
    btn.classList.add("active");
    document.getElementById("rec-status").textContent = "🟥 录制中";
    recordTimer = setInterval(window.addKeyframe, 300);
  } else {
    btn.textContent = "⏺ 开始录制";
    btn.classList.remove("active");
    document.getElementById("rec-status").textContent = "空闲";
    clearInterval(recordTimer);
  }
};

window.addKeyframe = function () {
  if (!rig) {
    document.getElementById("rec-status").textContent = t(
      "motionModelNotReady",
    );
    return;
  }
  if (keyframes.length >= MAX_MOTION_FRAMES) {
    if (isRecording) window.toggleRecord();
    document.getElementById("rec-status").textContent = t("motionFrameLimit");
    return;
  }
  player?.stop();
  const duration = isRecording ? 0.3 : Number(durationInput.value);
  if (!validDuration(duration)) return;
  const value = rig.capturePose();
  keyframes.push({ duration, value });
  renderKeyframes();
};

function renderKeyframes() {
  const div = document.getElementById("keyframes");
  document.getElementById("kf-count").textContent = keyframes.length;
  let html = "";
  let elapsed = 0;
  keyframes.forEach((kf, i) => {
    html +=
      '<div class="kf' +
      (i === currentFrame ? " active" : "") +
      '" data-index="' +
      i +
      '">';
    html += "#" + i + " t=" + elapsed.toFixed(2) + "s";
    html += "</div>";
    elapsed += kf.duration;
  });
  div.innerHTML = html;
  div.querySelectorAll("[data-index]").forEach((element) => {
    element.addEventListener("click", () =>
      window.selectKeyframe(Number(element.dataset.index)),
    );
  });

  const tl = document.getElementById("preview-timeline");
  tl.innerHTML = keyframes
    .map(
      (_, i) =>
        '<div class="tick' +
        (i === currentFrame ? " active" : "") +
        '" data-index="' +
        i +
        '">' +
        (i + 1) +
        "</div>",
    )
    .join("");
  tl.querySelectorAll("[data-index]").forEach((element) => {
    element.addEventListener("click", () =>
      window.selectKeyframe(Number(element.dataset.index)),
    );
  });
}
window.renderKeyframes = renderKeyframes;

window.selectKeyframe = function (idx) {
  player?.stop();
  currentFrame = idx;
  const kf = keyframes[idx];
  if (!kf) {
    renderKeyframes();
    return;
  }
  rig?.applyPose(kf.value);
  durationInput.value = kf.duration;
  buildSliders();
  renderKeyframes();
};

function applyToCurrent() {
  if (currentFrame < 0 || currentFrame >= keyframes.length) return;
  const duration = Number(durationInput.value);
  if (!validDuration(duration)) return;
  player?.stop();
  const pose = rig.capturePose();
  keyframes[currentFrame] = { value: pose, duration };
  renderKeyframes();
}
window.applyToCurrent = applyToCurrent;

function deleteKeyframe() {
  player?.stop();
  if (currentFrame < 0) return;
  keyframes.splice(currentFrame, 1);
  window.selectKeyframe(Math.min(currentFrame, keyframes.length - 1));
}
window.deleteKeyframe = deleteKeyframe;

function clearKeyframes() {
  if (isRecording) window.toggleRecord();
  player?.stop();
  keyframes.length = 0;
  currentFrame = -1;
  renderKeyframes();
}
window.clearKeyframes = clearKeyframes;

// Preview
window.previewAnimation = function () {
  if (!rig || !keyframes.length) return;
  if (isRecording) window.toggleRecord();
  stopPreview();
  player.stop({ reset: true });
  player.play(keyframes);
};

function stopPreview() {
  player?.stop();
  currentFrame = -1;
  renderKeyframes();
}
window.stopPreview = stopPreview;

// Export
window.exportAsCode = function () {
  const asset = libraryUI?.capture();
  if (!asset) return;
  document.getElementById("export-box").value =
    "const motion = " + JSON.stringify(asset, null, 2) + ";";
};

window.exportAsJSON = function () {
  libraryUI?.exportJson();
};

window.copyToClipboard = function () {
  const box = document.getElementById("export-box");
  box.select();
  document.execCommand("copy");
};

document
  .getElementById("btn-record")
  .addEventListener("click", window.toggleRecord);
document
  .getElementById("btn-add-keyframe")
  .addEventListener("click", window.addKeyframe);
document
  .getElementById("btn-preview")
  .addEventListener("click", window.previewAnimation);
document
  .getElementById("btn-stop-preview")
  .addEventListener("click", window.stopPreview);
document
  .getElementById("btn-delete-keyframe")
  .addEventListener("click", window.deleteKeyframe);
document
  .getElementById("btn-clear-keyframes")
  .addEventListener("click", window.clearKeyframes);
document
  .getElementById("btn-apply-keyframe")
  .addEventListener("click", window.applyToCurrent);
document.getElementById("btn-apply-keyframe").textContent =
  t("motionUpdateFrame");
document
  .getElementById("btn-reset-bones")
  .addEventListener("click", window.resetBones);
document.getElementById("btn-export-code").addEventListener("click", () => {
  try {
    window.exportAsCode();
  } catch (error) {
    libraryUI?.report(error);
  }
});
document.getElementById("btn-export-json").addEventListener("click", () => {
  try {
    window.exportAsJSON();
  } catch (error) {
    libraryUI?.report(error);
  }
});
document
  .getElementById("btn-copy")
  .addEventListener("click", window.copyToClipboard);

console.log(
  "🎬 录制器就绪。点击'开始录制'，手动调整骨骼，自动每0.3秒抓取关键帧。",
);

const durationLabel = document.createElement("label");
durationLabel.textContent = t("motionFrameDuration");
durationLabel.htmlFor = "motion-frame-duration";
const durationInput = document.createElement("input");
durationInput.id = "motion-frame-duration";
durationInput.type = "number";
durationInput.min = "0.05";
durationInput.max = "10";
durationInput.step = "0.05";
durationInput.value = "0.3";
document
  .getElementById("preview-timeline")
  .before(durationLabel, durationInput);
function validDuration(duration) {
  const valid = Number.isFinite(duration) && duration >= 0.05 && duration <= 10;
  if (!valid)
    document.getElementById("rec-status").textContent = t(
      "motionDurationInvalid",
    );
  return valid;
}
durationInput.addEventListener("change", () => {
  const duration = Number(durationInput.value);
  if (!validDuration(duration)) return;
  player?.stop();
});
window.addEventListener(
  "pagehide",
  () => {
    disposed = true;
    clearInterval(recordTimer);
    player?.stop();
    libraryUI?.dispose();
    cancelAnimationFrame(animationFrame);
    controls?.dispose();
    disposeModel(modelRoot);
    renderer.dispose();
  },
  { once: true },
);
