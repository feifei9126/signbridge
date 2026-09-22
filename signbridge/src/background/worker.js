import {
  endpointPermissionPattern,
  getAsrConfig,
  LOCAL_DEPLOYMENT_STORAGE_KEY,
  LOCAL_MODEL_ORIGINS,
  providerRequestConfig,
} from "../asr/asr-config.js";

const OFFSCREEN_PATH = "offscreen/audio-capture.html";

let asrState = {
  status: "stopped",
  tabId: null,
  provider: null,
  sessionId: null,
  error: null,
};
let creatingOffscreen = null;
let asrRevision = 0;

if (chrome.storage.local.setAccessLevel) {
  chrome.storage.local
    .setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" })
    .catch((error) => {
      console.warn(
        "[SignBridge] Could not restrict ASR secret storage:",
        error,
      );
    });
}

chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("popup/index.html") });
  }
});

async function hasOffscreenDocument() {
  const documentUrl = chrome.runtime.getURL(OFFSCREEN_PATH);
  if (chrome.runtime.getContexts) {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ["OFFSCREEN_DOCUMENT"],
      documentUrls: [documentUrl],
    });
    return contexts.length > 0;
  }
  const clients = await globalThis.clients.matchAll();
  return clients.some((client) => client.url === documentUrl);
}

async function ensureOffscreenDocument() {
  if (await hasOffscreenDocument()) return;
  if (!creatingOffscreen) {
    creatingOffscreen = chrome.offscreen
      .createDocument({
        url: OFFSCREEN_PATH,
        reasons: ["USER_MEDIA"],
        justification:
          "Capture the active video tab audio for speech recognition",
      })
      .finally(() => {
        creatingOffscreen = null;
      });
  }
  await creatingOffscreen;
}

async function sendToOffscreen(message, isCurrent = () => true) {
  await ensureOffscreenDocument();
  let lastError;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (!isCurrent()) return { ok: false, error: "capture-cancelled" };
    try {
      return await chrome.runtime.sendMessage({
        target: "offscreen",
        ...message,
      });
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => {
        setTimeout(resolve, 50);
      });
    }
  }
  throw lastError;
}

async function localModelPermissionGranted() {
  return chrome.permissions.contains({ origins: [...LOCAL_MODEL_ORIGINS] });
}

async function localWhisperStatus() {
  const stored = await chrome.storage.local.get(LOCAL_DEPLOYMENT_STORAGE_KEY);
  const persisted = stored?.[LOCAL_DEPLOYMENT_STORAGE_KEY];
  if (!(await hasOffscreenDocument())) {
    return persisted?.status === "ready"
      ? { ok: true, ...persisted }
      : { ok: true, status: "idle", progress: 0 };
  }
  const live = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "ASR_LOCAL_STATUS",
  });
  if (live?.status === "idle" && persisted?.status === "ready") {
    return { ok: true, ...persisted };
  }
  return live;
}

async function saveLocalWhisperState(state) {
  if (!["ready", "error"].includes(state?.status)) return { ok: false };
  await chrome.storage.local.set({
    [LOCAL_DEPLOYMENT_STORAGE_KEY]: state,
  });
  return { ok: true };
}

async function deployLocalWhisper(model) {
  if (!(await localModelPermissionGranted())) {
    return { ok: false, error: "asr-model-permission-required" };
  }
  return sendToOffscreen({ type: "ASR_LOCAL_DEPLOY", model });
}

function stopContentSession(state) {
  if (!state.sessionId || !Number.isInteger(state.tabId)) return;
  chrome.tabs
    .sendMessage(state.tabId, {
      action: "audioSessionStop",
      sessionId: state.sessionId,
    })
    .catch(() => {});
}

async function startAsr(message) {
  if (!Number.isInteger(message.tabId)) {
    return { ok: false, error: "invalid-capture-request" };
  }
  const stopping = stopAsr();
  const revision = asrRevision;
  const sessionId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const state = {
    status: "starting",
    tabId: message.tabId,
    provider: null,
    sessionId,
    error: null,
  };
  asrState = state;
  const isCurrent = () => revision === asrRevision && asrState === state;
  const cancelled = () => ({ ok: false, error: "capture-cancelled" });
  function failed(error) {
    if (!isCurrent()) return cancelled();
    stopContentSession(state);
    asrState = { ...state, status: "error", sessionId: null, error };
    return { ok: false, ...asrState };
  }
  try {
    await stopping;
    if (!isCurrent()) return cancelled();
    const config = await getAsrConfig();
    if (!isCurrent()) return cancelled();
    const requestConfig = providerRequestConfig(config);
    state.provider = requestConfig.provider;
    if (requestConfig.provider === "cloud") {
      if (
        requestConfig.endpoint.startsWith("https://api.openai.com/") &&
        !requestConfig.apiKey
      ) {
        return failed("asr-cloud-key-required");
      }
      const granted = await chrome.permissions.contains({
        origins: [endpointPermissionPattern(requestConfig.endpoint)],
      });
      if (!isCurrent()) return cancelled();
      if (!granted) return failed("asr-host-permission-required");
    } else {
      const localStatus = await localWhisperStatus();
      if (!isCurrent()) return cancelled();
      if (
        localStatus?.status !== "ready" ||
        localStatus?.model !== requestConfig.model
      ) {
        return failed("local-whisper-not-deployed");
      }
    }
    let streamId;
    try {
      streamId = await chrome.tabCapture.getMediaStreamId({
        targetTabId: message.tabId,
      });
    } catch {
      return failed("tab-audio-capture-failed");
    }
    if (!isCurrent()) return cancelled();
    const opened = await chrome.tabs.sendMessage(message.tabId, {
      action: "audioSessionStart",
      sessionId,
    });
    if (!isCurrent()) return cancelled();
    if (!opened?.ok) return failed("capture-cancelled");
    const response = await sendToOffscreen(
      {
        type: "ASR_CAPTURE_START",
        sessionId,
        tabId: message.tabId,
        streamId,
        requestConfig,
      },
      isCurrent,
    );
    if (!isCurrent()) return cancelled();
    if (!response?.ok) return failed(response?.error || "capture-start-failed");
    state.status = "running";
    return { ok: true, ...state };
  } catch (error) {
    return failed(error?.message || "capture-start-failed");
  }
}

async function stopAsr() {
  const revision = ++asrRevision;
  const previous = asrState;
  asrState = {
    status: "stopped",
    tabId: null,
    provider: null,
    sessionId: null,
    error: null,
  };
  stopContentSession(previous);
  if (await hasOffscreenDocument()) {
    if (revision === asrRevision) {
      await chrome.runtime.sendMessage({
        target: "offscreen",
        type: "ASR_CAPTURE_STOP",
      });
    }
  }
  return { ok: true, ...asrState };
}

async function currentAsrStatus() {
  const revision = asrRevision;
  const state = asrState;
  if (await hasOffscreenDocument()) {
    try {
      const status = await chrome.runtime.sendMessage({
        target: "offscreen",
        type: "ASR_CAPTURE_STATUS",
      });
      if (revision !== asrRevision || state !== asrState)
        return { ok: true, ...asrState };
      if (
        status?.sessionId &&
        (status.sessionId === state.sessionId || asrRevision === 0)
      ) {
        asrState.status = status.status;
        asrState.tabId = status.tabId;
        asrState.provider = status.provider;
        asrState.sessionId = status.sessionId;
      } else if (
        status?.status === "stopped" &&
        state.sessionId &&
        state.status !== "starting" &&
        state.status !== "loading-model"
      ) {
        stopContentSession(state);
        asrRevision += 1;
        asrState = {
          status: state.error ? "error" : "stopped",
          tabId: null,
          provider: state.provider,
          sessionId: null,
          error: state.error,
        };
      }
    } catch {}
  }
  return { ok: true, ...asrState };
}

async function handleRuntimeMessage(message, sender) {
  if (message?.target === "offscreen") return null;
  switch (message?.type) {
    case "ASR_START":
      return startAsr(message);
    case "ASR_STOP":
      return stopAsr();
    case "ASR_STOP_TAB":
      if (!Number.isInteger(sender?.tab?.id)) return { ok: false };
      if (asrRevision === 0) await currentAsrStatus();
      if (sender.tab.id !== asrState.tabId) return { ok: true };
      return stopAsr();
    case "ASR_GET_STATUS":
      return currentAsrStatus();
    case "ASR_LOCAL_DEPLOY":
      return deployLocalWhisper(message.model);
    case "ASR_LOCAL_STATUS":
      return localWhisperStatus();
    case "ASR_LOCAL_DEPLOY_STATE":
      return saveLocalWhisperState(message.state);
    case "ASR_CAPTURE_STATE":
      if (!asrState.sessionId && asrRevision === 0) await currentAsrStatus();
      if (
        !asrState.sessionId ||
        message.sessionId !== asrState.sessionId ||
        message.tabId !== asrState.tabId
      )
        return { ok: false };
      if (message.status === "stopped") {
        stopContentSession(asrState);
        asrRevision += 1;
        asrState.sessionId = null;
        asrState.tabId = null;
      }
      asrState.status = message.status;
      asrState.error = message.error || null;
      return { ok: true };
    case "ASR_TRANSCRIPT":
      if (!asrState.sessionId && asrRevision === 0) await currentAsrStatus();
      if (
        !asrState.sessionId ||
        message.sessionId !== asrState.sessionId ||
        message.tabId !== asrState.tabId ||
        !message.text ||
        !Number.isInteger(message.tabId)
      ) {
        return { ok: false };
      }
      await chrome.tabs.sendMessage(message.tabId, {
        action: "audioTranscript",
        text: message.text,
        sessionId: message.sessionId,
      });
      return { ok: true };
    default:
      return null;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target === "offscreen") return false;
  handleRuntimeMessage(message, sender)
    .then((response) => sendResponse(response))
    .catch((error) => {
      console.error("[SignBridge] ASR message failed:", error);
      sendResponse({ ok: false, error: error?.message || String(error) });
    });
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  async function stopClosedTab() {
    if (asrRevision === 0) await currentAsrStatus();
    if (tabId === asrState.tabId) await stopAsr();
  }
  stopClosedTab().catch(() => {});
});

console.log("[SignBridge] Service Worker initialized");
