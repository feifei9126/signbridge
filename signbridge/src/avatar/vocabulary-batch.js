import { selectEnabledMotions } from "./motion-library.js";
import {
  compileTranslationMatchers,
  translateText,
  translationAliasKey,
} from "./sign-language-data.js";

const VOCABULARY_BATCH_KEY = "signbridge.vocabulary-batch.v1";
const MAX_VOCABULARY_BATCH = 8;

function validateBatchWords(words) {
  if (!Array.isArray(words) || words.length > MAX_VOCABULARY_BATCH)
    throw new Error("batchInvalid");
  const keys = new Set();
  return words.map((word) => {
    if (typeof word !== "string" || !word.trim() || word.length > 100)
      throw new Error("batchInvalid");
    const key = translationAliasKey(word);
    if (!key || keys.has(key)) throw new Error("batchInvalid");
    keys.add(key);
    return word.trim();
  });
}

function evaluateVocabularyBatch(words, entries) {
  const motions = selectEnabledMotions(entries);
  const matchers = compileTranslationMatchers(motions);
  return validateBatchWords(words).map((word) => {
    const result = translateText(word, 12, matchers);
    const matched =
      result?.matches.length > 0 &&
      !result.unmatched.length &&
      !result.skipped.length &&
      !result.truncated;
    const drafts = entries
      .filter((entry) =>
        entry.asset.texts.some(
          (alias) => translationAliasKey(alias) === translationAliasKey(word),
        ),
      )
      .map((entry) => entry.asset.id);
    return {
      word,
      state: matched ? "matched" : drafts.length ? "draft" : "missing",
      matches: result?.matches.map(({ id, text }) => ({ id, text })) || [],
      draftIds: matched ? [] : drafts,
    };
  });
}

function createVocabularyBatchStore(
  storage = globalThis.chrome?.storage,
  locks = globalThis.navigator?.locks,
) {
  async function read() {
    const value = (await storage.local.get(VOCABULARY_BATCH_KEY))[
      VOCABULARY_BATCH_KEY
    ];
    if (value === undefined) return [];
    if (value?.version !== 1) throw new Error("batchInvalid");
    return validateBatchWords(value.words);
  }
  function update(operation) {
    if (!locks?.request) throw new Error("batchLockUnavailable");
    return locks.request(VOCABULARY_BATCH_KEY, async () => {
      const words = validateBatchWords(await operation());
      await storage.local.set({
        [VOCABULARY_BATCH_KEY]: { version: 1, words },
      });
      return words;
    });
  }
  return {
    read,
    add(word) {
      let candidate;
      try {
        [candidate] = validateBatchWords([word]);
      } catch {
        throw new Error("batchInvalidWord");
      }
      return update(async () => {
        const words = await read();
        if (
          words.some(
            (item) =>
              translationAliasKey(item) === translationAliasKey(candidate),
          )
        )
          return words;
        if (words.length >= MAX_VOCABULARY_BATCH) throw new Error("batchFull");
        return [...words, candidate];
      });
    },
    remove(word) {
      return update(async () => (await read()).filter((item) => item !== word));
    },
    clear: () => update(() => []),
    subscribe(listener) {
      const handle = (changes, area) => {
        if (area === "local" && Object.hasOwn(changes, VOCABULARY_BATCH_KEY))
          listener();
      };
      storage.onChanged.addListener(handle);
      return () => storage.onChanged.removeListener(handle);
    },
  };
}

export {
  VOCABULARY_BATCH_KEY,
  MAX_VOCABULARY_BATCH,
  validateBatchWords,
  evaluateVocabularyBatch,
  createVocabularyBatchStore,
};
