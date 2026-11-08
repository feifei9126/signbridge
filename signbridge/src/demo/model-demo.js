import { setLocale, t } from "../i18n/locales.js";
import { createModelApi } from "./model-demo-api.js";
import { createModelSession } from "./model-demo-session.js";

setLocale("zh-CN");
const tr = (key, args) => t(`modelDemo.${key}`, args);
for (const node of document.querySelectorAll("[data-i18n]"))
  node.textContent = t(node.dataset.i18n);
for (const node of document.querySelectorAll("[data-placeholder]"))
  node.placeholder = t(node.dataset.placeholder);
for (const node of document.querySelectorAll("[data-label]"))
  node.setAttribute("aria-label", t(node.dataset.label));
document.title = tr("title");
for (const node of document.querySelectorAll("[data-title]"))
  node.title = t(node.dataset.title);
const $ = (id) => document.getElementById(id);
const frame = $("avatar");
const api = createModelApi();
let catalog = [],
  ready = false,
  requestId = 0,
  matched = [],
  selected = null,
  paused = false,
  active = false,
  pendingPlayback = false;
const send = (type, data = {}) => {
  if (type === "PLAY" || type === "STOP") requestId++;
  frame.contentWindow.postMessage(
    { source: "signbridge-demo", type, requestId, ...data },
    location.origin,
  );
};
function halt() {
  send("STOP");
  active = false;
  paused = false;
  pendingPlayback = false;
  $("pause").disabled = true;
  $("pause").textContent = tr("pause");
  $("progress").value = 0;
  $("motion-status").textContent = tr("stopped");
}
function clearResult() {
  halt();
  matched = [];
  selected = null;
  $("play-motion").disabled = true;
  $("roles").replaceChildren();
  $("operators").textContent = "—";
  $("raw-model").textContent = "—";
  $("parse-status").textContent = tr("idle");
  $("model-basis").textContent = "";
  $("model-time").textContent = "";
  $("motion-gap").textContent = tr("unavailable");
  $("motion-evidence").textContent = "—";
  $("model-status").textContent = tr(api.connected ? "ready" : "disconnected");
  $("model-status").dataset.state = api.connected ? "ready" : "error";
  for (const button of document.querySelectorAll("[data-reference]"))
    button.setAttribute("aria-pressed", "false");
}
function render(result) {
  const p = result.prediction;
  $("model-status").textContent = tr("ready");
  $("model-status").dataset.state = "ready";
  $("parse-status").textContent = tr(
    p.status === "parsed" ? "parsed" : "refused",
  );
  $("roles").replaceChildren();
  for (const [role, value] of Object.entries(p.roles || {})) {
    const dt = document.createElement("dt"),
      dd = document.createElement("dd");
    dt.textContent = tr(`role.${role}`);
    dd.textContent = value;
    $("roles").append(dt, dd);
  }
  $("operators").textContent = p.operators?.length
    ? p.operators
        .map((value) => {
          const [role, word] = value.split(":");
          return `${tr(`role.${role}`)}［${word}］`;
        })
        .join(" → ")
    : tr("none");
  $("model-basis").textContent = tr(
    result.kind_resolved_by_explicit_structure ? "rule" : "learned",
  );
  $("model-time").textContent = tr("performance", {
    ms: Math.round(result.inference_ms),
  });
  $("raw-model").textContent = JSON.stringify(result, null, 2);
  matched = result.motion_plan?.items || [];
  $("play-motion").disabled = !ready || !matched.length;
  const gap = result.motion_plan?.gaps?.[0];
  $("motion-gap").textContent = tr(
    matched.length
      ? "matched"
      : gap === "directional_motion_unverified"
        ? "gapDirection"
        : gap === "operator_motion_unverified"
          ? "gapOperator"
          : gap === "model_abstained"
            ? "gapRefused"
            : "unavailable",
  );
}
const session = createModelSession({
  predict: (text, signal) => api.predict(text, signal),
  onStop: clearResult,
  onResult: render,
  onError: (error) => {
    resetConnection();
    $("model-status").textContent = tr(
      error.code === "incompatible" ? "incompatible" : "serviceError",
    );
    $("model-status").dataset.state = "error";
    $("retry").hidden = false;
  },
});
async function analyze() {
  if (!api.connected || !$("input").value.trim()) return;
  const pending = session.analyze($("input").value);
  $("model-status").textContent = tr("working");
  await pending;
}
$("analyze").addEventListener("click", analyze);
$("input").addEventListener("input", () => session.clear());
$("input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    analyze();
  }
});
for (const text of [
  "我",
  "我们",
  "你们",
  "我帮你",
  "你帮我",
  "我不想去",
  "我想不去",
  "我没有工作",
]) {
  const button = document.createElement("button");
  button.textContent = text;
  button.addEventListener("click", () => {
    $("input").value = text;
    analyze();
  });
  $("examples").append(button);
}
function play(items, reference) {
  if (!ready || !items.length) return;
  halt();
  selected = reference || null;
  pendingPlayback = true;
  active = true;
  $("motion-status").textContent = tr("playing", {
    text: items[0].matchedText,
  });
  if (reference) {
    $("motion-gap").textContent = tr("reference", { text: reference.text });
    $("motion-evidence").textContent = JSON.stringify(reference, null, 2);
  }
  const bounds = frame.getBoundingClientRect();
  if (bounds.top < 0 || bounds.bottom > window.innerHeight)
    frame.scrollIntoView({ block: "center", behavior: "instant" });
  send("PLAY", { items });
}
$("play-motion").addEventListener("click", () => play(matched));
$("pause").addEventListener("click", () => send("PAUSE"));
$("stop").addEventListener("click", () => session.clear());
$("speed").addEventListener("change", () =>
  send("SPEED", { speed: Number($("speed").value) }),
);
for (const button of document.querySelectorAll("[data-view]"))
  button.addEventListener("click", () =>
    send("VIEW", { view: button.dataset.view }),
  );
function renderCatalog() {
  $("references").replaceChildren();
  $("reference-count").textContent = String(catalog.length);
  for (const clip of catalog) {
    const button = document.createElement("button"),
      title = document.createElement("strong"),
      note = document.createElement("span");
    button.dataset.reference = clip.id;
    button.setAttribute("aria-pressed", "false");
    button.disabled = !ready;
    title.textContent = clip.text;
    note.textContent = tr("source", { seconds: clip.duration });
    button.append(title, note);
    button.addEventListener("click", () => {
      session.clear();
      for (const other of document.querySelectorAll("[data-reference]"))
        other.setAttribute("aria-pressed", String(other === button));
      play(
        [{ id: clip.id, source: "experimental", matchedText: clip.text }],
        clip,
      );
    });
    $("references").append(button);
  }
}
window.addEventListener("message", (event) => {
  const data = event.data;
  if (
    event.source !== frame.contentWindow ||
    event.origin !== location.origin ||
    data?.source !== "signbridge-demo-avatar"
  )
    return;
  if (data.type === "READY") {
    ready = true;
    $("motion-status").textContent = tr("idleMotion");
    renderCatalog();
    send("SMOOTHING", { enabled: true });
    return;
  }
  if (data.type === "ERROR" && data.fatal) {
    ready = false;
    halt();
    renderCatalog();
    $("play-motion").disabled = true;
    $("motion-status").textContent = tr("assetError");
    return;
  }
  if (data.requestId !== requestId) return;
  if (data.type === "CURRENT") {
    active = true;
    pendingPlayback = false;
    $("pause").disabled = false;
    $("motion-status").textContent = tr("playing", {
      text: data.item.matchedText,
    });
  } else if (data.type === "PROGRESS") {
    if (active) $("progress").value = Math.min(1, data.elapsed / data.duration);
  } else if (data.type === "PAUSED") {
    paused = data.paused;
    $("pause").textContent = tr(paused ? "resume" : "pause");
    $("motion-status").textContent = tr(paused ? "paused" : "playing", {
      text: selected?.text || matched[0]?.matchedText || "",
    });
  } else if (
    data.type === "FINISHED" ||
    (data.type === "STOPPED" && !pendingPlayback)
  ) {
    active = false;
    $("pause").disabled = true;
    $("motion-status").textContent = tr(
      data.type === "FINISHED" ? "finished" : "stopped",
    );
  } else if (data.type === "ERROR") {
    halt();
    $("motion-status").textContent = tr("assetError");
  }
});
frame.addEventListener("load", () => send("HELLO"));
let connectionId = 0;
function resetConnection() {
  connectionId++;
  api.disconnect();
  session.clear();
  catalog = [];
  renderCatalog();
  $("analyze").disabled = true;
  $("checkpoint").textContent = "";
}
async function connect(requestPermission = false) {
  resetConnection();
  const generation = connectionId;
  $("retry").hidden = true;
  $("model-status").textContent = tr("loading");
  try {
    const info = await api.connect($("endpoint").value, { requestPermission });
    if (generation !== connectionId) return;
    catalog = info.catalog;
    $("checkpoint").textContent = tr("model", { hash: info.checkpoint_sha256 });
    $("analyze").disabled = false;
    $("model-status").textContent = tr("ready");
    $("model-status").dataset.state = "ready";
    renderCatalog();
    send("HELLO");
  } catch (error) {
    if (generation !== connectionId) return;
    api.disconnect();
    $("analyze").disabled = true;
    $("model-status").textContent = tr(
      [
        "invalidEndpoint",
        "permissionRequired",
        "permissionDenied",
        "incompatible",
      ].includes(error.code)
        ? error.code
        : "disconnected",
    );
    $("model-status").dataset.state = "error";
    $("retry").hidden = api.extension;
  }
}
$("connection-panel").hidden = !api.extension;
$("connect").addEventListener("click", () => connect(true));
$("endpoint").addEventListener("input", resetConnection);
$("retry").addEventListener("click", () => connect(false));
window.addEventListener("pagehide", resetConnection, { once: true });
connect(false);
