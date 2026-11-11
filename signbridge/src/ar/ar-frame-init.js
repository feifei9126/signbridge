/**
 * AR 模式页面入口
 * 由 content script 以全屏 iframe 注入，负责启动摄像头、渲染虚拟人并接收播放指令
 */

import { setLocale, t } from "../i18n/locales.js";
import {
  startARMode,
  stopARMode,
  playSignLanguageInAR,
} from "./ar-controller.js";

const AR_MESSAGE_SOURCE = "signbridge-ar";

const container = document.getElementById("ar-container");
const statusEl = document.getElementById("ar-status");
const btnTest = document.getElementById("btnTest");
const btnExit = document.getElementById("btnExit");

let running = false;

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

function applyTranslations() {
  if (btnTest) btnTest.textContent = t("arTestSign");
  if (btnExit) btnExit.textContent = t("arExit");
  if (statusEl && !running) setStatus(t("arInitializing"));
}

function notifyParent(type, payload = {}) {
  try {
    window.parent?.postMessage(
      { source: AR_MESSAGE_SOURCE, type, ...payload },
      "*",
    );
  } catch (error) {
    console.warn("[AR Frame] 父页面通知失败:", error);
  }
}

function requestExit() {
  try {
    stopARMode();
  } catch (error) {
    console.warn("[AR Frame] 停止失败:", error);
  }
  running = false;
  notifyParent("ar-exit");
}

async function play(text) {
  if (!running) return false;
  setStatus(t("arPlaying", { text }));
  await playSignLanguageInAR(text);
  setStatus(t("arRunningShort"));
  return true;
}

async function init() {
  applyTranslations();
  setStatus(t("arStartingCamera"));
  try {
    await startARMode(container);
    running = true;
    setStatus(t("arRunningShort"));
    notifyParent("ar-ready");
  } catch (error) {
    const denied =
      /permission|denied|notallowed/i.test(error?.name || "") ||
      /permission|denied|NotAllowed/i.test(error?.message || "");
    setStatus(
      t(denied ? "arPermissionDenied" : "arInitFailed", {
        detail: error?.message || String(error),
      }),
    );
    notifyParent("ar-error", {
      error: error?.message || String(error),
      denied,
    });
  }
}

window.addEventListener("message", async (event) => {
  const data = event.data;
  if (!data || data.source !== "signbridge-page") return;
  const type = data.type || data.action;
  if (type === "PLAY_SIGN") {
    try {
      await play(data.text || "");
      notifyParent("ar-played", { ok: true });
    } catch (error) {
      setStatus(t("arPlayFailed", { detail: error?.message || String(error) }));
      notifyParent("ar-played", { ok: false, error: error?.message });
    }
  } else if (type === "AR_EXIT") {
    requestExit();
  }
});

btnTest?.addEventListener("click", () => {
  play("你好").catch((error) => {
    setStatus(t("arPlayFailed", { detail: error?.message || String(error) }));
  });
});

btnExit?.addEventListener("click", requestExit);

window.addEventListener("beforeunload", () => {
  try {
    stopARMode();
  } catch {}
});

async function bootstrap() {
  try {
    const { signbridge_config: config } =
      await chrome.storage.sync.get("signbridge_config");
    if (config?.uiLocale && config.uiLocale !== "auto") {
      setLocale(config.uiLocale);
    }
  } catch (error) {
    console.warn("[AR Frame] 读取语言配置失败:", error);
  }
  applyTranslations();
  await init();
}

bootstrap();
