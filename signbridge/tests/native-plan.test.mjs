import test from "node:test";
import assert from "node:assert/strict";
let api;
try {
  api = await import("../src/demo/native-plan.js");
} catch (e) {
  if (e.code !== "ERR_MODULE_NOT_FOUND") throw e;
}
const clips = ["我", "你", "帮助", "没有", "谢谢"].map((text, i) => ({
  id: "native_" + i,
  text,
  aliases: [text],
  source: "native",
}));
test("native composition preserves actor and patient and real per-unit sources", () => {
  assert.ok(api);
  const a = api.planNativeText("我帮你", clips),
    b = api.planNativeText("你帮我", clips);
  assert.equal(a.canPreview, true);
  assert.deepEqual(
    a.items.map((i) => i.id),
    ["native_0", "native_2", "native_1"],
  );
  assert.deepEqual(
    b.items.map((i) => i.id),
    ["native_1", "native_2", "native_0"],
  );
  assert.deepEqual(
    a.items.map((i) => i.semanticRole),
    ["actor", "predicate", "patient"],
  );
  assert.notEqual(a.analysis.meaningKey, b.analysis.meaningKey);
  const c = api.planNativeText("我们帮助他", clips);
  assert.equal(c.items[0].source, "semantic");
  assert.equal(c.items[1].source, "native");
  assert.equal(c.items[2].source, "semantic");
  assert.equal(c.cslTranslationVerified, false);
  assert.equal(api.planNativeText("我们", clips).items[0].source, "semantic");
  assert.equal(api.planNativeText("他", clips).items[0].id, "csl_he");
});
test("native whole clips are never sliced to fabricate words; unknowns and scope are retained", () => {
  assert.ok(api);
  const full = [
    {
      id: "native_whole",
      text: "我帮助你",
      aliases: ["我帮助你"],
      source: "native",
    },
  ];
  assert.equal(
    api.planNativeText("我帮助你", full).route,
    "native_exact_candidate",
  );
  assert.equal(api.planNativeText("我", full).canPreview, false);
  for (const text of ["我不想去", "我帮你但是明天取消", "我想不去"]) {
    const p = api.planNativeText(text, clips);
    assert.equal(p.canPreview, false);
    assert.equal(p.unmatched, text);
    assert.equal(p.items.length, 0);
  }
});
test("catalog explicit variant is respected and cannot cross a label boundary", () => {
  assert.ok(api);
  const other = { ...clips[0], id: "native_alternate" };
  assert.equal(
    api.planNativeText("我", [...clips, other], { nativeId: other.id }).items[0]
      .id,
    other.id,
  );
  assert.equal(
    api.planNativeText("你", [...clips, other], { nativeId: other.id }).items[0]
      .id,
    clips[1].id,
  );
  assert.equal(api.planNativeText("我爱你啊", clips).canPreview, false);
});
