import test from "node:test";
import assert from "node:assert/strict";
import {
  privateEndpoint,
  probeLocalService,
  understand,
} from "../src/private/private-api.js";

test("private client only sends to explicit loopback service", () => {
  assert.equal(
    privateEndpoint("http://127.0.0.1:8770"),
    "http://127.0.0.1:8770/v1/understand",
  );
  for (const value of [
    "https://example.com",
    "http://127.0.0.1.evil:8770",
    "http://user:password@127.0.0.1:8770",
    "http://127.0.0.1:8770/secret",
    "http://127.0.0.1:8770?token=abc",
  ])
    assert.throws(() => privateEndpoint(value));
});

test("service probe checks only the local health route without credentials or text", async () => {
  let request;
  const available = await probeLocalService("http://127.0.0.1:8770", {
    fetchImpl: async (url, options) => {
      request = { url, options };
      return { ok: true, json: async () => ({ status: "ok" }) };
    },
  });
  assert.equal(available, true);
  assert.equal(request.url, "http://127.0.0.1:8770/health");
  assert.equal(request.options.method, "GET");
  assert.equal(request.options.credentials, "omit");
  assert.equal(request.options.cache, "no-store");
  assert.equal("body" in request.options, false);
  assert.equal("headers" in request.options, false);
});

test("service probe reports unavailable or unexpected responses without throwing", async () => {
  assert.equal(
    await probeLocalService("http://127.0.0.1:8770", {
      fetchImpl: async () => {
        throw new TypeError("connection refused");
      },
    }),
    false,
  );
  assert.equal(
    await probeLocalService("http://127.0.0.1:8770", {
      fetchImpl: async () => ({ ok: false, json: async () => ({}) }),
    }),
    false,
  );
});

test("only the requested sentence and ephemeral bearer leave the thin client", async () => {
  let captured;
  const fakeFetch = async (url, options) => {
    captured = { url, options };
    return {
      ok: true,
      json: async () => ({
        status: "parsed",
        roles: { actor: "我" },
        csl_translation_trained: false,
      }),
    };
  };
  await understand({
    endpoint: "http://127.0.0.1:8770",
    token: "a".repeat(43),
    text: "我帮你",
    fetchImpl: fakeFetch,
  });
  assert.equal(
    captured.options.headers.Authorization,
    "Bearer " + "a".repeat(43),
  );
  assert.deepEqual(JSON.parse(captured.options.body), { text: "我帮你" });
  assert.equal(captured.options.credentials, "omit");
  assert.equal(captured.options.redirect, "error");
  assert.equal(captured.options.cache, "no-store");
});

test("client rejects oversized input, invalid tokens and non-model responses", async () => {
  for (const overrides of [{ text: "我".repeat(501) }, { token: "" }])
    await assert.rejects(
      understand({
        endpoint: "http://127.0.0.1:8770",
        token: "a".repeat(43),
        text: "我帮你",
        ...overrides,
      }),
    );
  await assert.rejects(
    understand({
      endpoint: "http://127.0.0.1:8770",
      token: "a".repeat(43),
      text: "我帮你",
      fetchImpl: async () => ({ ok: true, json: async () => ({ clips: [] }) }),
    }),
  );
});

test("private interface translations cover every supported locale", async () => {
  const { LOCALES } = await import("../src/i18n/locales.js");
  const expected = Object.keys(LOCALES["zh-CN"]).filter((k) =>
    k.startsWith("private"),
  );
  for (const [locale, values] of Object.entries(LOCALES)) {
    for (const key of expected) assert.ok(values[key], `${locale}: ${key}`);
    assert.equal(Object.keys(values.privateRoles).length, 11);
  }
});

test("private client rejects malformed role collections before rendering", async () => {
  for (const roles of [
    [],
    "text",
    { actor: 4 },
    Object.fromEntries(Array.from({ length: 12 }, (_, i) => [String(i), "我"])),
  ])
    await assert.rejects(
      understand({
        endpoint: "http://127.0.0.1:8770",
        token: "a".repeat(43),
        text: "我帮你",
        fetchImpl: async () => ({
          ok: true,
          json: async () => ({
            status: "parsed",
            roles,
            csl_translation_trained: false,
          }),
        }),
      }),
    );
});
