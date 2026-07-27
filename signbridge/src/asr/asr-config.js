const STORAGE_KEY = "signbridge_asr_config";
const LOCAL_DEPLOYMENT_STORAGE_KEY = "signbridge_local_whisper_deployment";
const LOCAL_MODEL_ORIGINS = Object.freeze([
  "https://huggingface.co/*",
  "https://*.huggingface.co/*",
  "https://*.hf.co/*",
  "https://hf-mirror.com/*",
]);

const DEFAULT_ASR_CONFIG = Object.freeze({
  provider: "local",
  localModel: "tiny",
  cloudEndpoint: "https://api.openai.com/v1/audio/transcriptions",
  cloudApiKey: "",
  cloudModel: "whisper-1",
  language: "zh",
  chunkSeconds: 6,
});

function normalizeEndpoint(value, fallback) {
  const candidate = String(value || fallback).trim();
  const url = new URL(candidate);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("asr-endpoint-protocol");
  }
  return url.href;
}

function normalizeAsrConfig(value = {}) {
  const provider = value.provider === "cloud" ? "cloud" : "local";
  const requestedLocalModel = String(value.localModel || "").trim();
  return {
    provider,
    localModel: ["tiny", "base", "small"].includes(requestedLocalModel)
      ? requestedLocalModel
      : DEFAULT_ASR_CONFIG.localModel,
    cloudEndpoint: normalizeEndpoint(
      value.cloudEndpoint,
      DEFAULT_ASR_CONFIG.cloudEndpoint,
    ),
    cloudApiKey: String(value.cloudApiKey || "").trim(),
    cloudModel: String(
      value.cloudModel || DEFAULT_ASR_CONFIG.cloudModel,
    ).trim(),
    language: String(value.language || DEFAULT_ASR_CONFIG.language).trim(),
    chunkSeconds: Math.min(
      15,
      Math.max(
        4,
        Number.parseInt(
          value.chunkSeconds || DEFAULT_ASR_CONFIG.chunkSeconds,
          10,
        ),
      ),
    ),
  };
}

function providerRequestConfig(config) {
  const normalized = normalizeAsrConfig(config);
  if (normalized.provider === "cloud") {
    return {
      provider: "cloud",
      endpoint: normalized.cloudEndpoint,
      apiKey: normalized.cloudApiKey,
      model: normalized.cloudModel,
      language: normalized.language,
      chunkSeconds: normalized.chunkSeconds,
    };
  }
  return {
    provider: "local",
    model: normalized.localModel,
    language: normalized.language,
    chunkSeconds: normalized.chunkSeconds,
  };
}

function endpointPermissionPattern(endpoint) {
  const url = new URL(endpoint);
  return `${url.protocol}//${url.hostname}/*`;
}

async function getAsrConfig(storage = globalThis.chrome?.storage?.local) {
  if (!storage?.get) return { ...DEFAULT_ASR_CONFIG };
  const result = await storage.get(STORAGE_KEY);
  return normalizeAsrConfig(result?.[STORAGE_KEY]);
}

async function setAsrConfig(
  value,
  storage = globalThis.chrome?.storage?.local,
) {
  const config = normalizeAsrConfig(value);
  if (storage?.set) await storage.set({ [STORAGE_KEY]: config });
  return config;
}

export {
  DEFAULT_ASR_CONFIG,
  LOCAL_DEPLOYMENT_STORAGE_KEY,
  LOCAL_MODEL_ORIGINS,
  STORAGE_KEY,
  endpointPermissionPattern,
  getAsrConfig,
  normalizeAsrConfig,
  providerRequestConfig,
  setAsrConfig,
};
