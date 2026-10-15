import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = process.env.SIGNBRIDGE_REALTIME_QA_DIR;
if (!output) throw new Error("Set a fresh SIGNBRIDGE_REALTIME_QA_DIR");
await mkdir(output, { recursive: false });
const server = createServer((_request, response) => {
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(
    '<!doctype html><title>SignBridge subtitle routing</title><video controls width="640" height="360"></video><p class="subtitle-text"></p>',
  );
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let context;
const report = {
  status: "running",
  startedAt: new Date().toISOString(),
  checks: [],
  errors: [],
  logs: [],
  sources: [],
};
try {
  const extension = process.env.SIGNBRIDGE_EXTENSION_DIR || join(root, "dist");
  context = await chromium.launchPersistentContext("", {
    executablePath: process.env.SIGNBRIDGE_EXTENSION_CHROME,
    headless: true,
    viewport: { width: 1200, height: 850 },
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
      "--enable-unsafe-swiftshader",
    ],
  });
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const extensionId = worker.url().split("/")[2];
  report.extensionVersion = await worker.evaluate(
    () => chrome.runtime.getManifest().version,
  );
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup/index.html`);
  await popup.waitForFunction(
    (version) =>
      document.querySelector("#extension-version").textContent ===
      `v${version}`,
    report.extensionVersion,
  );
  report.checks.push("popup reports the actual installed manifest version");
  await popup.close();
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));
  page.on("console", (message) => report.logs.push(message.text()));
  await page.addInitScript(() => {
    window.__motionEvents = [];
    window.addEventListener("message", (e) => {
      if (
        e.data?.source === "signbridge-iframe" &&
        e.data.type === "MOTION_SOURCE"
      )
        window.__motionEvents.push(e.data);
    });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.locator("#signbridge-overlay iframe").waitFor();
  await page.waitForFunction(
    () => !document.querySelector("#sb-loading"),
    undefined,
    { timeout: 30000 },
  );
  await page.bringToFront();
  const tabId = await worker.evaluate(
    async () =>
      (await chrome.tabs.query({ active: true, currentWindow: true }))[0].id,
  );
  const send = (message) =>
    worker.evaluate(
      ({ tabId, message }) => chrome.tabs.sendMessage(tabId, message),
      { tabId, message },
    );
  await send({ action: "sendText", text: "你好" });
  await page.waitForFunction(() =>
    window.__motionEvents.some((e) => e.sourceType === "dictionary"),
  );
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  await send({ action: "sendText", text: "工作忙吗？" });
  await page.waitForFunction(
    () => window.__motionEvents.some((e) => e.sourceType === "t08"),
    undefined,
    { timeout: 15000 },
  );
  report.sources.push(...(await page.evaluate(() => window.__motionEvents)));
  report.checks.push(
    "an exact trained phrase loads through the actual website overlay and packaged assets",
  );
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  await send({ action: "sendText", text: "工作忙吗？谢谢" });
  await page.waitForFunction(() => window.__motionEvents.length > 0);
  const first = await page.evaluate(() => window.__motionEvents[0]);
  report.sources.push(first);
  assert.equal(
    first.sourceType,
    "t08",
    "A known trained phrase plus a dictionary suffix must not downgrade the entire subtitle to built-ins",
  );
  assert.equal(first.referenceId, "pilot-greeting-busy-005");
  assert.equal(first.modelOutput, "token_decode");
  assert.equal(first.frames, 148);
  await page.waitForTimeout(300);
  const canvas = page
    .frameLocator("#signbridge-overlay iframe")
    .locator("canvas");
  const before = await canvas.screenshot();
  await page.waitForTimeout(400);
  const after = await canvas.screenshot();
  assert.notEqual(
    createHash("sha256").update(before).digest("hex"),
    createHash("sha256").update(after).digest("hex"),
  );
  const pixels = await page.evaluate(async (base64) => {
    const image = new Image();
    image.src = "data:image/png;base64," + base64;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(image, 0, 0);
    const rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const colors = new Set();
    let foreground = 0;
    for (let i = 0; i < rgba.length; i += 16) {
      colors.add(`${rgba[i]},${rgba[i + 1]},${rgba[i + 2]}`);
      if (
        Math.abs(rgba[i] - 220) +
          Math.abs(rgba[i + 1] - 232) +
          Math.abs(rgba[i + 2] - 245) >
        35
      )
        foreground++;
    }
    return {
      colors: colors.size,
      foregroundRatio: foreground / (rgba.length / 16),
    };
  }, after.toString("base64"));
  assert.ok(pixels.colors > 100 && pixels.foregroundRatio > 0.03);
  report.canvas = { ...pixels, moving: true };
  await writeFile(join(output, "trained-canvas.png"), after);
  assert.equal(
    await page
      .locator("#signbridge-motion-source")
      .getAttribute("data-source-type"),
    "t08",
  );
  assert.deepEqual(
    await page.evaluate(() => window.__motionEvents.map((e) => e.sourceType)),
    ["t08"],
  );
  await page
    .locator("#signbridge-overlay")
    .screenshot({ path: join(output, "trained-phrase.png") });
  await page.waitForFunction(
    () => window.__motionEvents.some((e) => e.sourceType === "dictionary"),
    undefined,
    { timeout: 15000 },
  );
  report.checks.push(
    "mixed subtitles retain the trained motion, then dictionary suffix, in source order",
  );
  assert.equal(
    await page
      .locator("#signbridge-motion-source")
      .getAttribute("data-source-type"),
    "dictionary",
  );
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  await send({ action: "sendText", text: "谢谢！工作忙吗？认识你很高兴" });
  await page.waitForFunction(
    () => window.__motionEvents.some((e) => e.sourceType === "experimental"),
    undefined,
    { timeout: 20000 },
  );
  const mixed = await page.evaluate(() => window.__motionEvents);
  assert.deepEqual(
    mixed.map((e) => e.sourceType),
    ["dictionary", "t08", "experimental"],
  );
  assert.equal(mixed[2].modelOutput, "smplx_fit_demo");
  assert.equal(mixed[2].presentation, "quaternion-temporal-v1");
  assert.equal(
    await page
      .locator("#signbridge-motion-source")
      .getAttribute("data-presentation"),
    "quaternion-temporal-v1",
  );
  report.sources.push(...mixed);
  report.checks.push(
    "dictionary prefix, trained phrase and source-4 fit play in order, with current-source badges",
  );
  await send({ action: "stop" });
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  await send({ action: "start" });
  await page.locator(".subtitle-text").evaluate((el) => {
    el.textContent = "工作忙吗？谢谢";
  });
  await page.waitForFunction(
    () => window.__motionEvents.some((e) => e.sourceType === "t08"),
    undefined,
    { timeout: 10000 },
  );
  report.checks.push(
    "actual subtitle DOM capture retains the trained span instead of using only built-ins",
  );
  await send({ action: "stop" });
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  await send({ action: "audioSessionStart", sessionId: "motion-qa" });
  await send({
    action: "audioTranscript",
    sessionId: "motion-qa",
    text: "工作忙吗？谢谢",
  });
  await page.waitForFunction(() =>
    window.__motionEvents.some((e) => e.sourceType === "t08"),
  );
  report.checks.push(
    "the authorized audio-transcript delivery path shares trained-span routing (ASR itself not run)",
  );
  await send({ action: "stop" });
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  const frame = page
    .frames()
    .find((f) => f.url().includes("avatar/avatar-frame.html"));
  await frame.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = async (url, options) => {
      if (String(url).endsWith("t08-candidates.json"))
        return new Response("{}", { status: 200 });
      return original(url, options);
    };
  });
  await send({ action: "sendText", text: "去人民广场怎么走？认识你很高兴" });
  await page.waitForFunction(
    () => window.__motionEvents.some((e) => e.sourceType === "experimental"),
    undefined,
    { timeout: 15000 },
  );
  const degraded = await page.evaluate(() => window.__motionEvents);
  assert.equal(degraded[0].sourceType, "dictionary");
  assert.ok(degraded[0].fallbackReason);
  assert.ok(degraded[0].label.includes("回退"));
  assert.equal(degraded[1].sourceType, "experimental");
  report.sources.push(...degraded);
  report.checks.push(
    "a broken reference asset falls back only for its own span; the next fitted motion is preserved",
  );
  await send({ action: "stop" });
  await page.evaluate(() => {
    window.__motionEvents = [];
  });
  await frame.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = async (url, options) => {
      if (String(url).includes("experimental/"))
        await new Promise((resolve) => setTimeout(resolve, 700));
      return original(url, options);
    };
  });
  await send({ action: "sendText", text: "我家附近有一家咖啡店" });
  await send({ action: "sendText", text: "工作忙吗？" });
  await page.waitForFunction(() =>
    window.__motionEvents.some((e) => e.sourceType === "t08"),
  );
  await page.waitForTimeout(1200);
  assert.deepEqual(
    await page.evaluate(() => window.__motionEvents.map((e) => e.sourceType)),
    ["t08"],
  );
  report.checks.push(
    "a manual replacement cancels an older in-flight asset load without late playback",
  );
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} catch (e) {
  report.status = "failed";
  report.failure = e.stack;
  throw e;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await context?.close();
  await new Promise((resolve) => server.close(resolve));
}
console.log(
  JSON.stringify(
    { status: report.status, checks: report.checks, output },
    null,
    2,
  ),
);
