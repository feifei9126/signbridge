import test from "node:test";
import assert from "node:assert/strict";
import {
  displayProfileForEntry,
  MOTION_DISPLAY_OVERRIDES,
} from "../src/tools/motion-library-audit.mjs";
import { MOTION_STABILIZATION_PROFILES } from "../src/demo/motion-stabilization.js";

test("only five evidence-backed fitted clips use tuned display profiles", () => {
  assert.equal(Object.keys(MOTION_DISPLAY_OVERRIDES).length, 5);
  for (const [id, profile] of Object.entries(MOTION_DISPLAY_OVERRIDES)) {
    assert.ok(Object.hasOwn(MOTION_STABILIZATION_PROFILES, profile), id);
    assert.equal(
      displayProfileForEntry(
        { id, quality_warning: true },
        "experimental",
        "needs_review",
      ),
      profile,
    );
  }
});

test("unmapped or non-fitted motions retain the existing policy", () => {
  assert.equal(
    displayProfileForEntry(
      { id: "other", quality_warning: true },
      "experimental",
      "needs_review",
    ),
    "quaternion-temporal-recovery-v1",
  );
  assert.equal(
    displayProfileForEntry({ id: "other" }, "t08", "stable"),
    "quaternion-temporal-v1",
  );
});
