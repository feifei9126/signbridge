// Real model playback and fail-closed analysis checks for either explicit build profile.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile, stat } from "node:fs/promises";
import { dirname, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveTestResultsDir } from "../scripts/test-results-dir.mjs";
const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(
  process.env.SIGNBRIDGE_DEMO_BUILD_DIR || join(root, "dist"),
);
const output = resolve(
  process.env.SIGNBRIDGE_AUDIT_QA_DIR ||
    join(resolveTestResultsDir(root), "audit-browser"),
);
const report = { status: "running", checks: [], errors: [] };
const server = createServer(async (request, response) => {
  try {
    const name = decodeURIComponent(
      new URL(request.url, "http://localhost").pathname,
    );
    const file = resolve(dist, "." + name);
    if (!file.startsWith(dist + sep) || !(await stat(file)).isFile()) {
      response.writeHead(404);
      response.end();
      return;
    }
    response.writeHead(200, {
      "Content-Type":
        {
          ".html": "text/html",
          ".js": "text/javascript",
          ".css": "text/css",
          ".json": "application/json",
          ".glb": "model/gltf-binary",
          ".jpg": "image/jpeg",
          ".png": "image/png",
        }[extname(file)] || "application/octet-stream",
    });
    response.end(await readFile(file));
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
  args: ["--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({
  viewport: { width: 1280, height: 900 },
  acceptDownloads: true,
});
page.on("pageerror", (error) => report.errors.push(error.message));
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/demo/index.html`);
  await page.locator("#input").fill("你好");
  await page.waitForFunction(() => !document.querySelector("#play").disabled);
  const metadata = JSON.parse(await readFile(join(dist, "BUILD.json"), "utf8"));
  report.profile = metadata.profile;
  const matches = async () => page.locator("#matches").innerText();
  await page.locator("#research-details > summary").click();
  await page.locator('[data-mode="dictionary"]').click();
  for (const text of ["不是", "好久不见", "人民广场", "了解一下"]) {
    await page.locator("#input").fill(text);
    assert.equal((await matches()).trim(), "");
    assert.equal(await page.locator("#play").isDisabled(), true);
  }
  await page.locator("#input").fill("你好，谢谢");
  assert.match(await matches(), /你好/);
  assert.match(await matches(), /谢谢/);
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("播放完成"),
  );
  report.checks.push(
    "shared Chinese boundaries and actual dictionary playback",
  );
  await page.locator('[data-mode="semantic"]').click();
  for (const text of [
    "我去",
    "我今天去",
    "我帮你",
    "你帮我",
    "我非常开心",
    "我没有去",
    "你去吗",
  ]) {
    await page.locator("#input").fill(text);
    assert.equal(await page.locator("#play").isDisabled(), true);
    assert.match(
      await page.locator("#semantic-status").textContent(),
      /不播放/,
    );
    assert.equal((await matches()).trim(), "");
    await page.locator("#input").press("Control+Enter");
    assert.equal(await page.locator("#current").textContent(), "待机");
  }
  const evidence = JSON.parse(
    await page.locator("#semantic-json").textContent(),
  );
  assert.equal(evidence.route, "analysis_only");
  assert.deepEqual(evidence.items, []);
  report.checks.push(
    "semantic results stay analysis-only for button and keyboard paths",
  );
  if (metadata.profile === "local-research") {
    const bundle = JSON.parse(
      await readFile(join(dist, "demo/t08-motion.json"), "utf8"),
    );
    const fitted = JSON.parse(
      await readFile(join(dist, "demo/experimental-index.json"), "utf8"),
    );
    await page.locator('[data-mode="semantic"]').click();
    await page.locator("#input").fill(fitted.clips[0].text);
    assert.equal(await page.locator("#play").isDisabled(), true);
    assert.deepEqual(
      JSON.parse(await page.locator("#semantic-json").textContent()).items,
      [],
    );
    await page.locator('[data-mode="auto"]').click();
    for (const text of [bundle.clips[0].text, fitted.clips[0].text]) {
      await page.locator("#input").fill(text);
      await page.locator("#play").click();
      await page.waitForFunction(() =>
        document.querySelector("#status").textContent.startsWith("正在播放"),
      );
      assert.doesNotMatch(
        await page.locator("#source-badge").textContent(),
        /词库/,
      );
      await page.locator("#stop").click();
    }
    if (fitted.recovery_profiles) {
      const id = Object.keys(fitted.recovery_profiles)[0];
      const clip = fitted.clips.find((c) => c.id === id);
      await page.locator("#input").fill(clip.text);
      await page.locator("#play").click();
      await page.waitForFunction(() =>
        document.querySelector("#status").textContent.startsWith("正在播放"),
      );
      const pending = page.waitForEvent("download");
      await page.locator("#download").click();
      const download = await pending;
      const session = JSON.parse(await readFile(await download.path(), "utf8"));
      assert.equal(
        session.lastPlayedMotion.presentation,
        clip.display_stabilization_profile,
      );
      await page.locator("#stop").click();
    }
    report.checks.push(
      "explicit local T08/SMPL-X playback and wrist recovery retained; never played in semantic mode",
    );
  } else {
    assert.equal(existsSync(join(dist, "demo/experimental")), false);
    report.checks.push("public demo contains no local reconstruction assets");
  }
  await mkdir(output, { recursive: true });
  await page.screenshot({
    path: join(output, "analysis-only.png"),
    fullPage: true,
  });
  let calls = 0;
  page.on("request", (request) => {
    if (request.url().includes("/v1/understand")) calls++;
  });
  assert.equal(await page.locator("#meaning-task").count(), 0);
  assert.equal(
    await page.locator('[href="../private/index.html?scope=1"]').count(),
    0,
  );
  assert.equal(existsSync(join(dist, "private/index.html")), false);
  assert.equal(calls, 0);
  report.checks.push(
    "public extension omits the trained-meaning page and contains no automatic inference route",
  );
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} finally {
  await mkdir(output, { recursive: true });
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
console.log(JSON.stringify(report));
