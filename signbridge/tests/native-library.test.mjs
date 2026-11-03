import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { loadSkeleton } from "../src/tools/motion-quality.mjs";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
let tool;
try {
  tool = await import("../src/tools/sign-native-library.mjs");
} catch (e) {
  if (e.code !== "ERR_MODULE_NOT_FOUND") throw e;
}
const v = (x, y, z = 0) => new THREE.Vector3(x, y, z);
test("closest segment distance distinguishes 3D crossings from separated projection crossings", () => {
  assert.ok(tool);
  const crossing = tool.segmentDistance(v(-1, 0), v(1, 0), v(0, -1), v(0, 1));
  assert.equal(crossing.distance, 0);
  assert.equal(crossing.s, 0.5);
  assert.equal(crossing.t, 0.5);
  assert.equal(
    tool.segmentDistance(v(-1, 0), v(1, 0), v(0, -1, 1), v(0, 1, 1)).distance,
    1,
  );
  assert.equal(
    tool.segmentDistance(v(0, 0), v(0, 0), v(1, 0), v(2, 0)).distance,
    1,
  );
});
test("native display selection never accepts geometry risk or promotes review flags", () => {
  assert.ok(tool);
  const candidate = {
    gate: { passed: true },
    geometry: { armCrossingFrames: 0, deepTorsoFrames: 0 },
    metrics: { fingerMidpointP95Degrees: 1 },
  };
  assert.equal(tool.chooseProfile({ current: candidate }), "current");
  assert.equal(
    tool.chooseProfile({
      current: {
        ...candidate,
        geometry: { armCrossingFrames: 1, deepTorsoFrames: 0 },
      },
    }),
    null,
  );
  assert.equal(
    tool.chooseProfile({
      current: { ...candidate, metrics: { fingerMidpointP95Degrees: 11 } },
    }),
    null,
  );
  assert.equal(
    tool.chooseProfile({ current: { ...candidate, gate: { passed: false } } }),
    null,
  );
});
test("handshape comparison is invariant to rigid wrist rotation but detects finger articulation", () => {
  const model = loadSkeleton(
    new URL("../src/avatar/model.glb", import.meta.url),
  );
  const rig = createHumanoidRig(model);
  const before = Object.fromEntries(
    Object.entries(rig.bones).map(([k, b]) => [k, b.quaternion.clone()]),
  );
  const after = Object.fromEntries(
    Object.entries(before).map(([k, q]) => [k, q.clone()]),
  );
  after.leftHand.multiply(
    new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), 0.2),
  );
  assert.ok(tool.handshapeDifference([before], [after], rig, model) < 1e-4);
  after.leftIndexProximal.multiply(
    new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 1),
  );
  assert.ok(tool.handshapeDifference([before], [after], rig, model) > 0.2);
});
