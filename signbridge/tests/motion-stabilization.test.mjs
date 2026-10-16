import test from "node:test";
import assert from "node:assert/strict";
import { Quaternion, Vector3 } from "three";
import * as stability from "../src/demo/motion-stabilization.js";

const axis = new Vector3(0, 1, 0);
const pose = (angle) => ({
  leftHand: new Quaternion().setFromAxisAngle(axis, angle),
  leftIndexDistal: new Quaternion().setFromAxisAngle(axis, angle),
});
function residual(frames, bone = "leftHand") {
  return frames.slice(1, -1).reduce(
    (sum, frame, i) =>
      sum +
      frames[i][bone]
        .clone()
        .slerp(frames[i + 2][bone], 0.5)
        .angleTo(frame[bone]),
    0,
  );
}
test("display smoothing reduces high-frequency jitter without mutating or retiming the track", () => {
  const raw = Array.from({ length: 100 }, (_, i) =>
    pose(i * 0.004 + (i % 2 ? 0.12 : -0.12)),
  );
  const saved = raw.map((frame) => frame.leftHand.toArray());
  const filtered = stability.stabilizeQuaternionTrack(raw, 25);
  assert.equal(filtered.length, raw.length);
  assert.ok(residual(filtered) < residual(raw) * 0.2);
  assert.ok(
    residual(filtered, "leftIndexDistal") <
      residual(raw, "leftIndexDistal") * 0.4,
  );
  assert.deepEqual(
    raw.map((frame) => frame.leftHand.toArray()),
    saved,
  );
  for (const i of [0, raw.length - 1])
    assert.ok(filtered[i].leftHand.angleTo(raw[i].leftHand) < 1e-7);
  assert.notEqual(filtered[10].leftHand, raw[10].leftHand);
});
test("symmetric smoothing preserves constant-speed turns, slow gestures and unit rotations", () => {
  const ramp = Array.from({ length: 100 }, (_, i) => pose(i * 0.01));
  const actual = stability.stabilizeQuaternionTrack(ramp, 25);
  for (let i = 0; i < ramp.length; i++)
    assert.ok(actual[i].leftHand.angleTo(ramp[i].leftHand) < 1e-6);
  const slow = Array.from({ length: 100 }, (_, i) =>
    pose(0.6 * Math.sin((i / 25) * 2 * Math.PI)),
  );
  const filtered = stability.stabilizeQuaternionTrack(slow, 25);
  assert.ok(
    filtered[6].leftHand.angleTo(new Quaternion()) >
      slow[6].leftHand.angleTo(new Quaternion()) * 0.94,
  );
  for (const frame of filtered)
    for (const q of Object.values(frame))
      assert.ok(Math.abs(q.length() - 1) < 1e-10);
});
test("targeted demo recovery applies stronger arm filtering and preserves continuous ramps", () => {
  const noisy = Array.from({ length: 100 }, (_, i) =>
    pose(i * 0.004 + (i % 2 ? 0.12 : -0.12)),
  );
  const regular = stability.stabilizeQuaternionTrack(noisy, 25);
  const recovery = stability.stabilizeQuaternionTrack(
    noisy,
    25,
    "quaternion-temporal-recovery-v1",
  );
  assert.ok(
    residual(recovery, "leftHand") < residual(regular, "leftHand") * 0.8,
  );
  assert.ok(
    residual(recovery, "leftIndexDistal") <=
      residual(regular, "leftIndexDistal") * 1.01,
  );
  const ramp = Array.from({ length: 100 }, (_, i) => pose(i * 0.01));
  const filtered = stability.stabilizeQuaternionTrack(
    ramp,
    25,
    "quaternion-temporal-recovery-v1",
  );
  for (let i = 0; i < ramp.length; i++)
    assert.ok(filtered[i].leftHand.angleTo(ramp[i].leftHand) < 1e-6);
  assert.ok(filtered[0].leftHand.angleTo(ramp[0].leftHand) < 1e-7);
  assert.ok(filtered.at(-1).leftHand.angleTo(ramp.at(-1).leftHand) < 1e-7);
});
test("targeted smoothing rejects unsafe or incomplete profiles", () => {
  assert.throws(() =>
    stability.stabilizeQuaternionTrack(
      [pose(0), pose(0), pose(0)],
      25,
      "quaternion-temporal-recovery-v9",
    ),
  );
});
test("quaternion sign flips never become rotation spikes", () => {
  const raw = Array.from({ length: 50 }, (_, i) => {
    const q = new Quaternion().setFromAxisAngle(axis, 0.4);
    if (i % 2) q.set(-q.x, -q.y, -q.z, -q.w);
    return { leftHand: q };
  });
  for (const frame of stability.stabilizeQuaternionTrack(raw, 25))
    assert.ok(frame.leftHand.angleTo(raw[0].leftHand) < 1e-7);
});
test("invalid rotations and incomplete frame shapes are rejected, never filled", () => {
  assert.throws(() =>
    stability.stabilizeQuaternionTrack([pose(0), {}, pose(0)], 25),
  );
  const invalid = [pose(0), pose(0), pose(0)];
  invalid[1].leftHand.x = NaN;
  assert.throws(() => stability.stabilizeQuaternionTrack(invalid, 25));
  assert.throws(() =>
    stability.stabilizeQuaternionTrack([pose(0), pose(0), pose(0)], 0),
  );
});
