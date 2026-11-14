import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mkdir, writeFile, mkdtemp, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

const root = process.env.SIGNBRIDGE_MODEL_DEMO_ROOT;
if (!root)
  throw new Error("Set SIGNBRIDGE_MODEL_DEMO_ROOT to the staged delivery");
const extension = resolve(root, "chrome-extension");
const out = resolve(
  process.env.SIGNBRIDGE_MODEL_QA_OUTPUT || join(root, "validation/browser-v1"),
);
await mkdir(out, { recursive: false });
const config = JSON.parse(await readFile(join(root, "model-config.json")));
const origin = config.extension_origins[0];
const profile = await mkdtemp(join(tmpdir(), "signbridge-extension-model-qa-"));
const report = {
  status: "running",
  extensionOrigin: origin,
  checks: [],
  inference: [],
  motion: [],
  errors: [],
  expectedFailures: [],
};
const context = await chromium.launchPersistentContext(profile, {
  headless: process.env.SIGNBRIDGE_MODEL_QA_HEADLESS === "1",
  executablePath: chromium.executablePath(),
  viewport: { width: 1440, height: 1000 },
  args: [
    `--disable-extensions-except=${extension}`,
    `--load-extension=${extension}`,
    "--enable-unsafe-swiftshader",
  ],
});
let page;
let expectedFailure = false;
try {
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  assert.equal("chrome-extension://" + new URL(worker.url()).hostname, origin);
  const popup = await context.newPage();
  await popup.goto(origin + "/popup/index.html");
  assert.equal(
    await popup.locator("#btnModelDemo").textContent(),
    "模型演示 Demo",
  );
  const opened = context.waitForEvent("page");
  await popup.locator("#btnModelDemo").click();
  page = await opened;
  await page.waitForLoadState();
  assert.equal(page.url(), origin + "/demo/model.html");
  page.on("pageerror", (error) => report.errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error")
      (expectedFailure ? report.expectedFailures : report.errors).push(
        message.text(),
      );
  });
  await page.evaluate(() => {
    window.motionEvents = [];
    window.addEventListener("message", (event) => {
      if (event.data?.source === "signbridge-demo-avatar")
        window.motionEvents.push({ at: performance.now(), ...event.data });
    });
  });
  await page.waitForFunction(() =>
    document.querySelector("#model-status").textContent.includes("授权"),
  );
  assert.equal(await page.locator("#analyze").isDisabled(), true);
  assert.equal(
    await page.evaluate(() =>
      chrome.permissions.contains({ origins: ["http://127.0.0.1/*"] }),
    ),
    false,
  );
  await page.locator("#connect").click();
  await page.waitForFunction(
    () => !document.querySelector("#analyze").disabled,
    null,
    { timeout: 30000 },
  );
  assert.equal(
    await page.evaluate(() =>
      chrome.permissions.contains({ origins: ["http://127.0.0.1/*"] }),
    ),
    true,
  );
  await page.waitForFunction(
    () =>
      document.querySelectorAll("[data-reference]").length === 8 &&
      !document.querySelector("[data-reference]").disabled,
  );
  report.checks.push(
    "Actual MV3 load, stable public-key ID, popup opens extension page",
    "No loopback access before click; actual optional permission granted after explicit click",
    "Real local model checkpoint and all eight local reference assets accepted",
  );
  async function analyze(text) {
    await page.locator("#input").fill(text);
    const responsePromise = page.waitForResponse(
      (res) =>
        res.url().endsWith("/v1/understand") &&
        res.request().method() === "POST",
    );
    await page.locator("#analyze").click();
    const response = await responsePromise;
    assert.equal(response.status(), 200);
    const result = await response.json();
    await page.waitForFunction((text) => {
      try {
        return (
          JSON.parse(document.querySelector("#raw-model").textContent).input ===
          text
        );
      } catch {
        return false;
      }
    }, text);
    report.inference.push({
      text,
      prediction: result.prediction,
      rawKind: result.raw_kind,
      checkpoint: result.checkpoint_sha256,
      motionItems: result.motion_plan.items.length,
    });
    assert.equal(result.checkpoint_sha256, config.checkpoint_sha256);
    assert.equal(result.training_ready, false);
    return result;
  }
  for (const text of ["我", "你", "他", "我们", "你们", "他们"]) {
    const result = await analyze(text);
    assert.equal(result.prediction.roles.actor, text);
    assert.equal(await page.locator("#play-motion").isDisabled(), true);
  }
  const a = await analyze("我帮你"),
    b = await analyze("你帮我");
  assert.equal(a.prediction.roles.patient, "你");
  assert.equal(b.prediction.roles.patient, "我");
  const c = await analyze("我不想去"),
    d = await analyze("我想不去");
  assert.notDeepEqual(c.prediction.operators, d.prediction.operators);
  for (const text of ["我没有工作", "我喝书", "我。去", "我去火星"]) {
    assert.equal((await analyze(text)).prediction.status, "abstained");
  }
  report.checks.push(
    "14 actual model inputs: person roles, reversed actors/patients, distinct negation scope and rejection; no unverified automatic motion",
  );
  const clips = await page.locator("[data-reference]").evaluateAll((nodes) =>
    nodes.map((n) => ({
      id: n.dataset.reference,
      text: n.querySelector("strong").textContent,
    })),
  );
  await page.selectOption("#speed", "1.25");
  for (const [index, clip] of clips.entries()) {
    const start = await page.evaluate(() => performance.now());
    await page.locator(`[data-reference="${clip.id}"]`).click();
    const visible = await page.locator("#avatar").boundingBox();
    assert(visible.y >= 0 && visible.y + visible.height <= 1000);
    await page.waitForFunction(
      ({ id, start }) =>
        window.motionEvents.some(
          (e) => e.type === "CURRENT" && e.item.id === id && e.at >= start,
        ),
      { id: clip.id, start },
    );
    await page.waitForFunction(
      () => document.querySelector("#progress").value > 0.15,
    );
    if (index === 0) {
      await page.locator("#pause").click();
      await page.waitForFunction(
        () => document.querySelector("#pause").textContent === "继续",
      );
      const before = await page.locator("#progress").getAttribute("value");
      await page.waitForTimeout(200);
      assert.equal(
        await page.locator("#progress").getAttribute("value"),
        before,
      );
      await page.locator("#pause").click();
    }
    await page.screenshot({ path: join(out, `motion-${index + 1}.png`) });
    await page.waitForFunction(
      (start) =>
        window.motionEvents.some((e) => e.type === "FINISHED" && e.at >= start),
      start,
      { timeout: 25000 },
    );
    const messages = await page.evaluate(
      (start) =>
        window.motionEvents.filter(
          (e) =>
            e.at >= start && ["CURRENT", "FINISHED", "ERROR"].includes(e.type),
        ),
      start,
    );
    assert.equal(
      messages.some((e) => e.type === "ERROR"),
      false,
    );
    assert.equal(messages.find((e) => e.type === "CURRENT").stabilized, true);
    report.motion.push({ ...clip, finished: true, messages });
    console.log(`Playback ${index + 1}/8: ${clip.text}`);
  }
  await page.locator("[data-reference]").nth(0).click();
  await page.waitForFunction(() => !document.querySelector("#pause").disabled);
  await page.locator("[data-reference]").nth(1).click();
  await page.waitForFunction(() =>
    document.querySelector("#motion-status").textContent.includes("记者"),
  );
  await page.locator("#input").fill("我们");
  await page.waitForFunction(
    () => document.querySelector("#motion-status").textContent === "已停止",
  );
  assert.equal(await page.locator("#raw-model").textContent(), "—");
  report.checks.push(
    "All eight fitted clips finished in extension iframe; display stabilization active, pause/resume, replacement and edit-stop passed",
  );
  expectedFailure = true;
  await page.route("**/v1/understand", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"error":"busy"}',
    }),
  );
  await page.locator("#input").fill("我");
  await page.locator("#analyze").click();
  await page.waitForFunction(
    () => document.querySelector("#model-status").dataset.state === "error",
  );
  assert.equal(await page.locator("#analyze").isDisabled(), true);
  assert.equal(await page.locator("[data-reference]").count(), 0);
  await page.unroute("**/v1/understand");
  await page.locator("#connect").click();
  await page.waitForFunction(
    () => !document.querySelector("#analyze").disabled,
  );
  await page.locator("#endpoint").fill("http://127.0.0.1:1");
  await page.locator("#connect").click();
  await page.waitForFunction(
    () => document.querySelector("#model-status").dataset.state === "error",
  );
  assert.equal(await page.locator("#analyze").isDisabled(), true);
  await page.locator("#endpoint").fill("https://evil.example");
  await page.locator("#connect").click();
  await page.waitForFunction(() =>
    document.querySelector("#model-status").textContent.includes("仅支持"),
  );
  await page.locator("#endpoint").fill("http://127.0.0.1:8787");
  await page.route("**/v1/demo-session", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.checkpoint_sha256 = "wrong";
    await route.fulfill({ response, json: data });
  });
  await page.locator("#connect").click();
  await page.waitForFunction(() =>
    document.querySelector("#model-status").textContent.includes("不匹配"),
  );
  assert.equal(await page.locator("#analyze").isDisabled(), true);
  await page.unroute("**/v1/demo-session");
  expectedFailure = false;
  await page.locator("#connect").click();
  await page.waitForFunction(
    () => !document.querySelector("#analyze").disabled,
  );
  await analyze("我不想去");
  await page.screenshot({ path: join(out, "desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.screenshot({ path: join(out, "mobile.png"), fullPage: true });
  await page.reload();
  await page.waitForFunction(
    () => !document.querySelector("#analyze").disabled,
  );
  report.checks.push(
    "503, unreachable service and incompatible checkpoint clear stale results; reconnect and reload work",
    "Non-loopback endpoint rejected, mobile layout has no horizontal overflow",
  );
  const stored = await worker.evaluate(() => chrome.storage.local.get(null));
  assert.equal(
    Object.keys(stored).some((key) => /model.*token|bearer/i.test(key)),
    false,
  );
  report.checks.push("No model bearer stored in extension local storage");
  const oldOpened = context.waitForEvent("page");
  await popup.locator("#btnDemo").click();
  assert.equal((await oldOpened).url(), origin + "/demo/index.html");
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  report.failedState = await page?.evaluate(() => ({
    events: window.motionEvents?.filter((e) => e.type !== "PROGRESS"),
    status: document.querySelector("#motion-status")?.textContent,
    visibility: document.visibilityState,
  }));
  await page?.screenshot({ path: join(out, "failure.png"), fullPage: true });
  throw error;
} finally {
  await writeFile(
    join(out, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await context.close();
}
console.log(
  JSON.stringify({
    status: report.status,
    checks: report.checks.length,
    inference: report.inference.length,
    motion: report.motion.length,
  }),
);
