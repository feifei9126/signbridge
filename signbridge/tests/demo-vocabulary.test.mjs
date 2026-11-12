import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SIGNS } from "../src/avatar/sign-language-data.js";

const raw = readFileSync(
  new URL("../src/demo/demo-vocabulary.json", import.meta.url),
  "utf8",
);
const vocabulary = JSON.parse(raw);
const NATIVE = "native_display_candidate";
const POSE = "builtin_handmade_pose";
const count = (status) =>
  vocabulary.entries.filter((e) => e.status === status).length;

test("basic vocabulary lists at least 100 unique entries and is not approved", () => {
  assert.equal(vocabulary.schema, "signbridge-demo-vocabulary-ui-v1");
  assert.equal(vocabulary.humanApproved, false);
  assert.ok(vocabulary.entries.length >= 100);
  assert.equal(
    new Set(vocabulary.entries.map((e) => e.text)).size,
    vocabulary.entries.length,
  );
});

test("status counts stay honest about how many words have a motion", () => {
  assert.equal(count(NATIVE), 29);
  assert.equal(count(POSE), 44);
  assert.equal(count("isolated_by_technical_gate"), 52);
  assert.equal(count("list_only"), 16);
  assert.equal(vocabulary.entries.length, 141);
});

test("built-in pose entries map to exactly one dictionary sign", () => {
  const signs = Object.values(SIGNS);
  for (const entry of vocabulary.entries.filter((e) => e.status === POSE)) {
    const hits = signs.filter((s) => entry.forms.includes(s.gloss));
    assert.equal(hits.length, 1, entry.text);
    assert.equal(entry.nativeId, null, entry.text);
  }
});

test("entries without a motion name no motion id and carry no private data", () => {
  for (const entry of vocabulary.entries.filter(
    (e) => e.status !== NATIVE && e.status !== POSE,
  ))
    assert.equal(entry.nativeId, null, entry.text);
  assert.ok(!raw.includes("/Users/"));
  assert.ok(!raw.toLowerCase().includes("seetacloud"));
  assert.ok(!raw.toLowerCase().includes("password"));
});

test("Demo loads the vocabulary and refuses to play words without a motion", () => {
  const source = readFileSync(
    new URL("../src/demo/demo.js", import.meta.url),
    "utf8",
  );
  assert.ok(source.includes("demo-vocabulary.json"));
  assert.ok(
    source.includes("blockedVocab !== null && input.value === blockedVocab"),
  );
});
