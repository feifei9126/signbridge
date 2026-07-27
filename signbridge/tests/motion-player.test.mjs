import assert from "node:assert/strict";
import test from "node:test";

import {
  createMotionPlayer,
  easeInOut,
  normalizeMotionFrames,
} from "../src/avatar/motion-player.js";

test("motion frames use safe defaults", () => {
  assert.deepEqual(normalizeMotionFrames(null), []);
  assert.deepEqual(normalizeMotionFrames([{ value: null, duration: -1 }]), [
    { value: {}, duration: 0.8 },
  ]);
});

test("motion easing preserves endpoints", () => {
  assert.equal(easeInOut(0), 0);
  assert.equal(easeInOut(1), 1);
  assert.equal(easeInOut(0.5), 0.5);
});

test("motion player delegates canonical poses to the rig", () => {
  const calls = [];
  const rig = {
    capture: () => ({ current: true }),
    createTargets: (pose) => {
      calls.push(pose);
      return { target: true };
    },
    interpolate: () => {},
    reset: () => calls.push("reset"),
  };
  const player = createMotionPlayer(rig, {
    requestFrame: () => 1,
    cancelFrame: () => {},
    setTimer: () => 1,
    clearTimer: () => {},
    now: () => 0,
  });
  assert.equal(
    player.play([{ value: { head: { x: 1 } }, duration: 0.5 }]),
    true,
  );
  assert.deepEqual(calls[0], { head: { x: 1 } });
  assert.equal(player.isPlaying, true);
  player.stop({ reset: true });
  assert.equal(player.isPlaying, false);
  assert.equal(calls.at(-1), "reset");
});
