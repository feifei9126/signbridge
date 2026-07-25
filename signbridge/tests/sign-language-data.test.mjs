import assert from "node:assert/strict";
import test from "node:test";

import {
  CHARS,
  GESTURES,
  SIGNS,
  findGesture,
  normalizeText,
  translateText,
} from "../src/avatar/sign-language-data.js";

test("dictionary keeps the published coverage", () => {
  assert.equal(Object.keys(SIGNS).length, 52);
  assert.equal(Object.keys(GESTURES).length, 172);
  assert.equal(Object.keys(CHARS).length, 16);
});

test("normalization removes punctuation and normalizes spaces", () => {
  assert.equal(normalizeText("  你好，  世界！ "), "你好 世界");
});

test("translation skips function words and returns a known sign", () => {
  const result = findGesture("我觉得这个可以的");
  assert.deepEqual(result.frames, SIGNS.csl_can.frames);
});

test("sentence translation keeps multiple known signs in source order", () => {
  const result = translateText("我现在可以");
  assert.deepEqual(
    result.matches.map((match) => match.id),
    ["csl_me", "csl_now", "csl_can"],
  );
  assert.ok(result.frames.length > SIGNS.csl_can.frames.length);
});

test("unknown text returns a neutral frame", () => {
  const result = findGesture("未收录词汇甲乙丙");
  assert.equal(result.frames.length, 1);
  assert.deepEqual(result.frames[0].value, {});
});
