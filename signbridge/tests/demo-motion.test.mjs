import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {
  matchT08Reference,
  planDemoText,
  validateT08CandidateBundle,
  validateT08Bundle,
} from "../src/demo/demo-motion.js";
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

test("realtime T08 routing selects only a complete reference phrase", () => {
  assert.equal(matchT08Reference("工作忙吗！？", clips)?.id, "phrase");
  assert.equal(matchT08Reference("工作忙吗，谢谢", clips), null);
  assert.equal(matchT08Reference("工作🚀忙吗？", clips), null);
  assert.equal(matchT08Reference("工作忙吗", []), null);
});

test("candidate references require provenance, remain separate from training, and route as candidates", () => {
  const candidate = {
    id: "candidate",
    text: "如果下雨可以借你一把。",
    aliases: ["如果下雨可以借你一把。"],
    runtime_candidate: true,
    training_data_member: false,
    training_ready: false,
    mirror_orientation_confirmed: false,
    speaker_identity_confirmed: false,
    authorization_status: "user_reported",
    motion_review_decision_sha256:
      "8297549518aaed82f88b94ff20550f4d708ddfe2229a1c614300a7f962752507",
    model_output: "token_decode_candidate",
    normalized_reconstruction_mse: 0.5,
    frames: 100,
    fps: 25,
    poses: Array.from({ length: 100 }, () =>
      Array.from({ length: 55 }, () => [0, 0, 0]),
    ),
    tokens: {
      body: Array(25).fill(0),
      left: Array(25).fill(0),
      right: Array(25).fill(0),
    },
    token_decode_parity_max: 0,
    feature_sha256: "a".repeat(64),
    source_sha256: "b".repeat(64),
  };
  const bundle = {
    schema: "signbridge-t08-motion-candidates-v1",
    training_checkpoint_sha256:
      "438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b",
    training_weights_updated: false,
    training_ready: false,
    text_to_sign_trained: false,
    research_only: true,
    training_checkpoint_step: 1000,
    representation: "effective-smplx-55-axis-angle",
    smplx_rest_model_sha256:
      "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992",
    restJoints: Array.from({ length: 55 }, () => [0, 0, 0]),
    parents: [-1, ...Array.from({ length: 54 }, (_, index) => index)],
    clips: [
      candidate,
      { ...candidate, id: "candidate-2", text: "我给她买了一件衣服" },
      { ...candidate, id: "candidate-3", text: "去人民广场怎么走？" },
    ],
  };
  assert.equal(validateT08CandidateBundle(bundle).clips.length, 3);
  assert.equal(
    planDemoText(candidate.text, "auto", [candidate]).items[0].source,
    "candidate",
  );
  assert.throws(() =>
    validateT08CandidateBundle({
      ...bundle,
      clips: [{ ...candidate, training_data_member: true }],
    }),
  );
  assert.throws(() =>
    validateT08CandidateBundle({
      ...bundle,
      clips: bundle.clips.map((clip) => ({
        ...clip,
        token_decode_parity_max: NaN,
      })),
    }),
  );
});

test("semantic mode delegates to the CSL meaning planner instead of substring matching", () => {
  const plan = planDemoText("我今天去", "semantic");
  assert.equal(plan.route, "analysis_only");
  assert.deepEqual(
    plan.draft.map((item) => item.motionId),
    ["csl_today", "csl_me", "csl_go"],
  );
  assert.equal(planDemoText("我帮你", "semantic").canPreview, false);
});
