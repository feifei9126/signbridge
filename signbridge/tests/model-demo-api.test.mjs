import assert from "node:assert/strict";
import test from "node:test";
import {
  createModelApi,
  normalizeModelEndpoint,
  MODEL_PROTOCOL,
  MODEL_CHECKPOINT,
} from "../src/demo/model-demo-api.js";
const clip = {
  id: "one",
  text: "通知",
  sha256: "a".repeat(64),
  human_approved: true,
  motion_approval_id: "review",
  source_sha256: "b".repeat(64),
  fitted_sha256: "c".repeat(64),
};
const info = () => ({
  protocol: MODEL_PROTOCOL,
  checkpoint_sha256: MODEL_CHECKPOINT,
  token: "t".repeat(43),
  research_only: true,
  human_approved: false,
  semantics_approved: false,
  training_ready: false,
  model_training_ready: false,
  csl_translation_verified: false,
  catalog: [
    {
      ...clip,
      source: "experimental",
      approval_id: "review",
      approval_scope: "motion_quality_only",
      semantic_status: "unverified",
    },
  ],
});
const loadIndex = async () => ({ clips: [clip] });
test("model endpoint allows explicit loopback only", () => {
  assert.equal(
    normalizeModelEndpoint("http://127.0.0.1:8787/"),
    "http://127.0.0.1:8787",
  );
  for (const url of [
    "https://evil.example",
    "http://localhost:8787",
    "http://127.0.0.1:0",
    "http://127.0.0.1:65536",
    "http://user@127.0.0.1:8787",
    "http://127.0.0.1:8787/?token=a",
    "http://127.1:8787",
    "http://127.0.0.1:8787/private",
  ])
    assert.throws(() => normalizeModelEndpoint(url));
});
test("permission is requested in click gesture before asynchronous work; token stays in memory", async () => {
  let called = false;
  const calls = [];
  const api = createModelApi({
    extension: true,
    loadIndex,
    permissions: {
      request(p) {
        called = true;
        assert.deepEqual(p, { origins: ["http://127.0.0.1/*"] });
        return Promise.resolve(true);
      },
    },
    fetcher: async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () =>
          url.endsWith("demo-session")
            ? info()
            : { checkpoint_sha256: MODEL_CHECKPOINT },
      };
    },
  });
  const pending = api.connect(undefined, { requestPermission: true });
  assert.equal(called, true);
  const connected = await pending;
  assert.equal(connected.token, undefined);
  await api.predict("我");
  assert.equal(calls[1].url, "http://127.0.0.1:8787/v1/understand");
  assert.equal(
    calls[1].options.headers.Authorization,
    "Bearer " + info().token,
  );
  api.disconnect();
  assert.equal(api.connected, false);
  await assert.rejects(api.predict("我"));
});
test("denied permission never contacts local service", async () => {
  const api = createModelApi({
    extension: true,
    loadIndex,
    permissions: { contains: async () => false, request: async () => false },
    fetcher: () => {
      throw Error("unexpected network");
    },
  });
  await assert.rejects(api.connect(), { code: "permissionRequired" });
  await assert.rejects(api.connect(undefined, { requestPermission: true }), {
    code: "permissionDenied",
  });
});
test("wrong model, protocol, approval or local asset is rejected", async () => {
  for (const change of [
    (v) => (v.protocol = "old"),
    (v) => (v.checkpoint_sha256 = "x"),
    (v) => (v.training_ready = true),
    (v) => (v.catalog[0].sha256 = "x"),
    (v) => (v.catalog[0].text = "我"),
    (v) => v.catalog.push(v.catalog[0]),
  ]) {
    const value = info();
    change(value);
    const api = createModelApi({
      extension: false,
      loadIndex,
      fetcher: async () => ({ ok: true, json: async () => value }),
    });
    await assert.rejects(api.connect(), { code: "incompatible" });
    assert.equal(api.connected, false);
  }
});
test("disconnect discards stale session even when fetch ignores abort", async () => {
  let resolve;
  const api = createModelApi({
    extension: false,
    loadIndex,
    fetcher: () =>
      new Promise((r) => {
        resolve = r;
      }),
  });
  const pending = api.connect();
  await Promise.resolve();
  api.disconnect();
  resolve({ ok: true, json: async () => info() });
  await assert.rejects(pending, { code: "cancelled" });
  assert.equal(api.connected, false);
});

test("index loading has a deadline and is cancelled even if the loader ignores abort", async () => {
  const stalled = () => new Promise(() => {});
  const api = createModelApi({
    extension: false,
    loadIndex: stalled,
    timeoutMs: 20,
    fetcher: async () => ({ ok: true, json: async () => info() }),
  });
  await assert.rejects(api.connect(), { code: "serviceError" });
  assert.equal(api.connected, false);
  const pending = api.connect();
  await new Promise((r) => setTimeout(r, 1));
  api.disconnect();
  await assert.rejects(pending, { code: "cancelled" });
});
