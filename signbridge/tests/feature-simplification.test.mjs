import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { getDefaultConfig } from "../src/utils/config.js";
const source = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");

test("ordinary popup exposes one settings and workbench entry, without production tools or fake language choices", () => {
  const html = source("popup/index.html");
  for (const id of [
    "btnToggle",
    "btnAudio",
    "textInput",
    "btnDemo",
    "btnSettings",
    "btnHelp",
  ])
    assert.ok(html.includes(`id="${id}"`), id);
  for (const id of [
    "signLanguage",
    "sourceLanguage",
    "btnAsrSettings",
    "btnPoseEditor",
    "btnRecordMode",
    "btnCoverage",
    "btnMotionReview",
  ])
    assert.ok(!html.includes(`id="${id}"`), id);
});

test("workbench keeps research controls behind native details and exposes the real learned-model client", () => {
  const html = source("demo/index.html");
  assert.match(html, /href="\.\.\/private\/index\.html"/);
  assert.match(html, /id="research-tools"/);
  assert.match(html, /<details[^>]*id="research-details"/);
  assert.doesNotMatch(html, /<strong>T08 · VQ-VAE<\/strong>/);
  const client = source("private/index.html");
  assert.match(client, /data-workbench hidden/);
  assert.match(client, /href="\.\.\/demo\/index\.html"/);
});

test("configuration defaults only describe controls with implemented behavior", () => {
  const defaults = getDefaultConfig();
  assert.deepEqual(
    Object.keys(defaults).sort(),
    ["avatarPosition", "avatarSize", "enabled", "uiLocale"].sort(),
  );
  assert.doesNotMatch(source("avatar/page-agent.js"), /config\.sourceLanguage/);
  assert.match(source("options/asr-settings.html"), /id="avatarSize"/);
  assert.match(
    source("options/asr-settings.html"),
    /<details[^>]*id="asr-advanced"/,
  );
});

test("workspace strings are present in all supported locales", async () => {
  const { LOCALES } = await import("../src/i18n/locales.js");
  const keys = Object.keys(LOCALES["zh-CN"]).filter((key) =>
    key.startsWith("workbench"),
  );
  for (const [locale, dictionary] of Object.entries(LOCALES))
    for (const key of keys) assert.ok(dictionary[key], `${locale}: ${key}`);
});

test("local web handoff carries no token or sentence in its URL", async () => {
  const { localServicePage } = await import("../src/private/private-api.js");
  assert.equal(
    localServicePage("http://127.0.0.1:8770"),
    "http://127.0.0.1:8770/private/index.html",
  );
  for (const endpoint of [
    "http://127.0.0.1:8770?token=secret",
    "http://127.0.0.1:8770#input",
    "https://example.com",
  ])
    assert.throws(() => localServicePage(endpoint));
});

test("full workbench hands off to service without a new extension permission dialog", async () => {
  const { needsLocalServicePage } =
    await import("../src/private/private-api.js");
  const endpoint = "http://127.0.0.1:8770";
  assert.equal(
    needsLocalServicePage(endpoint, "chrome-extension://example", true),
    true,
  );
  assert.equal(
    needsLocalServicePage(endpoint, "chrome-extension://example", false),
    false,
  );
  assert.equal(needsLocalServicePage(endpoint, endpoint, false), false);
  assert.equal(
    needsLocalServicePage(endpoint, "http://127.0.0.1:8766", true),
    true,
  );
});
