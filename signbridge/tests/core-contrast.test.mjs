import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { evaluateCoreCases } from "../src/tools/sign-core-eval.mjs";
const words = [
  ["speaker", "我"],
  ["addressee", "你"],
  ["work", "工作"],
  ["healthy", "健康"],
  ["relax", "放松"],
  ["drive", "开车"],
  ["absence", "没有"],
  ["home", "家"],
  ["drink", "饮料"],
  ["clothes", "衣服"],
  ["shoes", "鞋"],
  ["banana", "香蕉"],
  ["trousers", "裤子"],
];
test("frozen contrast cases check coverage and refusals, never an all-refusal success", () => {
  const manifest = {
    units: words.map(([key, text]) => ({
      key,
      text,
      id: "native_core_" + key + "_v1",
    })),
  };
  const fixture = JSON.parse(
    readFileSync(new URL("./fixtures/core-sentence-v1.json", import.meta.url)),
  );
  const r = evaluateCoreCases(manifest, fixture);
  assert.equal(
    r.summary.failed,
    0,
    JSON.stringify(r.records.filter((c) => !c.passed)),
  );
  assert.ok(r.summary.expectedPlayable > 20);
  assert.ok(r.summary.expectedRefusals > 20);
  assert.equal(r.summary.unexpectedAcceptance, 0);
  assert.equal(r.summary.incorrectRefusal, 0);
});
test("expanded frozen contrasts keep wrong object types and unknown clause tails blocked", () => {
  const expanded = [
    ...words,
    ["run", "跑步"],
    ["bathe", "洗澡"],
    ["returnhome", "回家"],
    ["hear", "听"],
    ["scarf", "围巾"],
    ["hat", "帽子"],
    ["jacket", "夹克"],
    ["socks", "袜子"],
    ["rice", "大米"],
    ["vinegar", "醋"],
    ["photo", "照片"],
    ["seasoning", "味精"],
    ["earrings", "耳环"],
    ["sunny", "晴"],
    ["age", "年龄"],
    ["sour", "酸"],
    ["bitter", "苦"],
  ];
  const manifest = {
    units: expanded.map(([key, text]) => ({
      key,
      text,
      id: "native_core_" + key + "_v1",
    })),
  };
  const fixture = JSON.parse(
    readFileSync(new URL("./fixtures/core-sentence-v2.json", import.meta.url)),
  );
  const r = evaluateCoreCases(manifest, fixture);
  assert.equal(
    r.summary.failed,
    0,
    JSON.stringify(r.records.filter((c) => !c.passed)),
  );
  assert.equal(r.summary.unexpectedAcceptance, 0);
  assert.equal(r.summary.incorrectRefusal, 0);
  assert.ok(r.summary.expectedPlayable > 60);
  assert.ok(r.summary.expectedRefusals >= 60);
});
