import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  NATIVE_FLAGS,
  NATIVE_MODEL_SHA256,
} from "../src/demo/native-motion.js";
import {
  validateCoreManifest,
  readCoreManifest,
} from "../src/demo/core-motion.js";
const sha = (b) => createHash("sha256").update(b).digest("hex");
function fixture() {
  const parent = {
    id: "native_parent",
    asset: "native/native_parent.json",
    sha256: "d".repeat(64),
    text: "我",
    aliases: ["我"],
    source: "native",
    frames: 10,
    fps: 25,
    source_sha256: "a".repeat(64),
    native_sha256: "b".repeat(64),
    model_sha256: NATIVE_MODEL_SHA256,
    display_profile: "raw",
    numeric_gate_passed: true,
    ...NATIVE_FLAGS,
  };
  const entry = {
    ...parent,
    id: "native_core_speaker_v1",
    asset: "native/native_core_speaker_v1.json",
    sha256: "e".repeat(64),
    frames: 6,
    core_unit_key: "speaker",
    lexical_role: "person",
    source_frame_range_1based: [3, 8],
    parent_native_id: parent.id,
    parent_asset_sha256: parent.sha256,
    boundary_status: "assistant_proposed_frame_interval",
  };
  const index = {
    schema: "signbridge-native-motion-index-v1",
    representation: "godette-local-quaternion-v1",
    model_sha256: NATIVE_MODEL_SHA256,
    source_index_sha256: "c".repeat(64),
    clips: [entry, parent],
    ...NATIVE_FLAGS,
  };
  const bytes = Buffer.from(JSON.stringify(index));
  const unit = {
    id: entry.id,
    key: "speaker",
    text: "我",
    role: "person",
    frames: 6,
    fps: 25,
    source_frame_range_1based: [3, 8],
    parent_native_id: parent.id,
    parent_asset_sha256: parent.sha256,
  };
  const manifest = {
    schema: "signbridge-core-motion-v1",
    native_index_sha256: sha(bytes),
    alignment_sha256: "f".repeat(64),
    units: [unit],
    ...NATIVE_FLAGS,
  };
  return { manifest, index, bytes };
}
test("core manifest binds exact native frames, word identity and source parent while rejecting implicit approval", () => {
  const f = fixture();
  assert.equal(validateCoreManifest(f.manifest, f.index), f.manifest);
  for (const change of [
    (m) => (m.human_approved = true),
    (m) => (m.units[0].source_frame_range_1based = [4, 9]),
    (m) => (m.units[0].text = "我们"),
    (m) => (m.units[0].key = "../escape"),
    (m) => m.units.push(m.units[0]),
    (m) => (m.units[0].parent_asset_sha256 = "1".repeat(64)),
  ]) {
    const m = structuredClone(f.manifest);
    change(m);
    assert.throws(() => validateCoreManifest(m, f.index));
  }
});
test("runtime core manifest refuses a modified native index even when JSON is otherwise valid", async () => {
  const f = fixture();
  const response = () => new Response(JSON.stringify(f.manifest));
  assert.equal(
    (await readCoreManifest(response(), f.index, f.bytes)).units.length,
    1,
  );
  await assert.rejects(() =>
    readCoreManifest(response(), f.index, Buffer.from("{}")),
  );
});
