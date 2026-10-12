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

function playerHarness(options = {}) {
  let clock = 0;
  let nextId = 0;
  const callbacks = new Map();
  const visited = [];
  const interpolated = [];
  const rig = {
    capture: () => ({}),
    createTargets: (pose) => {
      visited.push(pose.name);
      return pose;
    },
    interpolate: (_from, targets, amount) =>
      interpolated.push({ targets, amount }),
    reset: () => visited.push("reset"),
  };
  const schedule = (callback, delay) => {
    const id = ++nextId;
    callbacks.set(id, { callback, at: clock + delay });
    return id;
  };
  const player = createMotionPlayer(rig, {
    requestFrame: (callback) => schedule(callback, 16),
    cancelFrame: (id) => callbacks.delete(id),
    setTimer: schedule,
    clearTimer: (id) => callbacks.delete(id),
    now: () => clock,
    ...options,
  });
  function advance(milliseconds) {
    const end = clock + milliseconds;
    while (callbacks.size) {
      const [id, next] = [...callbacks].sort(
        (first, second) => first[1].at - second[1].at,
      )[0];
      if (next.at > end) break;
      clock = next.at;
      callbacks.delete(id);
      next.callback();
    }
    clock = end;
  }
  return { player, advance, visited, callbacks, interpolated };
}

function motion(...names) {
  return names.map((name) => ({ value: { name }, duration: 0.5 }));
}

test("queued subtitles finish the current sentence before the next one", () => {
  const { player, advance, visited } = playerHarness();
  player.enqueue(motion("first", "second"), { key: "sentence-one" });
  advance(200);
  player.enqueue(motion("third"), { key: "sentence-two" });
  advance(1500);
  assert.deepEqual(visited, ["first", "second", "third"]);
  assert.equal(player.isPlaying, false);
});

test("subtitle queue is bounded and suppresses duplicates across sources", () => {
  const { player, advance, visited } = playerHarness({ maxPendingMotions: 2 });
  player.enqueue(motion("current"), { key: "same" });
  assert.equal(player.enqueue(motion("duplicate"), { key: "same" }), false);
  player.enqueue(motion("old"), { key: "old" });
  player.enqueue(motion("newer"), { key: "newer" });
  player.enqueue(motion("newest"), { key: "newest" });
  advance(2000);
  assert.deepEqual(visited, ["current", "newer", "newest"]);
});

test("expired pending subtitles are dropped instead of building latency", () => {
  const { player, advance, visited } = playerHarness({ maxPendingAgeMs: 200 });
  player.enqueue(motion("current"));
  player.enqueue(motion("expired"));
  advance(1000);
  assert.deepEqual(visited, ["current"]);
});

test("stop cancels queued work and explicit play can replace a preview", () => {
  const { player, advance, visited, callbacks } = playerHarness();
  player.enqueue(motion("old", "never"));
  player.enqueue(motion("also-never"));
  player.stop({ reset: true });
  assert.equal(callbacks.size, 0);
  advance(2000);
  assert.deepEqual(visited, ["old", "reset"]);
  player.play(motion("preview"));
  player.play(motion("replacement"));
  advance(1000);
  assert.deepEqual(visited.slice(2), ["preview", "replacement"]);
});

test("completion fires once after the whole clip but not on cancellation", () => {
  let completed = 0;
  const { player, advance } = playerHarness({
    onComplete: () => {
      completed += 1;
    },
  });
  player.play(motion("first", "second"));
  advance(600);
  assert.equal(completed, 0);
  advance(600);
  assert.equal(completed, 1);
  player.play(motion("cancelled"));
  player.stop();
  advance(1000);
  assert.equal(completed, 1);
});

test("T08 quaternion tracks interpolate sampled poses on the live player timeline", () => {
  const { player, advance, interpolated } = playerHarness();
  const samples = [{ frame: 0 }, { frame: 1 }, { frame: 2 }];
  assert.equal(
    player.enqueue({
      type: "quaternion-track",
      samples,
      fps: 10,
      duration: 0.3,
    }),
    true,
  );
  advance(48);
  assert.ok(
    interpolated.some(
      (sample) =>
        sample.targets === samples[1] &&
        sample.amount > 0.4 &&
        sample.amount < 0.6,
    ),
  );
  advance(400);
  assert.equal(player.isPlaying, false);
});

test("stopping a T08 track cancels its animation frame", () => {
  const { player, callbacks } = playerHarness();
  player.play({
    type: "quaternion-track",
    samples: [{ frame: 0 }, { frame: 1 }],
    fps: 25,
    duration: 0.08,
  });
  assert.equal(callbacks.size, 1);
  player.stop();
  assert.equal(callbacks.size, 0);
  assert.equal(player.isPlaying, false);
});
