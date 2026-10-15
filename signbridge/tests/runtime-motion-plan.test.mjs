import assert from "node:assert/strict";
import test from "node:test";
import * as runtime from "../src/avatar/runtime-motion-plan.js";
import { compileTranslationMatchers } from "../src/avatar/sign-language-data.js";

const clips = [
  { id: "trained", text: "工作忙吗？", aliases: ["工作忙吗？"] },
  {
    id: "fit",
    text: "认识你很高兴",
    aliases: ["认识你很高兴"],
    experimental: true,
  },
];
test("subtitle spans preserve trained and fitted motions between dictionary gaps", () => {
  const plan = runtime.planRealtimeText(
    "谢谢！工作忙吗？谢谢，认识你很高兴",
    clips,
  );
  assert.deepEqual(
    plan.items.map((item) => item.source),
    ["dictionary", "t08", "dictionary", "experimental"],
  );
  assert.equal(plan.items[1].id, "trained");
  assert.equal(plan.items[3].id, "fit");
  assert.deepEqual(plan.unmatched, []);
});
test("uncovered text cannot fabricate a reference or play a neutral placeholder", () => {
  const plan = runtime.planRealtimeText("工作🚀忙吗？宇宙飞船", clips);
  assert.ok(plan.items.every((item) => item.source === "dictionary"));
  assert.ok(plan.unmatched.length > 0);
  assert.equal(runtime.planRealtimeText("宇宙飞船", clips).items.length, 0);
});
test("dictionary gaps retain enabled custom motions and input limits", () => {
  const matchers = compileTranslationMatchers([
    {
      id: "custom",
      texts: ["专用短语"],
      gloss: "custom",
      frames: [{ value: {}, duration: 0.3 }],
    },
  ]);
  const plan = runtime.planRealtimeText(
    "专用短语，工作忙吗？",
    clips,
    matchers,
  );
  assert.equal(plan.items[0].translation.matches[0].id, "custom");
  assert.equal(plan.items[1].id, "trained");
  const long = runtime.planRealtimeText("工作忙吗？".repeat(110), clips);
  assert.ok(long.truncated);
  assert.ok(long.items.length <= 40);
  assert.ok(long.remainingText.length > 0);
});
