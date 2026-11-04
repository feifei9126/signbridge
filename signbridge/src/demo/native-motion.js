import { Quaternion } from "three";
import { REQUIRED_SIGNING_BONES } from "../avatar/humanoid-rig.js";
import { MOTION_STABILIZATION_PROFILES } from "./motion-stabilization.js";
import { REPAIR_PROFILES } from "./motion-repair.js";

export const NATIVE_MODEL_SHA256 =
  "97c3bcc37aeb0212203376ba3e69c4c7346357dcef8e2b626768e96ecfe1dc69";
export const NATIVE_FLAGS = Object.freeze({
  human_approved: false,
  semantics_approved: false,
  boundaries_approved: false,
  text_verified: "",
  training_ready: false,
  model_training_ready: false,
  training_started: false,
});
export const NATIVE_BONES = Object.freeze([
  "neck",
  "head",
  "leftShoulder",
  "rightShoulder",
  ...REQUIRED_SIGNING_BONES,
]);
const digest = /^[a-f0-9]{64}$/;
const candidateFlags = (obj) =>
  Object.entries(NATIVE_FLAGS).every(([key, value]) => obj?.[key] === value);
const invalid = () => {
  throw new Error("nativeInvalidAsset");
};
function validEntry(c) {
  return (
    candidateFlags(c) &&
    /^native_[a-zA-Z0-9_-]+$/.test(c.id) &&
    typeof c.text === "string" &&
    c.text.trim() &&
    c.text.length <= 500 &&
    Array.isArray(c.aliases) &&
    c.aliases.length > 0 &&
    c.aliases.length <= 50 &&
    c.aliases.every(
      (s) => typeof s === "string" && s.trim() && s.length <= 500,
    ) &&
    c.source === "native" &&
    Number.isInteger(c.frames) &&
    c.frames >= 4 &&
    c.frames <= 2000 &&
    Number.isFinite(c.fps) &&
    c.fps > 0 &&
    c.fps <= 120 &&
    [c.native_sha256, c.source_sha256].every((s) => digest.test(s)) &&
    c.model_sha256 === NATIVE_MODEL_SHA256 &&
    c.numeric_gate_passed === true &&
    (c.display_profile === "raw" ||
      Object.hasOwn(MOTION_STABILIZATION_PROFILES, c.display_profile) ||
      Object.hasOwn(REPAIR_PROFILES, c.display_profile))
  );
}
export function validateNativeIndex(index) {
  if (
    index?.schema !== "signbridge-native-motion-index-v1" ||
    index.representation !== "godette-local-quaternion-v1" ||
    index.model_sha256 !== NATIVE_MODEL_SHA256 ||
    !digest.test(index.source_index_sha256) ||
    !candidateFlags(index) ||
    !Array.isArray(index.clips) ||
    index.clips.length > 400
  )
    invalid();
  const ids = new Set();
  for (const c of index.clips) {
    if (
      !validEntry(c) ||
      ids.has(c.id) ||
      c.asset !== `native/${c.id}.json` ||
      !digest.test(c.sha256)
    )
      invalid();
    ids.add(c.id);
  }
  return index;
}
export function decodeNativeClip(clip, entry) {
  if (
    clip?.schema !== "signbridge-native-quaternion-clip-v1" ||
    !validEntry(clip) ||
    ![
      "id",
      "text",
      "fps",
      "frames",
      "source_uid",
      "source_sha256",
      "native_sha256",
      "display_profile",
      "model_sha256",
    ].every((k) => clip[k] === entry[k]) ||
    JSON.stringify(clip.aliases) !== JSON.stringify(entry.aliases) ||
    !Array.isArray(clip.bones) ||
    clip.bones.length !== 40 ||
    new Set(clip.bones).size !== 40 ||
    !NATIVE_BONES.every((name) => clip.bones.includes(name)) ||
    clip.quaternions?.length !== clip.frames
  )
    invalid();
  if (entry.core_unit_key !== undefined) {
    const fields = [
      "core_unit_key",
      "lexical_role",
      "parent_native_id",
      "parent_asset_sha256",
      "boundary_status",
      "semantics_status",
    ];
    const range = entry.source_frame_range_1based;
    if (
      !fields.every((k) => clip[k] === entry[k]) ||
      !Array.isArray(range) ||
      range.length !== 2 ||
      !range.every(Number.isInteger) ||
      range[1] - range[0] + 1 !== clip.frames ||
      JSON.stringify(clip.source_frame_range_1based) !==
        JSON.stringify(range) ||
      JSON.stringify(clip.source_frame_ids_1based) !==
        JSON.stringify(
          Array.from({ length: clip.frames }, (_, i) => range[0] + i),
        )
    )
      invalid();
  }
  return clip.quaternions.map((values) => {
    if (
      !Array.isArray(values) ||
      values.length !== 160 ||
      !values.every(Number.isFinite)
    )
      invalid();
    return Object.fromEntries(
      clip.bones.map((bone, i) => {
        const q = new Quaternion(...values.slice(i * 4, i * 4 + 4));
        if (Math.abs(q.length() - 1) > 1e-5) invalid();
        return [bone, q.normalize()];
      }),
    );
  });
}
export function createNativeLoader(index, fetchAsset = (path) => fetch(path)) {
  validateNativeIndex(index);
  const cache = new Map();
  return {
    async load(id) {
      const entry = index.clips.find((c) => c.id === id);
      if (!entry) invalid();
      if (cache.has(id)) {
        const existing = cache.get(id);
        cache.delete(id);
        cache.set(id, existing);
        return existing;
      }
      const promise = (async () => {
        const response = await fetchAsset(entry.asset);
        if (!response.ok) invalid();
        const bytes = await response.arrayBuffer();
        if (bytes.byteLength > 12 * 1024 * 1024) invalid();
        const hash = [
          ...new Uint8Array(
            await globalThis.crypto.subtle.digest("SHA-256", bytes),
          ),
        ]
          .map((v) => v.toString(16).padStart(2, "0"))
          .join("");
        if (hash !== entry.sha256) invalid();
        const clip = JSON.parse(new globalThis.TextDecoder().decode(bytes));
        return { clip, frames: decodeNativeClip(clip, entry) };
      })();
      cache.set(id, promise);
      while (cache.size > 6) cache.delete(cache.keys().next().value);
      promise.catch(() => {
        if (cache.get(id) === promise) cache.delete(id);
      });
      return promise;
    },
    has(id) {
      return cache.has(id);
    },
    clear() {
      cache.clear();
    },
  };
}
