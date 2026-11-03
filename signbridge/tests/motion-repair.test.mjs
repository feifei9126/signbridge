import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { repairQuaternionTrack } from "../src/demo/motion-repair.js";
import { polygonDepth } from "../src/tools/motion-geometry.mjs";
const q = (angle) =>
  new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), angle);
test("repair removes alternating hand noise including endpoints without mutating frame data", () => {
  const frames = Array.from({ length: 80 }, (_, i) => ({
    leftIndexProximal: q(i * 0.005 + (i % 2 ? 0.1 : -0.1)),
    leftHand: q(0.4),
  }));
  const before = frames.map((f) => f.leftIndexProximal.toArray());
  const result = repairQuaternionTrack(frames, 25);
  const residual = (track) =>
    Math.max(
      ...track.slice(1, -1).map((f, i) =>
        track[i].leftIndexProximal
          .clone()
          .slerp(track[i + 2].leftIndexProximal, 0.5)
          .angleTo(f.leftIndexProximal),
      ),
    );
  assert.ok(residual(result) < residual(frames) * 0.15);
  assert.deepEqual(
    frames.map((f) => f.leftIndexProximal.toArray()),
    before,
  );
  assert.equal(result.length, 80);
  assert.ok(result.every((f) => Math.abs(f.leftHand.length() - 1) < 1e-6));
  assert.ok(result[40].leftIndexProximal.angleTo(q(0.2)) < 0.01);
});
test("repair rejects incomplete or nonfinite tracks and geometry depth includes a surface margin", () => {
  assert.throws(() => repairQuaternionTrack([{ hand: q(0) }], 25));
  const frames = Array.from({ length: 4 }, () => ({ hand: q(0) }));
  frames[2].hand.w = NaN;
  assert.throws(() => repairQuaternionTrack(frames, 25));
  const square = [
    [-1, -1],
    [1, -1],
    [1, 1],
    [-1, 1],
  ];
  assert.equal(polygonDepth([0, 0], square), 1);
  assert.equal(polygonDepth([2, 0], square), -1);
});
