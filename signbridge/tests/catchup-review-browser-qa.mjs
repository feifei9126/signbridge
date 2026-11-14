import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getSupportedLocales, setLocale, t } from "../src/i18n/locales.js";
const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = process.env.SIGNBRIDGE_CATCHUP_ROOT;
const url = process.env.SIGNBRIDGE_CATCHUP_URL;
if (!root || !url)
  throw new Error("Set SIGNBRIDGE_CATCHUP_ROOT and SIGNBRIDGE_CATCHUP_URL.");
const out = join(root, "../browser-qa");
await mkdir(out, { recursive: true });
const data = JSON.parse(await readFile(join(root, "review-data.json"), "utf8"));
const report = {
  status: "running",
  checks: [],
  errors: [],
  failedRequests: [],
  semanticAccuracy: "not_assessed",
};
const browser = await chromium.launch({
  headless: true,
  ...(process.env.SIGNBRIDGE_CHROME
    ? { executablePath: process.env.SIGNBRIDGE_CHROME }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on("pageerror", (error) => report.errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400) report.failedRequests.push(response.url());
});
try {
  for (const locale of getSupportedLocales()) {
    setLocale(locale.code);
    for (const key of [
      "catchupTitle",
      "catchupSummary",
      "catchupSources",
      "catchupSync",
      "catchupHksl",
    ])
      assert.notEqual(t(key), key);
  }
  report.checks.push(
    "new interface strings available for all registered locales",
  );
  await page.goto(url);
  await page.waitForFunction(
    () => document.querySelectorAll("#list section").length === 8,
  );
  assert.ok((await page.locator("#summary").textContent()).includes("76"));
  assert.equal(data.references.length, 76);
  assert.equal(data.sources.length, 134);
  await page.screenshot({ path: join(out, "desktop.png"), fullPage: false });
  const first = data.references[0];
  await page.locator("#search").fill(first.text);
  assert.equal(await page.locator("#list section").count(), 1);
  await page.locator("#list button").click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll("video")].every(
      (video) => video.currentTime > 0.2 && !video.paused,
    ),
  );
  await page.locator("#list button").click();
  assert.ok(
    await page.evaluate(() =>
      [...document.querySelectorAll("video")].every((video) => video.paused),
    ),
  );
  await page.locator("#list summary").click();
  await page.waitForFunction(
    () => document.querySelector("#list img").naturalWidth > 0,
  );
  await page.screenshot({ path: join(out, "hand-crops.png"), fullPage: true });
  report.checks.push("source video, overlay sync, pause and hand crop image");
  await page.locator("#search").fill("");
  await page.locator("#next").click();
  assert.ok((await page.locator("#count").textContent()).includes("2/10"));
  await page.locator("[data-view=sources]").click();
  assert.ok((await page.locator("#count").textContent()).includes("134"));
  await page.locator("#search").fill("香港");
  assert.equal(await page.locator("#list section").count(), 1);
  assert.ok(
    (await page.locator("#list").textContent()).includes("未纳入中国手语"),
  );
  report.checks.push(
    "134 source progress rows and separately labelled Hong Kong sign language",
  );
  await page.locator("#search").fill("");
  await page.locator("[data-view=subtitles]").click();
  assert.equal(await page.locator("#list section").count(), 50);
  await page.locator("#search").fill("不会存在的字幕候选🚀");
  assert.equal(await page.locator("#list section").count(), 0);
  await page.locator("#search").fill("");
  report.checks.push("raw caption pagination and unknown search");
  const mediaResults = await page.evaluate(async (rows) => {
    let checked = 0;
    for (const row of rows) {
      for (const file of [row.clip, row.overlay]) {
        const video = document.createElement("video");
        video.preload = "metadata";
        await new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error("Metadata timeout: " + file)),
            10000,
          );
          video.onloadedmetadata = () => {
            clearTimeout(timer);
            resolve();
          };
          video.onerror = () => {
            clearTimeout(timer);
            reject(new Error("Media error: " + file));
          };
          video.src = file;
        });
        if (!Number.isFinite(video.duration) || video.duration <= 0)
          throw new Error("Invalid media duration");
        video.removeAttribute("src");
        video.load();
        checked++;
      }
    }
    return checked;
  }, data.references);
  assert.equal(mediaResults, 152);
  report.checks.push("all 152 source/overlay videos load metadata in browser");
  await page.locator("[data-view=references]").click();
  await page.setViewportSize({ width: 375, height: 1000 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.screenshot({ path: join(out, "mobile.png"), fullPage: false });
  await page.goto(url + "?lang=en");
  assert.equal(
    await page.locator("h1").textContent(),
    "Video catch-up · Source clips and hand references",
  );
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.failedRequests, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  throw error;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(join(out, "report.json"), JSON.stringify(report, null, 2));
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
