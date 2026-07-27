/**
 * SignBridge Page Agent
 * 页面域只捕获字幕；扩展 iframe 负责已授权的语音识别。
 */
import { SubtitleCapturer } from "../utils/subtitle-capturer.js";

if (window.__SIGNBRIDGE_PAGE_AGENT__) {
  console.log("[SB] Duplicate page agent ignored");
} else {
  window.__SIGNBRIDGE_PAGE_AGENT__ = true;

  const state = {
    active: false,
    initialized: false,
    subtitleEl: null,
    lastText: "",
    capturer: null,
    config: {},
  };

  function recognitionLanguage() {
    const language = state.config.sourceLanguage;
    return language && language !== "auto" ? language : "zh-CN";
  }

  function sendToIframe(type, data) {
    window.postMessage(
      { source: "signbridge-page", type, ...(data || {}) },
      "*",
    );
  }

  function showTextOverlay(text) {
    const overlay = document.querySelector("#signbridge-overlay");
    if (!overlay) return;
    if (!state.subtitleEl?.isConnected) {
      state.subtitleEl = document.createElement("div");
      state.subtitleEl.style.cssText =
        "position:absolute;bottom:4px;left:4px;right:4px;padding:3px 6px;background:rgba(0,0,0,0.75);color:#fff;font-size:11px;font-family:sans-serif;text-align:center;border-radius:4px;pointer-events:none;line-height:1.3;max-height:36px;overflow:hidden;z-index:20";
      overlay.appendChild(state.subtitleEl);
    }
    state.subtitleEl.textContent = text || "";
    state.subtitleEl.style.opacity = text ? "1" : "0";
  }

  async function initialize(nextConfig = {}) {
    state.config = { ...state.config, ...nextConfig };
    if (state.initialized) return;
    console.log("[SB] Page agent initializing...");

    const overlay = await new Promise((resolve) => {
      const el = document.querySelector("#signbridge-overlay");
      if (el) {
        resolve(el);
        return;
      }
      let elapsed = 0;
      const t = setInterval(() => {
        elapsed += 100;
        const el = document.querySelector("#signbridge-overlay");
        if (el) {
          clearInterval(t);
          resolve(el);
        } else if (elapsed >= 10000) {
          clearInterval(t);
          resolve(null);
        }
      }, 100);
    });
    if (!overlay) {
      console.error("[SB] Overlay not found");
      return;
    }
    state.initialized = true;

    const loading = document.getElementById("sb-loading");
    if (loading) loading.remove();

    console.log("[SB] ✅ Page agent ready");
  }

  function startTranslation() {
    if (state.active) return;
    state.active = true;
    state.lastText = "";
    showTextOverlay("🔴 翻译中...");
    console.log("[SB] Translation starting...");

    // ===== 字幕捕获 =====
    state.capturer = new SubtitleCapturer({
      language: recognitionLanguage(),
      onSubtitle: (result) => {
        if (!state.active || !result.text) return;
        if (result.text === state.lastText) return;
        state.lastText = result.text;
        // 保留标点但清除多余空白
        const clean = result.text.trim();
        if (clean.length > 0) {
          sendToIframe("SUBTITLE_TEXT", { text: clean });
          showTextOverlay("📝 " + clean.substring(0, 40));
          console.log("[SB] 📝 subtitle:", clean);
        }
      },
    });
    state.capturer.start();

    // 诊断: 打印找到的字幕源
    setTimeout(() => {
      if (state.capturer) {
        const sources = state.capturer.activeSources;
        console.log(
          "[SB] Captured sources:",
          sources.length > 0 ? sources : "none",
        );
        if (sources.length === 0) {
          console.log("[SB] TIP: 请在视频播放器中打开CC字幕");
          showTextOverlay("💡 请打开视频CC字幕");
          setTimeout(() => {
            if (state.active && !state.lastText)
              showTextOverlay("🔴 翻译中...");
          }, 3000);
        }
      }
    }, 2000);

    console.log("[SB] Translation started");
  }

  function stopTranslation() {
    state.active = false;
    if (state.capturer) {
      state.capturer.stop();
      state.capturer = null;
    }
    showTextOverlay("");
    console.log("[SB] Translation stopped");
  }

  window.addEventListener("message", (ev) => {
    if (ev.data?.source !== "signbridge-content") return;
    switch (ev.data.type) {
      case "SIGNBRIDGE_AVATAR_READY":
        initialize(ev.data.config);
        break;
      case "SIGNBRIDGE_TOGGLE":
        state.active ? stopTranslation() : startTranslation();
        break;
      case "SIGNBRIDGE_START":
        startTranslation();
        break;
      case "SIGNBRIDGE_STOP":
        stopTranslation();
        break;
      case "SPEECH_TEXT":
        if (!state.active) startTranslation();
        if (!ev.data.text) break;
        state.lastText = ev.data.text;
        showTextOverlay("🔊 " + ev.data.text.substring(0, 40));
        break;
      case "SIGNBRIDGE_CONFIG":
        state.config = { ...state.config, ...(ev.data.config || {}) };
        break;
    }
  });

  console.log("[SB] Page agent loaded (v6)");
}
