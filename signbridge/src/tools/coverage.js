import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { disposeModel } from "../avatar/dispose-model.js";
import {
  createMotionLibrary,
  selectEnabledMotions,
} from "../avatar/motion-library.js";
import { SIGNS, GESTURES, CHARS } from "../avatar/sign-language-data.js";
import {
  MAX_COVERAGE_BYTES,
  MAX_COVERAGE_CHARS,
  parseCoverageInput,
  analyzeCoverage,
  coverageReportForExport,
} from "../avatar/coverage-analysis.js";
import { getConfig } from "../utils/config.js";
import { setLocale, getLocale, t } from "../i18n/locales.js";
import { createVocabularyBatchUI } from "./vocabulary-batch-ui.js";

const byId = (id) => document.getElementById(id);
const input = byId("coverage-text");
const format = byId("coverage-format");
const status = byId("coverage-status");
const analyzeButton = byId("coverage-analyze");
const exportButton = byId("coverage-export");
let revision = 0;
let importRevision = 0;
let disposed = false;
let libraryPromise = null;
let unsubscribe = null;
let report = null;
let batch = null;
const downloads = new Map();

function invalidate(key = "coverageChanged") {
  revision += 1;
  report = null;
  exportButton.disabled = true;
  analyzeButton.disabled = false;
  byId("coverage-results").hidden = true;
  byId("coverage-catalog").textContent = "";
  status.textContent = t(key);
}

function showError(error) {
  status.textContent = t("coverageFailure", {
    detail: t(error.message, { detail: error.detail || "" }),
  });
}

function getLibrary() {
  if (!libraryPromise) {
    libraryPromise = (async () => {
      const gltf = await new GLTFLoader().loadAsync(
        chrome.runtime.getURL("avatar/model.glb"),
      );
      try {
        if (disposed) return null;
        const rig = createHumanoidRig(gltf.scene);
        if (!rig.isSigningReady) throw new Error("coverageModelError");
        const library = createMotionLibrary(rig);
        unsubscribe = library.subscribe(() =>
          invalidate("coverageCatalogChanged"),
        );
        return library;
      } finally {
        disposeModel(gltf.scene);
      }
    })().catch(() => {
      libraryPromise = null;
      throw new Error("coverageModelError");
    });
  }
  return libraryPromise;
}

function append(parent, tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function authorButton(parent, word, tool, key) {
  const button = append(parent, "button", t(key));
  button.type = "button";
  button.disabled = word.length > 100;
  button.addEventListener("click", async () => {
    try {
      const url = new URL(chrome.runtime.getURL(`avatar/${tool}.html`));
      url.hash = new globalThis.URLSearchParams({
        "motion-text": word,
      }).toString();
      await chrome.tabs.create({ url: url.href });
    } catch {
      showError(new Error("coverageOpenFailed"));
    }
  });
}

function renderReport(result) {
  const summary = result.summary;
  byId("coverage-results").hidden = false;
  byId("coverage-summary").textContent = t("coverageSummary", {
    ratio:
      summary.coverage === null
        ? t("coverageNoTokens")
        : `${(summary.coverage * 100).toFixed(1)}%`,
    segments: summary.segments,
    matched: summary.matchedTokens,
    unknown: summary.unknownTokens,
    skipped: summary.skippedTokens,
  });
  byId("coverage-truncation").textContent = t("coverageTruncation", {
    count: summary.runtimeTruncatedSegments,
  });
  const unknownBody = byId("coverage-unknown");
  unknownBody.replaceChildren();
  for (const item of result.unknown.slice(0, 100)) {
    const row = document.createElement("tr");
    unknownBody.appendChild(row);
    append(row, "th", item.word).scope = "row";
    append(
      row,
      "td",
      t("coverageOccurrences", {
        count: item.count,
        segments: item.segmentCount,
      }),
    );
    append(row, "td", item.examples.join(", "));
    const actions = append(row, "td", "");
    authorButton(actions, item.word, "pose-editor", "poseEditor");
    authorButton(actions, item.word, "record-mode", "recorder");
    const addButton = append(actions, "button", t("batchAdd"));
    addButton.type = "button";
    addButton.disabled = item.word.length > 100;
    addButton.addEventListener("click", () => batch.add(item.word));
  }
  byId("coverage-unknown-note").textContent = result.unknown.length
    ? t("coverageUniqueUnknown", { count: result.unknown.length })
    : t("coverageNoUnknown");
  const details = byId("coverage-details");
  details.replaceChildren();
  for (const item of result.details.slice(0, 200)) {
    const node = document.createElement("details");
    details.appendChild(node);
    append(
      node,
      "summary",
      `${item.segment}. ${item.text.slice(0, 140)}${item.text.length > 140 ? "…" : ""}`,
    );
    append(node, "p", item.text);
    append(
      node,
      "p",
      t("coverageMatches", {
        value:
          item.matches
            .map((match) => `${match.text} [${match.id}]`)
            .join(", ") || "—",
      }),
    );
    append(
      node,
      "p",
      t("coverageUnmatched", { value: item.unmatched.join(", ") || "—" }),
    );
    append(
      node,
      "p",
      t("coverageSkipped", { value: item.skipped.join(", ") || "—" }),
    );
    if (item.truncated)
      append(node, "p", t("coverageRemaining", { value: item.remainingText }));
  }
  exportButton.disabled = false;
}

async function analyze() {
  invalidate("coverageLoading");
  const version = revision;
  analyzeButton.disabled = true;
  try {
    const segments = parseCoverageInput(input.value, format.value);
    const library = await getLibrary();
    if (disposed || version !== revision) return;
    const { entries, invalidCount } = await library.list();
    if (disposed || version !== revision) return;
    const motions = selectEnabledMotions(entries);
    report = analyzeCoverage(segments, motions);
    renderReport(report);
    byId("coverage-catalog").textContent = t("coverageCatalog", {
      signs: Object.keys(SIGNS).length,
      aliases: Object.keys(GESTURES).length,
      chars: Object.keys(CHARS).length,
      enabled: motions.length,
      drafts: entries.length - motions.length,
      invalid: invalidCount,
    });
    status.textContent = t("coverageDone");
  } catch (error) {
    if (!disposed && version === revision) showError(error);
  } finally {
    if (!disposed && version === revision) analyzeButton.disabled = false;
  }
}

async function init() {
  const config = await getConfig();
  if (disposed) return;
  setLocale(config.uiLocale === "auto" ? null : config.uiLocale);
  document.documentElement.lang = getLocale();
  document.title = `${t("coverageTitle")} · SignBridge`;
  for (const element of document.querySelectorAll("[data-i18n]"))
    element.textContent = t(element.dataset.i18n);
  status.textContent = t("coverageReady");
  batch = createVocabularyBatchUI({ getLibrary, authorButton });
  analyzeButton.addEventListener("click", analyze);
  for (const element of [input, format])
    element.addEventListener("input", () => {
      importRevision += 1;
      invalidate();
    });
  byId("coverage-clear").addEventListener("click", () => {
    importRevision += 1;
    input.value = "";
    byId("coverage-file").value = "";
    byId("coverage-include-text").checked = false;
    invalidate("coverageReady");
  });
  byId("coverage-file").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const version = ++importRevision;
    invalidate();
    try {
      if (file.size > MAX_COVERAGE_BYTES) throw new Error("coverageTooLarge");
      const extension = file.name.split(".").pop().toLowerCase();
      if (!["txt", "srt", "vtt"].includes(extension))
        throw new Error("coverageInvalidFormat");
      const bytes = await file.arrayBuffer();
      if (disposed || version !== importRevision) return;
      let text;
      try {
        text = new globalThis.TextDecoder("utf-8", { fatal: true }).decode(
          bytes,
        );
      } catch {
        throw new Error("coverageEncoding");
      }
      if (text.length > MAX_COVERAGE_CHARS) throw new Error("coverageTooLarge");
      invalidate();
      input.value = text;
      format.value = extension === "txt" ? "text" : extension;
      status.textContent = t("coverageImported");
    } catch (error) {
      if (!disposed && version === importRevision) showError(error);
    } finally {
      if (version === importRevision) event.target.value = "";
    }
  });
  exportButton.addEventListener("click", () => {
    if (!report) return;
    const value = coverageReportForExport(
      report,
      byId("coverage-include-text").checked,
    );
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "signbridge-coverage.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    const timer = setTimeout(() => {
      URL.revokeObjectURL(url);
      downloads.delete(url);
    }, 1000);
    downloads.set(url, timer);
  });
}

window.addEventListener("pagehide", () => {
  disposed = true;
  revision += 1;
  importRevision += 1;
  unsubscribe?.();
  libraryPromise = null;
  for (const [url, timer] of downloads) {
    clearTimeout(timer);
    URL.revokeObjectURL(url);
  }
  downloads.clear();
});
init().catch(showError);
