import test from "node:test";
import assert from "node:assert/strict";
import { passesStabilityGate } from "../src/tools/motion-quality.mjs";

const baseline = {
  metrics: { wristMidpointP95Cm: 1.2 },
  fingerEndJointDisplacementP95Cm: 4.5,
};

test("stability gate requires lower jitter, at least 90 percent range and bounded finger change", () => {
  const passing = {
    metrics: { wristMidpointP95Cm: 1.1 },
    minimumWristRangeRetention: 0.9,
    fingerEndJointDisplacementP95Cm: 4.7,
  };
  assert.equal(passesStabilityGate(passing, baseline), true);
  assert.equal(
    passesStabilityGate(
      { ...passing, minimumWristRangeRetention: 0.899 },
      baseline,
    ),
    false,
  );
  assert.equal(
    passesStabilityGate(
      { ...passing, metrics: { wristMidpointP95Cm: 1.2 } },
      baseline,
    ),
    true,
  );
  assert.equal(
    passesStabilityGate(
      { ...passing, fingerEndJointDisplacementP95Cm: 4.701 },
      baseline,
    ),
    false,
  );
});
