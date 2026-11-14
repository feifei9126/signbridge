import test from "node:test";
import assert from "node:assert/strict";
import { repairGate } from "../src/tools/sign-native-repair.mjs";
function fixture() {
  return {
    quality: {
      wristMidpointCm: { p95: 0.2, max: 0.5 },
      fingerMidpointDegrees: { p95: 1, max: 4 },
      armMidpointDegrees: { p95: 0.6, max: 3 },
      torsoSkinRiskFrames: [],
      forearmCapsuleRiskFrames: [],
      handForearmRiskFrames: [],
    },
    rotationDeviationP95Degrees: 6,
    wristRangeBefore: [25, 2],
    wristRangeAfter: [24, 1.5],
    finiteUnit: true,
  };
}
test("repair gate rejects visible peaks even when aggregate P95 is small", () => {
  const p = fixture();
  assert.equal(repairGate(p).passed, true);
  p.quality.fingerMidpointDegrees.max = 24;
  assert.equal(repairGate(p).passed, false);
  p.quality.fingerMidpointDegrees.max = 4;
  p.quality.wristMidpointCm.max = 1.1;
  assert.equal(repairGate(p).passed, false);
});
test("actual skin and capsule contact risk cannot be traded for smoother metrics", () => {
  for (const key of [
    "torsoSkinRiskFrames",
    "forearmCapsuleRiskFrames",
    "handForearmRiskFrames",
  ]) {
    const p = fixture();
    p.quality[key] = [10];
    assert.equal(repairGate(p).passed, false);
  }
  const p = fixture();
  p.quality.fingerMidpointDegrees.p95 = NaN;
  assert.equal(repairGate(p).passed, false);
});
