// Offline audit renderer: exact frame sampling, no animation or source mutation.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createT08Retarget } from "../demo/demo-retarget.js";

window.auditReady = false;
window.startAuditRenderer = async (bundle, modelUrl) => {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    preserveDrawingBuffer: true,
  });
  renderer.setSize(640, 520);
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0xe4ebee);
  document.body.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0xa2aca8, 2));
  const key = new THREE.DirectionalLight(0xfff5df, 2.6);
  key.position.set(2, 4, 4);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 1.2);
  fill.position.set(-3, 2, 1);
  scene.add(fill);
  const camera = new THREE.PerspectiveCamera(34, 640 / 520, 0.05, 30);
  camera.position.set(0, 1.31, 1.8);
  camera.lookAt(0, 1.29, 0);
  const model = (await new GLTFLoader().loadAsync(modelUrl)).scene;
  scene.add(model);
  const rig = createHumanoidRig(model),
    retarget = createT08Retarget(rig, model, bundle);
  if (!rig.isSigningReady)
    throw new Error("Missing signing bones in audit model");
  window.captureAuditFrames = (clip, samples) => {
    const raw = retarget.compile(clip, { stabilize: false });
    const display = retarget.compile(clip, {
      stabilize: clip.experimental === true,
    });
    return samples.flatMap((number) =>
      [raw, display].map((track, side) => {
        rig.interpolate(track[number - 1], track[number - 1], 1);
        model.updateMatrixWorld(true);
        renderer.render(scene, camera);
        return {
          frame_1based: number,
          mode: side ? "current_display" : "raw",
          image: renderer.domElement.toDataURL("image/jpeg", 0.88),
        };
      }),
    );
  };
  window.disposeAuditRenderer = () => {
    model.traverse((node) => {
      node.geometry?.dispose();
      const materials = Array.isArray(node.material)
        ? node.material
        : [node.material];
      for (const material of materials)
        if (material) {
          for (const value of Object.values(material))
            if (value?.isTexture) value.dispose();
          material.dispose();
        }
    });
    renderer.dispose();
    renderer.forceContextLoss();
  };
  window.auditReady = true;
};
