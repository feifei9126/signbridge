import assert from "node:assert/strict";
import test from "node:test";

import {
  bundleRuntime,
  deferred,
  flushTasks,
  runRuntime,
} from "./helpers/runtime-harness.mjs";

const code = await bundleRuntime("../../src/background/worker.js", {
  "../asr/asr-config.js": [
    "endpointPermissionPattern",
    "getAsrConfig",
    "LOCAL_DEPLOYMENT_STORAGE_KEY",
    "LOCAL_MODEL_ORIGINS",
    "providerRequestConfig",
  ],
});

function workerHarness(overrides = {}) {
  let listener;
  let tabRemoved;
  let offscreenStatus = {
    ok: true,
    status: "stopped",
    sessionId: null,
    tabId: null,
  };
  const sent = [];
  const tabMessages = [];
  runRuntime(code, {
    testDependencies: {
      getAsrConfig: overrides.getAsrConfig || (async () => ({})),
      providerRequestConfig: () => ({
        provider: "cloud",
        endpoint: "https://asr.example.test/v1/audio/transcriptions",
      }),
      endpointPermissionPattern: () => "https://asr.example.test/*",
    },
    chrome: {
      storage: { local: {} },
      permissions: { contains: async () => true },
      runtime: {
        getURL: (name) => `chrome-extension://test/${name}`,
        getContexts: async () => [{}],
        onInstalled: { addListener() {} },
        onMessage: { addListener: (callback) => (listener = callback) },
        sendMessage: async (message) => {
          sent.push(message);
          if (overrides.sendOffscreen) {
            const response = await overrides.sendOffscreen(message);
            if (response) return response;
          }
          if (message.type === "ASR_CAPTURE_START") {
            offscreenStatus = {
              ok: true,
              status: "running",
              sessionId: message.sessionId,
              tabId: message.tabId,
              provider: "cloud",
            };
          }
          if (message.type === "ASR_CAPTURE_STOP")
            offscreenStatus = {
              ok: true,
              status: "stopped",
              sessionId: null,
              tabId: null,
            };
          return message.type === "ASR_CAPTURE_STATUS"
            ? offscreenStatus
            : { ok: true };
        },
      },
      tabCapture: {
        getMediaStreamId: overrides.getMediaStreamId || (async () => "stream"),
      },
      tabs: {
        onRemoved: { addListener: (callback) => (tabRemoved = callback) },
        sendMessage: async (tabId, message) => {
          tabMessages.push({ tabId, ...message });
          return { ok: true };
        },
      },
    },
  });
  const send = (message, sender = {}) =>
    new Promise((resolve) => listener(message, sender, resolve));
  return {
    send,
    sent,
    tabMessages,
    removeTab: (tabId) => tabRemoved(tabId),
    setOffscreenStatus: (status) => {
      offscreenStatus = status;
    },
  };
}

test("stopping while tab capture permission is pending cancels the start", async () => {
  const stream = deferred();
  const harness = workerHarness({ getMediaStreamId: () => stream.promise });
  const starting = harness.send({ type: "ASR_START", tabId: 1 });
  await flushTasks();
  await harness.send({ type: "ASR_STOP" });
  stream.resolve("late-stream");
  assert.equal((await starting).ok, false);
  assert.equal(
    harness.sent.some((message) => message.type === "ASR_CAPTURE_START"),
    false,
  );
});

test("closing a tab overlay only stops that tab's audio session", async () => {
  const harness = workerHarness();
  const started = await harness.send({ type: "ASR_START", tabId: 7 });
  assert.equal(started.ok, true);
  await harness.send({ type: "ASR_STOP_TAB" }, { tab: { id: 8 } });
  assert.equal(
    (await harness.send({ type: "ASR_GET_STATUS" })).sessionId,
    started.sessionId,
  );
  await harness.send({ type: "ASR_STOP_TAB" }, { tab: { id: 7 } });
  assert.equal(
    (await harness.send({ type: "ASR_GET_STATUS" })).status,
    "stopped",
  );
});

test("late offscreen state and transcripts cannot resurrect a stopped session", async () => {
  const harness = workerHarness();
  const started = await harness.send({ type: "ASR_START", tabId: 7 });
  await harness.send({ type: "ASR_STOP" });
  await harness.send({
    type: "ASR_CAPTURE_STATE",
    sessionId: started.sessionId,
    tabId: 7,
    status: "running",
    provider: "cloud",
  });
  const late = await harness.send({
    type: "ASR_TRANSCRIPT",
    sessionId: started.sessionId,
    tabId: 7,
    text: "late",
  });
  assert.equal(late.ok, false);
  assert.equal(
    harness.tabMessages.some((message) => message.action === "audioTranscript"),
    false,
  );
  assert.equal(
    (await harness.send({ type: "ASR_GET_STATUS" })).status,
    "stopped",
  );
});

test("stop during configuration loading cannot start a stream later", async () => {
  const config = deferred();
  const harness = workerHarness({ getAsrConfig: () => config.promise });
  const starting = harness.send({ type: "ASR_START", tabId: 7 });
  await flushTasks();
  await harness.send({ type: "ASR_STOP" });
  config.resolve({});
  assert.equal((await starting).ok, false);
  assert.equal(
    harness.tabMessages.some(
      (message) => message.action === "audioSessionStart",
    ),
    false,
  );
});

test("a failed capture clears the content session authorization", async () => {
  const harness = workerHarness({
    sendOffscreen: async (message) =>
      message.type === "ASR_CAPTURE_START"
        ? { ok: false, error: "capture-failed" }
        : null,
  });
  const result = await harness.send({ type: "ASR_START", tabId: 7 });
  assert.equal(result.ok, false);
  const opened = harness.tabMessages.find(
    (message) => message.action === "audioSessionStart",
  );
  assert.ok(
    harness.tabMessages.some(
      (message) =>
        message.action === "audioSessionStop" &&
        message.sessionId === opened.sessionId,
    ),
  );
});

test("status polling clears a capture that stopped without a state event", async () => {
  const harness = workerHarness();
  const started = await harness.send({ type: "ASR_START", tabId: 7 });
  harness.setOffscreenStatus({
    ok: true,
    status: "stopped",
    sessionId: null,
    tabId: null,
  });
  const status = await harness.send({ type: "ASR_GET_STATUS" });
  assert.equal(status.status, "stopped");
  assert.equal(status.sessionId, null);
  const late = await harness.send({
    type: "ASR_TRANSCRIPT",
    sessionId: started.sessionId,
    tabId: 7,
    text: "late",
  });
  assert.equal(late.ok, false);
});

test("status polling does not cancel a start awaiting capture permission", async () => {
  const stream = deferred();
  const harness = workerHarness({ getMediaStreamId: () => stream.promise });
  const starting = harness.send({ type: "ASR_START", tabId: 7 });
  await flushTasks();
  assert.equal(
    (await harness.send({ type: "ASR_GET_STATUS" })).status,
    "starting",
  );
  stream.resolve("stream");
  assert.equal((await starting).ok, true);
});

test("a restarted worker restores a live session and stops it when its tab closes", async () => {
  const harness = workerHarness();
  harness.setOffscreenStatus({
    ok: true,
    status: "running",
    sessionId: "restored",
    tabId: 7,
    provider: "cloud",
  });
  harness.removeTab(7);
  await flushTasks();
  assert.equal(
    (await harness.send({ type: "ASR_GET_STATUS" })).status,
    "stopped",
  );
  assert.ok(
    harness.sent.some((message) => message.type === "ASR_CAPTURE_STOP"),
  );
});

test("stale status replies cannot replace a newly started session", async () => {
  const status = deferred();
  const harness = workerHarness({
    sendOffscreen: (message) =>
      message.type === "ASR_CAPTURE_STATUS" ? status.promise : null,
  });
  const polling = harness.send({ type: "ASR_GET_STATUS" });
  await flushTasks();
  const started = await harness.send({ type: "ASR_START", tabId: 7 });
  status.resolve({ ok: true, status: "running", sessionId: "old", tabId: 8 });
  assert.equal((await polling).sessionId, started.sessionId);
});
