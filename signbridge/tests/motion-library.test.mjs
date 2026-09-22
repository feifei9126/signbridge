import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
import {
  createMotionAsset,
  parseMotionAsset,
  serializeMotionAsset,
} from "../src/avatar/motion-asset.js";
import {
  MOTION_STORAGE_PREFIX,
  createMotionLibrary,
  selectEnabledMotions,
} from "../src/avatar/motion-library.js";
import {
  compileTranslationMatchers,
  translateText,
} from "../src/avatar/sign-language-data.js";

function fixture(locks) {
  const root = new THREE.Object3D();
  const head = new THREE.Bone();
  head.name = "Head_129";
  root.add(head);
  const rig = createHumanoidRig(root);
  const values = {};
  const listeners = new Set();
  const storage = {
    local: {
      async get() {
        return structuredClone(values);
      },
      async set(items) {
        Object.assign(values, JSON.parse(serializeMotionAsset(items)));
        for (const listener of listeners) listener(items, "local");
      },
    },
    onChanged: {
      addListener: (listener) => listeners.add(listener),
      removeListener: (listener) => listeners.delete(listener),
    },
  };
  const library = createMotionLibrary(rig, storage, locks);
  const asset = createMotionAsset(
    rig,
    [{ value: { head: { x: -0.4, y: 0, z: 0 } }, duration: 0.6 }],
    {
      id: "custom_test",
      gloss: "阶段二",
      texts: ["phase two", "实验动作"],
      tags: ["test"],
    },
  );
  return { rig, library, asset, values, storage };
}

test("draft cannot translate; explicit confirmation enables exact saved frames", async () => {
  const { library, asset } = fixture();
  await library.saveDraft(asset);
  assert.deepEqual(selectEnabledMotions((await library.list()).entries), []);
  await library.setEnabled(asset.id, true, asset);
  const enabled = selectEnabledMotions((await library.list()).entries);
  const result = translateText(
    "phase two",
    12,
    compileTranslationMatchers(enabled),
  );
  assert.equal(result.matches[0].id, asset.id);
  assert.deepEqual(result.frames[0], asset.frames[0]);
  await library.setEnabled(asset.id, false);
  assert.deepEqual(selectEnabledMotions((await library.list()).entries), []);
});

test("editing an enabled motion always creates a disabled draft", async () => {
  const { library, asset } = fixture();
  await library.saveDraft(asset);
  await library.setEnabled(asset.id, true, asset);
  asset.frames[0].value.head.x = 0.2;
  await library.saveDraft(asset);
  const { entries } = await library.list();
  assert.equal(entries[0].enabled, false);
  assert.equal(entries[0].review, null);
});

test("imports do not carry approval and changed saved content invalidates approval", async () => {
  const { library, asset, rig, values } = fixture();
  const imported = parseMotionAsset(
    JSON.stringify({
      ...asset,
      enabled: true,
      review: { confirmedAt: "today" },
    }),
    rig,
  );
  assert.equal(imported.enabled, undefined);
  await library.saveDraft(imported);
  await library.setEnabled(asset.id, true, asset);
  values[MOTION_STORAGE_PREFIX + asset.id].asset.frames[0].value.head.x = 0.5;
  assert.deepEqual(selectEnabledMotions((await library.list()).entries), []);
});

test("activation rejects unsaved edits, built-in alias overrides and duplicate custom aliases", async () => {
  const { library, asset } = fixture();
  await library.saveDraft(asset);
  await assert.rejects(
    library.setEnabled(asset.id, true, { ...asset, gloss: "changed" }),
    /motionSaveFirst/,
  );
  await library.setEnabled(asset.id, true, asset);
  const duplicate = { ...asset, id: "custom_other" };
  await library.saveDraft(duplicate);
  await assert.rejects(
    library.setEnabled(duplicate.id, true, duplicate),
    /motionAliasConflict/,
  );
  const builtIn = { ...asset, id: "custom_builtin", texts: ["你好"] };
  await library.saveDraft(builtIn);
  await assert.rejects(
    library.setEnabled(builtIn.id, true, builtIn),
    /motionAliasConflict/,
  );
});

test("malformed, noncanonical and mismatched entries cannot break valid library entries", async () => {
  const { library, asset, values } = fixture();
  await library.saveDraft(asset);
  values[MOTION_STORAGE_PREFIX + "custom_bad"] = { asset: { frames: [] } };
  values[MOTION_STORAGE_PREFIX + "custom_other"] = { asset };
  const result = await library.list();
  assert.equal(result.entries.length, 1);
  assert.equal(result.invalidCount, 2);
  assert.ok(values[MOTION_STORAGE_PREFIX + "custom_bad"]);
});

test("per-entry saves preserve other clips and storage listeners are removable", async () => {
  const { library, asset } = fixture();
  let events = 0;
  const unsubscribe = library.subscribe(() => {
    events += 1;
  });
  await Promise.all([
    library.saveDraft(asset),
    library.saveDraft({ ...asset, id: "custom_other" }),
  ]);
  assert.equal((await library.list()).entries.length, 2);
  assert.equal(events, 2);
  unsubscribe();
  await library.saveDraft(asset);
  assert.equal(events, 2);
});

test("empty alias cannot be enabled and duplicate approvals fail closed at runtime", async () => {
  const { library, asset } = fixture();
  const empty = { ...asset, texts: [] };
  await library.saveDraft(empty);
  await assert.rejects(
    library.setEnabled(empty.id, true, empty),
    /motionAliasConflict/,
  );
  const entries = [asset, { ...asset, id: "custom_duplicate" }].map(
    (motion) => ({
      asset: motion,
      enabled: true,
      review: {
        confirmedAt: "2026-09-20",
        assetJson: serializeMotionAsset(motion),
      },
    }),
  );
  assert.equal(selectEnabledMotions(entries).length, 1);
});

test("alias conflicts use the same token boundaries as translation", async () => {
  const { library, asset } = fixture();
  await library.saveDraft(asset);
  await library.setEnabled(asset.id, true, asset);
  for (const alias of ["phase-two", "thanks---", "---"]) {
    const duplicate = { ...asset, id: "custom_punctuation", texts: [alias] };
    await library.saveDraft(duplicate);
    await assert.rejects(
      library.setEnabled(duplicate.id, true, duplicate),
      /motionAliasConflict/,
    );
  }
});

test("cross-page confirmation cannot overwrite a concurrent draft save", async () => {
  let pending = Promise.resolve();
  const locks = {
    request: (_name, operation) => {
      const task = pending.then(operation);
      pending = task.catch(() => {});
      return task;
    },
  };
  const { library, rig, storage, asset } = fixture(locks);
  const otherPage = createMotionLibrary(rig, storage, locks);
  await library.saveDraft(asset);
  const changed = { ...asset, gloss: "修改后的动作" };
  await Promise.all([
    library.setEnabled(asset.id, true, asset),
    otherPage.saveDraft(changed),
  ]);
  const { entries } = await library.list();
  assert.equal(entries[0].asset.gloss, changed.gloss);
  assert.equal(entries[0].enabled, false);
});
