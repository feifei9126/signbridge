import test from "node:test";
import assert from "node:assert/strict";
import { frameDelta } from "../src/demo/demo-playback.js";
test("a queued RAF after compiling or replaying a clip never produces negative playback time", () => {
  assert.equal(frameDelta(1000, 1500), 0);
});
test("ordinary frame timing progresses while background-tab gaps remain bounded", () => {
  assert.equal(frameDelta(1016, 1000), 0.016);
  assert.equal(frameDelta(10000, 1000), 0.1);
});
