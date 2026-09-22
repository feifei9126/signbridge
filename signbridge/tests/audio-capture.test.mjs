import assert from "node:assert/strict";
import test from "node:test";

import {
  bundleRuntime,
  deferred,
  flushTasks,
  runRuntime,
} from "./helpers/runtime-harness.mjs";

const code = await bundleRuntime("../../src/offscreen/audio-capture.js", {
  "../asr/local-whisper.js": [
    "deployLocalWhisper",
    "getLocalWhisperStatus",
    "prepareLocalWhisper",
    "transcribeLocalAudio",
  ],
  "../asr/transcription-client.js": ["transcribeAudio"],
  "../asr/audio-pcm.js": ["decodeAudioBlob", "hasAudibleSignal"],
});

function captureHarness(overrides = {}) {
  let listener;
  const messages = [];
  const streams = [];
  const recorders = [];
  const timers = new Map();
  let timerId = 0;
  function makeStream() {
    const track = {
      stopped: false,
      stop() {
        this.stopped = true;
      },
      addEventListener() {},
    };
    const stream = {
      active: true,
      getTracks: () => [track],
      getAudioTracks: () => [track],
    };
    streams.push(stream);
    return stream;
  }
  class Recorder {
    static isTypeSupported() {
      return true;
    }
    constructor(stream) {
      this.stream = stream;
      this.events = {};
      this.state = "inactive";
      recorders.push(this);
    }
    addEventListener(type, callback) {
      this.events[type] = callback;
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
    }
  }
  runRuntime(code, {
    testDependencies: {
      prepareLocalWhisper: async () => {},
      transcribeAudio: async () => ({ text: "你好" }),
      ...overrides.dependencies,
    },
    chrome: {
      runtime: {
        onMessage: { addListener: (callback) => (listener = callback) },
        sendMessage: async (message) => messages.push(message),
      },
    },
    navigator: {
      mediaDevices: {
        getUserMedia: overrides.getUserMedia || (async () => makeStream()),
      },
    },
    AudioContext: class {
      state = "running";
      createMediaStreamSource() {
        return { connect() {} };
      }
      async close() {}
    },
    MediaRecorder: Recorder,
    setTimeout: (callback) => {
      timers.set(++timerId, callback);
      return timerId;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  const send = (type, data = {}) =>
    new Promise((resolve) =>
      listener({ target: "offscreen", type, ...data }, {}, resolve),
    );
  const start = (id = "first", provider = "local") =>
    send("ASR_CAPTURE_START", {
      sessionId: id,
      tabId: 1,
      streamId: `stream-${id}`,
      requestConfig: { provider, model: "tiny", chunkSeconds: 3 },
    });
  return { send, start, streams, recorders, messages, makeStream, timers };
}

test("stop during model loading prevents late tab capture", async () => {
  const model = deferred();
  const harness = captureHarness({
    dependencies: { prepareLocalWhisper: () => model.promise },
  });
  const starting = harness.start();
  await flushTasks();
  await harness.send("ASR_CAPTURE_STOP");
  model.resolve();
  assert.equal((await starting).ok, false);
  assert.equal(harness.streams.length, 0);
  assert.equal((await harness.send("ASR_CAPTURE_STATUS")).status, "stopped");
});

test("a stream arriving after stop is released immediately", async () => {
  const acquired = deferred();
  const harness = captureHarness({ getUserMedia: () => acquired.promise });
  const starting = harness.start("late", "cloud");
  await flushTasks();
  await harness.send("ASR_CAPTURE_STOP");
  const stream = harness.makeStream();
  acquired.resolve(stream);
  assert.equal((await starting).ok, false);
  assert.equal(stream.getTracks()[0].stopped, true);
  assert.equal(harness.recorders.length, 0);
});

test("an old recorder stop event cannot restart or upload into a new session", async () => {
  const harness = captureHarness();
  await harness.start("old", "cloud");
  const oldRecorder = harness.recorders[0];
  oldRecorder.events.dataavailable({ data: new Blob(["old audio"]) });
  await harness.start("new", "cloud");
  oldRecorder.events.stop();
  await flushTasks();
  assert.equal(harness.recorders.length, 2);
  assert.equal(harness.timers.size, 1);
  assert.equal(
    harness.messages.some((message) => message.type === "ASR_TRANSCRIPT"),
    false,
  );
  assert.equal((await harness.send("ASR_CAPTURE_STATUS")).sessionId, "new");
  await harness.send("ASR_CAPTURE_STOP");
});

test("an old model failure cannot stop a newer capture session", async () => {
  const model = deferred();
  const harness = captureHarness({
    dependencies: { prepareLocalWhisper: () => model.promise },
  });
  const first = harness.start("old");
  await flushTasks();
  assert.equal((await harness.start("new", "cloud")).ok, true);
  model.reject(new Error("old model failed"));
  assert.equal((await first).ok, false);
  assert.equal((await harness.send("ASR_CAPTURE_STATUS")).sessionId, "new");
  assert.equal(harness.streams[0].getTracks()[0].stopped, false);
  await harness.send("ASR_CAPTURE_STOP");
});

test("stop aborts an in-flight cloud request and drops its late response", async () => {
  const response = deferred();
  let signal;
  const harness = captureHarness({
    dependencies: {
      transcribeAudio: (_blob, _config, _fetch, options) => {
        signal = options.signal;
        return response.promise;
      },
    },
  });
  await harness.start("cloud", "cloud");
  const recorder = harness.recorders[0];
  recorder.events.dataavailable({ data: new Blob(["audio"]) });
  recorder.events.stop();
  assert.equal(signal.aborted, false);
  await harness.send("ASR_CAPTURE_STOP");
  assert.equal(signal.aborted, true);
  response.resolve({ text: "旧声音" });
  await flushTasks();
  assert.equal(
    harness.messages.some((message) => message.type === "ASR_TRANSCRIPT"),
    false,
  );
  assert.equal(harness.timers.size, 0);
});

test("uncancellable local inference cannot publish into a replacement session", async () => {
  const response = deferred();
  const harness = captureHarness({
    dependencies: {
      decodeAudioBlob: async () => new Float32Array([1]),
      hasAudibleSignal: () => true,
      transcribeLocalAudio: () => response.promise,
    },
  });
  await harness.start("local");
  harness.recorders[0].events.dataavailable({
    data: new Blob(["local audio"]),
  });
  harness.recorders[0].events.stop();
  await flushTasks();
  await harness.start("new", "cloud");
  const recorder = harness.recorders.at(-1);
  recorder.events.dataavailable({ data: new Blob(["new audio"]) });
  recorder.events.stop();
  response.resolve({ text: "旧推理" });
  await flushTasks();
  const transcripts = harness.messages.filter(
    (message) => message.type === "ASR_TRANSCRIPT",
  );
  assert.equal(transcripts.length, 1);
  assert.equal(transcripts[0].sessionId, "new");
  assert.equal(transcripts[0].text, "你好");
  await harness.send("ASR_CAPTURE_STOP");
});
