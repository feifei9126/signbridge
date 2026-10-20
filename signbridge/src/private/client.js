import { t, setLocale } from "../i18n/locales.js";
import {
  understand,
  needsLocalServicePage,
  localServicePage,
  probeLocalService,
} from "./private-api.js";

setLocale("zh-CN");
for (const node of document.querySelectorAll("[data-i18n]"))
  node.textContent = t(node.dataset.i18n);
const scopeExperiment =
  new URL(location.href).searchParams.get("scope") === "1";
document.title = t("privateTitle");
if (scopeExperiment) {
  const notice = document.createElement("p");
  notice.className = "scope";
  notice.textContent = t("privateScopeExperiment");
  document.querySelector("main").prepend(notice);
}
const form = document.querySelector("#understand-form");
const endpoint = document.querySelector("#endpoint");
if (document.documentElement.dataset.signbridgeService === "true")
  endpoint.value = location.origin;
const token = document.querySelector("#token");
const text = document.querySelector("#sentence");
const status = document.querySelector("#status");
const output = document.querySelector("#output");
const button = document.querySelector("#analyze");
const openServiceButton = document.querySelector("#open-local-service");
const serviceUnavailable = document.querySelector("#local-service-unavailable");
let pending = null;
function needsServicePage() {
  try {
    return needsLocalServicePage(
      endpoint.value,
      location.origin,
      !document.querySelector("[data-workbench]").hidden,
    );
  } catch {
    return false;
  }
}
function updateHandoff() {
  const needed = needsServicePage();
  serviceUnavailable.hidden = true;
  document.querySelector("#local-handoff").hidden = !needed;
  document.querySelector("#open-local-service").hidden = !needed;
  document.querySelector("#analysis-fields").hidden = needed;
  token.disabled = needed;
  text.disabled = needed;
  button.disabled = needed;
  if (needed) status.textContent = t("workbenchServiceHandoff");
}
endpoint.addEventListener("input", updateHandoff);
updateHandoff();
openServiceButton.addEventListener("click", async () => {
  openServiceButton.disabled = true;
  serviceUnavailable.hidden = true;
  try {
    const probeablePage =
      location.protocol === "http:" &&
      ["127.0.0.1", "localhost"].includes(location.hostname);
    if (probeablePage) {
      const controller = new globalThis.AbortController();
      const timeout = setTimeout(() => controller.abort(), 2500);
      let available = false;
      try {
        available = await probeLocalService(endpoint.value, {
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeout);
      }
      if (!available) {
        serviceUnavailable.hidden = false;
        status.textContent = t("privateServiceUnavailableStatus");
        return;
      }
    }
    location.assign(localServicePage(endpoint.value, scopeExperiment));
  } catch {
    status.textContent = t("privateEndpointInvalid");
  } finally {
    openServiceButton.disabled = false;
  }
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  pending?.abort();
  const controller = new globalThis.AbortController();
  pending = controller;
  const timeout = setTimeout(() => controller.abort(), 10000);
  button.disabled = true;
  status.textContent = t("privateAnalyzing");
  output.replaceChildren();
  try {
    if (needsServicePage()) {
      status.textContent = t("workbenchServiceHandoff");
      return;
    }
    if (pending !== controller || controller.signal.aborted) return;
    const result = await understand({
      endpoint: endpoint.value,
      token: token.value,
      text: text.value,
      signal: controller.signal,
    });
    if (pending !== controller) return;
    status.textContent = t(
      result.status === "abstained"
        ? "privateAbstained"
        : result.scope_experiment
          ? "privateScopeAnalyzed"
          : "privateParsed",
    );
    const dl = document.createElement("dl");
    for (const [role, value] of Object.entries(result.roles)) {
      const dt = document.createElement("dt");
      dt.textContent = t("privateRoles." + role);
      const dd = document.createElement("dd");
      dd.textContent = value;
      dl.append(dt, dd);
    }
    const meta = document.createElement("p");
    meta.textContent = t("privateModel", { model: result.model_id });
    output.append(dl, meta);
    if (result.event_graph) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = t("privateEventStructure");
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(result.event_graph, null, 2);
      details.append(summary, pre);
      output.append(details);
    }
    if (result.expression_plan) {
      const plan = result.expression_plan;
      const paragraph = document.createElement("p");
      paragraph.textContent = t("privatePlanEvidence", {
        components: plan.components.map((c) => c.text).join("、"),
        gaps: plan.uncovered.join("、") || t("privatePlanReview"),
      });
      output.append(paragraph);
    }
  } catch (error) {
    if (pending !== controller) return;
    const key = error.message?.startsWith("private")
      ? error.message
      : "privateConnectionFailed";
    status.textContent = t(key);
  } finally {
    clearTimeout(timeout);
    if (pending === controller) {
      button.disabled = false;
      pending = null;
    }
  }
});
function clearSession() {
  pending?.abort();
  pending = null;
  token.value = "";
  output.replaceChildren();
  button.disabled = false;
  status.textContent = t("privateDisconnected");
}
document.querySelector("#disconnect").addEventListener("click", clearSession);
window.addEventListener("pagehide", clearSession);
