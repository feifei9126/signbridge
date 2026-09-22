import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { flushTasks, runRuntime } from "./helpers/runtime-harness.mjs";

const code = readFileSync(
  new URL("../src/content/injector.js", import.meta.url),
  "utf8",
);

async function injectorHarness() {
  let listener;
  const windowEvents = {};
  const messages = [];
  const frameMessages = [];
  const runtimeMessages = [];
  const timers = new Map();
  let timerId = 0;
  class Element {
    children = [];
    style = {};
    events = {};
    parentNode = null;
    get isConnected() {
      return this === body || Boolean(this.parentNode?.isConnected);
    }
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    }
    remove() {
      if (this.parentNode)
        this.parentNode.children = this.parentNode.children.filter(
          (child) => child !== this,
        );
      this.parentNode = null;
    }
    setAttribute() {}
    addEventListener(type, callback) {
      this.events[type] = callback;
    }
  }
  const body = new Element();
  const byId = (id, root = body) =>
    root.id === id
      ? root
      : root.children.map((child) => byId(id, child)).find(Boolean);
  const document = {
    body,
    head: body,
    documentElement: body,
    querySelector: () => null,
    getElementById: byId,
    createElement: (tag) => {
      const element = new Element();
      element.tagName = tag;
      if (tag === "iframe")
        element.contentWindow = {
          postMessage: (message) => frameMessages.push(message),
        };
      return element;
    },
  };
  const window = {
    location: { hostname: "example.test" },
    addEventListener: (type, callback) => (windowEvents[type] = callback),
    postMessage: (message) => messages.push(message),
  };
  runRuntime(code, {
    window,
    document,
    chrome: {
      storage: { sync: { get: async () => ({}) } },
      runtime: {
        getURL: (name) => `chrome-extension://test/${name}`,
        onMessage: { addListener: (callback) => (listener = callback) },
        sendMessage: async (message) => {
          runtimeMessages.push(message);
          return { ok: true };
        },
      },
    },
    setTimeout: (callback) => {
      timers.set(++timerId, callback);
      return timerId;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  await flushTasks();
  const send = (message) =>
    new Promise((resolve) => listener(message, {}, resolve));
  function frameReady() {
    const frame = byId("signbridge-overlay")?.children.find(
      (child) => child.tagName === "iframe",
    );
    for (const type of ["LOADED", "READY"])
      windowEvents.message({
        source: frame.contentWindow,
        data: { source: "signbridge-iframe", type },
      });
  }
  const close = () =>
    byId("signbridge-overlay")
      .children.find((child) => child.tagName === "button")
      .events.click();
  return {
    send,
    byId,
    frameReady,
    close,
    messages,
    frameMessages,
    runtimeMessages,
    window,
    windowEvents,
  };
}

test("closing the avatar stops tab audio and ignores late transcripts", async () => {
  const harness = await injectorHarness();
  const opening = harness.send({ action: "start" });
  harness.frameReady();
  assert.equal((await opening).ok, true);
  harness.close();
  const late = harness.send({
    action: "audioTranscript",
    sessionId: "old",
    text: "你好",
  });
  await flushTasks();
  assert.equal(harness.byId("signbridge-overlay"), undefined);
  assert.equal(harness.runtimeMessages.at(-1).type, "ASR_STOP_TAB");
  assert.equal((await late).active, false);
});

test("stopping translation clears playback and rejects late page subtitles", async () => {
  const harness = await injectorHarness();
  const opening = harness.send({ action: "start" });
  harness.frameReady();
  assert.equal((await opening).ok, true);
  await harness.send({ action: "stop" });
  harness.windowEvents.message({
    source: harness.window,
    data: { source: "signbridge-page", type: "SUBTITLE_TEXT", text: "旧字幕" },
  });
  assert.equal(harness.frameMessages.at(-1).type, "PLAYBACK_RESET");
  assert.equal(
    harness.frameMessages.some((message) => message.text === "旧字幕"),
    false,
  );
});

test("only an explicit new audio session can reopen a closed avatar", async () => {
  const harness = await injectorHarness();
  const opening = harness.send({
    action: "audioSessionStart",
    sessionId: "first",
  });
  await flushTasks();
  assert.ok(harness.byId("signbridge-overlay"));
  harness.frameReady();
  assert.equal((await opening).ok, true);
  harness.close();
  const restarting = harness.send({
    action: "audioSessionStart",
    sessionId: "second",
  });
  await flushTasks();
  harness.frameReady();
  assert.equal((await restarting).ok, true);
  await harness.send({
    action: "audioTranscript",
    sessionId: "first",
    text: "旧的",
  });
  await harness.send({
    action: "audioTranscript",
    sessionId: "second",
    text: "新的",
  });
  assert.equal(
    harness.frameMessages.some((message) => message.text === "旧的"),
    false,
  );
  assert.equal(harness.frameMessages.at(-1).text, "新的");
});

test("closing during iframe loading does not block an explicit restart", async () => {
  const harness = await injectorHarness();
  const first = harness.send({ action: "start" });
  harness.close();
  const second = harness.send({ action: "start" });
  harness.frameReady();
  const results = await Promise.all([first, second]);
  assert.equal(
    results.every((result) => result.ok),
    true,
  );
  assert.ok(harness.byId("signbridge-overlay"));
  assert.equal(
    harness.frameMessages.filter((message) => message.type === "INIT").length,
    1,
  );
});

test("stopping during iframe loading cannot send a late start", async () => {
  const harness = await injectorHarness();
  const opening = harness.send({ action: "start" });
  await harness.send({ action: "stop" });
  harness.frameReady();
  assert.equal((await opening).ok, true);
  assert.equal(
    harness.messages.some((message) => message.type === "SIGNBRIDGE_START"),
    false,
  );
});

test("closing during a manual preview discards the pending text", async () => {
  const harness = await injectorHarness();
  const first = harness.send({ action: "sendText", text: "旧预览" });
  harness.close();
  const second = harness.send({ action: "start" });
  harness.frameReady();
  await Promise.all([first, second]);
  assert.equal(
    harness.frameMessages.some((message) => message.text === "旧预览"),
    false,
  );
});
