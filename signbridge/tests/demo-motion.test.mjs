import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { planDemoText, validateT08Bundle } from "../src/demo/demo-motion.js";
import {
  axisAngleQuaternion,
  sourceWorldRotations,
  boneFrame,
} from "../src/demo/demo-retarget.js";
const clips = [{ id: "phrase", text: "工作忙吗？", aliases: ["工作忙吗？"] }];
test("longest complete T08 phrase wins; unsupported spans are retained", () => {
  const p = planDemoText("工作忙吗？谢谢宇宙飞船", "auto", clips);
  assert.equal(p.items[0].source, "t08");
  assert.equal(p.items[0].id, "phrase");
  assert.ok(p.items.some((x) => x.id === "csl_thanks"));
  assert.ok(p.unmatched.includes("宇宙飞船"));
});
test("T08-only mode never treats an individual word as a full reference sentence", () => {
  assert.equal(planDemoText("工作", "t08", clips).items.length, 0);
  assert.equal(planDemoText("工作忙吗!", "t08", clips).items[0].id, "phrase");
});
test("dictionary mode retains source provenance and unknown input does not play neutral", () => {
  assert.ok(
    planDemoText("你好", "dictionary", clips).items.every(
      (x) => x.source === "dictionary",
    ),
  );
  const p = planDemoText("🚀", "auto", clips);
  assert.equal(p.items.length, 0);
  assert.ok(p.unmatched);
});
test("invalid model asset is rejected", () => {
  assert.throws(() =>
    validateT08Bundle({ schema: "signbridge-t08-demo-v1", clips: [] }),
  );
});
test("axis-angle rotation and parent FK preserve finite unit quaternions", () => {
  const q = axisAngleQuaternion([0, 0, Math.PI / 2]);
  const v = new THREE.Vector3(1, 0, 0).applyQuaternion(q);
  assert.ok(v.distanceTo(new THREE.Vector3(0, 1, 0)) < 1e-6);
  const w = sourceWorldRotations(
    [
      [0, 0, Math.PI / 2],
      [0, 0, 0],
    ],
    [-1, 0],
  );
  assert.ok(w[0].angleTo(w[1]) < 1e-6);
  assert.throws(() => axisAngleQuaternion([NaN, 0, 0]));
});
test("bone orientation frame gives an orthonormal calibrated forward axis", () => {
  const dir = new THREE.Vector3(1, -1, 0).normalize();
  const q = boneFrame(dir, new THREE.Vector3(0, 0, 1));
  assert.ok(
    new THREE.Vector3(0, 1, 0).applyQuaternion(q).distanceTo(dir) < 1e-6,
  );
});

test("symbols inside a phrase cannot be silently removed to fabricate a T08 match", () => {
  const p = planDemoText("工作🚀忙吗？", "t08", clips);
  assert.equal(p.items.length, 0);
  assert.ok(p.unmatched.includes("🚀"));
});
test("English matches respect both word boundaries and punctuation", () => {
  const p = planDemoText("yesterday xhello hello, thanks!", "dictionary");
  assert.deepEqual(
    p.items.map((s) => s.id),
    ["csl_hello", "csl_thanks"],
  );
  assert.equal(p.unmatched, "yesterdayxhello");
});
test("input and motion count limits preserve the unsupported tail", () => {
  const p = planDemoText("谢谢".repeat(60), "dictionary");
  assert.equal(p.items.length, 40);
  assert.equal(p.unmatched, "谢谢".repeat(20));
  assert.equal(planDemoText("宇".repeat(510)).truncated, true);
});
