import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { disposeModel } from "../avatar/dispose-model.js";
import { SIGNS } from "../avatar/sign-language-data.js";
import {
  validateT08Bundle,
  validateT08CandidateBundle,
} from "./demo-motion.js";
import { createT08Retarget } from "./demo-retarget.js";
import { frameDelta } from "./demo-playback.js";
const container = document.querySelector("#stage");
let renderer,
  rig,
  modelRoot,
  camera,
  scene,
  bundle,
  candidateBundle,
  retarget,
  raf = null,
  ready = false,
  disposed = false;
let running = false,
  paused = false,
  speed = 1,
  plan = [],
  itemIndex = 0,
  itemTime = 0,
  lastTime = 0,
  track = null,
  duration = 0,
  requestId = 0;
const cache = new Map();
const notify = (type, data = {}) =>
  parent.postMessage(
    { source: "signbridge-demo-avatar", type, requestId, ...data },
    location.origin,
  );
function stop(reset = true) {
  running = false;
  paused = false;
  plan = [];
  track = null;
  itemTime = 0;
  if (reset) rig?.reset();
  notify("STOPPED");
}
function setView(view) {
  const center = new THREE.Vector3(0, 1.29, 0);
  const offset =
    view === "left"
      ? new THREE.Vector3(1.95, 0.02, 0.35)
      : view === "right"
        ? new THREE.Vector3(-1.95, 0.02, 0.35)
        : new THREE.Vector3(0, 0.02, 1.8);
  camera.position.copy(center).add(offset);
  camera.lookAt(center);
  camera.updateProjectionMatrix();
}
function builtInTrack(sign) {
  const from = rig.capture();
  const samples = [],
    times = [];
  let time = 0;
  for (const f of sign.frames) {
    time += f.duration;
    times.push(time);
    samples.push(rig.createTargets(f.value));
  }
  return { kind: "dictionary", samples, times, from, duration: time };
}
function nextItem() {
  if (itemIndex >= plan.length) {
    running = false;
    track = null;
    rig.reset();
    notify("FINISHED");
    return;
  }
  const item = plan[itemIndex];
  itemTime = 0;
  if (item.source === "t08" || item.source === "candidate") {
    const clip = (
      item.source === "candidate" ? candidateBundle?.clips : bundle?.clips
    )?.find((c) => c.id === item.id);
    if (!clip) throw new Error("demoInvalidAsset");
    if (!cache.has(clip.id)) cache.set(clip.id, retarget.compile(clip));
    track = {
      kind: item.source,
      samples: cache.get(clip.id),
      fps: clip.fps,
      clip,
    };
    duration = clip.frames / clip.fps;
  } else {
    const sign = SIGNS[item.id];
    if (item.source !== "dictionary" || !sign)
      throw new Error("demoInvalidAsset");
    track = builtInTrack(sign);
    duration = track.duration;
  }
  notify("CURRENT", {
    item,
    itemIndex,
    count: plan.length,
    duration,
    tokens: track.clip?.tokens || null,
    normalizedReconstructionMse:
      track.kind === "candidate"
        ? track.clip.normalized_reconstruction_mse
        : null,
  });
}
function applyAt(time) {
  if (track.kind === "t08" || track.kind === "candidate") {
    const frame = Math.min(time * track.fps, track.samples.length - 1),
      i = Math.floor(frame),
      j = Math.min(i + 1, track.samples.length - 1);
    rig.interpolate(track.samples[i], track.samples[j], frame - i);
  } else {
    let idx = track.times.findIndex((t) => time < t);
    if (idx < 0) idx = track.samples.length - 1;
    const start = idx === 0 ? 0 : track.times[idx - 1];
    const from = idx === 0 ? track.from : track.samples[idx - 1];
    rig.interpolate(
      from,
      track.samples[idx],
      Math.min(
        1,
        (time - start) / Math.min(0.15, (track.times[idx] - start) * 0.35),
      ),
    );
  }
}
function tick(time) {
  if (disposed) return;
  const delta = frameDelta(time, lastTime);
  lastTime = time;
  if (running && !paused && track) {
    itemTime += delta * speed;
    if (itemTime >= duration) {
      itemIndex++;
      try {
        nextItem();
      } catch (e) {
        stop();
        notify("ERROR", { error: e.message });
      }
    }
    if (track) {
      applyAt(itemTime);
      notify("PROGRESS", { elapsed: itemTime, duration, itemIndex });
    }
  }
  renderer?.render(scene, camera);
  raf = requestAnimationFrame(tick);
}
function resize() {
  if (!renderer) return;
  const w = container.clientWidth,
    h = container.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
async function init() {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0xe4ebee);
    container.appendChild(renderer.domElement);
    scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0xa2aca8, 2.0));
    const key = new THREE.DirectionalLight(0xfff5df, 2.6);
    key.position.set(2, 4, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 1.2);
    fill.position.set(-3, 2, 1);
    scene.add(fill);
    camera = new THREE.PerspectiveCamera(34, 1, 0.05, 30);
    setView("front");
    resize();
    const gltf = await new GLTFLoader().loadAsync("../avatar/model.glb");
    modelRoot = gltf.scene;
    if (disposed) {
      disposeModel(modelRoot);
      return;
    }
    scene.add(modelRoot);
    rig = createHumanoidRig(modelRoot);
    if (!rig.isSigningReady) throw new Error("demoMissingBone");
    try {
      const response = await fetch("t08-motion.json");
      if (!response.ok) throw new Error("demoInvalidAsset");
      bundle = validateT08Bundle(await response.json());
      retarget = createT08Retarget(rig, modelRoot, bundle);
    } catch (e) {
      bundle = null;
      retarget = null;
      notify("ASSET_WARNING", { error: e.message });
    }
    try {
      const response = await fetch("t08-candidates.json");
      if (!response.ok) throw new Error("demoInvalidCandidateAsset");
      candidateBundle = validateT08CandidateBundle(await response.json());
      retarget ||= createT08Retarget(rig, modelRoot, candidateBundle);
    } catch (e) {
      candidateBundle = null;
      notify("ASSET_WARNING", { error: e.message });
    }
    if (disposed) return;
    ready = true;
    notify("READY", {
      modelAvailable: Boolean(bundle || candidateBundle),
      mappedBones: retarget?.mappedBones || 0,
      clipCount: bundle?.clips.length || 0,
      candidateCount: candidateBundle?.clips.length || 0,
    });
    lastTime = performance.now();
    raf = requestAnimationFrame(tick);
  } catch (e) {
    notify("ERROR", { error: e.message || String(e), fatal: true });
  }
}
window.addEventListener("message", (ev) => {
  if (
    ev.source !== parent ||
    ev.origin !== location.origin ||
    ev.data?.source !== "signbridge-demo"
  )
    return;
  const { type } = ev.data;
  if (type === "HELLO") {
    if (ready)
      notify("READY", {
        modelAvailable: Boolean(bundle || candidateBundle),
        mappedBones: retarget?.mappedBones || 0,
        clipCount: bundle?.clips.length || 0,
        candidateCount: candidateBundle?.clips.length || 0,
      });
    return;
  }
  if (!ready) return;
  try {
    if (type === "PLAY" || type === "STOP") {
      if (
        !Number.isSafeInteger(ev.data.requestId) ||
        ev.data.requestId < requestId
      )
        return;
      requestId = ev.data.requestId;
    }
    if (type === "PLAY") {
      const items = ev.data.items;
      if (!Array.isArray(items) || !items.length || items.length > 40)
        throw new Error("demoInvalidAsset");
      stop();
      plan = items;
      itemIndex = 0;
      running = true;
      paused = false;
      nextItem();
      lastTime = performance.now();
    } else if (type === "STOP") stop();
    else if (type === "PAUSE") {
      if (!running) return;
      paused = !paused;
      notify("PAUSED", { paused });
    } else if (type === "SPEED") {
      if (![0.5, 0.75, 1, 1.25, 1.5].includes(Number(ev.data.speed)))
        throw new Error("demoInvalidMode");
      speed = Number(ev.data.speed);
    } else if (type === "VIEW") {
      if (!["front", "left", "right"].includes(ev.data.view))
        throw new Error("demoInvalidMode");
      setView(ev.data.view);
    }
  } catch (e) {
    stop();
    notify("ERROR", { error: e.message });
  }
});
window.addEventListener("resize", resize);
window.addEventListener(
  "pagehide",
  () => {
    disposed = true;
    running = false;
    if (raf !== null) cancelAnimationFrame(raf);
    disposeModel(modelRoot);
    renderer?.dispose();
    cache.clear();
  },
  { once: true },
);
init();
