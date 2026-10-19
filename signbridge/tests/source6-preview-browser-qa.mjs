// Run against a separately served candidate-only preview; never mutates data.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { buildDemoPhraseCatalog } from "../src/demo/phrase-catalog.js";
import { validateExperimentalIndex } from "../src/demo/experimental-motion.js";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = process.env.SIGNBRIDGE_SOURCE6_PREVIEW_ROOT;
const output = process.env.SIGNBRIDGE_DEMO_QA_DIR;
const url = process.env.SIGNBRIDGE_DEMO_URL;
if (!root || !output || !url)
  throw new Error("Set preview root, a new QA output directory and served URL");
const json = async (path) => JSON.parse(await readFile(path, "utf8"));
const index = validateExperimentalIndex(
  await json(join(root, "demo/experimental-index.json")),
);
assert.equal(index.clips.length, 12);
assert.ok(
  index.clips.every((c) => c.preview_only && c.source_batch === "source-6"),
);
const reference = await json(join(root, "demo/t08-motion.json"));
const candidates = await json(join(root, "demo/t08-candidates.json"));
const catalog = buildDemoPhraseCatalog([
  ...reference.clips,
  ...candidates.clips,
  ...index.clips,
]);
await mkdir(output, { recursive: false });
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
  schema: "signbridge-source6-avatar-browser-qa-v1",
  status: "running",
  startedAt: new Date().toISOString(),
  url,
  indexSha256: createHash("sha256")
    .update(await readFile(join(root, "demo/experimental-index.json")))
    .digest("hex"),
  checks: [],
  clips: [],
  errors: [],
  networkFailures: [],
  requests: [],
  semanticSignAccuracy: "not_assessed",
  humanApproved: false,
  trainingReady: false,
  modelTrainingReady: false,
  trainingWeightsUpdated: false,
};
page.on("pageerror", (error) => report.errors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") report.errors.push(message.text());
});
page.on("response", (response) => {
  if (response.status() >= 400)
    report.networkFailures.push({
      url: response.url(),
      status: response.status(),
    });
});
page.on("request", (request) => {
  if (/experimental\/.*\.json/.test(request.url()))
    report.requests.push(request.url());
});
async function capture() {
  const bytes = await page
    .frameLocator("#avatar")
    .locator("canvas")
    .screenshot();
  return { bytes, hash: createHash("sha256").update(bytes).digest("hex") };
}
try {
  await page.goto(url);
  await page.locator("#research-details").evaluate((node) => {
    node.open = true;
  });
  await page.waitForFunction(
    () =>
      document.querySelector("#experimental-count").textContent === "12" &&
      !document.querySelector("#play").disabled,
    undefined,
    { timeout: 30000 },
  );
  assert.equal(report.requests.length, 0);
  assert.equal(await page.locator("#input").inputValue(), index.clips[0].text);
  assert.equal(
    await page.locator("#catalog-count").textContent(),
    `${catalog.length} / ${catalog.length}`,
  );
  assert.ok(
    (await page.locator("#experimental-warning").textContent()).includes(
      "文字和动作首尾是未核验候选",
    ),
  );
  await page.screenshot({ path: join(output, "desktop.png"), fullPage: true });
  await page.locator("#speed").selectOption("1.5");
  report.catalogCount = catalog.length;
  report.checks.push(
    "12 source-6 candidates, explicit unverified-label warning and lazy pose loading",
  );
  await page.locator("#input").fill(index.clips[0].text);
  await page.locator("#play").click();
  await page.waitForFunction(
    () =>
      parseFloat(document.querySelector("#progress-text").textContent) > 0.2,
  );
  await page.locator("#stop").click();
  await page.waitForFunction(
    () =>
      document.querySelector("#progress-text").textContent === "0:00" &&
      document.querySelector("#pause").disabled,
  );
  report.checks.push(
    "Stopping an active source-6 clip returns the avatar to idle",
  );
  for (const [number, clip] of index.clips.entries()) {
    await page.locator("#input").fill(clip.text);
    await page.locator("#play").click();
    const duration = clip.frames / clip.fps;
    await page.waitForFunction(
      (minimum) =>
        document
          .querySelector("#source-badge")
          .textContent.includes("SMPL-X") &&
        parseFloat(document.querySelector("#progress-text").textContent) >
          minimum,
      Math.min(1.2, duration * 0.25),
      { timeout: 15000 },
    );
    const before = await capture();
    await page.waitForTimeout(220);
    const moving = await capture();
    assert.notEqual(before.hash, moving.hash, "Static avatar: " + clip.id);
    await page.locator("#pause").click();
    await page.waitForFunction(() =>
      document.querySelector("#status").textContent.includes("已暂停"),
    );
    const time = await page.locator("#progress-text").textContent();
    const paused = await capture();
    await page.waitForTimeout(120);
    assert.equal(
      paused.hash,
      (await capture()).hash,
      "Paused avatar changed: " + clip.id,
    );
    await writeFile(join(output, clip.id + "-smoothed.png"), paused.bytes);
    await page.locator("#motion-smoothing").uncheck();
    await page.waitForFunction(() =>
      document.querySelector("#source-badge").textContent.includes("原始"),
    );
    assert.equal(await page.locator("#progress-text").textContent(), time);
    const raw = await capture();
    await writeFile(join(output, clip.id + "-raw.png"), raw.bytes);
    await page.locator("#motion-smoothing").check();
    await page.waitForFunction(() =>
      document.querySelector("#source-badge").textContent.includes("平滑"),
    );
    if (number === 0) {
      const event = page.waitForEvent("download");
      await page.locator("#download").click();
      await (await event).saveAs(join(output, "session.json"));
      const session = await json(join(output, "session.json"));
      assert.equal(session.textToSignGenerated, false);
      assert.equal(session.lastPlayedMotion.id, clip.id);
      assert.equal(session.lastPlayedMotion.experimental, true);
      assert.equal(session.lastPlayedMotion.humanApproved, false);
      assert.equal(session.lastPlayedMotion.trainingReady, false);
      assert.equal(
        session.lastPlayedMotion.presentation,
        "quaternion-temporal-v1",
      );
      assert.equal(session.lastPlayedMotion.motionAssetSha256, clip.sha256);
      assert.equal(session.matched.length, 1);
      assert.equal(session.matched[0].id, clip.id);
      report.checks.push(
        "Session export identifies the exact fitted asset, display profile and false approval/training flags",
      );
    }
    assert.ok(
      report.requests.some((request) => request.includes(clip.id + ".json")),
      "Wrong source asset: " + clip.id,
    );
    assert.ok(
      (await page.locator("#tokens").textContent()).includes("未更新模型权重"),
    );
    await page.locator("#pause").click();
    await page.waitForFunction(
      () => document.querySelector("#status").textContent === "本次播放完成。",
      undefined,
      { timeout: 20000 },
    );
    assert.equal(await page.locator("#progress-text").textContent(), "0:00");
    report.clips.push({
      id: clip.id,
      text: clip.text,
      frames: clip.frames,
      fps: clip.fps,
      duration,
      screenshotElapsedDisplay: time,
      nativeInputAssetVerified: true,
      animatedCanvas: true,
      pauseHeld: true,
      rawSwitchHeldTime: true,
      completePlaybackFinished: true,
    });
  }
  for (const [label, width, height] of [
    ["tablet", 768, 1024],
    ["mobile", 375, 812],
  ]) {
    await page.setViewportSize({ width, height });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      "Overflow: " + label,
    );
    await page.screenshot({
      path: join(output, label + ".png"),
      fullPage: true,
    });
  }
  assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
  assert.equal(
    report.networkFailures.length,
    0,
    JSON.stringify(report.networkFailures),
  );
  report.checks.push(
    "All twelve source-6 clips animate, pause, switch raw/smoothed and finish with original frame timing",
    "Desktop, tablet and mobile layouts render without horizontal overflow",
  );
  report.status = "passed";
} catch (error) {
  report.failure = String(error);
  report.status = "failed";
  throw error;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await browser.close();
  console.log(
    JSON.stringify(
      {
        output,
        status: report.status,
        clips: report.clips.length,
        errors: report.errors,
        failure: report.failure,
      },
      null,
      2,
    ),
  );
}
