import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createRigBinding } from "../avatar/motion-asset.js";
import { createMotionPlayer } from "../avatar/motion-player.js";
import { disposeModel } from "../avatar/dispose-model.js";
import {
  REVIEW_CELL,
  REVIEW_VIEWS,
  REVIEW_PROTOCOL,
  reviewHash,
} from "../avatar/motion-review.js";

async function createReviewStage(canvas, signal) {
  const response = await fetch(chrome.runtime.getURL("avatar/model.glb"), {
    signal,
  });
  if (!response.ok) throw new Error("reviewModelError");
  const bytes = await response.arrayBuffer();
  const modelHash = await reviewHash(bytes);
  signal.throwIfAborted();
  const gltf = await new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    new GLTFLoader().parseAsync(bytes, chrome.runtime.getURL("avatar/")).then(
      (loaded) => {
        signal.removeEventListener("abort", abort);
        if (signal.aborted) disposeModel(loaded.scene);
        else resolve(loaded);
      },
      (error) => {
        signal.removeEventListener("abort", abort);
        reject(error);
      },
    );
  });
  const model = gltf.scene;
  let renderer;
  try {
    signal.throwIfAborted();
    const rig = createHumanoidRig(model);
    if (!rig.isSigningReady) throw new Error("reviewMissingBones");
    const binding = createRigBinding(rig);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#e9f2f8");
    scene.add(model);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x667080, 2.2));
    const light = new THREE.DirectionalLight(0xffffff, 2.5);
    light.position.set(3, 5, 4);
    scene.add(light);
    model.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(model);
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    if (!Number.isFinite(size.y) || size.y <= 0)
      throw new Error("reviewModelError");
    const span = Math.max(
      size.y * 0.9,
      (size.x * 1.1 * REVIEW_CELL.height) / REVIEW_CELL.width,
    );
    const target = center.clone();
    target.y += size.y * 0.17;
    const halfWidth = (span * REVIEW_CELL.width) / REVIEW_CELL.height / 2;
    const camera = new THREE.OrthographicCamera(
      -halfWidth,
      halfWidth,
      span / 2,
      -span / 2,
      size.y * 0.01,
      size.y * 20,
    );
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(1);
    renderer.setSize(REVIEW_CELL.width, REVIEW_CELL.height, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const context = renderer.getContext();
    const debug = context.getExtension("WEBGL_debug_renderer_info");
    const environment = {
      protocol: REVIEW_PROTOCOL,
      modelHash,
      binding,
      threeRevision: THREE.REVISION,
      cell: REVIEW_CELL,
      views: REVIEW_VIEWS,
      camera: { span, target: target.toArray() },
      userAgent: navigator.userAgent,
      renderer: context.getParameter(
        debug ? debug.UNMASKED_RENDERER_WEBGL : context.RENDERER,
      ),
      vendor: context.getParameter(
        debug ? debug.UNMASKED_VENDOR_WEBGL : context.VENDOR,
      ),
    };
    const environmentHash = await reviewHash(environment);
    signal.throwIfAborted();
    let view = "front";
    let pending = null;
    let renderFrame = null;
    let disposed = false;

    function render(nextView = view) {
      if (disposed || context.isContextLost())
        throw new Error("reviewRenderError");
      view = nextView;
      camera.position.copy(target);
      if (view === "front") camera.position.z += size.y * 3;
      else camera.position.x += size.y * (view === "right" ? -3 : 3);
      camera.lookAt(target);
      renderer.render(scene, camera);
    }

    function endPlayback(error) {
      if (renderFrame !== null) cancelAnimationFrame(renderFrame);
      renderFrame = null;
      const completion = pending;
      pending = null;
      if (error) completion?.reject(error);
      else completion?.resolve();
    }

    const player = createMotionPlayer(rig, {
      onComplete: () => {
        try {
          render();
          endPlayback();
        } catch (error) {
          endPlayback(error);
        }
      },
    });

    function stop() {
      player.stop({ reset: true });
      endPlayback(new globalThis.DOMException("Aborted", "AbortError"));
    }

    function play(frames, abortSignal) {
      stop();
      abortSignal.throwIfAborted();
      abortSignal.addEventListener("abort", stop, { once: true });
      return new Promise((resolve, reject) => {
        pending = { resolve, reject };
        function tick() {
          try {
            render();
            if (player.isPlaying) renderFrame = requestAnimationFrame(tick);
          } catch (error) {
            player.stop();
            endPlayback(error);
          }
        }
        player.play(frames);
        tick();
      }).finally(() => abortSignal.removeEventListener("abort", stop));
    }

    function dispose() {
      stop();
      disposed = true;
      disposeModel(model);
      renderer.dispose();
    }
    render();
    return {
      rig,
      environment,
      environmentHash,
      render,
      play,
      stop,
      dispose,
      canvas,
    };
  } catch (error) {
    disposeModel(model);
    renderer?.dispose();
    throw error;
  }
}

async function captureReviewSheet(stage, frames, indices, signal) {
  const sheet = document.createElement("canvas");
  sheet.width = REVIEW_CELL.width * REVIEW_VIEWS.length;
  sheet.height = REVIEW_CELL.height * indices.length;
  const drawing = sheet.getContext("2d", { willReadFrequently: true });
  try {
    stage.stop();
    for (const [row, frameIndex] of indices.entries()) {
      signal.throwIfAborted();
      stage.rig.applyPose(frames[frameIndex].value);
      for (const [column, view] of REVIEW_VIEWS.entries()) {
        stage.render(view);
        drawing.drawImage(
          stage.canvas,
          column * REVIEW_CELL.width,
          row * REVIEW_CELL.height,
        );
      }
      await new Promise((resolve) => {
        requestAnimationFrame(resolve);
      });
    }
    signal.throwIfAborted();
    const image = await new Promise((resolve) => {
      sheet.toBlob(resolve, "image/png");
    });
    if (!image) throw new Error("reviewRenderError");
    return { image, width: sheet.width, height: sheet.height };
  } finally {
    sheet.width = sheet.height = 0;
    stage.rig.reset();
    stage.render("front");
  }
}

export { createReviewStage, captureReviewSheet };
