import { SIGNS } from "../avatar/sign-language-data.js";
import { createMotionLibrary } from "../avatar/motion-library.js";
import {
  REVIEW_PROTOCOL,
  MAX_REVIEW_BATCH,
  REVIEW_VIEWS,
  prepareReviewMotion,
  sampleFrameIndices,
  reviewHash,
  comparePixels,
  baselineCompatibility,
} from "../avatar/motion-review.js";
import { openReviewStore } from "../avatar/review-store.js";
import { createReviewStage, captureReviewSheet } from "./review-stage.js";
import { getConfig } from "../utils/config.js";
import { setLocale, getLocale, t } from "../i18n/locales.js";

const byId = (id) => document.getElementById(id);
const status = byId("review-status");
const urls = new Set();
const downloadTimers = new Set();
let stage = null;
let library = null;
let storePromise = null;
let unsubscribe = null;
let loading = null;
let running = null;
let revision = 0;
let disposed = false;
let entries = [];
let results = [];
let invalidCount = 0;

function message(key, replacements) {
  status.textContent = t(key, replacements);
}
function explain(error) {
  return t(error.message, { detail: error.detail || "" });
}
function showError(error) {
  message("reviewFailure", { detail: explain(error) });
}
function append(parent, tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  parent.appendChild(node);
  return node;
}
function blobUrl(blob) {
  const url = URL.createObjectURL(blob);
  urls.add(url);
  return url;
}
function releaseUrls() {
  urls.forEach((url) => URL.revokeObjectURL(url));
  urls.clear();
}
function clearResults() {
  releaseUrls();
  results = [];
  byId("review-cards").replaceChildren();
  byId("review-results").hidden = true;
  byId("review-export").disabled = true;
}
function selectedEntries() {
  const keys = new Set(
    Array.from(
      byId("review-catalog").querySelectorAll("input:checked"),
      (input) => input.value,
    ),
  );
  return entries.filter((entry) =>
    keys.has(`${entry.source}:${entry.motion.id}`),
  );
}
function syncControls() {
  const count = selectedEntries().length;
  byId("review-count").textContent = t("reviewCatalogCount", {
    total: entries.length,
    count,
    invalid: invalidCount,
    max: MAX_REVIEW_BATCH,
  });
  const available =
    stage && !running && !loading && count > 0 && count <= MAX_REVIEW_BATCH;
  byId("review-play").disabled = !available;
  byId("review-capture").disabled = !available;
  byId("review-stop").disabled = !running && !loading;
  byId("review-load").disabled = !!loading || !!running;
  byId("review-view").disabled = !!running;
  byId("review-catalog")
    .querySelectorAll("input")
    .forEach((input) => {
      input.disabled = !!running;
    });
  byId("review-cards")
    .querySelectorAll("button")
    .forEach((button) => {
      button.disabled = !!running;
    });
}
function cancel() {
  loading?.abort();
  running?.abort();
  stage?.stop();
}
function invalidate() {
  revision += 1;
  cancel();
  clearResults();
}
async function getStore() {
  if (!storePromise) {
    storePromise = openReviewStore()
      .then((store) => {
        if (disposed) {
          store.close();
          throw new Error("reviewStorageError");
        }
        return store;
      })
      .catch((error) => {
        storePromise = null;
        throw error;
      });
  }
  return storePromise;
}
function sourceLabel(entry) {
  return t(
    entry.source === "builtin"
      ? "reviewBuiltin"
      : entry.enabled
        ? "reviewEnabled"
        : "reviewDraft",
  );
}
function filterCatalog() {
  const query = byId("review-search").value.trim().toLocaleLowerCase();
  byId("review-catalog")
    .querySelectorAll("label")
    .forEach((label) => {
      label.hidden = !label.textContent.toLocaleLowerCase().includes(query);
    });
}
async function refreshCatalog() {
  const ticket = revision;
  const selected = new Set(
    selectedEntries().map((entry) => `${entry.source}:${entry.motion.id}`),
  );
  const catalog = await library.list();
  if (disposed || ticket !== revision) return;
  invalidCount = catalog.invalidCount;
  entries = [
    ...Object.values(SIGNS).map((motion) => ({ source: "builtin", motion })),
    ...catalog.entries.map((entry) => ({
      source: "custom",
      motion: entry.asset,
      enabled: entry.enabled,
    })),
  ];
  const container = byId("review-catalog");
  container.replaceChildren();
  for (const entry of entries) {
    const label = append(container, "label");
    const checkbox = append(label, "input");
    checkbox.type = "checkbox";
    checkbox.value = `${entry.source}:${entry.motion.id}`;
    checkbox.checked = selected.has(checkbox.value);
    append(
      label,
      "span",
      `${entry.motion.gloss} · ${entry.motion.id} · ${sourceLabel(entry)}`,
    );
    checkbox.addEventListener("change", syncControls);
  }
  filterCatalog();
  syncControls();
}

async function initialize() {
  if (loading || running) return;
  invalidate();
  unsubscribe?.();
  unsubscribe = null;
  stage?.dispose();
  stage = null;
  library = null;
  const operation = new globalThis.AbortController();
  loading = operation;
  const timeout = setTimeout(
    () => operation.abort(new Error("reviewModelError")),
    20000,
  );
  message("reviewLoading");
  syncControls();
  try {
    stage = await createReviewStage(byId("review-canvas"), operation.signal);
    library = createMotionLibrary(stage.rig);
    unsubscribe = library.subscribe(() => {
      invalidate();
      message("reviewCatalogChanged");
      refreshCatalog().catch(showError);
    });
    await refreshCatalog();
    operation.signal.throwIfAborted();
    message("reviewReady", { total: entries.length });
  } catch (error) {
    unsubscribe?.();
    unsubscribe = null;
    stage?.dispose();
    stage = null;
    library = null;
    if (!disposed) {
      if (error.name === "AbortError") message("reviewCancelled");
      else showError(error);
    }
  } finally {
    clearTimeout(timeout);
    loading = null;
    if (!disposed) syncControls();
  }
}

async function imagePixels(blob, width, height) {
  const bitmap = await globalThis.createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  try {
    if (bitmap.width !== width || bitmap.height !== height)
      throw new Error("reviewImageMismatch");
    canvas.width = width;
    canvas.height = height;
    const drawing = canvas.getContext("2d", { willReadFrequently: true });
    drawing.drawImage(bitmap, 0, 0);
    return drawing.getImageData(0, 0, width, height).data;
  } finally {
    bitmap.close();
    canvas.width = canvas.height = 0;
  }
}

async function loadComparison(result) {
  result.baselineError = null;
  result.difference = null;
  try {
    result.baseline = await (await getStore()).read(result.key);
    result.comparison = baselineCompatibility(result, result.baseline);
    if (result.comparison === "comparable") {
      if (
        (await reviewHash(await result.baseline.image.arrayBuffer())) !==
        result.baseline.imageHash
      )
        throw new Error("reviewImageMismatch");
      result.difference = comparePixels(
        await imagePixels(result.image, result.width, result.height),
        await imagePixels(result.baseline.image, result.width, result.height),
      );
    }
  } catch (error) {
    result.comparison = "unavailable";
    result.baselineError = explain(error);
  }
}

function download(blob, filename) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  link.click();
  const timer = setTimeout(() => {
    URL.revokeObjectURL(url);
    downloadTimers.delete(timer);
  }, 10000);
  downloadTimers.add(timer);
  urls.add(url);
}
async function assertFresh(result) {
  if (!results.includes(result)) throw new Error("reviewCatalogChanged");
  if (result.source === "custom") {
    const catalog = await library.list();
    const current = catalog.entries.find(
      (entry) => entry.asset.id === result.id,
    );
    if (!current || (await reviewHash(current.asset)) !== result.motionHash)
      throw new Error("reviewCatalogChanged");
  }
}
async function baselineAction(result, remove = false) {
  if (running) return;
  const operation = new globalThis.AbortController();
  running = operation;
  syncControls();
  try {
    await assertFresh(result);
    if (
      !confirm(
        t(remove ? "reviewDeleteConfirm" : "reviewSaveConfirm", {
          name: result.gloss,
        }),
      )
    )
      return;
    operation.signal.throwIfAborted();
    const store = await getStore();
    await assertFresh(result);
    operation.signal.throwIfAborted();
    const record = remove
      ? null
      : {
          key: result.key,
          token: globalThis.crypto.randomUUID(),
          protocol: REVIEW_PROTOCOL,
          savedAt: new Date().toISOString(),
          motionHash: result.motionHash,
          environmentHash: result.environmentHash,
          image: result.image,
          imageHash: result.imageHash,
          width: result.width,
          height: result.height,
          indices: result.indices,
        };
    await store.update(
      result.key,
      result.baseline?.token || null,
      record,
      operation.signal,
    );
    await loadComparison(result);
    operation.signal.throwIfAborted();
    renderResults();
    message(remove ? "reviewDeleted" : "reviewSaved");
  } catch (error) {
    if (!disposed && error.name !== "AbortError") showError(error);
  } finally {
    if (running === operation) running = null;
    if (!disposed) syncControls();
  }
}

function renderResults() {
  releaseUrls();
  const container = byId("review-cards");
  container.replaceChildren();
  byId("review-results").hidden = !results.length;
  byId("review-export").disabled = !results.length;
  for (const result of results) {
    const card = append(container, "article");
    card.className = "review-card";
    card.dataset.key = result.key;
    append(card, "h3", `${result.gloss} · ${result.id}`);
    if (result.error) {
      append(card, "p", t("reviewFailure", { detail: result.error }));
      continue;
    }
    const diagnostic = append(
      card,
      "p",
      t("reviewDiagnostics", {
        frames: result.frameCount,
        duration: result.duration.toFixed(2),
        bones: result.usedBones.length,
        indices: result.indices.map((index) => index + 1).join(", "),
        omitted: result.frameCount - result.indices.length,
      }),
    );
    diagnostic.className = "diagnostic";
    const comparisonKey = {
      missing: "reviewNoBaseline",
      incompatible: "reviewIncompatible",
      motionChanged: "reviewMotionChanged",
      comparable: "reviewCompared",
      unavailable: "reviewUnavailable",
    }[result.comparison];
    append(
      card,
      "p",
      t(comparisonKey, {
        ratio: ((result.difference?.changedRatio || 0) * 100).toFixed(3),
        mean: (result.difference?.meanDifference || 0).toFixed(3),
        detail: result.baselineError || "",
        date: result.baseline?.savedAt || "",
      }),
    );
    append(card, "p", t("reviewSheetOrder"));
    const comparison = append(card, "div");
    comparison.className = "comparison";
    for (const [blob, title] of [
      [result.image, t("reviewCurrent")],
      [result.baseline?.image, t("reviewBaseline")],
    ]) {
      if (!(blob instanceof Blob)) continue;
      const figure = append(comparison, "figure");
      append(figure, "figcaption", title);
      const image = append(figure, "img");
      image.src = blobUrl(blob);
      image.alt = `${result.gloss} · ${title} · ${t("reviewSheetOrder")}`;
    }
    const actions = append(card, "div");
    actions.className = "actions";
    const save = append(actions, "button", t("reviewSaveBaseline"));
    save.dataset.action = "save";
    save.addEventListener("click", () => baselineAction(result));
    const png = append(actions, "button", t("reviewDownloadImage"));
    png.dataset.action = "download";
    png.addEventListener("click", () =>
      download(result.image, `${result.id}.review.png`),
    );
    if (result.baseline) {
      const remove = append(actions, "button", t("reviewDeleteBaseline"));
      remove.dataset.action = "delete";
      remove.addEventListener("click", () => baselineAction(result, true));
    }
  }
  syncControls();
}

async function run(capture) {
  if (running || !stage) return;
  const selected = selectedEntries();
  if (!selected.length || selected.length > MAX_REVIEW_BATCH) return;
  const operation = new globalThis.AbortController();
  const ticket = revision;
  running = operation;
  if (capture) clearResults();
  syncControls();
  let failures = 0;
  try {
    for (const [index, entry] of selected.entries()) {
      operation.signal.throwIfAborted();
      message(capture ? "reviewCapturing" : "reviewPlaying", {
        name: entry.motion.gloss,
        index: index + 1,
        total: selected.length,
      });
      let motion;
      try {
        motion = prepareReviewMotion(entry, stage.rig);
      } catch (error) {
        failures += 1;
        if (capture)
          results.push({
            key: `${entry.source}:${entry.motion.id}`,
            id: entry.motion.id,
            gloss: entry.motion.gloss,
            error: explain(error),
          });
        continue;
      }
      if (!capture) {
        await stage.play(motion.asset.frames, operation.signal);
        continue;
      }
      const indices = sampleFrameIndices(motion.asset.frames.length);
      const sheet = await captureReviewSheet(
        stage,
        motion.asset.frames,
        indices,
        operation.signal,
      );
      const result = {
        ...sheet,
        protocol: REVIEW_PROTOCOL,
        key: motion.key,
        id: motion.id,
        source: motion.source,
        gloss: motion.asset.gloss,
        enabled: motion.enabled,
        frameCount: motion.asset.frames.length,
        duration: motion.totalDuration,
        usedBones: motion.usedBones,
        indices,
        motionHash: await reviewHash(motion.asset),
        imageHash: await reviewHash(await sheet.image.arrayBuffer()),
        environmentHash: stage.environmentHash,
        capturedAt: new Date().toISOString(),
      };
      await loadComparison(result);
      operation.signal.throwIfAborted();
      results.push(result);
    }
    if (capture) renderResults();
    message("reviewFinished", { count: selected.length - failures, failures });
  } catch (error) {
    if (error.name === "AbortError") {
      if (ticket === revision && !disposed) message("reviewCancelled");
    } else if (!disposed) showError(error);
    if (capture) clearResults();
  } finally {
    if (running === operation) running = null;
    if (!disposed) {
      stage?.stop();
      if (capture) byId("review-view").value = "front";
      try {
        stage?.render(byId("review-view").value);
      } catch (error) {
        showError(error);
      }
      syncControls();
    }
  }
}

function exportReport() {
  const report = {
    type: REVIEW_PROTOCOL,
    createdAt: new Date().toISOString(),
    scope:
      "SIGNS and saved compatible custom motions; not CHARS or sentence interpolation",
    linguisticApproval: false,
    pixelChannelTolerance: 16,
    environment: stage.environment,
    invalidLibraryEntries: invalidCount,
    views: REVIEW_VIEWS,
    motions: results.map(({ image: _image, baseline, ...result }) => ({
      ...result,
      baseline: baseline
        ? {
            savedAt: baseline.savedAt,
            motionHash: baseline.motionHash,
            environmentHash: baseline.environmentHash,
          }
        : null,
    })),
  };
  download(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
    "signbridge-visual-review.json",
  );
}

byId("review-load").addEventListener("click", initialize);
byId("review-search").addEventListener("input", filterCatalog);
byId("review-play").addEventListener("click", () => run(false));
byId("review-capture").addEventListener("click", () => run(true));
byId("review-stop").addEventListener("click", cancel);
byId("review-export").addEventListener("click", exportReport);
byId("review-view").addEventListener("change", () => {
  try {
    stage?.render(byId("review-view").value);
  } catch (error) {
    showError(error);
  }
});
byId("review-canvas").addEventListener("webglcontextlost", (event) => {
  event.preventDefault();
  invalidate();
  if (!disposed) message("reviewRenderError");
});
window.addEventListener("pagehide", () => {
  disposed = true;
  loading?.abort();
  cancel();
  unsubscribe?.();
  stage?.dispose();
  storePromise?.then((store) => store.close()).catch(() => {});
  releaseUrls();
  downloadTimers.forEach(clearTimeout);
});

getConfig()
  .then((config) => {
    setLocale(
      config.uiLocale === "auto" ? navigator.language : config.uiLocale,
    );
    document.documentElement.lang = getLocale();
    document.title = `SignBridge · ${t("reviewTitle")}`;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
      element.setAttribute("aria-label", t(element.dataset.i18nAria));
    });
    return initialize();
  })
  .catch(showError);
