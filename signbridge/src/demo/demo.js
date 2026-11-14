import { t, setLocale } from "../i18n/locales.js";
import { SIGNS } from "../avatar/sign-language-data.js";
import {
  planAutoText,
  planDemoText,
  validateT08Bundle,
  validateT08CandidateBundle,
  motionSource,
} from "./demo-motion.js";
import { buildDemoPhraseCatalog } from "./phrase-catalog.js";
import {
  validateExperimentalIndex,
  experimentalPreviewSample,
} from "./experimental-motion.js";
import { validateNativeIndex } from "./native-motion.js";
import { planNativeText } from "./native-plan.js";
import { planCoreText } from "./core-plan.js";
import { readCoreManifest } from "./core-motion.js";
import { buildCoreScenario, corePlaybackStatus } from "./core-scenario.js";
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
const researchDetails = document.querySelector("#research-details");
const openResearch = () => {
  researchDetails.open = true;
};
document
  .querySelector("#open-research")
  .addEventListener("click", openResearch);
window.addEventListener("hashchange", () => {
  if (location.hash === "#research-details") openResearch();
});
if (location.hash === "#research-details") openResearch();
if (globalThis.chrome?.runtime?.id) {
  document.querySelector("#extension-tools").hidden = false;
  document.querySelector("#extension-tools-note").hidden = true;
}

const status = document.querySelector("#status"),
  playButton = document.querySelector("#play"),
  pauseButton = document.querySelector("#pause"),
  stopButton = document.querySelector("#stop");
let clips = [],
  candidates = [],
  experimental = [],
  nativeClips = [],
  coreManifest = null,
  coreExpected = false,
  coreResponse = null,
  coreFailed = false,
  selectedNativeId = null,
  availableSources = new Set(),
  model = null,
  candidateModel = null,
  mode = "auto",
  catalogView = "phrases",
  vocabulary = [],
  blockedVocab = null,
  ready = false,
  modelAvailable = false,
  currentPlan = { items: [], unmatched: "" },
  current = null,
  running = false,
  requestId = 0;
const modeDescriptionKeys = {
  auto: "workbenchModeAutoDescription",
  t08: "workbenchModeT08Description",
  dictionary: "workbenchModeDictionaryDescription",
  semantic: "workbenchModeSemanticDescription",
  native: "nativeModeDescription",
  core: "coreModeDescription",
};
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
// Native mode is the default view. A word with only a builtin pose has no
// native clip, so a bare exact-match check would leave it unplayable ("暂不支持").
// Fall back to the auto route so those words still resolve to their pose.
function nativeFallback(plan) {
  if (plan.canPreview || plan.items.length) return plan;
  const text = String(plan.unmatched || "").trim();
  if (!text) return plan;
  const auto = planAutoText(
    text,
    playableClips(),
    nativeClips.filter((c) => !c.core_unit_key),
  );
  return auto.items.length ? auto : plan;
}
function refreshPlan() {
  currentPlan =
    mode === "core"
      ? planCoreText(input.value, coreManifest)
      : mode === "native"
        ? nativeFallback(
            planNativeText(
              input.value,
              nativeClips.filter((c) => !c.core_unit_key),
              { nativeId: selectedNativeId },
            ),
          )
        : mode === "auto"
          ? planAutoText(
              input.value,
              playableClips(),
              nativeClips.filter((c) => !c.core_unit_key),
            )
          : planDemoText(input.value, mode, playableClips());
  renderSemanticPlan();
  const analysisOnly = mode === "semantic";
  document.querySelector(".catalog-switch").hidden = mode === "core";
  document.querySelector("#motion-smoothing").disabled = [
    "native",
    "core",
  ].includes(mode);
  document.querySelector("#stabilization-profile").disabled = [
    "native",
    "core",
  ].includes(mode);
  if (coreManifest)
    document.querySelector("#core-scope").textContent = t(
      mode === "core" ? "coreScope" : "coreResearchScope",
    );
  if (coreManifest)
    document.querySelector("#native-repair-summary").hidden = mode === "core";
  document.querySelector("#native-warning").hidden =
    mode === "core" || !nativeClips.length;
  renderCoreEvidence();
  document.querySelector("#playback-actions").hidden = analysisOnly;
  document.querySelector("#motion-catalog").hidden = analysisOnly;
  document.querySelector(".coverage").hidden = analysisOnly;
  const routingNote = document.querySelector("#routing-note");
  routingNote.textContent = t(modeDescriptionKeys[mode]);
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
    const candidate = [...clips, ...nativeClips].find(
      (clip) => clip.id === item.id,
    );
    span.title = sourceLabel(item.source, candidate);
    matches.append(span);
  }
  document
    .querySelector("#unknown")
    .classList.toggle("supported", !currentPlan.unmatched);
  document.querySelector("#unknown").textContent =
    mode === "core"
      ? currentPlan.canPreview
        ? t("coreExact")
        : currentPlan.gaps.length
          ? t("coreGap", {
              words: [...new Set(currentPlan.gaps.map((g) => g.surface))].join(
                "、",
              ),
            })
          : t("coreBlocked")
      : mode === "semantic"
        ? t("cslAnalysisOnly")
        : currentPlan.unmatched
          ? t("demoUnknown", { text: currentPlan.unmatched })
          : currentPlan.route === "native_exact_candidate"
            ? t("nativeExactNote")
            : [
                  "bounded_demo_semantic",
                  "bounded_native_semantic",
                  "native_exact_candidate",
                  "native_auto_mix",
                ].includes(currentPlan.route)
              ? t("demoSemanticPreview")
              : input.value.trim()
                ? t("demoAllMatched")
                : "";
  if (currentPlan.truncated) setStatus("demoTooLong");
  else if (currentPlan.items.length === 40) setStatus("demoLimit");
  playButton.disabled =
    mode === "semantic" ||
    !ready ||
    !currentPlan.items.length ||
    (blockedVocab !== null && input.value === blockedVocab);
  status.dataset.playbackState =
    mode === "core" && !currentPlan.canPreview ? "blocked" : "available";
  if (mode === "core" && !running) {
    const feedback = corePlaybackStatus(currentPlan, {
      ready,
      failed: coreFailed,
    });
    setStatus(feedback.key, feedback.args);
  }
}
function renderSemanticPlan() {
  const panel = document.querySelector("#semantic-panel");
  panel.hidden =
    mode !== "semantic" &&
    ![
      "bounded_demo_semantic",
      "bounded_native_semantic",
      "core_candidate_plan",
    ].includes(currentPlan.route);
  if (panel.hidden) return;
  const plan = currentPlan;
  document.querySelector("#semantic-source-note").textContent = [
    "bounded_native_semantic",
    "core_candidate_plan",
  ].includes(plan.route)
    ? t("nativeUnitSources", {
        sources: plan.draft
          .map(
            (item) =>
              `${item.surface} (${sourceLabel(
                item.source,
                nativeClips.find((c) => c.id === item.id),
              )})`,
          )
          .join(" → "),
      })
    : t("cslSources");
  document.querySelector("#semantic-status").textContent =
    [
      "bounded_demo_semantic",
      "bounded_native_semantic",
      "core_candidate_plan",
    ].includes(plan.route) && plan.canPreview
      ? mode === "core"
        ? t("coreReadyToPlay", { count: plan.items.length })
        : t("cslDemoPreviewReady")
      : t("cslAnalysisOnly");
  const list = document.querySelector("#semantic-roles");
  list.replaceChildren();
  for (const [role, key] of Object.entries({
    actor: "cslActor",
    predicate: "cslPredicate",
    patient: "cslPatient",
    goal: "cslGoal",
    time: "cslTime",
    negation: "cslNegation",
    modality: "cslModality",
    question: "cslQuestion",
    degree: "cslDegree",
    politeness: "cslPoliteness",
  })) {
    list.append(
      element("dt", t(key)),
      element("dd", plan.analysis.meaning[role]?.surface || t("cslUnset")),
    );
  }
  document.querySelector("#semantic-draft").textContent = plan.draft.length
    ? plan.draft.map((unit) => unit.surface).join(" → ")
    : t("cslNoDraft");
  document.querySelector("#semantic-gaps").textContent = plan.gaps.length
    ? t("cslGaps", { words: plan.gaps.map((unit) => unit.surface).join("、") })
    : "";
  document.querySelector("#semantic-unknown").textContent =
    plan.analysis.unknown.length || plan.analysis.remainingText
      ? t("cslUnknown", {
          words:
            plan.analysis.unknown.map((unit) => unit.surface).join("") +
            plan.analysis.remainingText,
        })
      : "";
  const blockers = document.querySelector("#semantic-blockers");
  blockers.replaceChildren();
  for (const blocker of plan.blockers)
    blockers.append(
      element(
        "li",
        mode === "core"
          ? t(
              blocker === "directional_motion_missing"
                ? "coreIssueDirection"
                : blocker === "ambiguous_scope"
                  ? "coreIssueScope"
                  : blocker === "multiple_clauses_or_question"
                    ? "coreIssueQuestion"
                    : blocker === "motion_evidence_missing"
                      ? "coreBlocked"
                      : "coreIssueUnknown",
            )
          : t(`cslIssues.${blocker}`),
      ),
    );
  for (const warning of plan.warnings || [])
    blockers.append(
      element(
        "li",
        mode === "core" ? t("coreScope") : t(`cslIssues.${warning}`),
      ),
    );
  document.querySelector("#semantic-json").textContent = JSON.stringify(
    plan,
    null,
    2,
  );
}
function renderCoreEvidence() {
  const panel = document.querySelector("#core-evidence-panel"),
    list = document.querySelector("#core-evidence-list");
  panel.hidden = mode !== "core" || !currentPlan.items.length;
  list.replaceChildren();
  if (panel.hidden) return;
  for (const item of currentPlan.items) {
    const unit = coreManifest.units.find((u) => u.id === item.id);
    if (!unit) continue;
    const p = element("p"),
      link = element(
        "a",
        t("coreOriginal", {
          word: unit.text,
          start: unit.source_frame_range_1based[0],
          end: unit.source_frame_range_1based[1],
        }),
      );
    link.href = `core-evidence/${unit.key}/original.mp4`;
    link.target = "_blank";
    link.rel = "noopener";
    p.append(link);
    const record = element("a", t("coreAlignment", { word: unit.text }));
    record.href = `core-evidence/${unit.key}/alignment.json`;
    record.target = "_blank";
    record.rel = "noopener";
    p.append(element("br"), record);
    list.append(p);
  }
}
function playableClips() {
  return clips.filter((clip) => availableSources.has(motionSource(clip)));
}
function sourceLabel(source, clip, stabilized, presentation) {
  if (!source) return t("coreMissingSource");
  if (source === "native" && clip?.core_unit_key) return t("coreSource");
  if (source === "native") return t("nativeSource");
  if (source === "candidate")
    return t("demoCandidateDetail", {
      mse: clip?.normalized_reconstruction_mse?.toFixed(3) || "?",
    });
  if (source === "experimental")
    return t(
      presentation === "quaternion-temporal-adaptive-v1"
        ? clip?.quality_warning
          ? "demoAdaptiveFilteredWarningBadge"
          : "demoAdaptiveFilteredBadge"
        : stabilized === true
          ? clip?.quality_warning
            ? "demoExperimentalSmoothedWarningBadge"
            : "demoExperimentalSmoothedBadge"
          : stabilized === false
            ? "demoExperimentalRawBadge"
            : clip?.quality_warning
              ? "demoExperimentalWarningBadge"
              : "demoExperimentalBadge",
    );
  if (source === "semantic") return t("demoSourceSemantic");
  return t(
    source === "t08"
      ? "demoSourceT08"
      : source === "composition"
        ? "demoSourceComposition"
        : "demoSourceDictionary",
  );
}
function renderCatalog() {
  const query = document
    .querySelector("#search")
    .value.trim()
    .toLocaleLowerCase();
  const phrases = buildDemoPhraseCatalog(playableClips());
  const vocabView =
    catalogView === "vocab" && vocabulary.length > 0 && mode !== "core";
  const catalog = vocabView
    ? vocabulary.map((entry) => ({
        id: entry.forms.join(" "),
        text: entry.text,
        source: "vocab",
        status: entry.status,
        nativeId: entry.nativeId,
      }))
    : mode === "core"
      ? (coreManifest?.units || []).map((c) => ({
          id: c.id,
          text: c.text,
          source: "native",
        }))
      : mode === "native"
        ? nativeClips
            .filter((c) => !c.core_unit_key)
            .map((c) => ({ id: c.id, text: c.text, source: "native" }))
        : catalogView === "phrases"
          ? phrases.filter(
              (entry) =>
                mode === "auto" ||
                mode === "semantic" ||
                (mode === "t08" && entry.source !== "composition") ||
                (mode === "dictionary" && entry.source === "composition"),
            )
          : mode === "t08"
            ? []
            : Object.values(SIGNS).map((c) => ({
                id: c.id,
                text: c.gloss,
                source: "dictionary",
              }));
  const found = catalog.filter((c) =>
    (c.text + " " + c.id).toLocaleLowerCase().includes(query),
  );
  document.querySelector("#catalog-count").textContent =
    `${found.length} / ${catalog.length}`;
  const MOTION_STATUSES = [
    "native_display_candidate",
    "wrist_amplitude_reduced_candidate",
    "builtin_handmade_pose",
  ];
  document.querySelector("#catalog-note").textContent = vocabView
    ? t("demoVocabNote", {
        total: catalog.length,
        native: catalog.filter((e) => MOTION_STATUSES.includes(e.status))
          .length,
        pose: catalog.filter((e) => e.status === "builtin_handmade_pose")
          .length,
        none: catalog.filter((e) => !MOTION_STATUSES.includes(e.status)).length,
      })
    : mode === "core"
      ? t("coreCatalog", { count: catalog.length })
      : mode === "native"
        ? t("nativeCatalog", { count: catalog.length })
        : !researchDetails.open
          ? t("workbenchCatalogCount", { count: catalog.length })
          : catalogView === "phrases"
            ? t("demoPhraseSourceNote", {
                total: catalog.length,
                reference: catalog.filter((entry) => entry.source === "t08")
                  .length,
                candidate: catalog.filter(
                  (entry) => entry.source === "candidate",
                ).length,
                experimental: catalog.filter(
                  (entry) => entry.source === "experimental",
                ).length,
                composed: catalog.filter(
                  (entry) => entry.source === "composition",
                ).length,
              })
            : t("demoWordSourceNote", { count: catalog.length });
  const list = document.querySelector("#catalog-list");
  list.replaceChildren();
  for (const button of document.querySelectorAll("[data-catalog-view]")) {
    button.hidden =
      (button.dataset.catalogView === "vocab" && !vocabulary.length) ||
      (button.dataset.catalogView === "words" && mode === "native");
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.catalogView === catalogView),
    );
  }
  for (const entry of found) {
    const b = element("button", entry.text);
    b.type = "button";
    b.dataset.source = entry.source;
    b.title = sourceLabel(
      entry.source,
      [...clips, ...nativeClips].find((clip) => clip.id === entry.id),
    );
    b.dataset.id = entry.id;
    if (entry.status) {
      b.dataset.status = entry.status;
      b.title = vocabStatusLabel(entry.status);
    }
    b.addEventListener("click", () => {
      if (entry.source === "vocab") {
        pickVocabulary(entry);
        return;
      }
      send("STOP", { preservePose: true });
      resetUi();
      input.value = entry.text;
      selectedNativeId = entry.source === "native" ? entry.id : null;
      refreshPlan();
      input.focus();
    });
    list.append(b);
  }
}
function vocabStatusLabel(status) {
  return t(
    status === "native_display_candidate"
      ? "demoVocabStatusNative"
      : status === "wrist_amplitude_reduced_candidate"
        ? "demoVocabStatusNativeReduced"
        : status === "builtin_handmade_pose"
          ? "demoVocabStatusPose"
          : "demoVocabStatusNone",
  );
}
// Only words with a real motion are routed to a playable mode. Words without
// one stay blocked: no other motion is borrowed to stand in for them.
function pickVocabulary(entry) {
  send("STOP", { preservePose: true });
  resetUi();
  blockedVocab = null;
  const nativeClip = [
    "native_display_candidate",
    "wrist_amplitude_reduced_candidate",
  ].includes(entry.status)
    ? nativeClips.find((c) => !c.core_unit_key && c.text === entry.text)
    : null;
  if (nativeClip) {
    selectMode("native", true);
    input.value = entry.text;
    selectedNativeId = nativeClip.id;
  } else if (entry.status === "builtin_handmade_pose") {
    // Auto mode already resolves builtin poses, and native recordings win
    // whenever both exist. Locking to "dictionary" here routed every later
    // input to the word library and hid the sign library from playback.
    selectMode("auto", true);
    input.value = entry.text;
  } else {
    input.value = entry.text;
    blockedVocab = entry.text;
  }
  refreshPlan();
  if (blockedVocab) setStatus("demoVocabNoMotion", { text: entry.text });
  input.focus();
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
  if (blockedVocab !== null && input.value === blockedVocab) {
    setStatus("demoVocabNoMotion", { text: blockedVocab });
    return;
  }
  if (mode === "semantic") {
    setStatus("cslAnalysisOnly");
    return;
  }
  refreshPlan();
  if (!currentPlan.items.length) {
    if (mode === "core") {
      const feedback = corePlaybackStatus(currentPlan, {
        ready,
        failed: coreFailed,
      });
      setStatus(feedback.key, feedback.args);
    } else setStatus(mode === "semantic" ? "cslNoMatch" : "demoNoMatch");
    return;
  }
  resetUi();
  running = true;
  setStatus("demoLoading");
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
input.addEventListener("input", () => {
  if (running) {
    send("STOP", { preservePose: true });
    resetUi();
  }
  selectedNativeId = null;
  refreshPlan();
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    play();
  }
});
document.querySelector("#search").addEventListener("input", renderCatalog);
for (const button of document.querySelectorAll("[data-catalog-view]"))
  button.addEventListener("click", () => {
    catalogView = button.dataset.catalogView;
    renderCatalog();
  });
function selectMode(nextMode, keepVocabulary = false) {
  mode = nextMode;
  selectedNativeId = null;
  blockedVocab = null;
  if (keepVocabulary || (mode === "auto" && catalogView === "vocab"))
    catalogView = "vocab";
  else if (mode === "auto" || mode === "t08") catalogView = "phrases";
  else if (mode === "dictionary") catalogView = "words";
  else if (catalogView === "vocab") catalogView = "phrases";
  send("STOP", { preservePose: true });
  resetUi();
  for (const n of document.querySelectorAll("[data-mode]")) {
    const selected = n.dataset.mode === mode;
    n.classList.toggle("active", selected);
    n.setAttribute("aria-pressed", String(selected));
  }
  refreshPlan();
  renderCatalog();
  if (mode !== "core")
    setStatus(
      mode === "semantic"
        ? "cslAnalysisOnly"
        : modelAvailable || mode === "dictionary"
          ? "demoReady"
          : "demoPartialAsset",
    );
}
for (const b of document.querySelectorAll("[data-mode]"))
  b.addEventListener("click", () => selectMode(b.dataset.mode));
document
  .querySelector("#return-core")
  .addEventListener("click", () => selectMode("core"));
researchDetails.addEventListener("toggle", (event) => {
  renderCatalog();
  // Closing research returns the ordinary workflow to automatic matching.
  if (
    event.target === researchDetails &&
    !researchDetails.open &&
    (coreManifest ? mode !== "core" : !["auto", "native"].includes(mode))
  )
    selectMode(coreManifest ? "core" : "auto");
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
document
  .querySelector("#stabilization-profile")
  .addEventListener("change", (event) =>
    send("STABILIZATION_PROFILE", { profile: event.target.value }),
  );
document
  .querySelector("#motion-smoothing")
  .addEventListener("change", (event) =>
    send("SMOOTHING", { enabled: event.target.checked }),
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
    [
      "CURRENT",
      "PROGRESS",
      "PAUSED",
      "FINISHED",
      "STOPPED",
      "ERROR",
      "PRESENTATION",
    ].includes(message.type) &&
    !message.fatal &&
    message.requestId !== requestId
  )
    return;
  if (message.type === "READY") {
    ready = true;
    modelAvailable = message.modelAvailable;
    send("SMOOTHING", {
      enabled: document.querySelector("#motion-smoothing").checked,
    });
    availableSources = new Set(message.sources || []);
    document.querySelector("#loading").hidden = true;
    document.querySelector("#model-count").textContent = String(
      message.clipCount,
    );
    document.querySelector("#candidate-count").textContent = String(
      message.candidateCount || 0,
    );
    document.querySelector("#experimental-count").textContent = String(
      message.experimentalCount || 0,
    );
    document.querySelector("#native-count").textContent = String(
      message.nativeCount || 0,
    );
    refreshPlan();
    renderCatalog();
    document.querySelector("#retry").hidden = true;
    if (!running && mode !== "core")
      setStatus(
        coreFailed
          ? "coreInvalidAsset"
          : modelAvailable
            ? "demoReady"
            : "demoPartialAsset",
      );
  } else if (message.type === "ERROR") {
    document.querySelector("#loading").hidden = true;
    resetUi();
    if (message.fatal) ready = false;
    refreshPlan();
    document.querySelector("#retry").hidden = false;
    setStatus("demoFailed", { detail: t(message.error) });
  } else if (message.type === "ASSET_WARNING") {
    if (!coreFailed && mode !== "core") setStatus("demoPartialAsset");
  } else if (message.type === "CURRENT") {
    running = true;
    pauseButton.disabled = false;
    stopButton.disabled = false;
    current = message;
    document.querySelector("#current").textContent = message.item.label;
    const sourceBadge = document.querySelector("#source-badge");
    sourceBadge.textContent = sourceLabel(
      message.item.source,
      [...clips, ...nativeClips].find((clip) => clip.id === message.item.id),
      message.item.source === "experimental" ? message.stabilized : undefined,
      message.presentation,
    );
    sourceBadge.title = message.performance
      ? `${message.performance.cacheHit ? "cache" : "compile"}: ${Number(message.performance.compileMs).toFixed(2)}ms; ${message.performance.numericBytes ?? message.performance.numericCacheBytes} numeric cache bytes`
      : sourceBadge.textContent;
    document.querySelector("#tokens").textContent = message.tokens
      ? JSON.stringify(message.tokens, null, 2)
      : t(
          message.item.source === "native"
            ? "nativeToken"
            : message.item.source === "experimental"
              ? "demoExperimentalToken"
              : "demoDictionaryToken",
        );
    setStatus("demoPlaying", {
      index: message.itemIndex + 1,
      count: message.count,
      text: message.item.label,
    });
  } else if (message.type === "PRESENTATION") {
    if (current?.item.id === message.clipId) {
      current.stabilized = message.stabilized;
      current.presentation = message.presentation;
      if (message.stabilizationEnabled !== undefined)
        current.stabilizationEnabled = message.stabilizationEnabled;
      if (message.profile)
        document.querySelector("#stabilization-profile").value =
          message.profile;
      if (message.performance) {
        current.performance = message.performance;
        document.querySelector("#source-badge").title =
          `${message.performance.cacheHit ? "cache" : "compile"}: ${Number(message.performance.compileMs).toFixed(2)}ms; ${message.performance.numericBytes ?? message.performance.numericCacheBytes} numeric cache bytes`;
      }
      document.querySelector("#source-badge").textContent = sourceLabel(
        current.item.source,
        clips.find((clip) => clip.id === current.item.id),
        message.stabilized,
        message.presentation,
      );
    }
  } else if (message.type === "PROFILE_STATE") {
    document.querySelector("#stabilization-profile").dataset.activeProfile =
      message.profile;
    document.querySelector("#stabilization-profile").dataset.activeClip =
      message.clipId || "";
    document.querySelector("#stabilization-profile").dataset.experimentalClip =
      String(message.experimentalClip);
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
    semanticPlan: mode === "semantic" ? currentPlan : null,
    checkpointSha256: model?.checkpoint_sha256 || null,
    checkpointStep: model?.checkpoint_step || null,
    runtime: "offline_token_decode_and_fitted_motion_assets",
    textToSignGenerated: false,
    researchOnly: true,
    lastPlayedMotion: current
      ? {
          id: current.item.id,
          source: current.item.source,
          tokens: current.tokens,
          candidate: current.item.source === "candidate",
          experimental: current.item.source === "experimental",
          humanApproved:
            current.item.source === "experimental"
              ? clips.find((clip) => clip.id === current.item.id)
                  ?.human_approved === true
              : null,
          motionReviewStatus:
            current.item.source === "experimental"
              ? clips.find((clip) => clip.id === current.item.id)
                  ?.motion_review_status || null
              : null,
          motionApprovalScope:
            current.item.source === "experimental" &&
            clips.find((clip) => clip.id === current.item.id)
              ?.human_approved === true
              ? "motion_quality_only"
              : null,
          trainingReady: false,
          modelTrainingReady: false,
          presentation: current.presentation || "raw",
          motionAssetSha256:
            clips.find((clip) => clip.id === current.item.id)?.sha256 || null,
          performance: current.performance || null,
          stabilizationEnabled: current.stabilizationEnabled ?? null,
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
let researchLoaded = false;
const loadResearch = () => {
  if (researchDetails.open && !researchLoaded) {
    researchLoaded = true;
    research();
  }
};
researchDetails.addEventListener("toggle", loadResearch);
loadResearch();
// Discover the core scope before loading legacy references. A broken core
// resource must not turn the ordinary workflow into legacy playback.
try {
  coreResponse = await fetch("core-manifest.json");
  if (coreResponse.ok) {
    const declared = await coreResponse.clone().json();
    coreExpected = declared.unavailable !== true;
    if (coreExpected) mode = "core";
  }
} catch {
  coreExpected = true;
  mode = "core";
}
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
  document.querySelector("#candidate-warning").textContent = candidates.length
    ? t("demoCandidateWarning")
    : "";
} catch {
  setStatus("demoPartialAsset");
}
try {
  const response = await fetch("experimental-index.json");
  if (!response.ok) throw new Error("demoInvalidExperimentalAsset");
  const data = await response.json();
  if (!data.unavailable) experimental = validateExperimentalIndex(data).clips;
  input.value = experimentalPreviewSample(
    experimental,
    input.value,
    t("demoSample"),
  );
  clips = [...clips, ...experimental];
  document.querySelector("#experimental-warning").textContent =
    experimental.length
      ? t(
          experimental.some((c) => c.preview_only)
            ? "demoExperimentalPreviewWarning"
            : experimental.every((c) => c.human_approved === true)
              ? "demoExperimentalApprovedWarning"
              : experimental.some((c) => c.human_approved === true)
                ? "demoExperimentalMixedWarning"
                : "demoExperimentalWarning",
        )
      : "";
} catch {
  experimental = [];
}
try {
  const response = await fetch("native-index.json");
  if (!response.ok) throw new Error("nativeInvalidAsset");
  const indexBytes = await response.arrayBuffer();
  const data = JSON.parse(new globalThis.TextDecoder().decode(indexBytes));
  coreExpected = coreExpected || Boolean(data.core_version);
  if (!data.unavailable) nativeClips = validateNativeIndex(data).clips;
  if (data.repair_version) {
    document.querySelector("#native-repair-summary").hidden = false;
    document.querySelector("#native-repair-summary").textContent = t(
      "nativeRepairSummary",
      { count: nativeClips.filter((c) => !c.core_unit_key).length },
    );
  }
  if (nativeClips.length) {
    document.querySelector("#native-mode").hidden = false;
    document.querySelector("#native-count-panel").hidden = false;
    document.querySelector("#native-warning").hidden = false;
    document.querySelector("#native-warning").textContent = t("nativeWarning");
    if (data.core_version) {
      coreManifest = await readCoreManifest(
        coreResponse || (await fetch("core-manifest.json")),
        data,
        indexBytes,
      );
      if (!coreManifest) throw new Error("coreInvalidAsset");
      document.querySelector("#core-toolbar").hidden = false;
      document.querySelector("#core-mode").hidden = false;
      document.querySelector("#core-count").textContent = t("coreCount", {
        count: coreManifest.units.length,
      });
      const scenario = buildCoreScenario(coreManifest);
      document.querySelector("#core-scene-title").hidden = false;
      document.querySelector("#core-scene-title").textContent = t(
        scenario.titleKey,
      );
      for (const example of [
        ...scenario.examples.filter((e) => e.plan.canPreview),
        ...scenario.gaps,
      ]) {
        const text = example.text;
        const button = element(
          "button",
          example.plan.canPreview ? text : t("coreGapExampleLabel", { text }),
        );
        button.type = "button";
        button.dataset.scenario = example.plan.canPreview ? "playable" : "gap";
        button.dataset.text = text;
        button.title = t(
          example.plan.canPreview ? "coreScenePlayable" : "coreSceneGap",
        );
        button.addEventListener("click", () => {
          input.value = text;
          selectMode("core");
        });
        document
          .querySelector(
            example.plan.canPreview ? "#core-samples" : "#core-gap-samples",
          )
          .append(button);
      }
      input.value = "我工作";
      researchDetails.open = false;
      selectMode("core");
    } else if (new URL(location.href).searchParams.get("native") !== "0") {
      researchDetails.open = true;
      input.value =
        nativeClips.find((c) => c.text === "我")?.text || nativeClips[0].text;
      selectMode("native");
    }
  }
} catch (error) {
  nativeClips = [];
  if (coreExpected || error.message === "coreInvalidAsset") {
    coreFailed = true;
    mode = "core";
    setStatus("coreInvalidAsset");
  }
}
try {
  const response = await fetch("demo-vocabulary.json");
  if (!response.ok) throw new Error("demoInvalidAsset");
  const data = await response.json();
  if (
    data.schema !== "signbridge-demo-vocabulary-ui-v1" ||
    !Array.isArray(data.entries)
  )
    throw new Error("demoInvalidAsset");
  vocabulary = data.entries.filter(
    (e) => typeof e.text === "string" && Array.isArray(e.forms),
  );
  if (vocabulary.length && mode !== "core") catalogView = "vocab";
} catch {
  vocabulary = [];
}
renderCatalog();
refreshPlan();
send("HELLO");
window.addEventListener("pagehide", () => send("STOP"), { once: true });
