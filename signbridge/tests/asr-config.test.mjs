import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_ASR_CONFIG,
  endpointPermissionPattern,
  getAsrConfig,
  LOCAL_MODEL_ORIGINS,
  normalizeAsrConfig,
  providerRequestConfig,
  setAsrConfig,
} from "../src/asr/asr-config.js";

test("local model permissions include the automatic mirror fallback", () => {
  assert.equal(LOCAL_MODEL_ORIGINS.includes("https://hf-mirror.com/*"), true);
});

test("ASR config defaults to browser-local Whisper", () => {
  const config = normalizeAsrConfig();
  assert.equal(config.provider, "local");
  assert.equal(config.localModel, DEFAULT_ASR_CONFIG.localModel);
  assert.equal(config.chunkSeconds, 6);
  assert.equal("localEndpoint" in config, false);
});

test("ASR config clamps chunk duration and selects cloud credentials", () => {
  const request = providerRequestConfig({
    provider: "cloud",
    cloudEndpoint: "https://speech.example.test/transcribe",
    cloudApiKey: " secret ",
    cloudModel: "model-a",
    chunkSeconds: 30,
  });
  assert.deepEqual(request, {
    provider: "cloud",
    endpoint: "https://speech.example.test/transcribe",
    apiKey: "secret",
    model: "model-a",
    language: "zh",
    chunkSeconds: 15,
  });
});

test("ASR endpoint permissions are limited to the configured origin", () => {
  assert.equal(
    endpointPermissionPattern("https://speech.example.test:9443/v1/audio"),
    "https://speech.example.test/*",
  );
  assert.equal(
    endpointPermissionPattern("http://speech.example.test:8765/v1/audio"),
    "http://speech.example.test/*",
  );
});

test("ASR config rejects unsupported local model names", () => {
  const request = providerRequestConfig({
    provider: "local",
    localModel: "medium",
  });
  assert.deepEqual(request, {
    provider: "local",
    model: "tiny",
    language: "zh",
    chunkSeconds: 6,
  });
});

test("ASR secrets use the supplied local storage area", async () => {
  let saved;
  const storage = {
    async get() {
      return saved || {};
    },
    async set(value) {
      saved = value;
    },
  };
  await setAsrConfig({ provider: "cloud", cloudApiKey: "key-1" }, storage);
  const config = await getAsrConfig(storage);
  assert.equal(config.cloudApiKey, "key-1");
});
