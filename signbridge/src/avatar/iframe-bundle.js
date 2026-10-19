import { createMotionCache } from "../demo/motion-cache.js";
// BUILD: 1784252939651
/**
 * SignBridge v17 — Multi-site + structured gestures + eased blending
 * Godette模型: 227骨骼, 正确骨骼名映射
 */
import * as THREE from "./three.module.js";
import { GLTFLoader } from "./jsm/loaders/GLTFLoader.js";
import { createHumanoidRig } from "./humanoid-rig.js";
import { createMotionPlayer } from "./motion-player.js";
import {
  normalizeText,
  translateText,
  compileTranslationMatchers,
} from "./sign-language-data.js";
import { createMotionLibrary, selectEnabledMotions } from "./motion-library.js";
import { t, setLocale } from "../i18n/locales.js";
import {
  T08_CHECKPOINT_SHA256,
  validateT08CandidateBundle,
  validateT08Bundle,
} from "./reference-motion-asset.js";
import { createT08Retarget } from "../demo/demo-retarget.js";
import {
  validateExperimentalIndex,
  createExperimentalLoader,
} from "../demo/experimental-motion.js";
import { planRealtimeText } from "./runtime-motion-plan.js";
import { MOTION_SMOOTHING_PROFILE } from "../demo/motion-stabilization.js";

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
let translationMatchers = compileTranslationMatchers();
let unsubscribeMotions = null;
let motionLibraryVersion = 0;
let motionLibraryIdentity = "[]";
let t08ReferenceClips = [];
let t08MotionBundlePromise = null;
let t08CandidateBundlePromise = null;
let t08Retarget = null;
let t08CandidateRetarget = null;
let experimentalLoader = null;
let experimentalRetarget = null;
const t08TrackCache = createMotionCache({ maxEntries: 12, maxValues: 500000 });
let translationQueue = Promise.resolve();
let translationGeneration = 0;

async function loadT08ReferenceIndex() {
  try {
    const response = await fetch(
      chrome.runtime.getURL("avatar/t08-index.json"),
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const index = await response.json();
    if (
      index?.schema !== "signbridge-t08-runtime-index-v1" ||
      index.checkpoint_sha256 !== T08_CHECKPOINT_SHA256 ||
      ![14, 17].includes(index.clips?.length) ||
      index.clips?.filter((clip) => !clip.runtime_candidate).length !== 14 ||
      !index.clips.every(
        (clip) =>
          typeof clip.id === "string" &&
          typeof clip.text === "string" &&
          Array.isArray(clip.aliases) &&
          Number.isFinite(clip.fps) &&
          Number.isInteger(clip.frames) &&
          typeof clip.runtime_candidate === "boolean",
      )
    )
      throw new Error("T08 reference index provenance is invalid");
    t08ReferenceClips = index.clips;
    console.info(
      "[SB] T08 runtime index ready:",
      t08ReferenceClips.filter((clip) => !clip.runtime_candidate).length,
      "reference +",
      t08ReferenceClips.filter((clip) => clip.runtime_candidate).length,
      "candidate phrases",
    );
  } catch (error) {
    t08ReferenceClips = [];
    console.warn("[SB] T08 index unavailable; dictionary fallback:", error);
  }
  try {
    const response = await fetch(
      chrome.runtime.getURL("demo/experimental-index.json"),
    );
    if (!response.ok) throw new Error("Experimental index unavailable");
    const data = await response.json();
    if (!data.unavailable) {
      const index = validateExperimentalIndex(data);
      experimentalLoader = createExperimentalLoader(index, (path) =>
        fetch(chrome.runtime.getURL("demo/" + path)),
      );
      experimentalRetarget = createT08Retarget(rig, modelRoot, index);
      t08ReferenceClips.push(...index.clips);
      console.info(
        "[SB] Experimental fitted motions ready:",
        index.clips.length,
      );
    }
  } catch (error) {
    console.warn(
      "[SB] Experimental motions unavailable; dictionary fallback:",
      error,
    );
  }
}

function loadT08MotionBundle() {
  if (!t08MotionBundlePromise) {
    const pending = (async () => {
      const response = await fetch(
        chrome.runtime.getURL("demo/t08-motion.json"),
      );
      if (!response.ok) throw new Error(`T08 asset HTTP ${response.status}`);
      const bundle = validateT08Bundle(await response.json());
      if (bundle.checkpoint_sha256 !== T08_CHECKPOINT_SHA256)
        throw new Error("T08 checkpoint differs from the runtime index");
      t08Retarget = createT08Retarget(rig, modelRoot, bundle);
      console.info("[SB] T08 token-decoded motion asset loaded");
      return bundle;
    })();
    t08MotionBundlePromise = pending.catch((error) => {
      t08MotionBundlePromise = null;
      throw error;
    });
  }
  return t08MotionBundlePromise;
}

function loadT08CandidateBundle() {
  if (!t08CandidateBundlePromise) {
    const pending = (async () => {
      const response = await fetch(
        chrome.runtime.getURL("demo/t08-candidates.json"),
      );
      if (!response.ok)
        throw new Error(`T08 candidate HTTP ${response.status}`);
      const bundle = validateT08CandidateBundle(await response.json());
      t08CandidateRetarget = createT08Retarget(rig, modelRoot, bundle);
      console.info(
        "[SB] T08 motion candidate asset loaded:",
        bundle.clips.length,
      );
      return bundle;
    })();
    t08CandidateBundlePromise = pending.catch((error) => {
      t08CandidateBundlePromise = null;
      throw error;
    });
  }
  return t08CandidateBundlePromise;
}

async function loadMotionLibrary() {
  try {
    const library = createMotionLibrary(rig);
    async function refresh() {
      const version = ++motionLibraryVersion;
      try {
        const { entries, invalidCount } = await library.list();
        if (version !== motionLibraryVersion || !modelReady) return;
        const motions = selectEnabledMotions(entries);
        const identity = JSON.stringify(motions);
        if (identity !== motionLibraryIdentity) {
          translationGeneration += 1;
          translationQueue = Promise.resolve();
          motionPlayer?.stop({ reset: true });
          translationMatchers = compileTranslationMatchers(motions);
          motionLibraryIdentity = identity;
        }
        console.log("[SB] Motion library:", {
          enabled: motions.length,
          invalid: invalidCount,
        });
      } catch (error) {
        if (version !== motionLibraryVersion) return;
        translationGeneration += 1;
        translationQueue = Promise.resolve();
        motionPlayer?.stop({ reset: true });
        translationMatchers = compileTranslationMatchers();
        motionLibraryIdentity = "[]";
        console.warn("[SB] Motion library unavailable:", error.message);
      }
    }
    unsubscribeMotions = library.subscribe(refresh);
    await refresh();
  } catch (error) {
    console.warn("[SB] Motion library unavailable:", error.message);
  }
}

// ===== 字幕 → 手语 =====

function textToAnimation(text, manual = false) {
  if (!text || !modelReady) return false;
  if (manual) {
    translationGeneration++;
    translationQueue = Promise.resolve();
    motionPlayer?.stop({ reset: true });
  }
  const generation = translationGeneration;
  const plan = planRealtimeText(text, t08ReferenceClips, translationMatchers);
  console.info("[SB] Realtime motion plan:", {
    items: plan.items.map(({ id, source, text }) => ({ id, source, text })),
    unmatched: plan.unmatched,
    truncated: plan.truncated,
    remainingText: plan.remainingText,
  });
  if (!plan.items.length) return false;
  const route = async () => {
    if (!modelReady || generation !== translationGeneration) return;
    const motions = [];
    for (const item of plan.items) {
      if (item.source === "dictionary") {
        const motion = dictionaryMotion(item.text, item.translation);
        if (motion) motions.push(motion);
        continue;
      }
      try {
        const sourceType = item.source;
        const motionBundle =
          sourceType === "experimental"
            ? null
            : sourceType === "candidate"
              ? await loadT08CandidateBundle()
              : await loadT08MotionBundle();
        const clip =
          sourceType === "experimental"
            ? await experimentalLoader.load(item.id)
            : motionBundle.clips.find((candidate) => candidate.id === item.id);
        if (!modelReady || generation !== translationGeneration) return;
        if (!clip) throw new Error("T08 clip is missing from its motion asset");
        const compiled = t08TrackCache.get(`${sourceType}:${clip.id}`, () =>
          (sourceType === "experimental"
            ? experimentalRetarget
            : sourceType === "candidate"
              ? t08CandidateRetarget
              : t08Retarget
          ).compile(clip),
        );
        motions.push({
          type: "quaternion-track",
          samples: compiled.frames,
          fps: clip.fps,
          duration: clip.frames / clip.fps,
          sourceInfo: {
            sourceType,
            referenceId: clip.id,
            modelOutput: clip.model_output,
            presentation: clip.experimental
              ? clip.display_stabilization_profile || MOTION_SMOOTHING_PROFILE
              : "raw",
            frames: clip.frames,
            performance: {
              cacheHit: compiled.cacheHit,
              compileMs: compiled.compileMs,
              numericCacheBytes: t08TrackCache.stats().numericBytes,
            },
            matchedText: item.text,
            label: t(
              sourceType === "experimental"
                ? clip.quality_warning
                  ? "demoExperimentalSmoothedWarningBadge"
                  : "demoExperimentalSmoothedBadge"
                : sourceType === "candidate"
                  ? "demoCandidateBadge"
                  : "demoSourceT08",
            ),
          },
        });
      } catch (error) {
        console.warn(
          "[SB] T08 playback unavailable; using dictionary:",
          item.id,
          error,
        );
        if (!modelReady || generation !== translationGeneration) return;
        const fallback = dictionaryMotion(
          item.text,
          translateText(item.text, 12, translationMatchers),
          item.id,
          error.message,
        );
        if (fallback) motions.push(fallback);
      }
    }
    if (!modelReady || generation !== translationGeneration || !motions.length)
      return;
    const motion = { type: "motion-sequence", motions };
    if (manual) motionPlayer?.play(motion);
    else
      motionPlayer?.enqueue(motion, { key: normalizeText(text).toLowerCase() });
  };
  const next = translationQueue.then(route, route);
  translationQueue = next.catch((error) => {
    console.error("[SB] Realtime motion dispatch failed:", error);
  });
  return true;
}

function dictionaryMotion(
  text,
  result,
  referenceId = null,
  fallbackReason = null,
) {
  if (!result?.matches.length) return null;
  console.log("[SB] Translation coverage:", {
    matches: result.matches.map((match) => match.text),
    motionIds: result.matches.map((match) => match.id),
    unmatched: result.unmatched,
    truncated: result.truncated,
    remainingText: result.remainingText,
  });
  return {
    frames: result.frames,
    sourceInfo: {
      sourceType: "dictionary",
      referenceId,
      matchedText: text,
      fallbackReason,
      label: t(fallbackReason ? "demoSourceFallback" : "demoSourceDictionary"),
    },
  };
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
    async (gltf) => {
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
      motionPlayer = createMotionPlayer(rig, {
        onMotionStart(info) {
          console.info(
            "[SB] Realtime motion source:",
            info.sourceType,
            info.referenceId,
          );
          notify("MOTION_SOURCE", info);
        },
      });
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

      await loadT08ReferenceIndex();
      if (!modelRoot) return;
      modelReady = true;
      modelLoading = false;
      await loadMotionLibrary();
      if (!modelReady) return;
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
      setLocale(
        ev.data.config?.uiLocale === "auto" ? null : ev.data.config?.uiLocale,
      );
      init(ev.data.modelUrl);
      break;
    case "SUBTITLE_TEXT":
      if (modelReady && ev.data.text) {
        textToAnimation(ev.data.text, ev.data.manual === true);
      }
      break;
    case "PLAYBACK_RESET":
      translationGeneration += 1;
      translationQueue = Promise.resolve();
      motionPlayer?.stop({ reset: true });
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
  modelReady = false;
  translationGeneration += 1;
  translationQueue = Promise.resolve();
  motionLibraryVersion += 1;
  unsubscribeMotions?.();
  motionPlayer?.stop();
  if (renderFrameId) cancelAnimationFrame(renderFrameId);
  if (breathingFrameId) cancelAnimationFrame(breathingFrameId);
  if (blinkTimerId) clearTimeout(blinkTimerId);
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
  t08TrackCache.clear();
  t08Retarget = null;
  t08CandidateRetarget = null;
  t08MotionBundlePromise = null;
  t08CandidateBundlePromise = null;
  experimentalLoader?.clear();
  experimentalLoader = null;
  experimentalRetarget = null;
  rig = null;
  modelRoot = null;
  renderer?.dispose();
}
console.log("[SB] v17 — multi-site + structured gestures + eased blending");
