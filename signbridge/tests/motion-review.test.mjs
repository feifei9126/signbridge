import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import {
  createHumanoidRig,
  GODETTE_PROFILE,
} from "../src/avatar/humanoid-rig.js";
import { SIGNS } from "../src/avatar/sign-language-data.js";
import { createMotionAsset } from "../src/avatar/motion-asset.js";
import { LOCALES } from "../src/i18n/locales.js";
import {
  REVIEW_PROTOCOL,
  MAX_REVIEW_SAMPLES,
  prepareReviewMotion,
  sampleFrameIndices,
  reviewHash,
  comparePixels,
  baselineCompatibility,
} from "../src/avatar/motion-review.js";

function fixture() {
  const root = new THREE.Object3D();
  for (const names of Object.values(GODETTE_PROFILE.bones)) {
    const bone = new THREE.Bone();
    bone.name = names[0];
    root.add(bone);
  }
  return createHumanoidRig(root);
}

test("all unique built-in signs validate without mutation or alias duplication", () => {
  const rig = fixture();
  const before = JSON.stringify(SIGNS);
  for (const motion of Object.values(SIGNS)) {
    const result = prepareReviewMotion({ source: "builtin", motion }, rig);
    assert.equal(result.id, motion.id);
    assert.equal(result.asset.frames.length, motion.frames.length);
    assert.deepEqual(result.asset.frames, motion.frames);
    assert.ok(result.usedBones.length > 0);
    assert.equal(result.enabled, false);
  }
  assert.equal(JSON.stringify(SIGNS), before);
});

test("review preserves exact custom angles, frame times and draft status", () => {
  const rig = fixture();
  const asset = createMotionAsset(
    rig,
    [
      {
        value: { head: { x: 0.123456789123, y: 0, z: 0 } },
        duration: 0.637849375,
      },
    ],
    { id: "custom_review", gloss: "Review", texts: ["review"], tags: [] },
  );
  const result = prepareReviewMotion(
    { source: "custom", motion: asset, enabled: false },
    rig,
  );
  assert.deepEqual(result.asset, asset);
  assert.equal(result.enabled, false);
  assert.deepEqual(rig.capturePose().head, { x: 0, y: 0, z: 0 });
});

test("review rejects missing bones, invalid values, frames, duration and mismatched bindings", () => {
  const rig = fixture();
  const base = { source: "builtin", motion: structuredClone(SIGNS.csl_hello) };
  for (const change of [
    (entry) => {
      entry.motion.frames = [];
    },
    (entry) => {
      entry.motion.frames[0].value = [];
    },
    (entry) => {
      entry.motion.frames[0].value = null;
    },
    (entry) => {
      entry.motion.frames[0].duration = NaN;
    },
    (entry) => {
      entry.motion.frames[0].duration = 0;
    },
    (entry) => {
      entry.motion.frames[0].value.head = { x: Infinity, y: 0, z: 0 };
    },
    (entry) => {
      entry.motion.frames[0].value.unknown = { x: 0, y: 0, z: 0 };
    },
  ]) {
    const entry = structuredClone(base);
    change(entry);
    assert.throws(() => prepareReviewMotion(entry, rig));
  }
  delete rig.bones.rightHand;
  assert.throws(() => prepareReviewMotion(base, rig));
});

test("samples are deterministic, bounded, ordered and include first and last", () => {
  for (let count = 1; count <= 240; count++) {
    const indices = sampleFrameIndices(count);
    assert.equal(indices[0], 0);
    assert.equal(indices.at(-1), count - 1);
    assert.equal(indices.length, Math.min(count, MAX_REVIEW_SAMPLES));
    assert.equal(new Set(indices).size, indices.length);
    assert.deepEqual(
      indices,
      [...indices].sort((first, second) => first - second),
    );
  }
  for (const count of [0, -1, 241, 1.5, NaN])
    assert.throws(() => sampleFrameIndices(count));
  assert.throws(() => sampleFrameIndices(10, 1));
});

test("fingerprints are key-order independent and never round exact motion values", async () => {
  assert.equal(
    await reviewHash({ head: 1, arm: 2 }),
    await reviewHash({ arm: 2, head: 1 }),
  );
  assert.notEqual(
    await reviewHash({ angle: 0.1234567891 }),
    await reviewHash({ angle: 0.1234567892 }),
  );
  assert.notEqual(
    await reviewHash({ duration: 0.5 }),
    await reviewHash({ duration: 0.6 }),
  );
  assert.equal((await reviewHash(new Uint8Array([1, 2, 3]))).length, 64);
});

test("motion or environment changes disable pixel comparisons", () => {
  const baseline = {
    protocol: REVIEW_PROTOCOL,
    motionHash: "motion",
    environmentHash: "environment",
  };
  assert.equal(baselineCompatibility(baseline, null), "missing");
  assert.equal(baselineCompatibility(baseline, baseline), "comparable");
  assert.equal(
    baselineCompatibility({ ...baseline, motionHash: "new" }, baseline),
    "motionChanged",
  );
  assert.equal(
    baselineCompatibility({ ...baseline, environmentHash: "new" }, baseline),
    "incompatible",
  );
  assert.equal(
    baselineCompatibility(baseline, { ...baseline, protocol: "old" }),
    "incompatible",
  );
});

test("pixel metrics distinguish identical images, small noise and substantial changes", () => {
  const baseline = new Uint8ClampedArray([10, 20, 30, 255, 20, 30, 40, 255]);
  assert.equal(comparePixels(baseline, baseline).changedRatio, 0);
  assert.equal(comparePixels(baseline, baseline).meanDifference, 0);
  const next = baseline.slice();
  next[0] += 16;
  assert.equal(comparePixels(next, baseline).changedRatio, 0);
  next[0]++;
  assert.equal(comparePixels(next, baseline).changedRatio, 0.5);
  assert.equal(comparePixels(next, baseline).meanDifference, 17 / 6);
  assert.throws(() => comparePixels(next, baseline.slice(0, 4)));
  assert.throws(() => comparePixels([], []));
});

test("all review UI translations exist in every supported locale", () => {
  const keys = Object.keys(LOCALES["zh-CN"]).filter((key) =>
    key.startsWith("review"),
  );
  assert.ok(keys.length > 40);
  for (const locale of Object.values(LOCALES)) {
    for (const key of keys) {
      assert.equal(typeof locale[key], "string", key);
      assert.ok(locale[key].length, key);
      assert.deepEqual(
        [...locale[key].matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort(),
        [...LOCALES["zh-CN"][key].matchAll(/\{(\w+)\}/g)]
          .map((match) => match[1])
          .sort(),
        key,
      );
    }
  }
});
