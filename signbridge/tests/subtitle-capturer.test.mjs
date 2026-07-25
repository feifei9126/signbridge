import assert from "node:assert/strict";
import test from "node:test";

import { SubtitleCapturer } from "../src/utils/subtitle-capturer.js";

class FakeMutationObserver {
  static instances = [];

  constructor() {
    FakeMutationObserver.instances.push(this);
  }

  observe() {}

  disconnect() {}
}

test("subtitle capture can stop and bind existing sources again", () => {
  const originalDocument = globalThis.document;
  const originalObserver = globalThis.MutationObserver;
  globalThis.document = {
    body: {},
    querySelectorAll: () => [],
  };
  globalThis.MutationObserver = FakeMutationObserver;

  try {
    const capturer = new SubtitleCapturer();
    capturer.start();
    const firstTrackSet = capturer._watchedTracks;
    const firstElementSet = capturer._watchedElements;
    capturer.stop();
    capturer.start();

    assert.notEqual(capturer._watchedTracks, firstTrackSet);
    assert.notEqual(capturer._watchedElements, firstElementSet);
    assert.equal(FakeMutationObserver.instances.length, 2);
    capturer.stop();
  } finally {
    globalThis.document = originalDocument;
    globalThis.MutationObserver = originalObserver;
    FakeMutationObserver.instances.length = 0;
  }
});
