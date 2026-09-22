import {
  validateMotionAsset,
  motionIdentity,
  serializeMotionAsset,
} from "./motion-asset.js";
import { SIGNS, translationAliasKey } from "./sign-language-data.js";
import {
  createMotionPack,
  validateMotionPack,
  inspectMotionPack,
} from "./motion-pack.js";

const MOTION_STORAGE_PREFIX = "signbridge.motion.v1.";
const normalizedAlias = translationAliasKey;
const builtinAliases = new Set(
  Object.values(SIGNS).flatMap((sign) => sign.texts.map(normalizedAlias)),
);

function motionError(message, detail = "") {
  const error = new Error(message);
  error.detail = detail;
  return error;
}

function isConfirmed(entry) {
  return (
    entry.enabled === true &&
    typeof entry.review?.confirmedAt === "string" &&
    entry.review.assetJson === serializeMotionAsset(entry.asset)
  );
}

function aliasConflict(asset, aliases) {
  if (!asset.texts.length) return "texts";
  return (
    asset.texts.find(
      (text) => !normalizedAlias(text) || aliases.has(normalizedAlias(text)),
    ) ?? null
  );
}

function selectEnabledMotions(entries) {
  const used = new Set(builtinAliases);
  const motions = [];
  for (const entry of [...entries].sort((first, second) =>
    first.asset.id.localeCompare(second.asset.id),
  )) {
    if (!isConfirmed(entry) || aliasConflict(entry.asset, used) !== null)
      continue;
    motions.push(entry.asset);
    entry.asset.texts.forEach((text) => used.add(normalizedAlias(text)));
  }
  return motions;
}

function createMotionLibrary(
  rig,
  storage = globalThis.chrome?.storage,
  locks = globalThis.navigator?.locks,
) {
  if (!storage?.local) throw motionError("motionStorageUnavailable");
  const area = storage.local;
  const write = (operation) =>
    locks ? locks.request(MOTION_STORAGE_PREFIX, operation) : operation();
  async function list() {
    const values = await area.get(null);
    const entries = [];
    let invalidCount = 0;
    for (const [key, stored] of Object.entries(values)) {
      if (!key.startsWith(MOTION_STORAGE_PREFIX)) continue;
      try {
        const asset = validateMotionAsset(stored.asset, rig);
        if (key !== MOTION_STORAGE_PREFIX + asset.id)
          throw motionError("motionInvalidData");
        entries.push({
          asset,
          enabled: isConfirmed({ ...stored, asset }),
          review: stored.review,
        });
      } catch {
        invalidCount += 1;
      }
    }
    return { entries, invalidCount };
  }
  async function saveDraft(input) {
    const asset = validateMotionAsset(input, rig);
    const entry = { asset, enabled: false, review: null };
    await write(() => area.set({ [MOTION_STORAGE_PREFIX + asset.id]: entry }));
    return entry;
  }
  async function setEnabled(id, enabled, expectedAsset) {
    return write(async () => {
      const { entries } = await list();
      const entry = entries.find((candidate) => candidate.asset.id === id);
      if (!entry) throw motionError("motionSelectFirst");
      if (enabled) {
        if (motionIdentity(entry.asset) !== motionIdentity(expectedAsset))
          throw motionError("motionSaveFirst");
        const aliases = new Set(builtinAliases);
        for (const other of entries) {
          if (other.asset.id !== id && isConfirmed(other))
            other.asset.texts.forEach((text) =>
              aliases.add(normalizedAlias(text)),
            );
        }
        const conflict = aliasConflict(entry.asset, aliases);
        if (conflict !== null)
          throw motionError("motionAliasConflict", conflict);
      }
      await area.set({
        [MOTION_STORAGE_PREFIX + id]: {
          asset: entry.asset,
          enabled,
          review: enabled
            ? {
                confirmedAt: new Date().toISOString(),
                assetJson: serializeMotionAsset(entry.asset),
              }
            : null,
        },
      });
    });
  }
  async function storedMotions() {
    const values = await area.get(null);
    return Object.fromEntries(
      Object.entries(values)
        .filter(([key]) => key.startsWith(MOTION_STORAGE_PREFIX))
        .map(([key, value]) => [
          key.slice(MOTION_STORAGE_PREFIX.length),
          value,
        ]),
    );
  }
  async function exportPack() {
    const { entries, invalidCount } = await list();
    if (invalidCount) throw motionError("motionPackInvalidStored");
    return createMotionPack(entries, rig);
  }
  async function previewPack(input) {
    const pack = validateMotionPack(input, rig);
    return inspectMotionPack(pack, await storedMotions(), rig);
  }
  async function importPack(input, expectedRevision) {
    if (!locks?.request) throw motionError("motionPackLockUnavailable");
    const pack = validateMotionPack(input, rig);
    return write(async () => {
      const plan = inspectMotionPack(pack, await storedMotions(), rig);
      if (plan.revision !== expectedRevision)
        throw motionError("motionPackStale");
      if (plan.counts.conflict) throw motionError("motionPackConflict");
      const newIds = new Set(
        plan.items
          .filter((item) => item.state === "new")
          .map((item) => item.id),
      );
      const updates = Object.fromEntries(
        pack.motions
          .filter(({ asset }) => newIds.has(asset.id))
          .map(({ asset }) => [
            MOTION_STORAGE_PREFIX + asset.id,
            { asset, enabled: false, review: null },
          ]),
      );
      if (newIds.size) await area.set(updates);
      return { imported: newIds.size, skipped: plan.counts.existing };
    });
  }
  function subscribe(listener) {
    const handler = (changes, areaName) => {
      if (
        areaName === "local" &&
        Object.keys(changes).some((key) =>
          key.startsWith(MOTION_STORAGE_PREFIX),
        )
      )
        listener();
    };
    storage.onChanged.addListener(handler);
    return () => storage.onChanged.removeListener(handler);
  }
  return {
    list,
    saveDraft,
    setEnabled,
    subscribe,
    exportPack,
    previewPack,
    importPack,
  };
}

export { MOTION_STORAGE_PREFIX, createMotionLibrary, selectEnabledMotions };
