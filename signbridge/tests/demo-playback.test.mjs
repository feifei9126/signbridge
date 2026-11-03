import test from "node:test";
import assert from "node:assert/strict";
import {
  frameDelta,
  transitionAmount,
  restTransition,
} from "../src/demo/demo-playback.js";
test("a queued RAF after compiling or replaying a clip never produces negative playback time", () => {
  assert.equal(frameDelta(1000, 1500), 0);
});
test("ordinary frame timing progresses while background-tab gaps remain bounded", () => {
  assert.equal(frameDelta(1016, 1000), 0.016);
  assert.equal(frameDelta(10000, 1000), 0.1);
});
test("replacement transition is bounded, monotone and preserves both endpoints", () => {
  assert.equal(transitionAmount(-1), 0);
  assert.equal(transitionAmount(0), 0);
  assert.equal(transitionAmount(0.09), 0.5);
  assert.equal(transitionAmount(0.18), 1);
  assert.equal(transitionAmount(2), 1);
});
test("stopping captures REST as the destination while retaining the displayed pose", () => {
  const rig = {
    value: 8,
    capture() {
      return this.value;
    },
    reset() {
      this.value = 0;
    },
    interpolate(a, b, t) {
      this.value = a + (b - a) * t;
    },
  };
  const transition = restTransition(rig);
  assert.equal(rig.value, 8);
  assert.deepEqual(transition, { from: 8, to: 0, time: 0 });
  rig.interpolate(transition.from, transition.to, transitionAmount(0.09));
  assert.equal(rig.value, 4);
  rig.interpolate(transition.from, transition.to, transitionAmount(0.18));
  assert.equal(rig.value, 0);
});
