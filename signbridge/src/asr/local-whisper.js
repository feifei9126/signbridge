import { env, pipeline } from "@huggingface/transformers";

const LOCAL_WHISPER_MODELS = Object.freeze({
  tiny: "Xenova/whisper-tiny",
  base: "Xenova/whisper-base",
  small: "Xenova/whisper-small",
});
const MODEL_HOSTS = Object.freeze([
  "https://huggingface.co/",
  "https://hf-mirror.com/",
]);

let configured = false;
let currentModel = null;
let transcriber = null;
let transcriberPromise = null;
let deploymentState = null;

function normalizeLocalModel(model) {
  return Object.hasOwn(LOCAL_WHISPER_MODELS, model) ? model : "tiny";
}

function preferredModelHosts(language = navigator.language) {
  return String(language).toLowerCase().startsWith("zh")
    ? [MODEL_HOSTS[1], MODEL_HOSTS[0]]
    : [...MODEL_HOSTS];
}

function configureRuntime() {
  if (configured) return;
  env.allowLocalModels = false;
  env.allowRemoteModels = true;
  env.useBrowserCache = true;
  env.backends.onnx.wasm.wasmPaths = chrome.runtime.getURL("asr/");
  env.backends.onnx.wasm.numThreads = 1;
  configured = true;
}

function idleState(model = "tiny") {
  return {
    status: "idle",
    model: normalizeLocalModel(model),
    progress: 0,
    file: "",
    error: null,
    updatedAt: Date.now(),
  };
}

function readDeploymentState() {
  if (deploymentState) return { ...deploymentState };
  deploymentState = idleState();
  return { ...deploymentState };
}

function updateDeploymentState(changes) {
  const current = readDeploymentState();
  deploymentState = {
    ...current,
    ...changes,
    updatedAt: Date.now(),
  };
  return { ...deploymentState };
}

function progressValue(event) {
  const value = Number(event?.progress);
  return Number.isFinite(value)
    ? Math.min(99, Math.max(0, Math.round(value)))
    : 0;
}

async function releaseTranscriber() {
  if (transcriber?.dispose) await transcriber.dispose();
  transcriber = null;
  transcriberPromise = null;
  currentModel = null;
}

async function prepareLocalWhisper(model, onProgress = () => {}) {
  configureRuntime();
  const normalizedModel = normalizeLocalModel(model);
  if (transcriber && currentModel === normalizedModel) return transcriber;
  if (transcriberPromise && currentModel === normalizedModel) {
    return transcriberPromise;
  }
  if (currentModel && currentModel !== normalizedModel) {
    await releaseTranscriber();
  }

  currentModel = normalizedModel;
  transcriberPromise = (async () => {
    let lastError;
    for (const remoteHost of preferredModelHosts()) {
      try {
        env.remoteHost = remoteHost;
        const instance = await pipeline(
          "automatic-speech-recognition",
          LOCAL_WHISPER_MODELS[normalizedModel],
          {
            quantized: true,
            progress_callback: (event) => {
              const progress = progressValue(event);
              const file = String(event?.file || "");
              onProgress({
                progress,
                file,
                status: event?.status || "downloading",
              });
            },
          },
        );
        transcriber = instance;
        return instance;
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  })().catch((error) => {
    transcriberPromise = null;
    currentModel = null;
    throw error;
  });
  return transcriberPromise;
}

async function deployLocalWhisper(model, onProgress = () => {}) {
  const normalizedModel = normalizeLocalModel(model);
  updateDeploymentState({
    status: "downloading",
    model: normalizedModel,
    progress: 0,
    file: "",
    error: null,
  });
  try {
    await prepareLocalWhisper(normalizedModel, (progress) => {
      updateDeploymentState({
        status: "downloading",
        model: normalizedModel,
        progress: progress.progress,
        file: progress.file,
        error: null,
      });
      onProgress(progress);
    });
    return updateDeploymentState({
      status: "ready",
      model: normalizedModel,
      progress: 100,
      file: "",
      error: null,
    });
  } catch (error) {
    updateDeploymentState({
      status: "error",
      model: normalizedModel,
      error: error?.message || String(error),
    });
    throw error;
  }
}

async function getLocalWhisperStatus() {
  return readDeploymentState();
}

async function transcribeLocalAudio(samples, requestConfig) {
  const model = normalizeLocalModel(requestConfig.model);
  const instance = await prepareLocalWhisper(model);
  const options = { task: "transcribe" };
  if (requestConfig.language && requestConfig.language !== "auto") {
    options.language = requestConfig.language;
  }
  const result = await instance(samples, options);
  return { text: String(result?.text || "").trim() };
}

export {
  LOCAL_WHISPER_MODELS,
  deployLocalWhisper,
  getLocalWhisperStatus,
  normalizeLocalModel,
  preferredModelHosts,
  prepareLocalWhisper,
  transcribeLocalAudio,
};
