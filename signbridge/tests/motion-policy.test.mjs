import test from "node:test";
import assert from "node:assert/strict";
import {
  resolveMotionDisplayPolicy,
  isLearnedMotionSource,
} from "../src/demo/motion-policy.js";

test("all learned motion sources receive display stabilization", () => {
  for (const source of ["t08", "candidate", "experimental"]) {
    assert.equal(isLearnedMotionSource(source), true);
    const policy = resolveMotionDisplayPolicy(
      { id: "clip", quality_warning: false },
      source,
      { display_stabilization_profile: "quaternion-temporal-v1" },
    );
    assert.deepEqual(policy, {
      enabled: true,
      profile: "quaternion-temporal-v1",
    });
  }
});

test("quality-warning clips use the recovery profile unless an indexed policy overrides it", () => {
  assert.deepEqual(
    resolveMotionDisplayPolicy(
      { id: "warning", quality_warning: true },
      "experimental",
    ),
    { enabled: true, profile: "quaternion-temporal-recovery-v1" },
  );
  assert.deepEqual(
    resolveMotionDisplayPolicy(
      {
        id: "warning",
        quality_warning: true,
        display_stabilization_profile: "quaternion-temporal-v1",
      },
      "experimental",
    ),
    { enabled: true, profile: "quaternion-temporal-v1" },
  );
});

test("dictionary motion is not mislabeled as learned stabilized motion", () => {
  assert.equal(isLearnedMotionSource("dictionary"), false);
  assert.deepEqual(resolveMotionDisplayPolicy({ id: "word" }, "dictionary"), {
    enabled: false,
    profile: null,
  });
});
