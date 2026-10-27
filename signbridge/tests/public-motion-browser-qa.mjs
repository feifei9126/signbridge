// Run against the newly unpacked ZIP, never an old development build.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { join, resolve, extname } from "node:path";
import { createHash } from "node:crypto";
import { chromium } from "playwright";

const root = resolve(process.env.SIGNBRIDGE_DEMO_BUILD_DIR || "dist");
const output = process.env.SIGNBRIDGE_PUBLIC_QA_DIR;
if (!output) throw new Error("Set a new SIGNBRIDGE_PUBLIC_QA_DIR");
await mkdir(output, { recursive: false });
const load = async (name) => JSON.parse(await readFile(join(root, name)));
const reference = await load("demo/t08-motion.json");
const candidates = await load("demo/t08-candidates.json");
const fitted = await load("demo/experimental-index.json");
const build = await load("BUILD.json");
assert.equal(build.profile, "public-motion-demo");
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(
      new URL(request.url, "http://localhost").pathname,
    );
    if (path.includes("..")) throw new Error("Unsafe path");
    const bytes = await readFile(join(root, path));
    response.writeHead(200, {
      "Content-Type":
        {
          ".html": "text/html",
          ".js": "text/javascript",
          ".json": "application/json",
          ".css": "text/css",
        }[extname(path)] || "application/octet-stream",
    });
    response.end(bytes);
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({
  headless: true,
  args: ["--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const report = {
  status: "running",
  buildSourceSha256: build.source_sha256,
  clips: [],
  errors: [],
  networkFailures: [],
  checks: [],
  semanticAccuracy: "not-assessed",
  modelTrainingReady: false,
};
page.on("pageerror", (error) => report.errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400 && !response.url().endsWith("favicon.ico"))
    report.networkFailures.push(response.url());
});
await page.addInitScript(() => {
  window.__motionCurrent = null;
  window.addEventListener("message", (event) => {
    if (
      event.data?.source === "signbridge-demo-avatar" &&
      event.data.type === "CURRENT"
    )
      window.__motionCurrent = event.data;
  });
});
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/demo/index.html`);
  await page.waitForFunction(
    () =>
      !document.querySelector("#play").disabled &&
      document.querySelector("#experimental-count").textContent === "83",
    undefined,
    { timeout: 30000 },
  );
  await page.locator("#research-details").evaluate((element) => {
    element.open = true;
  });
  await page.locator('[data-mode="t08"]').click();
  assert.equal(await page.locator("#model-count").textContent(), "14");
  assert.equal(await page.locator("#candidate-count").textContent(), "3");
  assert.equal(await page.locator("#research-list button").count(), 0);
  const groups = [
    ["t08", reference.clips],
    ["candidate", candidates.clips],
    ["experimental", fitted.clips],
  ];
  for (const [source, clips] of groups) {
    for (const clip of clips) {
      await page.evaluate(() => {
        window.__motionCurrent = null;
      });
      await page.locator("#input").fill(clip.text);
      await page.locator("#play").click();
      await page.waitForFunction(
        (id) => window.__motionCurrent?.item?.id === id,
        clip.id,
        { timeout: 15000 },
      );
      const current = await page.evaluate(() => window.__motionCurrent);
      assert.equal(current.item.source, source);
      if (source !== "experimental")
        assert.deepEqual(current.tokens, clip.tokens);
      await page.waitForFunction(
        () =>
          parseFloat(document.querySelector("#progress-text").textContent) >
          0.15,
      );
      const canvas = page.frameLocator("#avatar").locator("canvas");
      const before = await canvas.screenshot();
      await page.waitForTimeout(160);
      const after = await canvas.screenshot();
      assert.notEqual(
        createHash("sha256").update(before).digest("hex"),
        createHash("sha256").update(after).digest("hex"),
        clip.id,
      );
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
        for (let i = 0; i < data.length; i += 64)
          colors.add(`${data[i]},${data[i + 1]},${data[i + 2]}`);
        return colors.size;
      }, after.toString("base64"));
      assert.ok(pixels > 100, "Nonblank avatar: " + clip.id);
      if (
        report.clips.length === 0 ||
        source === "candidate" ||
        clip.text === "认识你很高兴"
      )
        await page.screenshot({
          path: join(output, `${clip.id}.png`),
          fullPage: true,
        });
      report.clips.push({
        id: clip.id,
        source,
        frames: clip.frames,
        tokensVerified: source !== "experimental",
        moving: true,
        colors: pixels,
      });
      await page.locator("#stop").click();
      if (report.clips.length % 10 === 0)
        console.log(`Public motions checked: ${report.clips.length}/100`);
    }
  }
  assert.equal(report.clips.length, 100);
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.networkFailures, []);
  report.checks.push(
    "100 exact IDs use the packaged motion source, not dictionary fallback",
    "14+3 token streams match frozen assets",
    "100 canvases nonblank and moving",
    "no research images included",
  );
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
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
console.log(
  JSON.stringify({ status: report.status, clips: report.clips.length, output }),
);
