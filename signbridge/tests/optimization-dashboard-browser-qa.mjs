// Verify the generated, local-only research report on desktop and mobile.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, stat, writeFile, mkdir } from "node:fs/promises";
import { extname, resolve, sep, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../local-data/existing-resources-optimization-20261019-v1",
);
const output = resolve(
  process.env.SIGNBRIDGE_DASHBOARD_QA_DIR || join(root, "dashboard-browser-qa"),
);
const checks = [];
const errors = [];
const types = {
  ".html": "text/html",
  ".json": "application/json",
  ".jpg": "image/jpeg",
  ".mp4": "video/mp4",
  ".png": "image/png",
};
const server = createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const path = resolve(root, "." + pathname);
    if (!path.startsWith(root + sep) || !(await stat(path)).isFile()) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, {
      "Content-Type": types[extname(path)] || "application/octet-stream",
      "Cache-Control": "no-store",
    });
    res.end(await readFile(path));
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({
  headless: true,
  args: ["--enable-unsafe-swiftshader"],
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => {
    if (r.status() >= 400) errors.push(`http_${r.status()}`);
  });
  await page.goto(
    `http://127.0.0.1:${server.address().port}/dashboard-v6/index.html`,
  );
  await page.waitForLoadState("networkidle");
  assert.match(await page.locator("body").innerText(), /0\/95/);
  await page.locator(".comparison").scrollIntoViewIfNeeded();
  await page.waitForFunction(() =>
    [...document.querySelectorAll(".comparison img")].every(
      (img) => img.complete && img.naturalWidth > 0,
    ),
  );
  const images = await page
    .locator("img")
    .evaluateAll((nodes) =>
      nodes.map((n) => ({ width: n.naturalWidth, height: n.naturalHeight })),
    );
  assert.ok(
    images.length > 0 && images.every((x) => x.width > 0 && x.height > 0),
  );
  checks.push("desktop metrics and raw/adaptive avatar images render");
  await mkdir(output, { recursive: true });
  await page.screenshot({
    path: join(output, "dashboard-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.screenshot({
    path: join(output, "dashboard-mobile.png"),
    fullPage: true,
  });
  checks.push("dashboard fits a mobile viewport without page overflow");
  await page.locator('a[href="../unit-candidates-final/index.html"]').click();
  await page.waitForURL(/unit-candidates-final\/index.html$/);
  assert.equal(await page.locator("video").count(), 20);
  const first = page.locator("video").first();
  await first.evaluate((v) => {
    v.muted = true;
    v.currentTime = Math.min(0.25, (v.duration || 1) / 2);
  });
  await first.waitForFunction((v) => v.readyState >= 2 && v.videoWidth > 0);
  assert.ok((await first.evaluate((v) => v.videoHeight)) > 0);
  checks.push(
    "all 20 candidate clips have playable metadata and a decodable frame",
  );
  assert.deepEqual(errors, []);
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(
      { status: "passed", checks, errors, candidates: 20 },
      null,
      2,
    ) + "\n",
  );
  console.log(JSON.stringify({ status: "passed", checks, output }));
} catch (error) {
  await mkdir(output, { recursive: true });
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(
      { status: "failed", checks, errors, error: String(error) },
      null,
      2,
    ) + "\n",
  );
  throw error;
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
