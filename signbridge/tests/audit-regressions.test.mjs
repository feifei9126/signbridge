import test from "node:test";
import assert from "node:assert/strict";
import { normalizeAsrConfig } from "../src/asr/asr-config.js";
import { transcribeAudio } from "../src/asr/transcription-client.js";
import { planDemoText } from "../src/demo/demo-motion.js";
import { translateText } from "../src/avatar/sign-language-data.js";
import { planCslText } from "../src/demo/csl-semantic-plan.js";

test("ASR rejects remote HTTP before transmitting audio or credentials", async () => {
  for (const endpoint of [
    "http://speech.example.test/audio",
    "http://127.0.0.1.evil/audio",
    "https://user:pass@example.test/audio",
    "https://example.test/audio#secret",
  ]) {
    assert.throws(() => normalizeAsrConfig({ cloudEndpoint: endpoint }));
    let called = false;
    await assert.rejects(
      transcribeAudio(
        new Blob(["audio"]),
        { endpoint, apiKey: "not-a-real-key", model: "test" },
        async () => {
          called = true;
          return new Response("{}");
        },
      ),
    );
    assert.equal(called, false);
  }
  for (const endpoint of [
    "http://127.0.0.1:8771/audio",
    "http://localhost:8771/audio",
    "http://[::1]:8771/audio",
    "https://speech.example.test/audio",
  ])
    assert.equal(
      normalizeAsrConfig({ cloudEndpoint: endpoint }).cloudEndpoint,
      endpoint,
    );
});

test("ASR refuses redirects and omits browser credentials", async () => {
  await transcribeAudio(
    new Blob(["audio"]),
    { endpoint: "https://speech.example.test/audio", model: "test" },
    async (_url, options) => {
      assert.equal(options.redirect, "error");
      assert.equal(options.credentials, "omit");
      return new Response('{"text":"你好"}');
    },
  );
});

test("Demo and live dictionary matching retain the same Chinese word boundaries", () => {
  for (const text of [
    "好久不见",
    "不是",
    "人民广场",
    "了解一下",
    "你好，谢谢",
    "我今天去学校",
    "欢",
    "yesterday xhello hello, thanks!",
  ]) {
    assert.deepEqual(
      planDemoText(text, "dictionary").items.map((s) => s.id),
      translateText(text, 40).matches.map((s) => s.id),
      text,
    );
  }
  assert.equal(planDemoText("不是", "dictionary").items.length, 0);
  assert.ok(planDemoText("人民广场", "dictionary").unmatched.includes("人民"));
  assert.ok(
    planDemoText("工作🚀忙吗", "auto", [
      { id: "p", text: "工作忙吗", aliases: ["工作忙吗"] },
    ]).unmatched.includes("🚀"),
  );
});

test("semantic analysis never produces playable dictionary or retrieved motions", () => {
  const clip = {
    id: "unchecked",
    text: "我帮你",
    aliases: ["我帮你"],
    experimental: true,
    human_approved: false,
  };
  for (const text of [
    "我去",
    "我今天去",
    "我帮你",
    "我非常开心",
    "我没有去",
    "你去吗？",
  ]) {
    const p = planCslText(text, [clip]);
    assert.equal(p.canPreview, false, text);
    assert.deepEqual(p.items, [], text);
    assert.equal(p.route, "analysis_only");
    assert.equal(p.trainingReady, false);
  }
});
