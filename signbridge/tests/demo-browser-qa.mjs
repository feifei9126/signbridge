// Optional real-browser acceptance: npm run build, serve dist, then run this script.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { buildDemoPhraseCatalog } from "../src/demo/phrase-catalog.js";
const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out =
  process.env.SIGNBRIDGE_DEMO_QA_DIR ||
  join(root, "../local-data/demo-20261012/browser-qa");
await mkdir(out, { recursive: true });
const url =
  process.env.SIGNBRIDGE_DEMO_URL || "http://127.0.0.1:8766/demo/index.html";
const data = JSON.parse(
  await readFile(join(root, "dist/demo/t08-motion.json"), "utf8"),
);
const candidateData = JSON.parse(
  await readFile(join(root, "dist/demo/t08-candidates.json"), "utf8"),
);
const candidateClips = candidateData.clips || [];
const experimentalData = JSON.parse(
  await readFile(join(root, "dist/demo/experimental-index.json"), "utf8"),
);
const catalog = buildDemoPhraseCatalog([
  ...data.clips,
  ...candidateClips,
  ...(experimentalData.clips || []),
]);
const phraseCount = catalog.filter((c) => c.source !== "composition").length;
const composedPhraseCount = catalog.filter(
  (c) => c.source === "composition",
).length;
const catalogCount = catalog.length;
const browser = await chromium.launch({
  headless: true,
  ...(process.env.SIGNBRIDGE_CHROME
    ? { executablePath: process.env.SIGNBRIDGE_CHROME }
    : {}),
  args: ["--enable-unsafe-swiftshader"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
const page = await context.newPage();
const report = {
  schema: "signbridge-demo-browser-qa-v1",
  status: "running",
  startedAt: new Date().toISOString(),
  browser: browser.version(),
  url,
  t08: [],
  candidates: [],
  dictionary: [],
  checks: [],
  errors: [],
  networkFailures: [],
  screenshots: [],
  semanticSignAccuracy: "not-assessed",
  assetSha256: createHash("sha256")
    .update(await readFile(join(root, "dist/demo/t08-motion.json")))
    .digest("hex"),
};
page.on("pageerror", (e) => report.errors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error") report.errors.push(m.text());
});
page.on("response", (r) => {
  if (r.status() >= 400)
    report.networkFailures.push({ url: r.url(), status: r.status() });
});
async function screenshot(file, fullPage = true) {
  await page.screenshot({ path: join(out, file), fullPage });
  report.screenshots.push(file);
}
async function ready() {
  await page.waitForFunction(() => !document.querySelector("#play").disabled, {
    timeout: 30000,
  });
}
async function played(text) {
  await page.locator("#input").fill(text);
  await page.locator("#play").click();
  await page.waitForFunction(
    () => document.querySelector("#status").textContent.startsWith("正在播放"),
    { timeout: 10000 },
  );
}
try {
  await page.goto(url);
  await ready();
  assert.equal(
    await page.locator("#catalog-count").textContent(),
    `${catalogCount} / ${catalogCount}`,
  );
  assert.equal(await page.locator("#model-count").textContent(), "14");
  assert.equal(
    await page.locator("#candidate-count").textContent(),
    String(candidateClips.length),
  );
  assert.equal(
    await page.locator('[data-source="composition"]').count(),
    composedPhraseCount,
  );
  assert.ok(
    (await page.locator("#catalog-note").textContent()).includes(
      `${composedPhraseCount} 条词库组合`,
    ),
  );
  await screenshot("desktop.png");
  report.checks.push("70 phrase catalog with explicit source counts");
  await page.evaluate(() => {
    document.querySelector("#play").click();
    document.querySelector('[data-mode="dictionary"]').click();
  });
  await page.waitForTimeout(200);
  assert.equal(await page.locator("#current").textContent(), "待机");
  assert.equal(await page.locator("#pause").isDisabled(), true);
  assert.equal(
    await page.locator("#status").textContent(),
    "已就绪，输入文字或选择片段。",
  );
  await page.locator('[data-mode="auto"]').click();
  report.checks.push(
    "immediate play / mode switch ignores superseded iframe events",
  );
  await page.locator("[data-catalog-view=phrases]").click();
  await page.locator("#search").fill("我可以帮助你");
  assert.equal(await page.locator('[data-source="composition"]').count(), 1);
  await page.locator('[data-source="composition"]').click();
  assert.equal(await page.locator("#input").inputValue(), "我可以帮助你");
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    document.querySelector("#source-badge").textContent.includes("词库"),
  );
  await page.waitForFunction(
    () => document.querySelector("#status").textContent === "本次播放完成。",
    { timeout: 15000 },
  );
  assert.equal(
    await page.locator("#tokens").textContent(),
    "当前播放内置词库动作，不使用 T08 token。",
  );
  await page.locator("#search").fill("");
  report.checks.push(
    "composed phrase plays dictionary motions and is not routed as trained T08",
  );
  await played("工作忙吗？谢谢🚀");
  await page.waitForFunction(
    () =>
      parseFloat(document.querySelector("#progress-text").textContent) > 0.3,
  );
  await page.locator("#pause").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("已暂停"),
  );
  const paused = await page.locator("#progress-text").textContent();
  await page.waitForTimeout(250);
  assert.equal(await page.locator("#progress-text").textContent(), paused);
  await screenshot("t08-paused.png");
  const tokens = JSON.parse(await page.locator("#tokens").textContent());
  assert.ok(tokens.body.length > 0);
  assert.ok((await page.locator("#unknown").textContent()).includes("🚀"));
  await page.locator("#pause").click();
  await page.waitForFunction(
    (previous) =>
      document.querySelector("#progress-text").textContent !== previous,
    paused,
  );
  await page.locator("#stop").click();
  assert.equal(await page.locator("#current").textContent(), "待机");
  report.checks.push(
    "mixed matching, real tokens, unknown text, pause, resume, stop",
  );
  await played("工作忙吗？");
  await page.waitForFunction(
    () =>
      parseFloat(document.querySelector("#progress-text").textContent) > 0.2,
  );
  await page.locator("#play").click();
  await page.waitForFunction(
    () =>
      parseFloat(document.querySelector("#progress-text").textContent) < 0.2,
  );
  await page.locator("#stop").click();
  report.checks.push("cached replay resets clock");
  await page.locator("[data-view=left]").click();
  assert.equal(
    await page.locator("[data-view=left]").getAttribute("aria-pressed"),
    "true",
  );
  await screenshot("left-view.png");
  await page.locator("[data-view=right]").click();
  await screenshot("right-view.png");
  await page.locator("[data-view=front]").click();
  await page.locator("#speed").selectOption("1.5");
  report.checks.push("three views and speed");
  await page.locator("[data-mode=t08]").click();
  assert.equal(
    await page.locator("#catalog-count").textContent(),
    `${phraseCount} / ${phraseCount}`,
  );
  for (const [i, clip] of data.clips.entries()) {
    await played(clip.text);
    await page.waitForFunction(
      () =>
        parseFloat(document.querySelector("#progress-text").textContent) > 0.1,
    );
    const actual = JSON.parse(await page.locator("#tokens").textContent());
    assert.deepEqual(actual, clip.tokens);
    if ([0, 2, 11].includes(i)) {
      await page.waitForTimeout(500);
      await screenshot(`t08-${i + 1}.png`);
    }
    await page.waitForFunction(
      () => document.querySelector("#status").textContent === "本次播放完成。",
      { timeout: Math.ceil(clip.duration * 1600) + 10000 },
    );
    report.t08.push({
      id: clip.id,
      frames: clip.frames,
      tokensVerified: true,
      playback: "completed",
    });
    console.log(`T08 completed ${i + 1}/14: ${clip.id}`);
  }
  for (const [i, clip] of candidateClips.entries()) {
    await played(clip.text);
    await page.waitForFunction(() =>
      document.querySelector("#source-badge").textContent.includes("候选"),
    );
    assert.deepEqual(
      JSON.parse(await page.locator("#tokens").textContent()),
      clip.tokens,
    );
    await page.waitForTimeout(500);
    await screenshot(`candidate-${i + 1}.png`);
    await page.waitForFunction(
      () => document.querySelector("#status").textContent === "本次播放完成。",
      undefined,
      { timeout: Math.ceil(clip.duration * 1600) + 10000 },
    );
    report.candidates.push({
      id: clip.id,
      frames: clip.frames,
      tokensVerified: true,
      candidateLabelVerified: true,
      trainingWeightsUpdated: false,
      playback: "completed",
    });
    console.log(`Candidate completed ${i + 1}/3: ${clip.id}`);
  }
  await page.locator("[data-mode=dictionary]").click();
  await page.locator("[data-catalog-view=words]").click();
  assert.equal(await page.locator("#catalog-count").textContent(), "52 / 52");
  const labels = await page.locator("#catalog-list button").allTextContents();
  for (const [i, label] of labels.entries()) {
    await played(label);
    await page.waitForFunction(
      () => document.querySelector("#status").textContent === "本次播放完成。",
      { timeout: 10000 },
    );
    report.dictionary.push({ text: label, playback: "completed" });
    if ((i + 1) % 13 === 0) console.log(`Dictionary completed ${i + 1}/52`);
  }
  await page.locator("#input").fill("宇宙飞船🚀");
  assert.equal(await page.locator("#play").isDisabled(), true);
  assert.ok((await page.locator("#unknown").textContent()).includes("🚀"));
  await page.locator("#input").fill("你好");
  await page.locator("#input").press("Control+Enter");
  await page.waitForFunction(
    () => document.querySelector("#status").textContent === "本次播放完成。",
  );
  report.checks.push("unknown-only and keyboard playback");
  await page.locator("#search").fill("不存在的条目");
  assert.equal(await page.locator("#catalog-list button").count(), 0);
  await page.locator("#search").fill("谢谢");
  assert.equal(await page.locator("#catalog-list button").count(), 1);
  await page.locator("#catalog-list button").click();
  assert.equal(await page.locator("#input").inputValue(), "谢谢");
  await page.locator("#search").fill("");
  report.checks.push("search and selecting an example");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download").click();
  const download = await downloadPromise;
  await download.saveAs(join(out, "session.json"));
  const session = JSON.parse(await readFile(join(out, "session.json"), "utf8"));
  assert.equal(session.matched[0].source, "dictionary");
  assert.equal(session.textToSignGenerated, false);
  assert.equal(session.checkpointSha256, data.checkpoint_sha256);
  report.checks.push("session JSON download and provenance");
  const research = await page.locator("#research-list button").count();
  assert.equal(research, 6);
  for (let i = 0; i < research; i++) {
    await page.locator("#research-list button").nth(i).click();
    await page.waitForFunction(() => {
      const img = document.querySelector("#research-image");
      return img.complete && img.naturalWidth > 0;
    });
    await page.locator("#close-preview").click();
    assert.equal(await page.locator("#research-preview").isVisible(), false);
  }
  report.checks.push("six read-only keyframe comparison images");
  await page.locator("[data-mode=auto]").click();
  await page.locator("[data-catalog-view=phrases]").click();
  await page.locator("#input").fill("工作忙吗？谢谢");
  for (const width of [768, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await screenshot(`responsive-${width}.png`);
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
  }
  report.checks.push("375px / 768px layouts without horizontal overflow");
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.networkFailures, []);
  const fallback = await context.newPage();
  await fallback.route("**/t08-motion.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"unavailable":true}',
    }),
  );
  await fallback.route("**/t08-candidates.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"clips":[]}',
    }),
  );
  await fallback.route("**/experimental-index.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"unavailable":true}',
    }),
  );
  await fallback.goto(url);
  await fallback.waitForFunction(
    () => !document.querySelector("#play").disabled,
  );
  assert.equal(await fallback.locator("#model-count").textContent(), "0");
  assert.equal(
    await fallback.locator("#catalog-count").textContent(),
    `${composedPhraseCount} / ${composedPhraseCount}`,
  );
  await fallback.locator("[data-catalog-view=words]").click();
  assert.equal(
    await fallback.locator("#catalog-count").textContent(),
    "52 / 52",
  );
  await fallback.locator("#input").fill("谢谢");
  await fallback.locator("#play").click();
  await fallback.waitForFunction(
    () => document.querySelector("#status").textContent === "本次播放完成。",
  );
  await fallback.locator("[data-mode=t08]").click();
  assert.equal(await fallback.locator("#play").isDisabled(), true);
  await fallback.close();
  report.checks.push("T08 unavailable still allows dictionary playback");
  const failed = await context.newPage();
  await failed.route("**/avatar/model.glb", (route) =>
    route.fulfill({ status: 503, body: "test-model-unavailable" }),
  );
  await failed.goto(url);
  await failed.locator("#retry").waitFor({ state: "visible" });
  assert.equal(await failed.locator("#play").isDisabled(), true);
  await failed.unroute("**/avatar/model.glb");
  await failed.locator("#retry").click();
  await failed.waitForFunction(() => !document.querySelector("#play").disabled);
  await failed.close();
  report.checks.push("model load failure exposes a working reload action");
  if (process.env.SIGNBRIDGE_EXTENSION_CHROME) {
    const extension = join(root, "dist");
    const extensionContext = await chromium.launchPersistentContext("", {
      executablePath: process.env.SIGNBRIDGE_EXTENSION_CHROME,
      headless: true,
      viewport: { width: 1440, height: 1000 },
      args: [
        `--disable-extensions-except=${extension}`,
        `--load-extension=${extension}`,
        "--enable-unsafe-swiftshader",
      ],
    });
    try {
      const worker =
        extensionContext.serviceWorkers()[0] ||
        (await extensionContext.waitForEvent("serviceworker", {
          timeout: 15000,
        }));
      const id = worker.url().split("/")[2];
      const popup = await extensionContext.newPage();
      await popup.goto(`chrome-extension://${id}/popup/index.html`);
      const opened = extensionContext.waitForEvent("page");
      await popup.locator("#btnDemo").click();
      const demo = await opened;
      await demo.waitForURL(`chrome-extension://${id}/demo/index.html`);
      await demo.waitForFunction(
        () => !document.querySelector("#play").disabled,
        { timeout: 30000 },
      );
      assert.equal(
        await demo.locator("#catalog-count").textContent(),
        `${catalogCount} / ${catalogCount}`,
      );
      await demo.locator("#play").click();
      await demo.waitForFunction(
        () =>
          parseFloat(document.querySelector("#progress-text").textContent) >
          0.2,
      );
      await demo.locator("#pause").click();
      await demo.screenshot({
        path: join(out, "extension.png"),
        fullPage: true,
      });
      report.screenshots.push("extension.png");
      report.extension = {
        id,
        popupEntry: "passed",
        t08Playback: "passed",
        origin: await demo.evaluate(() => location.origin),
      };
      report.checks.push(
        "actual unpacked extension, popup Demo entry and T08 playback",
      );

      const live = await extensionContext.newPage();
      const motionSources = [];
      const frameErrors = [];
      live.on("pageerror", (error) => frameErrors.push(error.message));
      await live.addInitScript(() => {
        window.__signbridgeMessages = [];
        window.addEventListener("message", (event) => {
          if (
            event.source === window &&
            event.data?.source === "signbridge-iframe"
          )
            window.__signbridgeMessages.push(event.data);
        });
      });
      await live.goto(`chrome-extension://${id}/avatar/avatar-frame.html`);
      await live.waitForFunction(
        () =>
          window.__signbridgeMessages?.some(
            (message) => message.type === "LOADED",
          ),
        { timeout: 15000 },
      );
      await live.evaluate(() =>
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
      await live.waitForFunction(
        () =>
          window.__signbridgeMessages?.some(
            (message) => message.type === "READY",
          ),
        { timeout: 30000 },
      );
      await live.evaluate(() =>
        window.postMessage(
          {
            source: "signbridge-page",
            type: "SUBTITLE_TEXT",
            text: "工作忙吗？",
          },
          location.origin,
        ),
      );
      await live.waitForFunction(
        () =>
          window.__signbridgeMessages?.some(
            (message) =>
              message.type === "MOTION_SOURCE" && message.sourceType === "t08",
          ),
        { timeout: 20000 },
      );
      motionSources.push("t08");
      await live.evaluate(() =>
        window.postMessage(
          { source: "signbridge-page", type: "SUBTITLE_TEXT", text: "谢谢" },
          location.origin,
        ),
      );
      await live.waitForFunction(
        () =>
          window.__signbridgeMessages?.some(
            (message) =>
              message.type === "MOTION_SOURCE" &&
              message.sourceType === "dictionary",
          ),
        { timeout: 10000 },
      );
      motionSources.push("dictionary");
      assert.deepEqual(motionSources, ["t08", "dictionary"]);
      assert.deepEqual(frameErrors, []);
      await live.screenshot({ path: join(out, "extension-live-t08.png") });
      report.screenshots.push("extension-live-t08.png");
      report.checks.push(
        "production avatar iframe routes a live complete reference phrase to T08 and falls back to the dictionary",
      );
    } finally {
      await extensionContext.close();
    }
  }
  report.status = "passed";
  console.log("Demo browser acceptance passed");
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  throw error;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(
    join(out, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await browser.close();
}
