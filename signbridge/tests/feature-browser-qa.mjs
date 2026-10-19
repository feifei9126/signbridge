// Actual extension navigation, settings, research access and motion preview.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveTestResultsDir } from "../scripts/test-results-dir.mjs";
const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const extension = resolve(
  process.env.SIGNBRIDGE_DEMO_BUILD_DIR || join(root, "dist"),
);
const metadata = JSON.parse(
  await readFile(join(extension, "BUILD.json"), "utf8"),
);
const output = resolve(
  process.env.SIGNBRIDGE_FEATURE_QA_DIR ||
    join(resolveTestResultsDir(root), "feature-browser"),
);
const profile = await mkdtemp(join(tmpdir(), "signbridge-features-"));
const report = { status: "running", checks: [], errors: [] };
async function installPlaybackTiming(page) {
  await page.evaluate(() => {
    window.__signbridgePlaybackTiming = {
      armed: false,
      clickedAt: null,
      firstUpdateMs: null,
    };
    document.addEventListener(
      "click",
      (event) => {
        const timing = window.__signbridgePlaybackTiming;
        if (timing?.armed && event.target.closest("#play"))
          timing.clickedAt = performance.now();
      },
      true,
    );
    window.addEventListener("message", (event) => {
      const timing = window.__signbridgePlaybackTiming;
      if (
        timing?.armed &&
        timing.clickedAt !== null &&
        event.source === document.querySelector("#avatar")?.contentWindow &&
        event.data?.source === "signbridge-demo-avatar" &&
        event.data.type === "PROGRESS"
      ) {
        timing.armed = false;
        timing.firstUpdateMs = performance.now() - timing.clickedAt;
      }
    });
  });
}

async function measurePlaybackStart(page) {
  await page.evaluate(() => {
    window.__signbridgePlaybackTiming.armed = true;
    window.__signbridgePlaybackTiming.clickedAt = null;
    window.__signbridgePlaybackTiming.firstUpdateMs = null;
  });
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    Number.isFinite(window.__signbridgePlaybackTiming.firstUpdateMs),
  );
  return page.evaluate(() => window.__signbridgePlaybackTiming.firstUpdateMs);
}

const server = createServer((_request, response) => {
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(
    '<!doctype html><html><head><title>Local feature check</title></head><body><video></video><p class="subtitle-text"></p></body></html>',
  );
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let context;
try {
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
    headless: true,
    locale: "zh-CN",
    viewport: { width: 1280, height: 950 },
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
      "--enable-unsafe-swiftshader",
    ],
  });
  context.on("page", (page) =>
    page.on("pageerror", (error) => report.errors.push(error.message)),
  );
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const origin = `chrome-extension://${new URL(worker.url()).host}`;
  report.extension_origin = origin;
  const previousAsr = {
    provider: "local",
    localModel: "base",
    cloudEndpoint: "https://speech.example.test/v1/audio",
    cloudApiKey: "test-only-marker",
    cloudModel: "existing-model",
    language: "zh",
    chunkSeconds: 9,
  };
  await worker.evaluate(async (asr) => {
    await chrome.storage.sync.set({
      signbridge_config: {
        avatarSize: 260,
        uiLocale: "zh-CN",
        avatarStyle: "old-preserved-value",
        sourceLanguage: "auto",
      },
    });
    await chrome.storage.local.set({ signbridge_asr_config: asr });
  }, previousAsr);
  const video = await context.newPage();
  await video.goto(`http://127.0.0.1:${server.address().port}/`);
  await video.waitForFunction(
    () =>
      document.getElementById("signbridge-overlay") &&
      !document.getElementById("sb-loading"),
  );
  const popup = await context.newPage();
  await video.bringToFront();
  await popup.goto(`${origin}/popup/index.html`);
  await popup.waitForFunction(() =>
    document.querySelector("#extension-version").textContent.startsWith("v"),
  );
  assert.equal(await popup.locator("select").count(), 0);
  assert.equal(await popup.locator("button").count(), 6);
  await popup.locator("#textInput").fill("你好");
  await popup.locator("#btnSendText").click();
  await video.locator("#signbridge-motion-source").waitFor();
  assert.match(
    await video.locator("#signbridge-motion-source").textContent(),
    /词库/,
  );
  await mkdir(output, { recursive: true });
  await popup.setViewportSize({ width: 360, height: 650 });
  await popup.screenshot({ path: join(output, "popup.png") });
  const settingsOpened = context.waitForEvent("page");
  await popup.locator("#btnSettings").click();
  const settings = await settingsOpened;
  await settings.waitForURL(`${origin}/options/asr-settings.html`);
  await settings.waitForFunction(
    () => document.querySelector("#localModel").value === "base",
  );
  assert.equal(
    await settings.locator("#asr-advanced").getAttribute("open"),
    null,
  );
  assert.equal(await settings.locator("#cloudEndpoint").isVisible(), false);
  await settings.locator("#avatarSize").evaluate((node) => {
    node.value = "300";
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settings.locator("#btnSave").click();
  await settings.waitForFunction(() =>
    document.querySelector("#saveStatus").textContent.includes("已保存"),
  );
  assert.equal(
    await video
      .locator("#signbridge-overlay")
      .evaluate((node) => node.style.width),
    "300px",
  );
  const saved = await worker.evaluate(async () => ({
    sync: await chrome.storage.sync.get("signbridge_config"),
    local: await chrome.storage.local.get("signbridge_asr_config"),
  }));
  assert.equal(saved.sync.signbridge_config.avatarStyle, "old-preserved-value");
  assert.deepEqual(saved.local.signbridge_asr_config, previousAsr);
  await settings.reload();
  await settings.waitForFunction(
    () => document.querySelector("#avatarSize").value === "300",
  );
  await settings.locator("#asr-advanced > summary").click();
  await settings.locator('input[name="provider"][value="cloud"]').check();
  assert.equal(await settings.locator("#cloudEndpoint").isVisible(), true);
  assert.equal(await settings.locator("#localModelPanel").isVisible(), false);
  // Do not send audio or request remote permissions in this regression.
  await settings.locator('input[name="provider"][value="local"]').check();
  await settings.locator("#asr-advanced > summary").click();
  await settings.screenshot({
    path: join(output, "settings.png"),
    fullPage: true,
  });
  report.checks.push(
    "six-action popup sends text to the real avatar; one settings entry preserves ASR and legacy data and resizes open avatars",
  );
  const workspaceOpened = context.waitForEvent("page");
  await popup.locator("#btnDemo").click();
  const page = await workspaceOpened;
  await page.waitForURL(`${origin}/demo/index.html`);
  await page.locator("#input").fill("你好，谢谢");
  await page.waitForFunction(() => !document.querySelector("#play").disabled);
  assert.equal(
    await page.locator("#research-details").getAttribute("open"),
    null,
  );
  assert.equal(
    await page.locator('[data-mode="dictionary"]').isVisible(),
    false,
  );
  assert.equal(await page.locator("#download").isVisible(), false);
  assert.equal(await page.locator("#tokens").isVisible(), false);
  assert.equal(await page.locator("#speed").isVisible(), true);
  assert.equal(await page.locator("#stabilization-profile").isVisible(), false);
  if (metadata.profile === "local-research") {
    await page.locator("#research-details > summary").click();
    assert.equal(
      await page.locator("#stabilization-profile").isVisible(),
      true,
    );
    const fittedIndex = JSON.parse(
      await readFile(join(extension, "demo/experimental-index.json"), "utf8"),
    );
    const sample = fittedIndex.clips[0];
    await page.locator("#stabilization-profile").selectOption("asset");
    await page.locator("#input").fill(sample.text);
    await installPlaybackTiming(page);
    const coldToFirstUpdateMs = await measurePlaybackStart(page);
    await page.waitForFunction(
      () =>
        document.querySelector("#status").textContent.startsWith("正在播放") &&
        Number(
          document.querySelector("#progress-text").textContent.split(" /")[0],
        ) > 1,
    );
    await page.locator("#pause").click();
    await page.waitForFunction(() =>
      document.querySelector("#status").textContent.includes("暂停"),
    );
    await page.screenshot({
      path: join(output, "sample-existing-profile.png"),
    });
    await page.locator("#stabilization-profile").selectOption("adaptive");
    await page.waitForFunction(
      () =>
        document.querySelector("#stabilization-profile").dataset
          .activeProfile === "adaptive",
    );
    await page.waitForTimeout(300);
    assert.match(
      await page.locator("#source-badge").textContent(),
      /隔离尖峰/,
      `profile=${await page.locator("#stabilization-profile").inputValue()} runtime=${await page.locator("#stabilization-profile").getAttribute("data-active-clip")} experimental=${await page.locator("#stabilization-profile").getAttribute("data-experimental-clip")} status=${await page.locator("#status").textContent()} badge=${await page.locator("#source-badge").textContent()}`,
    );
    await page.screenshot({
      path: join(output, "sample-isolated-spike-experiment.png"),
    });
    const reportDownload = page.waitForEvent("download");
    await page.locator("#download").click();
    const downloaded = await reportDownload;
    const session = JSON.parse(await readFile(await downloaded.path(), "utf8"));
    assert.equal(
      session.lastPlayedMotion.presentation,
      "quaternion-temporal-adaptive-v1",
    );
    assert.equal(session.lastPlayedMotion.trainingReady, false);
    assert.ok(session.lastPlayedMotion.performance.compileMs >= 0);
    assert.ok(session.lastPlayedMotion.performance.numericBytes >= 0);
    const beforeSwitch = Number(
      await page
        .locator("#progress-text")
        .textContent()
        .then((v) => v.split(" /")[0]),
    );
    await page.locator("#stabilization-profile").selectOption("asset");
    await page.waitForTimeout(150);
    const afterSwitch = Number(
      (await page.locator("#progress-text").textContent()).split(" /")[0],
    );
    assert.ok(afterSwitch >= beforeSwitch);
    const cachedDownload = page.waitForEvent("download");
    await page.locator("#download").click();
    const cachedFile = await cachedDownload;
    const cachedSession = JSON.parse(
      await readFile(await cachedFile.path(), "utf8"),
    );
    assert.equal(cachedSession.lastPlayedMotion.performance.cacheHit, true);
    await page.locator("#stop").click();
    const warmReplayToFirstUpdateMs = [];
    for (let index = 0; index < 3; index++) {
      await page.waitForFunction(
        () => document.querySelector("#stop").disabled,
      );
      warmReplayToFirstUpdateMs.push(await measurePlaybackStart(page));
      await page.locator("#stop").click();
    }
    assert.ok(Number.isFinite(coldToFirstUpdateMs) && coldToFirstUpdateMs >= 0);
    assert.equal(warmReplayToFirstUpdateMs.length, 3);
    assert.ok(warmReplayToFirstUpdateMs.every(Number.isFinite));
    report.playbackStartup = {
      clipId: sample.id,
      coldToFirstUpdateMs,
      warmReplayToFirstUpdateMs,
      warmCacheHit: cachedSession.lastPlayedMotion.performance.cacheHit,
      milestone:
        "play-click-to-first-progress-message-after-pose-apply-and-render-call",
      environment: "headless-chromium-local-research-build",
    };
    await page.locator("#research-details > summary").click();
    assert.equal(
      await page.locator("#research-details").getAttribute("open"),
      null,
    );
  }
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.startsWith("正在播放"),
  );
  await page.locator("#pause").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("暂停"),
  );
  await page.locator("#pause").click();
  await page.locator("#stop").click();
  await page.screenshot({
    path: join(output, "workspace.png"),
    fullPage: true,
  });
  await page.locator("#open-research").click();
  assert.equal(
    await page.locator("#research-details").getAttribute("open"),
    "",
  );
  assert.equal(await page.locator("#extension-tools").isVisible(), true);
  await page.locator("#motion-authoring > summary").click();
  for (const [id, path] of [
    ["btnPoseEditor", "avatar/pose-editor.html"],
    ["btnRecordMode", "avatar/record-mode.html"],
    ["btnCoverage", "tools/coverage.html"],
    ["btnMotionReview", "tools/motion-review.html"],
  ]) {
    assert.equal(await page.locator(`#${id}`).isVisible(), true);
    assert.equal(
      await page.evaluate(async (path) => (await fetch(path)).ok, `../${path}`),
      true,
    );
  }
  await page.locator('[data-mode="semantic"]').click();
  assert.equal(await page.locator("#playback-actions").isVisible(), false);
  await page.locator("#input").fill("我帮你");
  await page.locator("#input").press("Control+Enter");
  assert.match(await page.locator("#status").textContent(), /分析/);
  await page.locator("#research-details > summary").click();
  await page.waitForFunction(
    () =>
      document
        .querySelector('[data-mode="auto"]')
        .getAttribute("aria-pressed") === "true",
  );
  assert.equal(await page.locator("#playback-actions").isVisible(), true);
  report.checks.push(
    "ordinary motion preview works; research preserves all four tools, hides technical controls by default and restores automatic routing on close",
  );
  // In-progress playback must leave with the motion task. Analysis never starts a model call on navigation.
  await page.locator("#input").fill("你好，谢谢");
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.startsWith("正在播放"),
  );
  let inferenceRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/v1/understand")) inferenceRequests++;
  });
  await page.locator("#meaning-task").click();
  await page.waitForURL(`${origin}/private/index.html?scope=1`);
  assert.equal(await page.locator("#token").inputValue(), "");
  assert.equal(await page.locator("#analysis-fields").isVisible(), false);
  assert.equal(await page.locator("#output").textContent(), "");
  assert.equal(inferenceRequests, 0);
  assert.equal(await page.locator("iframe").count(), 0);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.screenshot({
    path: join(output, "meaning-mobile.png"),
    fullPage: true,
  });
  await page.locator('[data-workbench] a[href="../demo/index.html"]').click();
  await page.waitForFunction(() => document.querySelector("#stop").disabled);
  assert.equal(
    await page.locator("#research-details").getAttribute("open"),
    null,
  );
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.screenshot({
    path: join(output, "workspace-mobile.png"),
    fullPage: true,
  });
  report.checks.push(
    "trained-model task shares the client, makes no automatic request, clears playback on navigation and fits mobile screens",
  );
  report.profile = JSON.parse(
    await readFile(join(extension, "BUILD.json"), "utf8"),
  ).profile;
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} finally {
  await mkdir(output, { recursive: true });
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await context?.close();
  await new Promise((resolve) => server.close(resolve));
  await rm(profile, { recursive: true, force: true });
}
console.log(JSON.stringify(report));
