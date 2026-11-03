import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
let api;
try {
  api = await import("../src/demo/native-motion.js");
} catch (e) {
  if (e.code !== "ERR_MODULE_NOT_FOUND") throw e;
}
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
function fixture() {
  assert.ok(api);
  const entry = {
    id: "native_fit_test",
    text: "我",
    aliases: ["我"],
    source: "native",
    fps: 25,
    frames: 4,
    source_uid: "chunk:fit_test",
    source_sha256: "a".repeat(64),
    native_sha256: "b".repeat(64),
    model_sha256: api.NATIVE_MODEL_SHA256,
    display_profile: "raw",
    numeric_gate_passed: true,
    ...api.NATIVE_FLAGS,
  };
  const clip = {
    schema: "signbridge-native-quaternion-clip-v1",
    ...entry,
    bones: api.NATIVE_BONES,
    quaternions: Array.from({ length: 4 }, () =>
      api.NATIVE_BONES.flatMap(() => [0, 0, 0, 1]),
    ),
  };
  const bytes = Buffer.from(JSON.stringify(clip));
  const index = {
    schema: "signbridge-native-motion-index-v1",
    representation: "godette-local-quaternion-v1",
    model_sha256: api.NATIVE_MODEL_SHA256,
    source_index_sha256: "c".repeat(64),
    ...api.NATIVE_FLAGS,
    clips: [
      { ...entry, asset: "native/native_fit_test.json", sha256: digest(bytes) },
    ],
  };
  return { entry: index.clips[0], clip, index, bytes };
}
test("native index/clip bind model, candidate flags, exact signing bones and unit rotations", () => {
  const f = fixture();
  assert.equal(api.validateNativeIndex(f.index), f.index);
  assert.equal(api.decodeNativeClip(f.clip, f.entry).length, 4);
  for (const changed of [
    { ...f.index, model_sha256: "f".repeat(64) },
    { ...f.index, human_approved: true },
    { ...f.index, clips: [f.entry, f.entry] },
  ])
    assert.throws(() => api.validateNativeIndex(changed));
  for (const change of [
    (c) => c.quaternions.pop(),
    (c) => (c.quaternions[0][0] = NaN),
    (c) => c.bones.pop(),
    (c) => (c.quaternions[0][3] = 2),
    (c) => (c.text_verified = "我"),
  ]) {
    const clone = structuredClone(f.clip);
    change(clone);
    assert.throws(() => api.decodeNativeClip(clone, f.entry));
  }
});
test("native loader checks byte hash, shares requests and permits retry after failure", async () => {
  const f = fixture();
  let calls = 0;
  const loader = api.createNativeLoader(f.index, async () => {
    calls++;
    return new Response(calls === 1 ? "tampered" : f.bytes);
  });
  await assert.rejects(() => loader.load(f.entry.id));
  const [a, b] = await Promise.all([
    loader.load(f.entry.id),
    loader.load(f.entry.id),
  ]);
  assert.equal(a, b);
  assert.equal(calls, 2);
  assert.equal(a.frames.length, 4);
  loader.clear();
});
