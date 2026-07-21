/**
 * SignBridge Page Agent v6
 * 双重识别: SpeechRecognition(iframe) + SubtitleCapturer(页面)
 * 增加: 启动诊断日志
 */
import { SubtitleCapturer } from "../utils/subtitle-capturer.js";
import { SpeechRecognizer } from "../utils/speech-recognizer.js";

const state = {
  active: false,
  initialized: false,
  subtitleEl: null,
  lastText: "",
  recognizer: null,
  capturer: null,
};

function sendToIframe(type, data) {
  window.postMessage({ source: "signbridge-page", type, ...(data || {}) }, "*");
}

function showTextOverlay(text) {
  const overlay = document.querySelector("#signbridge-overlay");
  if (!overlay) return;
  if (!state.subtitleEl) {
    state.subtitleEl = document.createElement("div");
    state.subtitleEl.style.cssText =
      "position:absolute;bottom:4px;left:4px;right:4px;padding:3px 6px;background:rgba(0,0,0,0.75);color:#fff;font-size:11px;font-family:sans-serif;text-align:center;border-radius:4px;pointer-events:none;line-height:1.3;max-height:36px;overflow:hidden;z-index:20";
    overlay.appendChild(state.subtitleEl);
  }
  state.subtitleEl.textContent = text || "";
  state.subtitleEl.style.opacity = text ? "1" : "0";
}

async function initialize(config) {
  if (state.initialized) return;
  state.initialized = true;
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
    language: "zh-CN",
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
        console.log("[SB] TIP: 请在B站视频上手动打开CC字幕");
        showTextOverlay("💡 请打开B站CC字幕");
        setTimeout(() => {
          if (!state.lastText) showTextOverlay("🔴 翻译中...");
        }, 3000);
      }
    }
  }, 2000);

  // ===== 语音识别 (在 iframe 里, 不在这里重复) =====
  // 只做后备 SpeechRecognition
  state.recognizer = new SpeechRecognizer({
    language: "zh-CN",
    interimResults: false,
    onResult: (result) => {
      if (!state.active || !result.isFinal || !result.text) return;
      if (result.text === state.lastText) return;
      state.lastText = result.text;
      sendToIframe("SUBTITLE_TEXT", { text: result.text });
      showTextOverlay("🎤 " + result.text.substring(0, 40));
    },
    onError: () => {},
    onStateChange: (s) => {
      if (s === "demo") {
        console.log("[SB] Speech demo mode (no mic)");
        showTextOverlay("💡 请打开B站CC字幕或授权麦克风");
        setTimeout(() => {
          if (!state.lastText) showTextOverlay("🔴 翻译中...");
        }, 3000);
      }
    },
  });
  state.recognizer.start().catch(() => {});

  console.log("[SB] Translation started");
}

function stopTranslation() {
  state.active = false;
  if (state.recognizer) {
    state.recognizer.stop();
    state.recognizer = null;
  }
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
    case "MIC_ENABLE":
      if (state.recognizer) {
        try {
          state.recognizer.start();
        } catch (e) {}
        console.log("[SB] Mic enabled");
      }
      break;
    case "MIC_DISABLE":
      if (state.recognizer) {
        try {
          state.recognizer.stop();
        } catch (e) {}
        console.log("[SB] Mic disabled");
      }
      break;
    case "SPEECH_STATUS":
      // 来自 iframe 的状态反馈
      if (ev.data.status === "denied" || ev.data.status === "unavailable") {
        console.log("[SB] iframe mic:", ev.data.status);
      }
      break;
  }
});

console.log("[SB] Page agent loaded (v6)");
