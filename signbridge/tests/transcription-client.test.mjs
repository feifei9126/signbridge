import assert from "node:assert/strict";
import test from "node:test";

import { transcribeAudio } from "../src/asr/transcription-client.js";

test("transcription client sends an OpenAI-compatible multipart request", async () => {
  let request;
  const result = await transcribeAudio(
    new Blob(["audio"], { type: "audio/webm" }),
    {
      endpoint: "https://speech.example.test/v1/audio/transcriptions",
      apiKey: "secret",
      model: "whisper-1",
      language: "zh",
    },
    async (url, options) => {
      request = { url, options };
      return new Response(JSON.stringify({ text: "你好" }), { status: 200 });
    },
  );

  assert.equal(result.text, "你好");
  assert.equal(
    request.url,
    "https://speech.example.test/v1/audio/transcriptions",
  );
  assert.equal(request.options.headers.Authorization, "Bearer secret");
  assert.equal(request.options.body.get("model"), "whisper-1");
  assert.equal(request.options.body.get("language"), "zh");
  assert.equal(request.options.body.get("file").name, "signbridge-audio.webm");
});

test("transcription client surfaces provider errors", async () => {
  await assert.rejects(
    transcribeAudio(
      new Blob(["audio"]),
      {
        endpoint: "https://speech.example.test/transcribe",
        model: "model-a",
        language: "auto",
      },
      async () =>
        new Response(JSON.stringify({ error: { message: "bad key" } }), {
          status: 401,
        }),
    ),
    (error) => error.code === "asr-http-401" && error.message === "bad key",
  );
});

test("transcription client preserves WAV file metadata", async () => {
  await transcribeAudio(
    new Blob(["wav"], { type: "audio/wav" }),
    {
      endpoint: "https://speech.example.test/transcribe",
      model: "model-a",
      language: "auto",
    },
    async (_url, options) => {
      assert.equal(options.body.get("file").name, "signbridge-audio.wav");
      assert.equal(options.body.has("language"), false);
      return new Response(JSON.stringify({ text: "" }), { status: 200 });
    },
  );
});
