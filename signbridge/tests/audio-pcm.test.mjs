import assert from "node:assert/strict";
import test from "node:test";

import {
  audioBufferToMono16Khz,
  hasAudibleSignal,
} from "../src/asr/audio-pcm.js";

function audioBuffer(sampleRate, channels) {
  return {
    sampleRate,
    numberOfChannels: channels.length,
    length: channels[0].length,
    getChannelData(index) {
      return channels[index];
    },
  };
}

test("audio is mixed to mono and resampled to 16 kHz", () => {
  const left = Float32Array.from({ length: 48000 }, (_, index) =>
    index % 2 ? 1 : -1,
  );
  const right = Float32Array.from({ length: 48000 }, () => 0);
  const output = audioBufferToMono16Khz(audioBuffer(48000, [left, right]));
  assert.equal(output.length, 16000);
  assert.equal(output[0], -0.5);
  assert.equal(output[1], 0.5);
});

test("silence is skipped before local Whisper inference", () => {
  assert.equal(hasAudibleSignal(new Float32Array(16000)), false);
  assert.equal(hasAudibleSignal(Float32Array.from([0.1, -0.1])), true);
});
