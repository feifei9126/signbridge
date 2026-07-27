import { transcribeAudio } from "../asr/transcription-client.js";
import {
  deployLocalWhisper,
  getLocalWhisperStatus,
  prepareLocalWhisper,
  transcribeLocalAudio,
} from "../asr/local-whisper.js";
import { decodeAudioBlob, hasAudibleSignal } from "../asr/audio-pcm.js";

let captureStream = null;
let audioContext = null;
let mediaRecorder = null;
let chunkTimer = null;
let session = null;
let queuedAudio = null;
let processingAudio = false;
let consecutiveFailures = 0;
let deploymentTask = null;

function recorderMimeType() {
  const supported = ["audio/webm;codecs=opus", "audio/webm"];
  return (
    supported.find((type) => globalThis.MediaRecorder.isTypeSupported(type)) ||
    ""
  );
}

function sendState(status, extra = {}) {
  if (!session) return;
  chrome.runtime
    .sendMessage({
      target: "worker",
      type: "ASR_CAPTURE_STATE",
      sessionId: session.id,
      tabId: session.tabId,
      provider: session.requestConfig.provider,
      status,
      ...extra,
    })
    .catch(() => {});
}

async function startCapture(message) {
  await stopCapture(false);
  session = {
    id: message.sessionId,
    tabId: message.tabId,
    requestConfig: message.requestConfig,
    running: true,
  };
  sendState("starting");

  try {
    if (session.requestConfig.provider === "local") {
      sendState("loading-model");
      await prepareLocalWhisper(session.requestConfig.model);
    }
    captureStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: message.streamId,
        },
      },
      video: false,
    });

    audioContext = new globalThis.AudioContext();
    const source = audioContext.createMediaStreamSource(captureStream);
    source.connect(audioContext.destination);
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    for (const track of captureStream.getAudioTracks()) {
      track.addEventListener("ended", () => stopCapture(), { once: true });
    }
    sendState("running");
    startRecordingChunk();
    return { ok: true };
  } catch (error) {
    sendState("error", {
      error: error?.code || error?.name || "audio-capture-failed",
      message: error?.message || String(error),
    });
    await stopCapture(false);
    return {
      ok: false,
      error: error?.code || error?.name || "audio-capture-failed",
    };
  }
}

function startRecordingChunk() {
  if (!session?.running || !captureStream?.active) return;
  const chunks = [];
  const mimeType = recorderMimeType();
  mediaRecorder = new globalThis.MediaRecorder(
    captureStream,
    mimeType ? { mimeType } : undefined,
  );
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });
  mediaRecorder.addEventListener(
    "stop",
    () => {
      clearTimeout(chunkTimer);
      chunkTimer = null;
      if (chunks.length > 0) {
        queueAudio(
          new Blob(chunks, { type: mediaRecorder?.mimeType || mimeType }),
        );
      }
      if (session?.running) startRecordingChunk();
    },
    { once: true },
  );
  mediaRecorder.addEventListener(
    "error",
    (event) => {
      sendState("error", {
        error: event.error?.name || "media-recorder-error",
        message: event.error?.message || "MediaRecorder failed",
      });
      stopCapture().catch(() => {});
    },
    { once: true },
  );
  mediaRecorder.start();
  chunkTimer = setTimeout(() => {
    if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  }, session.requestConfig.chunkSeconds * 1000);
}

function queueAudio(blob) {
  if (!session?.running) return;
  queuedAudio = {
    blob,
    sessionId: session.id,
    tabId: session.tabId,
    requestConfig: session.requestConfig,
  };
  if (!processingAudio) processAudioQueue();
}

async function processAudioQueue() {
  processingAudio = true;
  while (queuedAudio) {
    const item = queuedAudio;
    queuedAudio = null;
    if (!session?.running || item.sessionId !== session.id) continue;
    try {
      let result;
      if (item.requestConfig.provider === "local") {
        const samples = await decodeAudioBlob(item.blob, audioContext);
        result = hasAudibleSignal(samples)
          ? await transcribeLocalAudio(samples, item.requestConfig)
          : { text: "" };
      } else {
        result = await transcribeAudio(item.blob, item.requestConfig);
      }
      if (!session?.running || item.sessionId !== session.id) continue;
      consecutiveFailures = 0;
      if (result.text) {
        chrome.runtime
          .sendMessage({
            target: "worker",
            type: "ASR_TRANSCRIPT",
            sessionId: item.sessionId,
            tabId: item.tabId,
            text: result.text,
          })
          .catch(() => {});
      }
      sendState("running");
    } catch (error) {
      if (!session?.running || item.sessionId !== session.id) continue;
      consecutiveFailures += 1;
      sendState("error", {
        error: error?.code || "asr-request-failed",
        message: error?.message || String(error),
      });
      if (consecutiveFailures >= 3) {
        await stopCapture(false);
        break;
      }
    }
  }
  processingAudio = false;
}

async function stopCapture(notify = true) {
  if (session) session.running = false;
  clearTimeout(chunkTimer);
  chunkTimer = null;
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try {
      mediaRecorder.stop();
    } catch {}
  }
  mediaRecorder = null;
  captureStream?.getTracks().forEach((track) => track.stop());
  captureStream = null;
  if (audioContext) {
    try {
      await audioContext.close();
    } catch {}
  }
  audioContext = null;
  queuedAudio = null;
  consecutiveFailures = 0;
  if (notify && session) sendState("stopped");
  session = null;
  return { ok: true };
}

function captureStatus() {
  return {
    ok: true,
    status: session?.running ? "running" : "stopped",
    sessionId: session?.id ?? null,
    tabId: session?.tabId ?? null,
    provider: session?.requestConfig?.provider ?? null,
  };
}

async function startLocalDeployment(model) {
  const current = await getLocalWhisperStatus();
  if (deploymentTask) return { ok: true, ...current };
  deploymentTask = deployLocalWhisper(model)
    .then((state) => {
      chrome.runtime
        .sendMessage({
          target: "worker",
          type: "ASR_LOCAL_DEPLOY_STATE",
          state,
        })
        .catch(() => {});
      return state;
    })
    .finally(() => {
      deploymentTask = null;
    });
  deploymentTask.catch((error) => {
    console.error("[SignBridge] Local Whisper deployment failed:", error);
  });
  return { ok: true, ...(await getLocalWhisperStatus()) };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.target !== "offscreen") return false;
  let operation;
  if (message.type === "ASR_CAPTURE_START") {
    operation = startCapture(message);
  } else if (message.type === "ASR_CAPTURE_STOP") {
    operation = stopCapture();
  } else if (message.type === "ASR_CAPTURE_STATUS") {
    operation = Promise.resolve(captureStatus());
  } else if (message.type === "ASR_LOCAL_DEPLOY") {
    operation = startLocalDeployment(message.model);
  } else if (message.type === "ASR_LOCAL_STATUS") {
    operation = getLocalWhisperStatus().then((state) => ({
      ok: true,
      ...state,
    }));
  } else {
    return false;
  }
  operation.then(sendResponse).catch((error) => {
    sendResponse({ ok: false, error: error?.message || String(error) });
  });
  return true;
});
