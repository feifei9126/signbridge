import test from "node:test";
import assert from "node:assert/strict";
let api;
try {
  api = await import("../src/demo/core-plan.js");
} catch (error) {
  if (error.code !== "ERR_MODULE_NOT_FOUND") throw error;
}
const words = [
  ["speaker", "我", "person"],
  ["addressee", "你", "person"],
  ["work", "工作", "predicate"],
  ["healthy", "健康", "predicate"],
  ["relax", "放松", "predicate"],
  ["drive", "开车", "predicate"],
  ["absence", "没有", "absence"],
  ["home", "家", "noun"],
  ["drink", "饮料", "noun"],
];
const manifest = {
  units: words.map(([key, text, role]) => ({
    key,
    text,
    role,
    id: "native_core_" + key + "_v1",
  })),
};
test("core routing plays only core units and preserves sentence roles, including swapped participants in blocked directional requests", () => {
  assert.ok(api);
  for (const [text, actor] of [
    ["我工作", "我"],
    ["你工作", "你"],
    ["我健康", "我"],
    ["你开车", "你"],
  ]) {
    const p = api.planCoreText(text, manifest);
    assert.equal(p.canPreview, true);
    assert.equal(p.analysis.meaning.actor.surface, actor);
    assert.equal(
      p.items.every((i) => i.source === "native"),
      true,
    );
  }
  for (const [text, actor, patient] of [
    ["我帮你", "我", "你"],
    ["你帮我", "你", "我"],
  ]) {
    const p = api.planCoreText(text, manifest);
    assert.equal(p.canPreview, false);
    assert.equal(p.analysis.meaning.actor.surface, actor);
    assert.equal(p.analysis.meaning.patient.surface, patient);
    assert.ok(p.blockers.includes("directional_motion_missing"));
    assert.equal(p.items.length, 0);
  }
});
test("absence is not substituted for not, questions and ambiguous event negation are rejected", () => {
  assert.ok(api);
  const p = api.planCoreText("我没有家", manifest);
  assert.equal(p.canPreview, true);
  assert.equal(p.analysis.meaning.negation.kind, "absence");
  assert.equal(p.items.length, 3);
  for (const text of [
    "我不工作",
    "我没有工作",
    "我不想工作",
    "你工作吗",
    "我想不去",
    "我工作，你健康",
    "我工作但是取消",
  ]) {
    const plan = api.planCoreText(text, manifest);
    assert.equal(plan.canPreview, false, text);
    assert.equal(plan.unmatched, text);
    assert.equal(plan.items.length, 0);
  }
});
test("missing he/we/time/go are explicit gaps; whole-phrase research aliases cannot fill them", () => {
  assert.ok(api);
  for (const [text, gap] of [
    ["我们工作", "我们"],
    ["他工作", "他"],
    ["我去医院", "去"],
    ["今天我工作", "今天"],
    ["谢谢", "谢谢"],
  ]) {
    const p = api.planCoreText(text, manifest);
    assert.equal(p.canPreview, false);
    assert.ok(
      p.gaps.some((g) => g.surface === gap),
      text,
    );
    assert.equal(p.unmatched, text);
  }
  assert.equal(
    api.planCoreText("我", manifest).items[0].id,
    "native_core_speaker_v1",
  );
  assert.equal(api.planCoreText("你好", manifest).canPreview, false);
  assert.equal(
    api.planCoreText("我" + "啊".repeat(600), manifest).canPreview,
    false,
  );
});
