import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { decodeNativeClip } from "../demo/native-motion.js";
import { disposeModel } from "../avatar/dispose-model.js";
const renderer = new THREE.WebGLRenderer({
  antialias: true,
  preserveDrawingBuffer: true,
});
renderer.setSize(640, 600);
renderer.setClearColor(0xe4ebee);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.append(renderer.domElement);
const scene = new THREE.Scene();
scene.add(new THREE.HemisphereLight(0xffffff, 0xa2aca8, 2));
const key = new THREE.DirectionalLight(0xfff5df, 2.6);
key.position.set(2, 4, 4);
scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 1.2);
fill.position.set(-3, 2, 1);
scene.add(fill);
const camera = new THREE.PerspectiveCamera(34, 640 / 600, 0.05, 30);
camera.position.set(0, 1.29, 1.85);
camera.lookAt(0, 1.29, 0);
const gltf = await new GLTFLoader().loadAsync("/model.glb"),
  model = gltf.scene;
scene.add(model);
const rig = createHumanoidRig(model);
let frames;
globalThis.__repairView = {
  ready: true,
  setClip(clip) {
    frames = decodeNativeClip(clip, clip);
    return frames.length;
  },
  render(frame, side = "front") {
    if (!frames || frame < 0 || frame >= frames.length)
      throw new Error("frame mismatch");
    rig.interpolate(frames[frame], frames[frame], 1);
    model.updateMatrixWorld(true);
    camera.position.set(
      side === "left" ? 1.85 : side === "right" ? -1.85 : 0,
      1.29,
      side === "front" ? 1.85 : 0.1,
    );
    camera.lookAt(0, 1.29, 0);
    renderer.render(scene, camera);
    return {
      image: renderer.domElement.toDataURL("image/jpeg", 0.9).split(",")[1],
      frame: frame + 1,
      wrists: ["leftHand", "rightHand"].map((name) =>
        rig.bones[name].getWorldPosition(new THREE.Vector3()).toArray(),
      ),
    };
  },
};
window.addEventListener(
  "pagehide",
  () => {
    disposeModel(model);
    renderer.dispose();
  },
  { once: true },
);
