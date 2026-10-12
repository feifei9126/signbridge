import assert from "node:assert/strict";
import test from "node:test";

import {
  bundleRuntime,
  flushTasks,
  runRuntime,
} from "./helpers/runtime-harness.mjs";

const code = await bundleRuntime("../../src/popup/popup.js", {
  "../utils/config.js": ["getConfig", "setConfig"],
  "../i18n/locales.js": ["setLocale", "t"],
});

test("stopping translation updates the audio button so the next click restarts capture", async () => {
  const elements = {};
  const sent = [];
  for (const id of ["btnToggle", "btnAudio", "audioStatus", "btnToggleText"]) {
    elements[id] = {
      events: {},
      classList: { toggle() {} },
      addEventListener(type, handler) {
        this.events[type] = handler;
      },
    };
  }
  runRuntime(code, {
    document: {
      getElementById: (id) => elements[id] || null,
      querySelectorAll: () => [],
    },
    testDependencies: {
      getConfig: async () => ({}),
      setConfig: async (config) => config,
      setLocale() {},
      t: (key) => key,
    },
    chrome: {
      tabs: {
        query: async () => [{ id: 7 }],
        sendMessage: async (_tabId, message) => ({
          ok: true,
          active: message.action !== "stop",
        }),
      },
      runtime: {
        sendMessage: async (message) => {
          sent.push(message);
          return { ok: true, status: "running", tabId: 7 };
        },
      },
    },
  });
  await flushTasks();
  assert.equal(elements.audioStatus.textContent, "audioListening");
  await elements.btnToggle.events.click();
  assert.equal(elements.audioStatus.textContent, "audioStopped");
  await elements.btnAudio.events.click();
  assert.equal(sent.at(-1).type, "ASR_START");
  assert.equal(elements.btnToggleText.textContent, "stop");
});

test("Demo popup entry opens a full-page extension tab without depending on the current website", async () => {
  let onClick;
  const opened = [];
  runRuntime(code, {
    document: {
      getElementById: (id) =>
        id === "btnDemo"
          ? {
              addEventListener(_type, fn) {
                onClick = fn;
              },
            }
          : null,
      querySelectorAll: () => [],
    },
    testDependencies: {
      getConfig: async () => ({}),
      setConfig: async (c) => c,
      setLocale() {},
      t: (key) => key,
    },
    chrome: {
      tabs: {
        query: async () => [],
        create: (options) => opened.push(options),
      },
      runtime: { getURL: (path) => "chrome-extension://test/" + path },
    },
  });
  await flushTasks();
  onClick();
  assert.deepEqual(
    opened.map((o) => o.url),
    ["chrome-extension://test/demo/index.html"],
  );
});
