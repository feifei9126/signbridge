(() => {
  // src/content/injector.js — Multi-site support
  console.log("[SB-CS] Content script loaded");
  (function () {
    "use strict";
    let container = null,
      iframe = null,
      injected = false,
      config = {},
      active = false;

    // Video site patterns — only show overlay on these
    const VIDEO_SITES = [
      "bilibili.com",
      "youtube.com",
      "youtu.be",
      "vimeo.com",
      "dailymotion.com",
      "twitch.tv",
      "netflix.com",
      "primevideo.com",
      "amazon.com/video",
      "iqiyi.com",
      "youku.com",
      "tudou.com",
      "qq.com/video",
      "ixigua.com",
      "douyin.com",
      "kuaishou.com",
      "ted.com",
      "coursera.org",
      "udemy.com",
      "video.",
      "tv.",
      "live.",
      "watch.",
    ];
    function isVideoSite() {
      const host = window.location.hostname;
      const path = window.location.pathname;
      // Any page with a <video> tag
      if (document.querySelector("video")) return true;
      // Check known video site patterns
      for (const site of VIDEO_SITES) {
        if (host.includes(site) || window.location.href.includes(site))
          return true;
      }
      // Check for common video player indicators
      if (
        document.querySelector(
          ".video-player,.player-container,[class*='player']",
        )
      )
        return true;
      return false;
    }

    async function init() {
      if (!isVideoSite()) {
        console.log("[SB-CS] Not a video site, skipping");
        return;
      }
      if (document.getElementById("signbridge-overlay")) return;
      try {
        const res = await chrome.storage.sync.get("signbridge_config");
        config = res.signbridge_config || {};
      } catch (e) {}
      chrome.runtime.onMessage.addListener(handleRuntimeMessage);
      await inject();
    }
    async function inject() {
      if (injected) return;
      injected = true;
      const size = config.avatarSize || 280;
      const pos = config.avatarPosition || "bottom-right";
      const posMap = {
        "bottom-right": "bottom:16px;right:16px;",
        "bottom-left": "bottom:16px;left:16px;",
        "top-right": "top:16px;right:16px;",
        "top-left": "top:16px;left:16px;",
      };
      const c = document.createElement("div");
      c.id = "signbridge-overlay";
      c.style.cssText =
        "position:fixed;z-index:2147483647;width:" +
        size +
        "px;height:" +
        size * 1.2 +
        "px;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.3);cursor:grab;user-select:none;" +
        (posMap[pos] || "bottom:16px;right:16px;");
      c.innerHTML =
        '<div id="sb-loading" style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;background:rgba(26,26,46,0.95);flex-direction:column;gap:8px;"><div style="width:28px;height:28px;border:3px solid rgba(79,70,229,0.3);border-top-color:#4f46e5;border-radius:50%;animation:sbSpin 0.8s linear infinite;"></div><span style="font-size:11px;color:#a0a0cc">加载中...</span></div>';
      document.body.appendChild(c);
      const closeBtn = document.createElement("div");
      closeBtn.textContent = "×";
      closeBtn.style.cssText =
        "position:absolute;top:2px;right:6px;width:20px;height:20px;line-height:20px;text-align:center;color:#fff;background:rgba(0,0,0,0.5);border-radius:50%;cursor:pointer;font-size:14px;z-index:20;";
      closeBtn.addEventListener("click", () => {
        const el = document.getElementById("signbridge-overlay");
        if (el) el.remove();
        if (container) container = null;
        injected = false;
      });
      c.appendChild(closeBtn);
      const dh = document.createElement("div");
      dh.style.cssText =
        "position:absolute;top:0;left:0;right:0;height:20px;cursor:grab;z-index:10;";
      dh.onpointerdown = (e) => {
        const r = c.getBoundingClientRect(),
          sx = e.clientX,
          sy = e.clientY,
          sl = r.left,
          st = r.top;
        c.style.bottom = "auto";
        c.style.right = "auto";
        c.style.left = sl + "px";
        c.style.top = st + "px";
        c.style.cursor = "grabbing";
        const mv = (e2) => {
          c.style.left = sl + e2.clientX - sx + "px";
          c.style.top = st + e2.clientY - sy + "px";
        };
        const up = () => {
          document.removeEventListener("pointermove", mv);
          document.removeEventListener("pointerup", up);
          c.style.cursor = "grab";
        };
        document.addEventListener("pointermove", mv);
        document.addEventListener("pointerup", up);
      };
      c.appendChild(dh);
      const st = document.createElement("style");
      st.textContent = "@keyframes sbSpin{to{transform:rotate(360deg)}}";
      document.head.appendChild(st);
      container = c;
      const frameUrl = chrome.runtime.getURL("avatar/avatar-frame.html");
      const f = document.createElement("iframe");
      f.src = frameUrl;
      f.style.cssText =
        "width:100%;height:100%;border:none;background:transparent;";
      f.setAttribute("allow", "microphone; autoplay");
      c.querySelector("#sb-loading")?.after(f);
      iframe = f;
      await new Promise((resolve) => {
        const handler = (e) => {
          if (
            e.data?.source === "signbridge-iframe" &&
            e.data.type === "LOADED"
          ) {
            window.removeEventListener("message", handler);
            resolve();
          }
        };
        window.addEventListener("message", handler);
        setTimeout(resolve, 10000);
      });
      const modelUrl = chrome.runtime.getURL("avatar/model.glb");
      postMessageToIframe("INIT", { modelUrl });
      console.log("[SB-CS] INIT sent to iframe");
      const agentUrl = chrome.runtime.getURL("avatar/page-agent.js");
      const script = document.createElement("script");
      script.src = agentUrl;
      script.onload = () => console.log("[SB-CS] page-agent injected");
      document.body.appendChild(script);
      setTimeout(() => {
        postMessageToPage("SIGNBRIDGE_AVATAR_READY", { config });
        console.log("[SB-CS] AVATAR_READY sent");
        setTimeout(() => {
          postMessageToPage("SIGNBRIDGE_START");
          console.log("[SB-CS] SIGNBRIDGE_START sent");
        }, 500);
      }, 1500);
      setupDrag(c);
      window.addEventListener("message", onMessage);
    }
    function setupDrag(c) {
      let dragging = false,
        startX,
        startY,
        startLeft,
        startTop;
      c.addEventListener("pointerdown", (e) => {
        if (e.target.tagName === "BUTTON") return;
        if (e.target.closest && e.target.closest("#sb-3d-ctrl")) return;
        dragging = true;
        c.setPointerCapture(e.pointerId);
        startX = e.clientX;
        startY = e.clientY;
        const r = c.getBoundingClientRect();
        startLeft = r.left;
        startTop = r.top;
        c.style.cursor = "grabbing";
        c.style.bottom = "auto";
        c.style.right = "auto";
        c.style.left = startLeft + "px";
        c.style.top = startTop + "px";
        e.preventDefault();
      });
      c.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        c.style.left = startLeft + e.clientX - startX + "px";
        c.style.top = startTop + e.clientY - startY + "px";
      });
      c.addEventListener("pointerup", () => {
        dragging = false;
        c.style.cursor = "grab";
      });
      c.addEventListener("pointerleave", () => {
        if (!dragging) c.style.cursor = "grab";
      });
    }
    function postMessageToPage(type, data) {
      window.postMessage(
        { source: "signbridge-content", type, ...(data || {}) },
        "*",
      );
    }
    function postMessageToIframe(type, data) {
      if (iframe) {
        try {
          iframe.contentWindow.postMessage(
            { source: "signbridge-page", type, ...(data || {}) },
            "*",
          );
        } catch (ex) {}
      }
    }
    function onMessage(e) {
      if (!e.data) return;
      if (
        e.data.source === "signbridge-iframe" &&
        e.data.type === "SUBTITLE_TEXT"
      ) {
        postMessageToIframe("SUBTITLE_TEXT", { text: e.data.text });
        return;
      }
      if (e.data.source === "signbridge-page") {
        if (
          e.data.type === "SUBTITLE_CAPTURED" ||
          e.data.type === "SUBTITLE_TEXT"
        ) {
          postMessageToIframe("SUBTITLE_TEXT", { text: e.data.text });
        }
      }
    }
    function handleRuntimeMessage(msg, sender, sendResponse) {
      // Support both popup format (action) and legacy format (type)
      const action = msg.action || msg.type;

      if (action === "toggle" || action === "TOGGLE") {
        if (container) {
          container.style.display =
            container.style.display === "none" ? "block" : "none";
        } else {
          inject();
        }
      }

      if (action === "start" || action === "SIGNBRIDGE_START") {
        postMessageToPage("SIGNBRIDGE_START");
      }

      if (action === "stop" || action === "SIGNBRIDGE_STOP") {
        postMessageToPage("SIGNBRIDGE_STOP");
      }

      if (action === "micOn" || action === "micOff") {
        postMessageToPage(action === "micOn" ? "MIC_ENABLE" : "MIC_DISABLE");
      }

      if (action === "sendText" || action === "SEND_TEXT") {
        if (msg.text) {
          postMessageToIframe("SUBTITLE_TEXT", { text: msg.text });
        }
      }

      if (action === "getStatus" || action === "GET_STATUS") {
        sendResponse?.({ active: active });
        return true; // keep channel open for async response
      }

      if (action === "updateConfig" || action === "SET_CONFIG") {
        const cfg = msg.config || {};
        config = { ...config, ...cfg };
        if (container && cfg.avatarSize) {
          const newSize = cfg.avatarSize;
          container.style.width = newSize + "px";
          container.style.height = newSize * 1.2 + "px";
          postMessageToIframe("RESIZE", {
            width: newSize,
            height: Math.round(newSize * 1.2),
          });
        }
      }

      sendResponse?.({ ok: true });
    }
    init();
  })();
})();
