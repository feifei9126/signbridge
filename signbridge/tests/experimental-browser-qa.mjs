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
const output = process.env.SIGNBRIDGE_DEMO_QA_DIR;
if (!output) throw new Error("Set a new SIGNBRIDGE_DEMO_QA_DIR for evidence");
await mkdir(output, { recursive: false });
const url =
  process.env.SIGNBRIDGE_DEMO_URL || "http://127.0.0.1:8766/demo/index.html";
const buildRoot = process.env.SIGNBRIDGE_DEMO_BUILD_DIR || join(root, "dist");
const loadJson = async (path) =>
  JSON.parse(await readFile(join(buildRoot, "demo", path), "utf8"));
const index = await loadJson("experimental-index.json");
const catalog = buildDemoPhraseCatalog([
  ...(await loadJson("t08-motion.json")).clips,
  ...(await loadJson("t08-candidates.json")).clips,
  ...index.clips,
]);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.SIGNBRIDGE_CHROME,
  args: ["--enable-unsafe-swiftshader"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
const page = await context.newPage();
const report = {
  status: "running",
  startedAt: new Date().toISOString(),
  checks: [],
  clips: [],
  errors: [],
  requests: [],
  semanticAccuracy: "not-assessed",
  trainingWeightsUpdated: false,
};
page.on("pageerror", (e) => report.errors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error") report.errors.push(m.text());
});
page.on("request", (r) => {
  if (/experimental\/.*\.json/.test(r.url())) report.requests.push(r.url());
});
async function ready(target = page) {
  await target.waitForFunction(
    (count) =>
      document.querySelector("#experimental-count").textContent ===
        String(count) && !document.querySelector("#play").disabled,
    index.clips.length,
    { timeout: 30000 },
  );
  await target.locator('[data-source="experimental"]').first().waitFor();
}
async function play(text) {
  await page.locator("#input").fill(text);
  await page.locator("#play").click();
  await page.waitForFunction(
    () => document.querySelector("#source-badge").textContent.includes("实验"),
    undefined,
    { timeout: 15000 },
  );
}
async function canvasShot() {
  const bytes = await page
    .frameLocator("#avatar")
    .locator("canvas")
    .screenshot();
  const pixels = await page.evaluate(async (base64) => {
    const image = new Image();
    image.src = "data:image/png;base64," + base64;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(image, 0, 0);
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const colors = new Set();
    let foreground = 0;
    for (let i = 0; i < data.length; i += 16) {
      colors.add(`${data[i]},${data[i + 1]},${data[i + 2]}`);
      if (
        Math.abs(data[i] - 228) +
          Math.abs(data[i + 1] - 235) +
          Math.abs(data[i + 2] - 238) >
        35
      )
        foreground++;
    }
    return {
      colors: colors.size,
      foregroundRatio: foreground / (data.length / 16),
    };
  }, bytes.toString("base64"));
  assert.ok(
    pixels.colors > 100 && pixels.foregroundRatio > 0.03,
    JSON.stringify(pixels),
  );
  return {
    bytes,
    hash: createHash("sha256").update(bytes).digest("hex"),
    ...pixels,
  };
}
try {
  await page.goto(url);
  await page.locator("#research-details").evaluate((node) => {
    node.open = true;
  });
  await ready();
  assert.equal(await page.locator("#motion-smoothing").count(), 1);
  assert.equal(await page.locator("#motion-smoothing").isChecked(), true);
  assert.equal(
    await page.locator("#catalog-count").textContent(),
    `${catalog.length} / ${catalog.length}`,
  );
  const approvedCount = index.clips.filter(
    (clip) => clip.human_approved === true,
  ).length;
  if (approvedCount === index.clips.length && approvedCount > 0) {
    assert.match(
      await page.locator("#experimental-warning").textContent(),
      /动作质量人工审核|human motion-quality review/,
    );
  }
  assert.equal(report.requests.length, 0);
  await page.screenshot({ path: join(output, "desktop.png"), fullPage: true });
  report.checks.push("deduplicated catalog; no pose downloads before playback");
  for (const [i, clip] of index.clips.entries()) {
    await play(clip.text);
    assert.ok(
      (await page.locator("#source-badge").textContent()).includes("平滑"),
    );
    await page.waitForFunction(
      () =>
        parseFloat(document.querySelector("#progress-text").textContent) > 0.25,
    );
    const before = await canvasShot();
    await page.waitForTimeout(400);
    const after = await canvasShot();
    assert.notEqual(before.hash, after.hash, `Static canvas: ${clip.id}`);
    assert.ok(
      (await page.locator("#tokens").textContent()).includes("未更新模型权重"),
    );
    if (i === 0 || clip.text === "认识你很高兴")
      await writeFile(join(output, `${clip.id}.png`), after.bytes);
    report.clips.push({
      id: clip.id,
      frames: clip.frames,
      moving: true,
      foregroundRatio: after.foregroundRatio,
      qualityWarning: clip.quality_warning,
    });
    await page.locator("#stop").click();
    if ((i + 1) % 10 === 0)
      console.log(`Experimental clips checked: ${i + 1}/${index.clips.length}`);
  }
  report.checks.push(
    "every experimental clip hash-validated, compiled, rendered nonblank and moving",
  );
  const example = index.clips.find((c) => c.text === "认识你很高兴");
  await play(example.text);
  await page.waitForFunction(
    () =>
      parseFloat(document.querySelector("#progress-text").textContent) > 0.4,
  );
  await page.locator("#pause").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("已暂停"),
  );
  const time = await page.locator("#progress-text").textContent();
  await page.waitForTimeout(250);
  assert.equal(await page.locator("#progress-text").textContent(), time);
  const stable = await canvasShot();
  await page.locator("#motion-smoothing").uncheck();
  await page.waitForFunction(() =>
    document.querySelector("#source-badge").textContent.includes("原始"),
  );
  const raw = await canvasShot();
  assert.notEqual(stable.hash, raw.hash);
  assert.equal(await page.locator("#progress-text").textContent(), time);
  assert.ok((await page.locator("#status").textContent()).includes("已暂停"));
  await page.locator("#motion-smoothing").check();
  await page.waitForFunction(() =>
    document.querySelector("#source-badge").textContent.includes("平滑"),
  );
  assert.equal(await page.locator("#progress-text").textContent(), time);
  report.checks.push(
    "raw/smoothed comparison preserves pause state and timeline position",
  );
  await page.locator("#pause").click();
  await page.locator("#speed").selectOption("1.5");
  for (const view of ["left", "right", "front"]) {
    await page.locator(`[data-view=${view}]`).click();
    await canvasShot();
  }
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download").click();
  const download = await downloadPromise;
  await download.saveAs(join(output, "session.json"));
  const session = JSON.parse(
    await readFile(join(output, "session.json"), "utf8"),
  );
  assert.equal(session.lastPlayedMotion.source, "experimental");
  assert.equal(session.lastPlayedMotion.trainingDataMember, false);
  assert.equal(
    session.lastPlayedMotion.humanApproved,
    example.human_approved === true,
  );
  assert.equal(session.lastPlayedMotion.motionAssetSha256, example.sha256);
  assert.equal(
    session.lastPlayedMotion.motionReviewStatus,
    example.motion_review_status,
  );
  assert.equal(
    session.lastPlayedMotion.motionApprovalScope,
    example.human_approved ? "motion_quality_only" : null,
  );
  assert.equal(session.lastPlayedMotion.modelTrainingReady, false);
  assert.equal(session.lastPlayedMotion.presentation, "quaternion-temporal-v1");
  await page.waitForFunction(
    () => document.querySelector("#status").textContent === "本次播放完成。",
    undefined,
    { timeout: 15000 },
  );
  report.checks.push(
    "pause/resume, three views, speed, complete playback and honest session export",
  );
  for (const width of [768, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await play(example.text);
    await page.waitForTimeout(350);
    await canvasShot();
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.screenshot({
      path: join(output, `mobile-${width}.png`),
      fullPage: true,
    });
    await page.locator("#stop").click();
  }
  report.checks.push("tablet/mobile layout and framed nonblank moving avatar");
  const delayed = await context.newPage();
  await delayed.route("**/experimental/*.json", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700));
    await route.continue();
  });
  await delayed.goto(url);
  await ready(delayed);
  await delayed.locator("#input").fill(example.text);
  await delayed.locator("#play").click();
  await delayed.locator("#stop").click();
  await delayed.waitForTimeout(1400);
  assert.equal(await delayed.locator("#current").textContent(), "待机");
  assert.equal(await delayed.locator("#pause").isDisabled(), true);
  await delayed.close();
  report.checks.push(
    "stopping during an in-flight download cannot resurrect old playback",
  );
  const broken = await context.newPage();
  await broken.route("**/experimental/*.json", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await broken.goto(url);
  await ready(broken);
  await broken.locator("#input").fill(example.text);
  await broken.locator("#play").click();
  await broken.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("加载失败"),
  );
  await broken.locator("#research-details > summary").click();
  await broken.locator("[data-mode=dictionary]").click();
  await broken.locator("#input").fill("谢谢");
  await broken.locator("#play").click();
  await broken.waitForFunction(
    () => document.querySelector("#status").textContent === "本次播放完成。",
  );
  await broken.close();
  report.checks.push("tampered pose bytes rejected; dictionary stays usable");
  assert.deepEqual(report.errors, []);
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
  await browser.close();
}
console.log(
  JSON.stringify(
    {
      status: report.status,
      clips: report.clips.length,
      checks: report.checks,
      output,
    },
    null,
    2,
  ),
);
