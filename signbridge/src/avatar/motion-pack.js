import {
  MAX_MOTION_BYTES,
  serializeMotionAsset,
  validateMotionAsset,
} from "./motion-asset.js";
import { SIGNS, translationAliasKey } from "./sign-language-data.js";

const MAX_MOTION_PACK_BYTES = 8 * 1024 * 1024;
const MAX_MOTION_PACK_ASSETS = 500;

function reject(message = "motionPackInvalid") {
  throw new Error(message);
}

function validateMotionPack(input, rig) {
  if (
    input?.type !== "signbridge-motion-pack" ||
    input.version !== 1 ||
    typeof input.createdAt !== "string" ||
    !Number.isFinite(Date.parse(input.createdAt)) ||
    !Array.isArray(input.motions)
  )
    reject();
  if (!input.motions.length) reject("motionPackEmpty");
  if (input.motions.length > MAX_MOTION_PACK_ASSETS)
    reject("motionPackTooLarge");
  const ids = new Set();
  const motions = input.motions.map((entry) => {
    const asset = validateMotionAsset(entry?.asset, rig);
    if (ids.has(asset.id)) reject("motionPackDuplicateId");
    ids.add(asset.id);
    if (new Blob([serializeMotionAsset(asset)]).size > MAX_MOTION_BYTES)
      reject("motionPackTooLarge");
    return { asset, wasEnabled: entry.wasEnabled === true };
  });
  const pack = {
    type: "signbridge-motion-pack",
    version: 1,
    createdAt: input.createdAt,
    motions,
  };
  if (new Blob([JSON.stringify(pack, null, 2)]).size > MAX_MOTION_PACK_BYTES)
    reject("motionPackTooLarge");
  return pack;
}

function createMotionPack(entries, rig) {
  return validateMotionPack(
    {
      type: "signbridge-motion-pack",
      version: 1,
      createdAt: new Date().toISOString(),
      motions: entries.map((entry) => ({
        asset: entry.asset,
        wasEnabled: entry.enabled === true,
      })),
    },
    rig,
  );
}

function parseMotionPack(json, rig) {
  if (typeof json !== "string") reject();
  if (new Blob([json]).size > MAX_MOTION_PACK_BYTES)
    reject("motionPackTooLarge");
  let input;
  try {
    input = JSON.parse(json);
  } catch {
    reject();
  }
  return validateMotionPack(input, rig);
}

function inspectMotionPack(input, stored, rig) {
  const pack = validateMotionPack(input, rig);
  const aliases = new Map();
  function addAliases(asset) {
    for (const text of asset.texts) {
      const key = translationAliasKey(text);
      if (!aliases.has(key)) aliases.set(key, new Set());
      aliases.get(key).add(asset.id);
    }
  }
  Object.values(SIGNS).forEach(addAliases);
  const valid = new Map();
  for (const [id, entry] of Object.entries(stored)) {
    try {
      const asset = validateMotionAsset(entry?.asset, rig);
      if (asset.id !== id) continue;
      valid.set(id, asset);
      addAliases(asset);
    } catch {
      continue;
    }
  }
  pack.motions.forEach((entry) => addAliases(entry.asset));
  const counts = { new: 0, existing: 0, conflict: 0 };
  const items = pack.motions.map(({ asset, wasEnabled }) => {
    let state = "new";
    if (Object.hasOwn(stored, asset.id)) {
      state =
        valid.has(asset.id) &&
        serializeMotionAsset(valid.get(asset.id)) ===
          serializeMotionAsset(asset)
          ? "existing"
          : "conflict";
    }
    counts[state] += 1;
    return {
      id: asset.id,
      gloss: asset.gloss,
      state,
      wasEnabled,
      aliasConflicts: asset.texts.filter((text) => {
        const key = translationAliasKey(text);
        return !key || [...aliases.get(key)].some((id) => id !== asset.id);
      }),
      emptyTexts: asset.texts.length === 0,
    };
  });
  return { pack, items, counts, revision: serializeMotionAsset(stored) };
}

export {
  MAX_MOTION_PACK_BYTES,
  MAX_MOTION_PACK_ASSETS,
  createMotionPack,
  validateMotionPack,
  parseMotionPack,
  inspectMotionPack,
};
