import assert from "node:assert/strict";
import test from "node:test";

import { bundleRuntime, runRuntime } from "./helpers/runtime-harness.mjs";

const code = await bundleRuntime("../../src/avatar/page-agent.js", {
  "../utils/subtitle-capturer.js": ["SubtitleCapturer"],
});

function pageHarness() {
  const events = {};
  const messages = [];
  const capturers = [];
  const window = {
    addEventListener: (type, handler) => {
      events[type] = handler;
    },
    postMessage: (message) => messages.push(message),
  };
  runRuntime(code, {
    window,
    document: {
      querySelector: () => null,
      addEventListener: (type, handler) => {
        events[type] = handler;
      },
    },
    testDependencies: {
      SubtitleCapturer: class {
        resets = 0;
        stopped = false;
        constructor(options) {
          this.options = options;
          capturers.push(this);
        }
        start() {}
        stop() {
          this.stopped = true;
        }
        reset() {
          this.resets += 1;
        }
      },
    },
    setTimeout: () => 1,
  });
  const send = (type, data = {}, source = window) =>
    events.message({
      source,
      data: { source: "signbridge-content", type, ...data },
    });
  return { events, messages, capturers, send };
}

test("speech text does not auto-start a stopped page agent", () => {
  const harness = pageHarness();
  harness.send("SPEECH_TEXT", { text: "迟到文字" });
  assert.equal(harness.capturers.length, 0);
  harness.send("SIGNBRIDGE_START");
  harness.send("SIGNBRIDGE_STOP");
  harness.send("SPEECH_TEXT", { text: "迟到文字" });
  assert.equal(harness.capturers.length, 1);
  assert.equal(harness.capturers[0].stopped, true);
});

test("video seek clears playback and allows the same subtitle again", () => {
  const harness = pageHarness();
  harness.send("SIGNBRIDGE_START");
  const capturer = harness.capturers[0];
  capturer.options.onSubtitle({ text: "你好" });
  harness.events.seeking({ target: { tagName: "VIDEO" } });
  assert.equal(capturer.resets, 1);
  assert.equal(harness.messages.at(-1).type, "PLAYBACK_RESET");
  capturer.options.onSubtitle({ text: "你好" });
  assert.equal(
    harness.messages.filter((message) => message.text === "你好").length,
    2,
  );
  harness.send("SIGNBRIDGE_STOP");
  harness.events.emptied({ target: { tagName: "VIDEO" } });
  assert.equal(capturer.resets, 1);
});

test("other windows cannot start the page agent", () => {
  const harness = pageHarness();
  harness.send("SIGNBRIDGE_START", {}, {});
  assert.equal(harness.capturers.length, 0);
});
