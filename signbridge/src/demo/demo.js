import { t, setLocale } from "../i18n/locales.js";
import { SIGNS } from "../avatar/sign-language-data.js";
import {
  planDemoText,
  validateT08Bundle,
  validateT08CandidateBundle,
} from "./demo-motion.js";
const locale = new URL(location.href).searchParams.get("lang") || "zh-CN";
setLocale(locale);
document.documentElement.lang = locale;
for (const el of document.querySelectorAll("[data-i18n]"))
  el.textContent = t(el.dataset.i18n);
for (const el of document.querySelectorAll("[data-i18n-placeholder]"))
  el.placeholder = t(el.dataset.i18nPlaceholder);
for (const el of document.querySelectorAll("[data-i18n-aria]"))
  el.setAttribute("aria-label", t(el.dataset.i18nAria));
const frame = document.querySelector("#avatar"),
  input = document.querySelector("#input");
frame.title = t("demoStage");
const status = document.querySelector("#status"),
  playButton = document.querySelector("#play"),
  pauseButton = document.querySelector("#pause"),
  stopButton = document.querySelector("#stop");
let clips = [],
  candidates = [],
  model = null,
  candidateModel = null,
  mode = "auto",
  ready = false,
  modelAvailable = false,
  currentPlan = { items: [], unmatched: "" },
  current = null,
  running = false,
  requestId = 0;
const setStatus = (key, args = {}) => {
  status.textContent = t(key, args);
};
const send = (type, data = {}) => {
  if (type === "PLAY" || type === "STOP") requestId++;
  frame.contentWindow.postMessage(
    { source: "signbridge-demo", type, requestId, ...data },
    location.origin,
  );
};
function element(tag, text) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  return n;
}
function refreshPlan() {
  currentPlan = planDemoText(input.value, mode, modelAvailable ? clips : []);
  document.querySelector("#chars").textContent =
    `${[...input.value].length} / 500`;
  document.querySelector("#match-count").textContent = t("demoCount", {
    count: currentPlan.items.length,
  });
  const matches = document.querySelector("#matches");
  matches.replaceChildren();
  for (const item of currentPlan.items) {
    const span = element("span", item.matchedText);
    span.className = item.source;
    const candidate = clips.find((clip) => clip.id === item.id);
    span.title =
      item.source === "candidate"
        ? t("demoCandidateDetail", {
            mse: candidate?.normalized_reconstruction_mse?.toFixed(3) || "?",
          })
        : t(item.source === "t08" ? "demoSourceT08" : "demoSourceDictionary");
    matches.append(span);
  }
  document
    .querySelector("#unknown")
    .classList.toggle("supported", !currentPlan.unmatched);
  document.querySelector("#unknown").textContent = currentPlan.unmatched
    ? t("demoUnknown", { text: currentPlan.unmatched })
    : input.value.trim()
      ? t("demoAllMatched")
      : "";
  if (currentPlan.truncated) setStatus("demoTooLong");
  else if (currentPlan.items.length === 40) setStatus("demoLimit");
  playButton.disabled = !ready || !currentPlan.items.length;
}
function renderCatalog() {
  const query = document
    .querySelector("#search")
    .value.trim()
    .toLocaleLowerCase();
  const catalog = [];
  if (mode !== "dictionary" && modelAvailable)
    catalog.push(
      ...clips.map((c) => ({
        id: c.id,
        text: c.text,
        source: c.runtime_candidate ? "candidate" : "t08",
      })),
    );
  if (mode !== "t08")
    catalog.push(
      ...Object.values(SIGNS).map((c) => ({
        id: c.id,
        text: c.gloss,
        source: "dictionary",
      })),
    );
  const found = catalog.filter((c) =>
    (c.text + " " + c.id).toLocaleLowerCase().includes(query),
  );
  document.querySelector("#catalog-count").textContent =
    `${found.length} / ${catalog.length}`;
  const list = document.querySelector("#catalog-list");
  list.replaceChildren();
  for (const entry of found) {
    const b = element("button", entry.text);
    b.type = "button";
    b.dataset.source = entry.source;
    b.title =
      entry.source === "candidate"
        ? t("demoCandidateDetail", {
            mse:
              clips
                .find((clip) => clip.id === entry.id)
                ?.normalized_reconstruction_mse?.toFixed(3) || "?",
          })
        : t(entry.source === "t08" ? "demoSourceT08" : "demoSourceDictionary");
    b.addEventListener("click", () => {
      send("STOP");
      resetUi();
      input.value = entry.text;
      refreshPlan();
      input.focus();
    });
    list.append(b);
  }
}
function resetUi() {
  running = false;
  pauseButton.disabled = true;
  stopButton.disabled = true;
  pauseButton.textContent = t("demoPause");
  document.querySelector("#progress-bar").style.width = "0%";
  document.querySelector("#progress-text").textContent = "0:00";
  document.querySelector("#current").textContent = t("demoAtRest");
  document.querySelector("#source-badge").textContent = t("demoReadyBadge");
}
function play() {
  if (!ready) return;
  refreshPlan();
  if (!currentPlan.items.length) {
    setStatus("demoNoMatch");
    return;
  }
  resetUi();
  running = true;
  pauseButton.disabled = false;
  stopButton.disabled = false;
  send("PLAY", { items: currentPlan.items });
}
playButton.addEventListener("click", play);
pauseButton.addEventListener("click", () => send("PAUSE"));
stopButton.addEventListener("click", () => {
  send("STOP");
  resetUi();
  setStatus("demoStopped");
});
input.addEventListener("input", refreshPlan);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    play();
  }
});
document.querySelector("#search").addEventListener("input", renderCatalog);
for (const b of document.querySelectorAll("[data-mode]"))
  b.addEventListener("click", () => {
    mode = b.dataset.mode;
    send("STOP");
    resetUi();
    for (const n of document.querySelectorAll("[data-mode]")) {
      n.classList.toggle("active", n === b);
      n.setAttribute("aria-pressed", String(n === b));
    }
    refreshPlan();
    renderCatalog();
    setStatus(
      modelAvailable || mode === "dictionary"
        ? "demoReady"
        : "demoPartialAsset",
    );
  });
for (const b of document.querySelectorAll("[data-view]"))
  b.addEventListener("click", () => {
    send("VIEW", { view: b.dataset.view });
    for (const n of document.querySelectorAll("[data-view]"))
      n.setAttribute("aria-pressed", String(n === b));
  });
document
  .querySelector("#speed")
  .addEventListener("change", (e) =>
    send("SPEED", { speed: Number(e.target.value) }),
  );
window.addEventListener("message", (e) => {
  if (
    e.source !== frame.contentWindow ||
    e.origin !== location.origin ||
    e.data?.source !== "signbridge-demo-avatar"
  )
    return;
  const message = e.data;
  // Ignore queued events from a clip superseded by stop, mode change or replay.
  if (
    ["CURRENT", "PROGRESS", "PAUSED", "FINISHED", "STOPPED", "ERROR"].includes(
      message.type,
    ) &&
    !message.fatal &&
    message.requestId !== requestId
  )
    return;
  if (message.type === "READY") {
    ready = true;
    modelAvailable = message.modelAvailable;
    document.querySelector("#loading").hidden = true;
    document.querySelector("#model-count").textContent = String(
      message.clipCount,
    );
    document.querySelector("#candidate-count").textContent = String(
      message.candidateCount || candidates.length,
    );
    refreshPlan();
    renderCatalog();
    document.querySelector("#retry").hidden = true;
    if (!running) setStatus(modelAvailable ? "demoReady" : "demoPartialAsset");
  } else if (message.type === "ERROR") {
    document.querySelector("#loading").hidden = true;
    resetUi();
    if (message.fatal) ready = false;
    refreshPlan();
    document.querySelector("#retry").hidden = false;
    setStatus("demoFailed", { detail: t(message.error) });
  } else if (message.type === "ASSET_WARNING") {
    setStatus("demoPartialAsset");
  } else if (message.type === "CURRENT") {
    running = true;
    pauseButton.disabled = false;
    stopButton.disabled = false;
    current = message;
    document.querySelector("#current").textContent = message.item.label;
    document.querySelector("#source-badge").textContent =
      message.item.source === "candidate"
        ? t("demoCandidateDetail", {
            mse: message.normalizedReconstructionMse.toFixed(3),
          })
        : t(
            message.item.source === "t08"
              ? "demoSourceT08"
              : "demoSourceDictionary",
          );
    document.querySelector("#tokens").textContent = message.tokens
      ? JSON.stringify(message.tokens, null, 2)
      : t("demoDictionaryToken");
    setStatus("demoPlaying", {
      index: message.itemIndex + 1,
      count: message.count,
      text: message.item.label,
    });
  } else if (message.type === "PROGRESS") {
    document.querySelector("#progress-bar").style.width =
      `${Math.min(100, (message.elapsed / message.duration) * 100)}%`;
    document.querySelector("#progress-text").textContent =
      `${message.elapsed.toFixed(1)} / ${message.duration.toFixed(1)}s`;
  } else if (message.type === "PAUSED") {
    pauseButton.textContent = t(message.paused ? "demoResume" : "demoPause");
    if (message.paused) setStatus("demoPaused");
    else if (current)
      setStatus("demoPlaying", {
        index: current.itemIndex + 1,
        count: current.count,
        text: current.item.label,
      });
  } else if (message.type === "FINISHED") {
    resetUi();
    setStatus("demoFinished");
  } else if (message.type === "STOPPED") {
    if (!running) resetUi();
  }
});
document.querySelector("#download").addEventListener("click", () => {
  const report = {
    schema: "signbridge-demo-session-v1",
    createdAt: new Date().toISOString(),
    input: input.value,
    mode,
    matched: currentPlan.items.map(({ id, source, label, matchedText }) => ({
      id,
      source,
      label,
      matchedText,
    })),
    unmatched: currentPlan.unmatched,
    checkpointSha256: model?.checkpoint_sha256 || null,
    checkpointStep: model?.checkpoint_step || null,
    runtime: "offline_cpu_token_decode_assets",
    textToSignGenerated: false,
    researchOnly: true,
    lastPlayedMotion: current
      ? {
          id: current.item.id,
          source: current.item.source,
          tokens: current.tokens,
          candidate: current.item.source === "candidate",
          normalizedReconstructionMse: current.normalizedReconstructionMse,
          trainingDataMember: current.item.source === "t08",
        }
      : null,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
  );
  const a = element("a");
  a.href = url;
  a.download = "signbridge-demo-session.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  setStatus("demoExported");
});
async function research() {
  const list = document.querySelector("#research-list");
  try {
    const response = await fetch("research.json");
    if (!response.ok) throw new Error("missing");
    const data = await response.json();
    if (!data.length) list.textContent = t("demoResearchMissing");
    for (const r of data) {
      const b = element("button", r.label);
      const hint = element("small", r.series);
      b.append(hint);
      b.addEventListener("click", () => {
        document.querySelector("#research-preview").hidden = false;
        document.querySelector("#research-caption").textContent = t(
          "demoResearchLabel",
          { text: r.label, series: r.series },
        );
        const img = document.querySelector("#research-image");
        img.alt = t("demoResearchLabel", { text: r.label, series: r.series });
        img.src = r.image;
      });
      list.append(b);
    }
  } catch {
    list.textContent = t("demoResearchMissing");
  }
}
document.querySelector("#close-preview").addEventListener("click", () => {
  document.querySelector("#research-preview").hidden = true;
  document.querySelector("#research-image").removeAttribute("src");
});
document
  .querySelector("#retry")
  .addEventListener("click", () => location.reload());
input.value = t("demoSample");
document.querySelector("#tokens").textContent = t("demoTokenEmpty");
renderCatalog();
refreshPlan();
research();
try {
  const r = await fetch("t08-motion.json");
  if (!r.ok) throw new Error("demoInvalidAsset");
  model = validateT08Bundle(await r.json());
  clips = model.clips;
  try {
    const candidatesResponse = await fetch("t08-candidates.json");
    if (!candidatesResponse.ok) throw new Error("demoInvalidCandidateAsset");
    candidateModel = validateT08CandidateBundle(
      await candidatesResponse.json(),
    );
    candidates = candidateModel.clips;
    clips = [...clips, ...candidates];
  } catch {
    candidates = [];
    candidateModel = null;
  }
  document.querySelector("#asset-evidence").textContent = t("demoCheckpoint", {
    hash: model.checkpoint_sha256,
    steps: model.checkpoint_step,
  });
  renderCatalog();
  refreshPlan();
  document.querySelector("#candidate-count").textContent = String(
    candidates.length,
  );
  document.querySelector("#candidate-warning").textContent = candidates.length
    ? t("demoCandidateWarning")
    : "";
} catch {
  setStatus("demoPartialAsset");
}
send("HELLO");
window.addEventListener("pagehide", () => send("STOP"), { once: true });
