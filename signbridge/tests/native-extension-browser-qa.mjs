// Verify the exact unpacked local release under the real MV3 extension CSP.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { chromium } from "playwright";
const extension = resolve(process.env.SIGNBRIDGE_NATIVE_QA_BUILD || ""),
  output = process.env.SIGNBRIDGE_NATIVE_QA_OUTPUT;
if (!output || !process.env.SIGNBRIDGE_NATIVE_QA_BUILD)
  throw new Error("Set explicit unpacked build and new output");
await mkdir(output, { recursive: false });
const index = JSON.parse(
  await readFile(join(extension, "demo/native-index.json")),
);
const report = {
  status: "running",
  checks: [],
  errors: [],
  trainingStarted: false,
};
let context;
try {
  context = await chromium.launchPersistentContext("", {
    headless: true,
    executablePath: chromium.executablePath(),
    viewport: { width: 1440, height: 1000 },
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
      "--enable-unsafe-swiftshader",
    ],
  });
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker", { timeout: 15000 }));
  const id = worker.url().split("/")[2];
  report.extensionId = id;
  report.version = await worker.evaluate(
    () => chrome.runtime.getManifest().version,
  );
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(() => {
    window.__events = [];
    window.addEventListener("message", (e) => {
      if (
        e.data?.source === "signbridge-demo-avatar" &&
        e.data.type !== "PROGRESS"
      )
        window.__events.push(e.data);
    });
  });
  await page.goto(`chrome-extension://${id}/demo/index.html`);
  await page.waitForFunction(
    (n) =>
      document.querySelector("#native-count")?.textContent === String(n) &&
      !document.querySelector("#play").disabled,
    index.clips.length,
    { timeout: 30000 },
  );
  await page.locator("#input").fill("我帮你");
  await page.locator("#play").click();
  await page.waitForFunction(
    () =>
      window.__events?.some(
        (e) => e.type === "CURRENT" && e.item.source === "native",
      ),
    undefined,
    { timeout: 15000 },
  );
  report.current = await page.evaluate(() =>
    window.__events.filter((e) => e.type === "CURRENT").at(-1),
  );
  assert.equal(report.current.performance.precompiled, true);
  assert.equal(report.current.item.semanticRole, "actor");
  await page.screenshot({
    path: join(output, "extension-native.png"),
    fullPage: true,
  });
  await page.locator("#stop").click();
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup/index.html`);
  await popup.waitForFunction(
    (version) =>
      document.querySelector("#extension-version")?.textContent ===
      `v${version}`,
    report.version,
  );
  const workbench = context.waitForEvent("page");
  await popup.locator("#btnDemo").click();
  const opened = await workbench;
  await opened.waitForLoadState();
  assert.ok(opened.url().endsWith("/demo/index.html"));
  await opened.waitForFunction(
    (n) => document.querySelector("#native-count")?.textContent === String(n),
    index.clips.length,
    { timeout: 15000 },
  );
  assert.equal(
    await opened.locator("#native-mode").getAttribute("aria-pressed"),
    "true",
  );
  report.checks.push(
    "unpacked MV3 service worker loads",
    "native precompiled motion plays under extension CSP",
    "actor role is retained",
    "popup reports installed version and opens candidate workbench",
  );
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  throw error;
} finally {
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await context?.close();
}
console.log(JSON.stringify(report));
