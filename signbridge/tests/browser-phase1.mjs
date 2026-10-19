import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveTestResultsDir } from "../scripts/test-results-dir.mjs";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(resolveTestResultsDir(root), "phase1-browser");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "signbridge-phase1-"));
const server = createServer((_request, response) => {
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(
    '<!doctype html><title>SignBridge local test</title><h1>SignBridge 本地回归测试</h1><video controls width="640" height="360"></video><p class="subtitle-text"></p>',
  );
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let context;
const errors = [];
const logs = [];
const checks = [];
try {
  const extension = join(root, "dist");
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
    headless: true,
    viewport: { width: 1440, height: 900 },
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    logs.push(message.text());
    if (message.type() === "error") errors.push(message.text());
  });
  const url = `http://127.0.0.1:${server.address().port}/`;
  await page.goto(url);
  await page.locator("#signbridge-overlay iframe").waitFor();
  await page.waitForFunction(() => !document.getElementById("sb-loading"));
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
  assert.equal((await send({ action: "getStatus" })).ready, true);
  assert.equal(await page.locator("#signbridge-overlay").count(), 1);
  checks.push("model loaded and only one overlay");
  await page.screenshot({ path: join(output, "01-loaded.png") });
  await send({ action: "sendText", text: "你好" });
  await page.waitForTimeout(300);
  await page
    .locator("#signbridge-overlay")
    .screenshot({ path: join(output, "02-hello.png") });
  assert.ok(logs.some((line) => line.includes("Translation coverage:")));
  checks.push("manual preview reaches the built animation runtime");

  const beforeDrag = await page.locator("#signbridge-overlay").boundingBox();
  const handle = await page.locator("#sb-window-drag-handle").boundingBox();
  await page.mouse.move(handle.x + 50, handle.y + 12);
  await page.mouse.down();
  await page.mouse.move(handle.x - 70, handle.y - 68, { steps: 10 });
  await page.mouse.up();
  const afterDrag = await page.locator("#signbridge-overlay").boundingBox();
  assert.ok(afterDrag.x < beforeDrag.x - 100);
  assert.ok(afterDrag.y < beforeDrag.y - 60);
  checks.push("overlay drag remains functional");

  await page.locator("#signbridge-overlay button").click();
  assert.equal(await page.locator("#signbridge-overlay").count(), 0);
  await send({ action: "audioTranscript", sessionId: "stale", text: "你好" });
  assert.equal(await page.locator("#signbridge-overlay").count(), 0);
  checks.push("close ignores a late audio transcript without reopening");
  await send({ action: "start" });
  await page.waitForFunction(() => !document.getElementById("sb-loading"));
  assert.equal(await page.locator("#signbridge-overlay").count(), 1);
  assert.equal((await send({ action: "getStatus" })).ready, true);
  checks.push("explicit restart creates one ready overlay");

  await page.locator(".subtitle-text").evaluate((element) => {
    element.textContent = "你好，谢谢";
  });
  await page.waitForTimeout(100);
  await page.locator(".subtitle-text").evaluate((element) => {
    element.textContent = "再见";
  });
  await page.waitForTimeout(100);
  assert.ok(logs.some((line) => line.includes("subtitle: 再见")));
  await page
    .locator("video")
    .evaluate((video) => video.dispatchEvent(new Event("seeking")));
  await page.waitForTimeout(100);
  assert.ok(logs.some((line) => line.includes("iframe rx: PLAYBACK_RESET")));
  checks.push(
    "real subtitle DOM mutations reach playback; seek resets playback",
  );

  await send({ action: "stop" });
  const coverageBefore = logs.filter((line) =>
    line.includes("Translation coverage:"),
  ).length;
  await page.locator(".subtitle-text").evaluate((element) => {
    element.textContent = "可以";
  });
  await page.waitForTimeout(200);
  assert.equal(
    logs.filter((line) => line.includes("Translation coverage:")).length,
    coverageBefore,
  );
  assert.equal((await send({ action: "getStatus" })).active, false);
  checks.push("stopped capture ignores subsequent subtitle changes");
  await page.screenshot({ path: join(output, "03-stopped.png") });
  assert.deepEqual(errors, []);
} finally {
  await writeFile(
    join(output, "report.json"),
    JSON.stringify({ checks, errors, logs }, null, 2),
  );
  await context?.close();
  await new Promise((resolve) => server.close(resolve));
  await rm(profile, { recursive: true, force: true });
}
console.log(JSON.stringify({ checks, errors, output }, null, 2));
