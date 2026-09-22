import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
import {
  createMotionAsset,
  validateMotionAsset,
  convertLegacyMotion,
} from "../src/avatar/motion-asset.js";

function makeRig() {
  const root = new THREE.Object3D();
  const head = new THREE.Bone();
  head.name = "Head_129";
  head.rotation.set(-0.074, -0.002, 0.017);
  root.add(head);
  return createHumanoidRig(root);
}

const metadata = {
  id: "custom_test",
  gloss: "测试动作",
  texts: ["测试动作"],
  tags: [],
};

test("canonical export/import preserves REST-delta radians and target quaternion", () => {
  const rig = makeRig();
  rig.applyPose({ head: { x: -0.7661995416255106, y: 0.12, z: 0.03 } });
  const before = rig.capture();
  const asset = createMotionAsset(
    rig,
    [{ value: rig.capturePose(), duration: 0.37 }],
    metadata,
  );
  const imported = validateMotionAsset(JSON.parse(JSON.stringify(asset)), rig);
  rig.reset();
  rig.applyPose(imported.frames[0].value);
  assert.ok(before.head.angleTo(rig.capture().head) < 1e-7);
  assert.equal(imported.frames[0].duration, 0.37);
  assert.equal(imported.unit, "radians");
});

test("legacy editor degrees convert explicitly, never play degrees as radians", () => {
  const rig = makeRig();
  const asset = convertLegacyMotion(
    { head: { x: -43.9, y: 0, z: 0 } },
    "editor-degrees",
    rig,
    metadata,
  );
  assert.equal(asset.frames[0].value.head.x, (-43.9 * Math.PI) / 180);
  assert.throws(() =>
    validateMotionAsset({ head: { x: -43.9, y: 0, z: 0 } }, rig),
  );
});

test("legacy recorder and absolute editor exports have separate explicit adapters", () => {
  const rig = makeRig();
  const recorder = convertLegacyMotion(
    { frames: [{ pose: { head: { x: 30, y: 0, z: 0 } }, duration: 0.3 }] },
    "recorder-degrees",
    rig,
    metadata,
  );
  assert.equal(recorder.frames[0].value.head.x, Math.PI / 6);
  const absolute = convertLegacyMotion(
    { head: { x: 0.2, y: 0, z: 0 } },
    "absolute-radians",
    rig,
    metadata,
  );
  rig.applyPose(absolute.frames[0].value);
  assert.ok(Math.abs(rig.bones.head.rotation.x - 0.2) < 1e-9);
});

test("reject wrong units, unknown bones, non-finite angles, invalid durations and model binding", () => {
  const rig = makeRig();
  const asset = createMotionAsset(
    rig,
    [{ value: { head: { x: 0.2, y: 0, z: 0 } }, duration: 0.3 }],
    metadata,
  );
  for (const mutate of [
    (entry) => {
      entry.unit = "degrees";
    },
    (entry) => {
      entry.version = 2;
    },
    (entry) => {
      entry.space = "absolute";
    },
    (entry) => {
      entry.frames[0].value.bogus = { x: 0, y: 0, z: 0 };
    },
    (entry) => {
      entry.frames[0].value.head.x = Infinity;
    },
    (entry) => {
      entry.frames[0].duration = -1;
    },
    (entry) => {
      entry.frames[0].duration = 0;
    },
    (entry) => {
      entry.rig.rest = "different model";
    },
    (entry) => {
      entry.frames = [{ pose: {}, duration: 0.3 }];
    },
  ]) {
    const invalid = JSON.parse(JSON.stringify(asset));
    mutate(invalid);
    assert.throws(() => validateMotionAsset(invalid, rig));
  }
  const otherRig = makeRig();
  otherRig.rest.head.rotation.x += 0.01;
  assert.throws(() => validateMotionAsset(asset, otherRig));
});
