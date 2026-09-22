import {
  MAX_VOCABULARY_BATCH,
  createVocabularyBatchStore,
  evaluateVocabularyBatch,
} from "../avatar/vocabulary-batch.js";
import { MOTION_STORAGE_PREFIX } from "../avatar/motion-library.js";
import { t } from "../i18n/locales.js";

function createVocabularyBatchUI({ getLibrary, authorButton }) {
  const store = createVocabularyBatchStore();
  const byId = (id) => document.getElementById(id);
  const status = byId("batch-status");
  const rows = byId("batch-rows");
  const exportButton = byId("batch-export");
  let revision = 0;
  let disposed = false;
  let snapshot = null;
  const downloads = new Map();
  function append(parent, tag, text) {
    const node = document.createElement(tag);
    node.textContent = text;
    parent.appendChild(node);
    return node;
  }
  function button(parent, key, action) {
    const node = append(parent, "button", t(key));
    node.type = "button";
    node.addEventListener("click", () => run(action));
    return node;
  }
  function fail(error) {
    status.textContent = t("batchFailure", { detail: t(error.message) });
  }
  async function run(action) {
    try {
      await action();
      if (!disposed) await refresh();
      return true;
    } catch (error) {
      if (!disposed) fail(error);
      return false;
    }
  }
  async function refresh() {
    const version = ++revision;
    snapshot = null;
    exportButton.disabled = true;
    rows.replaceChildren();
    status.textContent = t("batchLoading");
    try {
      const words = await store.read();
      if (disposed || version !== revision) return;
      for (const word of words) {
        const row = append(rows, "tr", "");
        row.dataset.word = word;
        append(row, "th", word).scope = "row";
        append(row, "td", t("batchLoading")).className = "batch-state";
        const actions = append(row, "td", "");
        authorButton(actions, word, "pose-editor", "poseEditor");
        authorButton(actions, word, "record-mode", "recorder");
        button(actions, "batchRemove", () => store.remove(word));
      }
      if (!words.length) {
        status.textContent = t("batchEmpty");
        return;
      }
      const library = await getLibrary();
      if (disposed || version !== revision) return;
      const { entries, invalidCount } = await library.list();
      if (disposed || version !== revision) return;
      const items = evaluateVocabularyBatch(words, entries);
      items.forEach((item, index) => {
        const cell = rows.children[index].querySelector(".batch-state");
        cell.textContent = t(
          {
            matched: "batchMatched",
            draft: "batchDraft",
            missing: "batchMissing",
          }[item.state],
        );
        append(
          cell,
          "div",
          [
            ...new Set(item.matches.map((match) => match.id)),
            ...item.draftIds,
          ].join(", "),
        ).className = "muted";
      });
      snapshot = {
        format: "signbridge-vocabulary-batch",
        version: 1,
        generatedAt: new Date().toISOString(),
        extensionVersion: chrome.runtime.getManifest().version,
        includesSourceText: false,
        linguisticReview: "not-assessed",
        invalidLibraryEntries: invalidCount,
        items,
      };
      exportButton.disabled = false;
      status.textContent = t("batchSummary", {
        count: words.length,
        max: MAX_VOCABULARY_BATCH,
        matched: items.filter((item) => item.state === "matched").length,
        invalid: invalidCount,
      });
    } catch (error) {
      if (!disposed && version === revision) {
        rows.querySelectorAll(".batch-state").forEach((cell) => {
          cell.textContent = t("batchUnverified");
        });
        fail(error);
      }
    }
  }
  byId("batch-refresh").addEventListener("click", refresh);
  byId("batch-add-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const field = byId("batch-word");
    const word = field.value;
    const added = await run(() => store.add(word));
    if (added && !disposed && field.value === word) field.value = "";
  });
  byId("batch-clear").addEventListener("click", () => {
    if (window.confirm(t("batchClearConfirm"))) run(() => store.clear());
  });
  byId("batch-review").addEventListener("click", async () => {
    try {
      await chrome.tabs.create({
        url: chrome.runtime.getURL("tools/motion-review.html"),
      });
    } catch {
      fail(new Error("coverageOpenFailed"));
    }
  });
  exportButton.addEventListener("click", async () => {
    await refresh();
    if (disposed || !snapshot) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(snapshot, null, 2)], {
        type: "application/json",
      }),
    );
    const link = append(document.body, "a", "");
    link.href = url;
    link.download = "signbridge-vocabulary-batch.json";
    link.click();
    link.remove();
    downloads.set(
      url,
      setTimeout(() => {
        URL.revokeObjectURL(url);
        downloads.delete(url);
      }, 1000),
    );
  });
  const unsubscribe = store.subscribe(refresh);
  const changed = (changes, area) => {
    if (
      area === "local" &&
      Object.keys(changes).some((key) => key.startsWith(MOTION_STORAGE_PREFIX))
    )
      refresh();
  };
  chrome.storage.onChanged.addListener(changed);
  window.addEventListener(
    "pagehide",
    () => {
      disposed = true;
      revision += 1;
      unsubscribe();
      chrome.storage.onChanged.removeListener(changed);
      for (const [url, timer] of downloads) {
        clearTimeout(timer);
        URL.revokeObjectURL(url);
      }
      downloads.clear();
    },
    { once: true },
  );
  refresh();
  return { add: (word) => run(() => store.add(word)) };
}

export { createVocabularyBatchUI };
