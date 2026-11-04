import { NATIVE_FLAGS, validateNativeIndex } from "./native-motion.js";
const digest = /^[a-f0-9]{64}$/;
function fail() {
  throw new Error("coreInvalidAsset");
}
export function validateCoreManifest(data, index) {
  validateNativeIndex(index);
  if (
    data?.schema !== "signbridge-core-motion-v1" ||
    !digest.test(data.native_index_sha256) ||
    !digest.test(data.alignment_sha256) ||
    !Array.isArray(data.units) ||
    data.units.length < 1 ||
    data.units.length > 20 ||
    !Object.entries(NATIVE_FLAGS).every(([k, v]) => data[k] === v)
  )
    fail();
  const ids = new Set(),
    labels = new Set();
  for (const unit of data.units) {
    const entry = index.clips.find((c) => c.id === unit.id),
      range = unit.source_frame_range_1based;
    if (
      !entry ||
      typeof unit.key !== "string" ||
      !/^[a-z]+$/.test(unit.key) ||
      ids.has(unit.id) ||
      labels.has(unit.text) ||
      entry.text !== unit.text ||
      entry.aliases.length !== 1 ||
      entry.aliases[0] !== unit.text ||
      entry.frames !== unit.frames ||
      entry.fps !== unit.fps ||
      entry.core_unit_key !== unit.key ||
      !["person", "predicate", "noun", "absence"].includes(unit.role) ||
      entry.lexical_role !== unit.role ||
      !Array.isArray(range) ||
      range.length !== 2 ||
      !range.every(Number.isInteger) ||
      range[0] < 1 ||
      range[1] - range[0] + 1 !== unit.frames ||
      JSON.stringify(entry.source_frame_range_1based) !==
        JSON.stringify(range) ||
      entry.parent_native_id !== unit.parent_native_id ||
      entry.parent_asset_sha256 !== unit.parent_asset_sha256 ||
      !digest.test(unit.parent_asset_sha256) ||
      entry.boundary_status !== "assistant_proposed_frame_interval"
    )
      fail();
    const parent = index.clips.find((c) => c.id === unit.parent_native_id);
    if (
      !parent ||
      parent.sha256 !== unit.parent_asset_sha256 ||
      range[1] > parent.frames
    )
      fail();
    ids.add(unit.id);
    labels.add(unit.text);
  }
  return data;
}
export async function readCoreManifest(response, index, indexBytes) {
  if (!response.ok) fail();
  const data = await response.json();
  if (data.unavailable) return null;
  const actual = [
    ...new Uint8Array(
      await globalThis.crypto.subtle.digest("SHA-256", indexBytes),
    ),
  ]
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
  if (actual !== data.native_index_sha256) fail();
  return validateCoreManifest(data, index);
}
