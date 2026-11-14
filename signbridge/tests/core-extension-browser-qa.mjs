import { chromium } from "playwright";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import assert from "node:assert/strict";
const extension = resolve(process.env.SIGNBRIDGE_CORE_QA_BUILD || ""),
  out = process.env.SIGNBRIDGE_CORE_QA_OUTPUT;
if (!out || !process.env.SIGNBRIDGE_CORE_QA_BUILD)
  throw new Error("Set unpacked build and fresh QA output");
await mkdir(out, { recursive: false });
const core = JSON.parse(
    await readFile(join(extension, "demo/core-manifest.json")),
  ),
  report = {
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
  report.version = await worker.evaluate(
    () => chrome.runtime.getManifest().version,
  );
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(() => {
    window.__current = [];
    window.addEventListener("message", (e) => {
      if (
        e.data?.source === "signbridge-demo-avatar" &&
        e.data.type === "CURRENT"
      )
        window.__current.push(e.data);
    });
  });
  await page.goto(`chrome-extension://${id}/demo/index.html`);
  await page.waitForFunction(
    () =>
      document.querySelector("#core-mode")?.getAttribute("aria-pressed") ===
        "true" && !document.querySelector("#play").disabled,
    undefined,
    { timeout: 30000 },
  );
  assert.equal(
    await page.locator("#catalog-list button").count(),
    core.units.length,
  );
  await page.locator("#input").fill("我工作");
  await page.locator("#play").click();
  await page.waitForFunction(() => window.__current.length > 0);
  assert.equal(
    (await page.evaluate(() => window.__current[0])).item.id,
    core.units.find((u) => u.key === "speaker").id,
  );
  await page.locator("#input").fill("我们工作");
  assert.equal(await page.locator("#play").isDisabled(), true);
  assert.ok((await page.locator("#unknown").innerText()).includes("我们"));
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup/index.html`);
  const opened = context.waitForEvent("page");
  await popup.locator("#btnDemo").click();
  const tab = await opened;
  await tab.waitForLoadState();
  await tab.waitForFunction(
    () =>
      document.querySelector("#core-mode")?.getAttribute("aria-pressed") ===
      "true",
  );
  report.checks.push(
    "real MV3 installation and CSP",
    "popup defaults to core",
    "source-bound core plays",
    "missing we blocks without dictionary fallback",
  );
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  throw error;
} finally {
  await writeFile(
    join(out, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await context?.close();
}
console.log(JSON.stringify(report));
