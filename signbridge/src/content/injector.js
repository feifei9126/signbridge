(() => {
  "use strict";

  if (window.__SIGNBRIDGE_CONTENT_SCRIPT__) {
    console.log("[SB-CS] Duplicate content script ignored");
    return;
  }
  window.__SIGNBRIDGE_CONTENT_SCRIPT__ = true;
  console.log("[SB-CS] Content script loaded");

  const VIDEO_SITES = [
    "bilibili.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "netflix.com",
    "primevideo.com",
    "iqiyi.com",
    "youku.com",
    "tudou.com",
    "v.qq.com",
    "ixigua.com",
    "douyin.com",
    "kuaishou.com",
    "ted.com",
    "coursera.org",
    "udemy.com",
  ];

  let container = null;
  let iframe = null;
  let config = {};
  let active = true;
  let iframeReady = false;
  let injectPromise = null;
  let resolveIframeLoaded = null;
  const pendingIframeMessages = [];

  function isVideoSite() {
    const host = window.location.hostname;
    return (
      Boolean(document.querySelector("video")) ||
      VIDEO_SITES.some((site) => host === site || host.endsWith(`.${site}`)) ||
      Boolean(
        document.querySelector(
          ".video-player,.player-container,[class*='video-player']",
        ),
      )
    );
  }

  async function init() {
    try {
      const result = await chrome.storage.sync.get("signbridge_config");
      config = result.signbridge_config || {};
      active = config.enabled ?? true;
    } catch (error) {
      console.warn("[SB-CS] Config load failed:", error.message);
    }

    chrome.runtime.onMessage.addListener(handleRuntimeMessage);
    window.addEventListener("message", onWindowMessage);

    if (isVideoSite()) await ensureInjected();
  }

  function ensureInjected() {
    if (container?.isConnected && iframe?.isConnected) {
      return Promise.resolve();
    }
    if (injectPromise) return injectPromise;
    injectPromise = inject().finally(() => {
      injectPromise = null;
    });
    return injectPromise;
  }

  async function inject() {
    if (!document.body) {
      await new Promise((resolve) => {
        document.addEventListener("DOMContentLoaded", resolve, { once: true });
      });
    }

    const existing = document.getElementById("signbridge-overlay");
    if (existing) existing.remove();

    const size = clamp(Number(config.avatarSize) || 260, 120, 420);
    const position = config.avatarPosition || "bottom-right";
    const positionStyles = {
      "bottom-right": "bottom:16px;right:16px;",
      "bottom-left": "bottom:16px;left:16px;",
      "top-right": "top:16px;right:16px;",
      "top-left": "top:16px;left:16px;",
    };

    container = document.createElement("div");
    container.id = "signbridge-overlay";
    container.style.cssText =
      `position:fixed;z-index:2147483647;width:${size}px;height:${size * 1.2}px;` +
      "border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.3);user-select:none;" +
      (positionStyles[position] || positionStyles["bottom-right"]);

    const loading = document.createElement("div");
    loading.id = "sb-loading";
    loading.className = "signbridge-loading";
    loading.textContent = "加载中...";
    container.appendChild(loading);

    const dragHandle = document.createElement("div");
    dragHandle.id = "sb-window-drag-handle";
    dragHandle.title = "拖动窗口";
    dragHandle.style.cssText =
      "position:absolute;top:0;left:0;right:30px;height:24px;cursor:grab;z-index:20;";
    setupWindowDrag(dragHandle);
    container.appendChild(dragHandle);

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.textContent = "×";
    closeButton.title = "关闭虚拟人";
    closeButton.setAttribute("aria-label", "关闭虚拟人");
    closeButton.style.cssText =
      "position:absolute;top:3px;right:5px;width:22px;height:22px;border:0;border-radius:50%;" +
      "color:#fff;background:rgba(0,0,0,0.55);cursor:pointer;font-size:16px;line-height:20px;z-index:30;";
    closeButton.addEventListener("click", removeOverlay);
    container.appendChild(closeButton);

    iframe = document.createElement("iframe");
    iframe.src = chrome.runtime.getURL("avatar/avatar-frame.html");
    iframe.title = "SignBridge 手语虚拟人";
    iframe.style.cssText =
      "width:100%;height:100%;border:none;background:transparent;display:block;";
    iframe.setAttribute("allow", "microphone; autoplay");
    container.appendChild(iframe);
    document.body.appendChild(container);

    iframeReady = false;
    const loaded = new Promise((resolve) => {
      resolveIframeLoaded = resolve;
    });
    await Promise.race([
      loaded,
      new Promise((resolve) => {
        setTimeout(resolve, 10000);
      }),
    ]);

    if (!iframe?.isConnected) return;
    injectPageAgent();
    postMessageToIframe("INIT", {
      modelUrl: chrome.runtime.getURL("avatar/model.glb"),
    });
    console.log("[SB-CS] INIT sent to iframe");
  }

  function injectPageAgent() {
    if (document.getElementById("signbridge-page-agent")) return;
    const script = document.createElement("script");
    script.id = "signbridge-page-agent";
    script.src = chrome.runtime.getURL("avatar/page-agent.js");
    script.onload = () => console.log("[SB-CS] Page agent injected");
    script.onerror = () => console.error("[SB-CS] Page agent failed to load");
    document.documentElement.appendChild(script);
  }

  function setupWindowDrag(handle) {
    handle.addEventListener("pointerdown", (event) => {
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const startLeft = rect.left;
      const startTop = rect.top;

      container.style.bottom = "auto";
      container.style.right = "auto";
      container.style.left = `${startLeft}px`;
      container.style.top = `${startTop}px`;
      handle.style.cursor = "grabbing";
      handle.setPointerCapture(event.pointerId);

      const move = (nextEvent) => {
        const maxLeft = Math.max(0, window.innerWidth - rect.width);
        const maxTop = Math.max(0, window.innerHeight - rect.height);
        container.style.left = `${clamp(startLeft + nextEvent.clientX - startX, 0, maxLeft)}px`;
        container.style.top = `${clamp(startTop + nextEvent.clientY - startY, 0, maxTop)}px`;
      };
      const stop = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        handle.style.cursor = "grab";
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
      event.preventDefault();
    });
  }

  function removeOverlay() {
    postMessageToPage("SIGNBRIDGE_STOP");
    active = false;
    container?.remove();
    container = null;
    iframe = null;
    iframeReady = false;
    resolveIframeLoaded = null;
    pendingIframeMessages.length = 0;
  }

  function postMessageToPage(type, data) {
    window.postMessage(
      { source: "signbridge-content", type, ...(data || {}) },
      "*",
    );
  }

  function postMessageToIframe(type, data) {
    if (!iframe?.contentWindow) return;
    if (!iframeReady && type !== "INIT" && type !== "RESIZE") {
      pendingIframeMessages.push({ type, data });
      return;
    }
    iframe.contentWindow.postMessage(
      { source: "signbridge-page", type, ...(data || {}) },
      "*",
    );
  }

  function flushIframeMessages() {
    while (pendingIframeMessages.length > 0) {
      const message = pendingIframeMessages.shift();
      postMessageToIframe(message.type, message.data);
    }
  }

  function onWindowMessage(event) {
    const message = event.data;
    if (!message) return;

    if (
      event.source === iframe?.contentWindow &&
      message.source === "signbridge-iframe"
    ) {
      if (message.type === "LOADED") {
        resolveIframeLoaded?.();
        resolveIframeLoaded = null;
      } else if (message.type === "READY") {
        iframeReady = true;
        document.getElementById("sb-loading")?.remove();
        flushIframeMessages();
        postMessageToPage("SIGNBRIDGE_AVATAR_READY", { config });
        if (active) postMessageToPage("SIGNBRIDGE_START");
        console.log("[SB-CS] Avatar ready");
      } else if (message.type === "ERROR") {
        showLoadError(message.message || "虚拟人加载失败");
      }
      return;
    }

    if (
      event.source === window &&
      message.source === "signbridge-page" &&
      (message.type === "SUBTITLE_CAPTURED" || message.type === "SUBTITLE_TEXT")
    ) {
      postMessageToIframe("SUBTITLE_TEXT", { text: message.text });
    }
  }

  function showLoadError(message) {
    const loading = document.getElementById("sb-loading");
    if (!loading) return;
    loading.className = "signbridge-error";
    loading.textContent = message;
  }

  function handleRuntimeMessage(message, _sender, sendResponse) {
    handleRuntimeMessageAsync(message)
      .then((response) => sendResponse(response))
      .catch((error) => {
        console.error("[SB-CS] Message failed:", error);
        sendResponse({ ok: false, error: error.message });
      });
    return true;
  }

  async function handleRuntimeMessageAsync(message) {
    const action = message.action || message.type;

    if (action === "toggle" || action === "TOGGLE") {
      if (!container) {
        await ensureInjected();
      } else {
        container.style.display =
          container.style.display === "none" ? "block" : "none";
      }
    } else if (action === "start" || action === "SIGNBRIDGE_START") {
      active = true;
      await ensureInjected();
      if (iframeReady) postMessageToPage("SIGNBRIDGE_START");
    } else if (action === "stop" || action === "SIGNBRIDGE_STOP") {
      active = false;
      postMessageToPage("SIGNBRIDGE_STOP");
    } else if (action === "micOn" || action === "micOff") {
      await ensureInjected();
      postMessageToPage(action === "micOn" ? "MIC_ENABLE" : "MIC_DISABLE");
    } else if (action === "sendText" || action === "SEND_TEXT") {
      await ensureInjected();
      if (message.text) {
        postMessageToIframe("SUBTITLE_TEXT", { text: message.text });
      }
    } else if (action === "updateConfig" || action === "SET_CONFIG") {
      updateConfig(message.config || {});
    }

    return { ok: true, active, ready: iframeReady };
  }

  function updateConfig(updates) {
    config = { ...config, ...updates };
    postMessageToPage("SIGNBRIDGE_CONFIG", { config });
    if (!container || !updates.avatarSize) return;
    const size = clamp(Number(updates.avatarSize), 120, 420);
    container.style.width = `${size}px`;
    container.style.height = `${size * 1.2}px`;
    postMessageToIframe("RESIZE", {
      width: size,
      height: Math.round(size * 1.2),
    });
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  init().catch((error) => console.error("[SB-CS] Init failed:", error));
})();
