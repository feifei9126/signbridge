import { t, setLocale } from "../i18n/locales.js";
import { understand } from "./private-api.js";

setLocale("zh-CN");
for (const node of document.querySelectorAll("[data-i18n]"))
  node.textContent = t(node.dataset.i18n);
document.title = t("privateTitle");
const form = document.querySelector("#understand-form");
const endpoint = document.querySelector("#endpoint");
if (location.protocol === "http:" && location.hostname === "127.0.0.1")
  endpoint.value = location.origin;
const token = document.querySelector("#token");
const text = document.querySelector("#sentence");
const status = document.querySelector("#status");
const output = document.querySelector("#output");
const button = document.querySelector("#analyze");
let pending = null;
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
    const result = await understand({
      endpoint: endpoint.value,
      token: token.value,
      text: text.value,
      signal: controller.signal,
    });
    if (pending !== controller) return;
    status.textContent = t(
      result.status === "parsed" ? "privateParsed" : "privateAbstained",
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
