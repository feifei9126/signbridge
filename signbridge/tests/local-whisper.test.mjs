import assert from "node:assert/strict";
import test from "node:test";

const { normalizeLocalModel, preferredModelHosts } =
  await import("../src/asr/local-whisper.js");

test("local Whisper selects supported models", () => {
  assert.equal(normalizeLocalModel("base"), "base");
  assert.equal(normalizeLocalModel("medium"), "tiny");
});

test("Chinese browsers prefer the reachable model mirror", () => {
  assert.equal(preferredModelHosts("zh-CN")[0], "https://hf-mirror.com/");
  assert.equal(preferredModelHosts("en-US")[0], "https://huggingface.co/");
});
