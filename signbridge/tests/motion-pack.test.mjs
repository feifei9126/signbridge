import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
import { LOCALES } from "../src/i18n/locales.js";
import {
  createMotionAsset,
  serializeMotionAsset,
} from "../src/avatar/motion-asset.js";
import {
  MAX_MOTION_PACK_BYTES,
  MAX_MOTION_PACK_ASSETS,
  createMotionPack,
  parseMotionPack,
  inspectMotionPack,
} from "../src/avatar/motion-pack.js";
import {
  MOTION_STORAGE_PREFIX,
  createMotionLibrary,
  selectEnabledMotions,
} from "../src/avatar/motion-library.js";

function fixture() {
  const root = new THREE.Object3D();
  const head = new THREE.Bone();
  head.name = "Head_129";
  root.add(head);
  const rig = createHumanoidRig(root);
  const asset = createMotionAsset(
    rig,
    [
      { value: { head: { x: -0.432156781923, y: 0, z: 0 } }, duration: 0.7 },
      { value: { head: { x: 0.223456789123, y: 0, z: 0 } }, duration: 1.4 },
    ],
    { id: "custom_pack", gloss: "pack fixture", texts: ["quasar"], tags: [] },
  );
  const values = {};
  const calls = [];
  let failWrite = false;
  let pending = Promise.resolve();
  const locks = {
    request: (_name, operation) => {
      const task = pending.then(operation);
      pending = task.catch(() => {});
      return task;
    },
  };
  const storage = {
    local: {
      get: async () => structuredClone(values),
      set: async (items) => {
        calls.push(structuredClone(items));
        if (failWrite) throw new Error("QUOTA_BYTES");
        Object.assign(values, structuredClone(items));
      },
    },
  };
  const library = createMotionLibrary(rig, storage, locks);
  const pack = createMotionPack([{ asset, enabled: true }], rig);
  return {
    rig,
    asset,
    pack,
    values,
    calls,
    library,
    storage,
    locks,
    fail: () => (failWrite = true),
  };
}

test("motion pack round-trip preserves exact frames but cannot carry approval or secrets", () => {
  const { rig, asset, pack } = fixture();
  const imported = parseMotionPack(
    JSON.stringify({
      ...pack,
      apiKey: "secret-must-not-leave-storage",
      motions: [
        { ...pack.motions[0], enabled: true, review: { trusted: true } },
      ],
    }),
    rig,
  );
  assert.deepEqual(imported.motions[0].asset, asset);
  assert.equal(imported.motions[0].wasEnabled, true);
  assert.equal(imported.motions[0].enabled, undefined);
  assert.equal(imported.motions[0].review, undefined);
  assert.equal(imported.apiKey, undefined);
});

test("invalid JSON, schema, duplicate IDs, bounds and rig mismatch reject the entire pack", () => {
  const { rig, pack } = fixture();
  const bad = [
    "{",
    JSON.stringify({ ...pack, version: 2 }),
    JSON.stringify({ ...pack, motions: [] }),
    JSON.stringify({ ...pack, motions: [pack.motions[0], pack.motions[0]] }),
    JSON.stringify({
      ...pack,
      motions: Array(MAX_MOTION_PACK_ASSETS + 1).fill(pack.motions[0]),
    }),
    " ".repeat(MAX_MOTION_PACK_BYTES + 1),
  ];
  const wrongRig = structuredClone(pack);
  wrongRig.motions[0].asset.rig.rest = "different";
  const invalidFrame = structuredClone(pack);
  invalidFrame.motions[0].asset.frames[0].duration = -1;
  bad.push(JSON.stringify(wrongRig), JSON.stringify(invalidFrame));
  for (const json of bad) assert.throws(() => parseMotionPack(json, rig));
});

test("preflight separates new, identical and conflicting IDs, including unreadable local records", () => {
  const { rig, asset, pack } = fixture();
  assert.equal(inspectMotionPack(pack, {}, rig).counts.new, 1);
  const identical = inspectMotionPack(pack, { [asset.id]: { asset } }, rig);
  assert.equal(identical.counts.existing, 1);
  for (const stored of [
    { asset: { ...asset, gloss: "changed" } },
    null,
    { asset: {} },
  ]) {
    assert.equal(
      inspectMotionPack(pack, { [asset.id]: stored }, rig).counts.conflict,
      1,
    );
  }
});

test("preflight warns about runtime-equivalent built-in, saved and incoming aliases", () => {
  const { rig, asset } = fixture();
  const first = { ...asset, texts: ["hello---", "phase-two", "shared alias"] };
  const second = { ...asset, id: "custom_second", texts: ["shared-alias"] };
  const material = { ...asset, id: "custom_material", texts: [] };
  const pack = createMotionPack(
    [first, second, material].map((entry) => ({ asset: entry })),
    rig,
  );
  const plan = inspectMotionPack(
    pack,
    {
      custom_saved: {
        asset: { ...asset, id: "custom_saved", texts: ["phase two"] },
      },
    },
    rig,
  );
  assert.deepEqual(plan.items[0].aliasConflicts, [
    "hello---",
    "phase-two",
    "shared alias",
  ]);
  assert.deepEqual(plan.items[1].aliasConflicts, ["shared-alias"]);
  assert.equal(plan.items[2].emptyTexts, true);
  assert.equal(plan.counts.new, 3);
});

test("library backup contains only saved motion data and refuses silent omission of broken entries", async () => {
  const { asset, library, values } = fixture();
  await library.saveDraft(asset);
  await library.setEnabled(asset.id, true, asset);
  values.asrConfig = { apiKey: "secret", transcript: "private" };
  const exported = await library.exportPack();
  assert.equal(exported.motions[0].wasEnabled, true);
  assert.equal(JSON.stringify(exported).includes("secret"), false);
  values[MOTION_STORAGE_PREFIX + "custom_broken"] = { broken: true };
  await assert.rejects(library.exportPack(), /motionPackInvalidStored/);
});

test("one batch write imports drafts; repeated import is a no-op and preserves local approval", async () => {
  const { asset, pack, library, calls, values } = fixture();
  const plan = await library.previewPack(pack);
  assert.equal(calls.length, 0);
  assert.deepEqual(await library.importPack(pack, plan.revision), {
    imported: 1,
    skipped: 0,
  });
  assert.equal(calls.length, 1);
  assert.deepEqual(selectEnabledMotions((await library.list()).entries), []);
  await library.setEnabled(asset.id, true, asset);
  const before = structuredClone(values);
  const repeat = await library.previewPack(pack);
  assert.deepEqual(await library.importPack(pack, repeat.revision), {
    imported: 0,
    skipped: 1,
  });
  assert.deepEqual(values, before);
});

test("one ID conflict blocks every new item, not just the conflicting row", async () => {
  const { asset, rig, library, values } = fixture();
  await library.saveDraft(asset);
  const pack = createMotionPack(
    [
      { asset: { ...asset, id: "custom_new" } },
      { asset: { ...asset, gloss: "different" } },
    ],
    rig,
  );
  const before = structuredClone(values);
  const plan = await library.previewPack(pack);
  await assert.rejects(
    library.importPack(pack, plan.revision),
    /motionPackConflict/,
  );
  assert.deepEqual(values, before);
});

test("storage changes invalidate preflight and concurrent imports cannot overwrite drafts", async () => {
  const { rig, asset, library, pack, storage, locks, values } = fixture();
  const plan = await library.previewPack(pack);
  const other = createMotionLibrary(rig, storage, locks);
  await other.saveDraft({ ...asset, gloss: "new local work" });
  const before = structuredClone(values);
  await assert.rejects(
    library.importPack(pack, plan.revision),
    /motionPackStale/,
  );
  assert.deepEqual(values, before);
  const fresh = fixture();
  const firstPlan = await fresh.library.previewPack(fresh.pack);
  const results = await Promise.allSettled([
    fresh.library.importPack(fresh.pack, firstPlan.revision),
    fresh.library.importPack(fresh.pack, firstPlan.revision),
  ]);
  assert.equal(
    results.filter((result) => result.status === "fulfilled").length,
    1,
  );
  assert.equal(fresh.calls.length, 1);
});

test("quota failure is propagated without approval or per-item writes; retry is possible", async () => {
  const { rig, asset, library, fail, calls, values } = fixture();
  const pack = createMotionPack(
    [{ asset }, { asset: { ...asset, id: "custom_other" } }],
    rig,
  );
  const plan = await library.previewPack(pack);
  fail();
  await assert.rejects(library.importPack(pack, plan.revision), /QUOTA_BYTES/);
  assert.equal(calls.length, 1);
  assert.equal(Object.keys(calls[0]).length, 2);
  assert.deepEqual(values, {});
});

test("batch import fails closed without cross-page locking", async () => {
  const { rig, storage, pack, values } = fixture();
  const library = createMotionLibrary(rig, storage, null);
  const plan = await library.previewPack(pack);
  await assert.rejects(
    library.importPack(pack, plan.revision),
    /motionPackLockUnavailable/,
  );
  assert.deepEqual(values, {});
});

test("preflight version changes for review edits but not unrelated storage settings", async () => {
  const { asset, library, pack, values } = fixture();
  await library.saveDraft(asset);
  const first = await library.previewPack(pack);
  values.config = { language: "en" };
  assert.equal((await library.previewPack(pack)).revision, first.revision);
  await library.setEnabled(asset.id, true, asset);
  assert.notEqual((await library.previewPack(pack)).revision, first.revision);
  const backup = await library.exportPack();
  assert.equal(
    serializeMotionAsset(backup.motions[0].asset),
    serializeMotionAsset(asset),
  );
});

test("motion pack UI messages and placeholders exist in all supported languages", () => {
  const source = LOCALES["zh-CN"];
  for (const key of Object.keys(source).filter((key) =>
    key.startsWith("motionPack"),
  )) {
    for (const locale of Object.values(LOCALES)) {
      assert.equal(typeof locale[key], "string", key);
      assert.deepEqual(
        (locale[key].match(/\{\w+\}/g) || []).sort(),
        (source[key].match(/\{\w+\}/g) || []).sort(),
        key,
      );
    }
  }
});
