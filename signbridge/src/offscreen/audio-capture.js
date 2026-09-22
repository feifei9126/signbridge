import { transcribeAudio } from "../asr/transcription-client.js";
import {
  deployLocalWhisper,
  getLocalWhisperStatus,
  prepareLocalWhisper,
  transcribeLocalAudio,
} from "../asr/local-whisper.js";
import { decodeAudioBlob, hasAudibleSignal } from "../asr/audio-pcm.js";

let session = null;
let captureRevision = 0;
let queuedAudio = null;
let processingAudio = false;
let deploymentTask = null;

function recorderMimeType() {
  const supported = ["audio/webm;codecs=opus", "audio/webm"];
  return (
    supported.find((type) => globalThis.MediaRecorder.isTypeSupported(type)) ||
    ""
  );
}

function sendState(status, extra = {}, owner = session) {
  if (!owner) return;
  owner.status = status;
  chrome.runtime
    .sendMessage({
      target: "worker",
      type: "ASR_CAPTURE_STATE",
      sessionId: owner.id,
      tabId: owner.tabId,
      provider: owner.requestConfig.provider,
      status,
      ...extra,
    })
    .catch(() => {});
}

function isCurrent(owner) {
  return owner === session && owner.running;
}

function cancelledCapture() {
  return { ok: false, error: "capture-cancelled" };
}

async function startCapture(message) {
  const stopping = stopCapture(false);
  const revision = captureRevision;
  await stopping;
  if (revision !== captureRevision) return cancelledCapture();
  const owner = {
    id: message.sessionId,
    tabId: message.tabId,
    requestConfig: message.requestConfig,
    running: true,
    status: "starting",
    stream: null,
    context: null,
    recorder: null,
    timer: null,
    failures: 0,
    abortController: new globalThis.AbortController(),
  };
  session = owner;
  sendState("starting");

  try {
    if (owner.requestConfig.provider === "local") {
      sendState("loading-model");
      await prepareLocalWhisper(owner.requestConfig.model);
    }
    if (!isCurrent(owner)) return cancelledCapture();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: message.streamId,
        },
      },
      video: false,
    });
    if (!isCurrent(owner)) {
      stream.getTracks().forEach((track) => track.stop());
      return cancelledCapture();
    }
    owner.stream = stream;

    const context = new globalThis.AudioContext();
    owner.context = context;
    const source = context.createMediaStreamSource(stream);
    source.connect(context.destination);
    if (context.state === "suspended") {
      await context.resume();
    }
    if (!isCurrent(owner)) return cancelledCapture();

    for (const track of stream.getAudioTracks()) {
      track.addEventListener(
        "ended",
        () => {
          if (isCurrent(owner)) stopCapture().catch(() => {});
        },
        { once: true },
      );
    }
    sendState("running");
    startRecordingChunk(owner);
    return { ok: true };
  } catch (error) {
    if (!isCurrent(owner)) return cancelledCapture();
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

function startRecordingChunk(owner) {
  if (!isCurrent(owner) || !owner.stream?.active) return;
  const chunks = [];
  const mimeType = recorderMimeType();
  const recorder = new globalThis.MediaRecorder(
    owner.stream,
    mimeType ? { mimeType } : undefined,
  );
  owner.recorder = recorder;
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });
  recorder.addEventListener(
    "stop",
    () => {
      if (!isCurrent(owner) || owner.recorder !== recorder) return;
      clearTimeout(owner.timer);
      owner.timer = null;
      if (chunks.length > 0) {
        queueAudio(
          new Blob(chunks, { type: recorder.mimeType || mimeType }),
          owner,
        );
      }
      startRecordingChunk(owner);
    },
    { once: true },
  );
  recorder.addEventListener(
    "error",
    (event) => {
      if (!isCurrent(owner)) return;
      sendState("error", {
        error: event.error?.name || "media-recorder-error",
        message: event.error?.message || "MediaRecorder failed",
      });
      stopCapture().catch(() => {});
    },
    { once: true },
  );
  recorder.start();
  owner.timer = setTimeout(() => {
    if (isCurrent(owner) && recorder.state === "recording") recorder.stop();
  }, owner.requestConfig.chunkSeconds * 1000);
}

function queueAudio(blob, owner) {
  if (!isCurrent(owner)) return;
  queuedAudio = {
    blob,
    owner,
  };
  if (!processingAudio) processAudioQueue();
}

async function processAudioQueue() {
  processingAudio = true;
  while (queuedAudio) {
    const item = queuedAudio;
    queuedAudio = null;
    const { owner } = item;
    if (!isCurrent(owner)) continue;
    try {
      let result;
      if (owner.requestConfig.provider === "local") {
        const samples = await decodeAudioBlob(item.blob, owner.context);
        if (!isCurrent(owner)) continue;
        result = hasAudibleSignal(samples)
          ? await transcribeLocalAudio(samples, owner.requestConfig)
          : { text: "" };
      } else {
        result = await transcribeAudio(
          item.blob,
          owner.requestConfig,
          globalThis.fetch,
          {
            signal: owner.abortController.signal,
          },
        );
      }
      if (!isCurrent(owner)) continue;
      owner.failures = 0;
      if (result.text) {
        chrome.runtime
          .sendMessage({
            target: "worker",
            type: "ASR_TRANSCRIPT",
            sessionId: owner.id,
            tabId: owner.tabId,
            text: result.text,
          })
          .catch(() => {});
      }
      sendState("running");
    } catch (error) {
      if (!isCurrent(owner)) continue;
      owner.failures += 1;
      sendState("error", {
        error: error?.code || "asr-request-failed",
        message: error?.message || String(error),
      });
      if (owner.failures >= 3) {
        await stopCapture(false);
      }
    }
  }
  processingAudio = false;
}

async function stopCapture(notify = true) {
  captureRevision += 1;
  const owner = session;
  session = null;
  queuedAudio = null;
  if (!owner) return { ok: true };
  owner.running = false;
  owner.abortController.abort();
  clearTimeout(owner.timer);
  owner.timer = null;
  if (owner.recorder && owner.recorder.state !== "inactive") {
    try {
      owner.recorder.stop();
    } catch {}
  }
  owner.recorder = null;
  owner.stream?.getTracks().forEach((track) => track.stop());
  owner.stream = null;
  if (notify) sendState("stopped", {}, owner);
  if (owner.context) {
    try {
      await owner.context.close();
    } catch {}
  }
  owner.context = null;
  return { ok: true };
}

function captureStatus() {
  return {
    ok: true,
    status: session?.status ?? "stopped",
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
