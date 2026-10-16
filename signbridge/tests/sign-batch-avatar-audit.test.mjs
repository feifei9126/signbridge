import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {
  angularMetrics,
  percentile,
} from "../src/tools/sign-batch-avatar-audit.mjs";

test("avatar audit preserves empty metrics and quaternion rotation wrap", () => {
  assert.equal(percentile([]), null);
  const frames = [179, -179, -177].map((v) => ({
    hand: new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 0, 1),
      (v * Math.PI) / 180,
    ),
  }));
  const result = angularMetrics(frames);
  assert.ok(Math.abs(result.adjacentP95Deg - 2) < 1e-5);
  assert.ok(result.residualP95Deg < 1e-5);
});
test("avatar audit identifies exact isolated spike frames", () => {
  const frames = [0, 0, 2, 0, 0].map((v) => ({
    hand: new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(1, 0, 0),
      v,
    ),
  }));
  assert.deepEqual(angularMetrics(frames).spikeFramesOver30Deg, [2, 3, 4]);
});
