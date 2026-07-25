import assert from "node:assert/strict";
import test from "node:test";

import { SpeechRecognizer } from "../src/utils/speech-recognizer.js";

class FakeRecognition {
  static starts = 0;

  start() {
    FakeRecognition.starts += 1;
  }

  stop() {}
}

test("speech recognition retries after a previous permission failure", async () => {
  const originalWindow = globalThis.window;
  globalThis.window = { SpeechRecognition: FakeRecognition };

  try {
    const recognizer = new SpeechRecognizer();
    recognizer._silent = true;
    await recognizer.start();

    assert.equal(recognizer.isSilent, false);
    assert.equal(FakeRecognition.starts, 1);
    recognizer.stop();
  } finally {
    globalThis.window = originalWindow;
    FakeRecognition.starts = 0;
  }
});
