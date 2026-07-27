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

async function sendToOffscreen(message) {
  await ensureOffscreenDocument();
  let lastError;
  for (let attempt = 0; attempt < 20; attempt += 1) {
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

async function startAsr(message) {
  if (!Number.isInteger(message.tabId)) {
    return { ok: false, error: "invalid-capture-request" };
  }
  const config = await getAsrConfig();
  const requestConfig = providerRequestConfig(config);
  if (
    requestConfig.provider === "cloud" &&
    requestConfig.endpoint.startsWith("https://api.openai.com/") &&
    !requestConfig.apiKey
  ) {
    return { ok: false, error: "asr-cloud-key-required" };
  }
  if (requestConfig.provider === "cloud") {
    const hasEndpointPermission = await chrome.permissions.contains({
      origins: [endpointPermissionPattern(requestConfig.endpoint)],
    });
    if (!hasEndpointPermission) {
      return { ok: false, error: "asr-host-permission-required" };
    }
  } else {
    const localStatus = await localWhisperStatus();
    if (
      localStatus?.status !== "ready" ||
      localStatus?.model !== requestConfig.model
    ) {
      return { ok: false, error: "local-whisper-not-deployed" };
    }
  }
  let streamId;
  try {
    streamId = await chrome.tabCapture.getMediaStreamId({
      targetTabId: message.tabId,
    });
  } catch (error) {
    return {
      ok: false,
      error: "tab-audio-capture-failed",
      message: error?.message || String(error),
    };
  }
  const sessionId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  asrState = {
    status: "starting",
    tabId: message.tabId,
    provider: requestConfig.provider,
    sessionId,
    error: null,
  };
  const response = await sendToOffscreen({
    type: "ASR_CAPTURE_START",
    sessionId,
    tabId: message.tabId,
    streamId,
    requestConfig,
  });
  if (!response?.ok) {
    asrState.status = "error";
    asrState.error = response?.error || "capture-start-failed";
  }
  return { ...asrState, ok: Boolean(response?.ok) };
}

async function stopAsr() {
  try {
    if (await hasOffscreenDocument()) {
      await chrome.runtime.sendMessage({
        target: "offscreen",
        type: "ASR_CAPTURE_STOP",
      });
    }
  } finally {
    asrState = {
      status: "stopped",
      tabId: null,
      provider: null,
      sessionId: null,
      error: null,
    };
  }
  return { ok: true, ...asrState };
}

async function currentAsrStatus() {
  if (await hasOffscreenDocument()) {
    try {
      const status = await chrome.runtime.sendMessage({
        target: "offscreen",
        type: "ASR_CAPTURE_STATUS",
      });
      if (status?.status === "running") {
        asrState.status = "running";
        asrState.tabId = status.tabId;
        asrState.provider = status.provider;
        asrState.sessionId = status.sessionId;
      }
    } catch {}
  }
  return { ok: true, ...asrState };
}

async function handleRuntimeMessage(message) {
  if (message?.target === "offscreen") return null;
  switch (message?.type) {
    case "ASR_START":
      return startAsr(message);
    case "ASR_STOP":
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
      if (!asrState.sessionId) {
        asrState.sessionId = message.sessionId;
        asrState.tabId = message.tabId;
        asrState.provider = message.provider;
      }
      if (message.sessionId !== asrState.sessionId) return { ok: false };
      asrState.status = message.status;
      asrState.error = message.error || null;
      return { ok: true };
    case "ASR_TRANSCRIPT":
      if (
        message.sessionId !== asrState.sessionId ||
        !message.text ||
        !Number.isInteger(message.tabId)
      ) {
        return { ok: false };
      }
      await chrome.tabs.sendMessage(message.tabId, {
        action: "audioTranscript",
        text: message.text,
      });
      return { ok: true };
    default:
      return null;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.target === "offscreen") return false;
  handleRuntimeMessage(message)
    .then((response) => sendResponse(response))
    .catch((error) => {
      console.error("[SignBridge] ASR message failed:", error);
      sendResponse({ ok: false, error: error?.message || String(error) });
    });
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === asrState.tabId) stopAsr().catch(() => {});
});

console.log("[SignBridge] Service Worker initialized");
