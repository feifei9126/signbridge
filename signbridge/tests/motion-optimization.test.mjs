import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {
  MOTION_STABILIZATION_PROFILES,
  stabilizeQuaternionTrack,
} from "../src/demo/motion-stabilization.js";
const profile = "quaternion-temporal-adaptive-v1";
const q = (a) =>
  new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), a);

test("event-gated filter corrects isolated angular spikes by a bounded amount", () => {
  assert.ok(
    MOTION_STABILIZATION_PROFILES[profile],
    "event-gated research profile missing",
  );
  const frames = Array.from({ length: 60 }, (_, i) => ({
    leftHand: q(i === 30 ? 0.22 : i * 0.003),
    leftIndexDistal: q(i === 30 ? 0.22 : i * 0.002),
  }));
  const before = JSON.stringify(frames);
  const result = stabilizeQuaternionTrack(frames, 25, profile);
  assert.equal(JSON.stringify(frames), before);
  assert.equal(result.length, frames.length);
  assert.ok(result[0].leftHand.angleTo(frames[0].leftHand) < 1e-8);
  assert.ok(result.at(-1).leftHand.angleTo(frames.at(-1).leftHand) < 1e-8);
  const correction = result[30].leftHand.angleTo(frames[30].leftHand);
  assert.ok(correction > 0 && (correction * 180) / Math.PI <= 3.01);
  assert.ok(result[20].leftHand.angleTo(frames[20].leftHand) < 1e-8);
});

test("adaptive profile preserves a fast sustained handshape and rejects missing observations", () => {
  assert.ok(MOTION_STABILIZATION_PROFILES[profile]);
  const frames = Array.from({ length: 40 }, (_, i) => ({
    leftIndexDistal: q(i >= 15 && i <= 25 ? 1 : 0),
  }));
  const result = stabilizeQuaternionTrack(frames, 25, profile);
  assert.ok(result[20].leftIndexDistal.angleTo(q(1)) < 0.01);
  assert.throws(() =>
    stabilizeQuaternionTrack(
      [{ leftHand: q(0) }, { leftHand: null }],
      25,
      profile,
    ),
  );
});
