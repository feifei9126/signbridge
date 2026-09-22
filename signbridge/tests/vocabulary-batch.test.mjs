import assert from "node:assert/strict";
import test from "node:test";
import {
  VOCABULARY_BATCH_KEY,
  createVocabularyBatchStore,
  evaluateVocabularyBatch,
  validateBatchWords,
} from "../src/avatar/vocabulary-batch.js";
import { serializeMotionAsset } from "../src/avatar/motion-asset.js";
import { LOCALES } from "../src/i18n/locales.js";

test("batch UI strings are available in every supported locale", () => {
  const keys = Object.keys(LOCALES["zh-CN"]).filter((key) =>
    key.startsWith("batch"),
  );
  assert.ok(keys.length > 20);
  for (const locale of Object.values(LOCALES))
    for (const key of keys) assert.equal(typeof locale[key], "string", key);
});

function fixture() {
  const values = { unrelated: { enabled: true } };
  const listeners = new Set();
  let pending = Promise.resolve();
  const storage = {
    local: {
      async get(key) {
        return structuredClone({ [key]: values[key] });
      },
      async set(updates) {
        Object.assign(values, structuredClone(updates));
        listeners.forEach((listener) => listener(updates, "local"));
      },
    },
    onChanged: {
      addListener: (listener) => listeners.add(listener),
      removeListener: (listener) => listeners.delete(listener),
    },
  };
  const locks = {
    request(key, action) {
      assert.equal(key, VOCABULARY_BATCH_KEY);
      const next = pending.then(action);
      pending = next.catch(() => {});
      return next;
    },
  };
  return {
    values,
    storage,
    locks,
    store: createVocabularyBatchStore(storage, locks),
  };
}

test("batch validates limits and deduplicates by the actual translation tokenizer", () => {
  assert.deepEqual(validateBatchWords([" 医院 "]), ["医院"]);
  for (const value of [
    null,
    {},
    [""],
    ["..."],
    ["a".repeat(101)],
    ["Word", "word"],
    Array.from({ length: 9 }, (_, index) => `word${index}`),
  ])
    assert.throws(() => validateBatchWords(value), /batchInvalid/);
});

test("invalid manual words report an input error without creating a list", async () => {
  const { store, values } = fixture();
  assert.throws(() => store.add("..."), /batchInvalidWord/);
  assert.equal(values[VOCABULARY_BATCH_KEY], undefined);
});

test("batch concurrent writes retain both selections and never change motion data", async () => {
  const { store, storage, locks, values } = fixture();
  const other = createVocabularyBatchStore(storage, locks);
  await Promise.all([store.add("医院"), other.add("学校")]);
  await store.add("学校");
  assert.deepEqual(await store.read(), ["医院", "学校"]);
  assert.deepEqual(values.unrelated, { enabled: true });
  assert.deepEqual(
    Object.keys(values).sort(),
    [VOCABULARY_BATCH_KEY, "unrelated"].sort(),
  );
  await store.remove("医院");
  assert.deepEqual(await other.read(), ["学校"]);
  await store.clear();
  assert.deepEqual(await other.read(), []);
});

test("full batch refuses a ninth word without replacing earlier selections", async () => {
  const { store } = fixture();
  for (let index = 0; index < 8; index++) await store.add(`word${index}`);
  const before = await store.read();
  await assert.rejects(store.add("ninth"), /batchFull/);
  assert.deepEqual(await store.read(), before);
});

test("malformed storage is preserved until an explicit clear; unavailable locks stop writes", async () => {
  const { store, values, storage } = fixture();
  values[VOCABULARY_BATCH_KEY] = { version: 999, words: ["keep"] };
  await assert.rejects(store.read(), /batchInvalid/);
  await assert.rejects(store.add("new"), /batchInvalid/);
  assert.equal(values[VOCABULARY_BATCH_KEY].version, 999);
  const unlocked = createVocabularyBatchStore(storage, null);
  assert.throws(() => unlocked.clear(), /batchLockUnavailable/);
  await store.clear();
  assert.deepEqual(await store.read(), []);
});

test("only exact confirmed assets count as runtime matches, edits revoke that status", () => {
  const asset = {
    id: "custom_quasar",
    texts: ["quasar"],
    frames: [{ value: {}, duration: 0.4 }],
  };
  const entry = { asset, enabled: false, review: null };
  assert.equal(evaluateVocabularyBatch(["quasar"], [entry])[0].state, "draft");
  entry.enabled = true;
  entry.review = {
    confirmedAt: "2026-09-22",
    assetJson: serializeMotionAsset(asset),
  };
  assert.equal(
    evaluateVocabularyBatch(["quasar"], [entry])[0].state,
    "matched",
  );
  asset.frames[0].duration = 0.5;
  assert.equal(evaluateVocabularyBatch(["quasar"], [entry])[0].state, "draft");
});

test("builtins are matching data, partial matches and skipped-only words are not completion", () => {
  const results = evaluateVocabularyBatch(
    ["你好", "你好quasar", "的", "quasar"],
    [],
  );
  assert.deepEqual(
    results.map((item) => item.state),
    ["matched", "missing", "missing", "missing"],
  );
  assert.equal(results[0].matches[0].id, "csl_hello");
  assert.deepEqual(results[3].draftIds, []);
});

test("subscriptions only react to batch changes and detach", async () => {
  const { store, storage } = fixture();
  let changes = 0;
  const stop = store.subscribe(() => changes++);
  await storage.local.set({ unrelated: 1 });
  await store.add("quasar");
  assert.equal(changes, 1);
  stop();
  await store.clear();
  assert.equal(changes, 1);
});
