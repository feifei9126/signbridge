import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output =
  process.env.SIGNBRIDGE_REALTIME_QA_DIR ||
  join(root, "../local-data/demo-20261012/realtime-browser-qa");
const executablePath = process.env.SIGNBRIDGE_EXTENSION_CHROME;
if (!executablePath)
  throw new Error("Set SIGNBRIDGE_EXTENSION_CHROME to Chrome for Testing.");

await mkdir(output, { recursive: true });
const extension = join(root, "dist");
const context = await chromium.launchPersistentContext("", {
  executablePath,
  headless: true,
  viewport: { width: 1200, height: 850 },
  args: [
    `--disable-extensions-except=${extension}`,
    `--load-extension=${extension}`,
    "--enable-unsafe-swiftshader",
  ],
});
const report = {
  schema: "signbridge-realtime-t08-browser-qa-v1",
  status: "running",
  startedAt: new Date().toISOString(),
  checks: [],
  pageErrors: [],
  t08PoseScreenshotSha256: null,
};

try {
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker", { timeout: 15000 }));
  const id = worker.url().split("/")[2];
  const page = await context.newPage();
  page.on("pageerror", (error) => report.pageErrors.push(error.message));
  await page.addInitScript(() => {
    window.__signbridgeMessages = [];
    window.addEventListener("message", (event) => {
      if (event.source === window && event.data?.source === "signbridge-iframe")
        window.__signbridgeMessages.push(event.data);
    });
  });
  await page.goto(`chrome-extension://${id}/avatar/avatar-frame.html`);
  await page.waitForFunction(() =>
    window.__signbridgeMessages?.some((message) => message.type === "LOADED"),
  );
  await page.evaluate(() =>
    window.postMessage(
      {
        source: "signbridge-page",
        type: "INIT",
        modelUrl: chrome.runtime.getURL("avatar/model.glb"),
        config: { uiLocale: "zh-CN" },
      },
      location.origin,
    ),
  );
  await page.waitForFunction(
    () =>
      window.__signbridgeMessages?.some((message) => message.type === "READY"),
    undefined,
    { timeout: 30000 },
  );
  report.checks.push("production Godette iframe loads and initializes");

  await page.evaluate(() =>
    window.postMessage(
      { source: "signbridge-page", type: "SUBTITLE_TEXT", text: "工作忙吗？" },
      location.origin,
    ),
  );
  await page.waitForFunction(
    () =>
      window.__signbridgeMessages?.some(
        (message) =>
          message.type === "MOTION_SOURCE" &&
          message.sourceType === "t08" &&
          message.referenceId === "pilot-greeting-busy-005",
      ),
    undefined,
    { timeout: 30000 },
  );
  await page.waitForTimeout(750);
  const pose = await page.locator("canvas").screenshot();
  report.t08PoseScreenshotSha256 = createHash("sha256")
    .update(pose)
    .digest("hex");
  await writeFile(join(output, "live-t08-frame.png"), pose);
  report.checks.push(
    "full realtime phrase selects pilot-greeting-busy-005 token-decoded T08 motion",
  );

  await page.evaluate(() =>
    window.postMessage(
      { source: "signbridge-page", type: "PLAYBACK_RESET" },
      location.origin,
    ),
  );
  await page.evaluate(() =>
    window.postMessage(
      { source: "signbridge-page", type: "SUBTITLE_TEXT", text: "谢谢" },
      location.origin,
    ),
  );
  await page.waitForFunction(
    () =>
      window.__signbridgeMessages?.some(
        (message) =>
          message.type === "MOTION_SOURCE" &&
          message.sourceType === "dictionary",
      ),
    undefined,
    { timeout: 10000 },
  );
  report.checks.push(
    "untrained single word remains on the existing dictionary",
  );

  await page.evaluate(() => {
    window.__signbridgeMessages = [];
    window.postMessage(
      {
        source: "signbridge-page",
        type: "SUBTITLE_TEXT",
        text: "工作忙吗？谢谢",
      },
      location.origin,
    );
  });
  await page.waitForFunction(
    () =>
      window.__signbridgeMessages?.some(
        (message) =>
          message.type === "MOTION_SOURCE" &&
          message.sourceType === "dictionary",
      ),
    undefined,
    { timeout: 10000 },
  );
  assert.deepEqual(report.pageErrors, []);
  report.checks.push(
    "extra unmatched words do not trigger a false exact T08 reference match",
  );
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  throw error;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await context.close();
}

console.log(JSON.stringify(report, null, 2));
