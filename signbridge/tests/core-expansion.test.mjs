import test from "node:test";
import assert from "node:assert/strict";
import { planCoreText } from "../src/demo/core-plan.js";
const definitions = [
  ["speaker", "我", "person"],
  ["addressee", "你", "person"],
  ["home", "家", "noun"],
  ["work", "工作", "predicate"],
  ["run", "跑步", "predicate"],
  ["bathe", "洗澡", "predicate"],
  ["returnhome", "回家", "predicate"],
  ["hear", "听", "predicate"],
  ["scarf", "围巾", "noun"],
  ["hat", "帽子", "noun"],
  ["absence", "没有", "absence"],
  ["sunny", "晴", "noun"],
  ["age", "年龄", "noun"],
  ["rice", "大米", "noun"],
];
const manifest = {
  units: definitions.map(([key, text, role]) => ({
    key,
    text,
    role,
    id: "native_core_" + key + "_v1",
  })),
};
test("expanded events retain exact core IDs and swapped actors without borrowing missing actions", () => {
  for (const word of ["跑步", "洗澡", "回家", "听"])
    for (const person of ["我", "你"]) {
      const p = planCoreText(person + word, manifest);
      assert.equal(p.canPreview, true, person + word);
      assert.equal(p.analysis.meaning.actor.surface, person);
      assert.equal(
        p.items[1].id,
        manifest.units.find((u) => u.text === word).id,
      );
    }
  const p = planCoreText("我回家", manifest);
  assert.equal(p.items.length, 2);
  assert.equal(p.gaps.length, 0);
  assert.equal(planCoreText("我去家", manifest).canPreview, false);
});
test("possessive absence accepts physical objects, rejects participants events weather and abstract measures", () => {
  for (const word of ["围巾", "帽子", "大米"])
    assert.equal(planCoreText("我没有" + word, manifest).canPreview, true);
  for (const text of [
    "我没有我",
    "我没有你",
    "我没有跑步",
    "你没有洗澡",
    "我没有晴",
    "我没有年龄",
    "我有你",
    "我跑步医院",
    "我洗澡但你不洗澡",
    "我回家了",
    "我不跑步",
  ]) {
    const p = planCoreText(text, manifest);
    assert.equal(p.canPreview, false, text);
    assert.equal(p.items.length, 0);
    assert.equal(p.unmatched, text);
  }
});
