import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = process.env.SIGNBRIDGE_ALIGNMENT_REVIEW_ROOT;
const url = process.env.SIGNBRIDGE_ALIGNMENT_REVIEW_URL;
if (!root || !url)
  throw new Error("Set SIGNBRIDGE_ALIGNMENT_REVIEW_ROOT and URL.");
const output = join(root, "../browser-qa");
await mkdir(output, { recursive: true });
const rows = (await readFile(join(root, "cases.jsonl"), "utf8"))
  .split(/\n/)
  .filter(Boolean)
  .map(JSON.parse);
const summary = JSON.parse(await readFile(join(root, "summary.json"), "utf8"));
const report = {
  status: "running",
  checks: [],
  errors: [],
  failedRequests: [],
  approval: "not-granted",
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
  await page.goto(url);
  assert.equal(rows.length, 380);
  assert.equal(await page.locator("#list section").count(), 16);
  assert.ok((await page.locator("#summary").textContent()).includes("380 帧"));
  await page.screenshot({ path: join(output, "desktop.png") });

  await page.locator("#filter").selectOption("fail");
  assert.ok((await page.locator("#count").textContent()).includes("95 项"));
  assert.equal(await page.locator("#list section").count(), 16);
  assert.ok((await page.locator("#list").textContent()).includes("门槛未通过"));
  await page.locator("#filter").selectOption("all");
  await page.locator("#search").fill("catchup-70f98ee0403f20c2-005-f000100");
  assert.equal(await page.locator("#list section").count(), 1);
  await page.waitForFunction(
    () => document.querySelector("#list img").naturalWidth > 0,
  );
  await page.screenshot({ path: join(output, "failed-gate-case.png") });
  report.checks.push("gate filters preserve failed frames and case search");

  await page.locator("#search").fill("");
  await page.locator("#filter").selectOption("noguess");
  assert.ok((await page.locator("#count").textContent()).includes("12 项"));
  await page.locator("#filter").selectOption("pass");
  assert.ok((await page.locator("#count").textContent()).includes("285 项"));
  await page.locator("#search").fill("");
  for (let start = 0; start < rows.length; start += 20) {
    const paths = rows
      .slice(start, start + 20)
      .filter((row) => row.image)
      .map((row) => row.image);
    const loaded = await page.evaluate(
      async (images) =>
        Promise.all(
          images.map(
            (src) =>
              new Promise((resolve, reject) => {
                const image = new Image();
                const timer = setTimeout(
                  () => reject(new Error("Image timeout: " + src)),
                  15000,
                );
                image.onload = () => {
                  clearTimeout(timer);
                  resolve(image.naturalWidth > 0);
                };
                image.onerror = () => {
                  clearTimeout(timer);
                  reject(new Error("Image load failed: " + src));
                };
                image.src = src;
              }),
          ),
        ),
      paths,
    );
    assert.ok(loaded.every(Boolean));
  }
  report.checks.push("380 frame comparison artifacts load");

  await page.setViewportSize({ width: 375, height: 900 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.screenshot({ path: join(output, "mobile.png") });
  report.checks.push("375px layout has no horizontal overflow");
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.failedRequests, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = error.stack;
  throw error;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(join(output, "report.json"), JSON.stringify(report, null, 2));
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
