import assert from "node:assert/strict";
import test from "node:test";

import { HUMANOID_BONES } from "../src/avatar/humanoid-rig.js";

import {
  CHARS,
  GESTURES,
  SIGNS,
  findGesture,
  gesture,
  handShape,
  normalizeText,
  translateText,
} from "../src/avatar/sign-language-data.js";

test("dictionary keeps the published coverage", () => {
  assert.equal(Object.keys(SIGNS).length, 52);
  assert.equal(Object.keys(GESTURES).length, 172);
  assert.equal(Object.keys(CHARS).length, 16);
});

test("every published alias still matches as a complete term", () => {
  for (const alias of Object.keys(GESTURES)) {
    const result = translateText(alias);
    assert.equal(result.matches.length, 1, alias);
    assert.deepEqual(result.unmatched, [], alias);
    assert.deepEqual(result.frames[0], GESTURES[alias][0], alias);
  }
});

test("every sign exposes a versioned humanoid motion clip", () => {
  const knownBones = new Set(HUMANOID_BONES);
  for (const sign of Object.values(SIGNS)) {
    assert.equal(sign.motion.id, sign.id);
    assert.equal(sign.motion.space, "humanoid-local-v1");
    assert.equal(sign.motion.frames, sign.frames);
    for (const frame of sign.frames) {
      for (const bone of Object.keys(frame.value)) {
        assert.equal(knownBones.has(bone), true, `${sign.id}: ${bone}`);
      }
    }
  }
});

test("hand shapes drive full finger chains without changing the other hand", () => {
  const fist = handShape("fist", "right");
  assert.equal(Object.keys(fist).length, 15);
  assert.ok(fist.rightIndexProximal);
  assert.ok(fist.rightIndexIntermediate);
  assert.ok(fist.rightIndexDistal);
  assert.equal(
    Object.keys(fist).some((name) => name.startsWith("left")),
    false,
  );

  const oneHand = gesture(new Array(12).fill(0), "flat");
  assert.equal(
    Object.keys(oneHand).some((name) => name.startsWith("left")),
    false,
  );
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

test("English aliases match whole words without case sensitivity", () => {
  assert.equal(translateText("Hello").matches[0].id, "csl_hello");
  for (const text of ["higher", "doctor", "thisisnot", "can't", "don't"]) {
    assert.deepEqual(translateText(text).matches, [], text);
  }
  assert.deepEqual(
    translateText("HELLO, you!").matches.map((match) => match.id),
    ["csl_hello", "csl_you"],
  );
});

test("function words are skipped as tokens, never removed inside a word", () => {
  for (const text of ["了不起", "不一定"]) {
    assert.deepEqual(translateText(text).matches, [], text);
    assert.deepEqual(findGesture(text).matches, [], text);
  }
  assert.deepEqual(
    translateText("过来吧").matches.map((match) => match.text),
    ["过来"],
  );
  assert.deepEqual(
    translateText("你好吗").matches.map((match) => match.id),
    ["csl_hello"],
  );
});

test("translation reports unknown words and the unplayed truncated tail", () => {
  const partial = translateText("我们今天去医院看医生");
  assert.deepEqual(partial.unmatched, ["医院", "医生"]);
  assert.equal(partial.truncated, false);
  const limited = translateText("可以".repeat(13));
  assert.equal(limited.matches.length, 12);
  assert.equal(limited.truncated, true);
  assert.equal(limited.remainingText, "可以");
});
