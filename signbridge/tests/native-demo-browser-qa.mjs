// Real full-duration playback from the newly unpacked local candidate release.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { extname, join, resolve, sep } from "node:path";
import { createHash } from "node:crypto";
import { chromium } from "playwright";

const root = resolve(process.env.SIGNBRIDGE_NATIVE_QA_BUILD || ""),
  output = process.env.SIGNBRIDGE_NATIVE_QA_OUTPUT;
if (!output || !process.env.SIGNBRIDGE_NATIVE_QA_BUILD)
  throw new Error("Set explicit new QA output and unpacked build");
await mkdir(output, { recursive: false });
const index = JSON.parse(await readFile(join(root, "demo/native-index.json"))),
  build = JSON.parse(await readFile(join(root, "BUILD.json")));
assert.equal(build.profile, "local-research");
assert.equal(build.native_candidate_count, index.clips.length);
const report = {
  schema: "signbridge-native-demo-browser-qa-v1",
  status: "running",
  buildSourceSha256: build.source_sha256,
  clips: [],
  checks: [],
  errors: [],
  networkFailures: [],
  screenshots: [],
  semanticAccuracy: "not-assessed",
  humanApproved: false,
  trainingStarted: false,
  visualRegression: "inconclusive_no_baseline",
};
const server = createServer(async (req, res) => {
  try {
    const relative = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const path = resolve(join(root, relative));
    if (!path.startsWith(root + sep)) throw new Error("Unsafe path");
    const bytes = await readFile(path);
    res.writeHead(200, {
      "Content-Type":
        {
          ".html": "text/html",
          ".js": "text/javascript",
          ".css": "text/css",
          ".json": "application/json",
        }[extname(path)] || "application/octet-stream",
    });
    res.end(bytes);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const browser = await chromium.launch({
  headless: true,
  args: ["--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.on("pageerror", (error) => report.errors.push(error.message));
page.on("response", (r) => {
  if (r.status() >= 400 && !r.url().endsWith("favicon.ico"))
    report.networkFailures.push(r.url());
});
await page.addInitScript(() => {
  window.__nativeQA = { events: [], progress: null };
  window.addEventListener("message", (e) => {
    if (e.data?.source !== "signbridge-demo-avatar") return;
    if (e.data.type === "PROGRESS") window.__nativeQA.progress = e.data;
    else window.__nativeQA.events.push(e.data);
  });
});
const clear = () =>
  page.evaluate(() => {
    window.__nativeQA.events = [];
    window.__nativeQA.progress = null;
  });
const waitCurrent = (id) =>
  page.waitForFunction(
    (id) =>
      window.__nativeQA.events.some(
        (e) => e.type === "CURRENT" && e.item.id === id,
      ),
    id,
    { timeout: 15000 },
  );
const latest = () =>
  page.evaluate(() =>
    window.__nativeQA.events.filter((e) => e.type === "CURRENT").at(-1),
  );
async function screenshot(name) {
  const path = join(output, name);
  await page.screenshot({ path, fullPage: true });
  report.screenshots.push({
    path,
    sha256: createHash("sha256")
      .update(await readFile(path))
      .digest("hex"),
  });
}
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/demo/index.html`);
  await page.waitForFunction(
    (n) =>
      document.querySelector("#native-count")?.textContent === String(n) &&
      !document.querySelector("#play").disabled,
    index.clips.length,
    { timeout: 30000 },
  );
  assert.equal(
    await page.locator("#native-mode").getAttribute("aria-pressed"),
    "true",
  );
  assert.ok(
    (await page.locator("#catalog-note").innerText()).includes(
      String(index.clips.length),
    ),
  );
  assert.equal(await page.locator("#motion-smoothing").isDisabled(), true);
  await page.locator("#research-details").evaluate((e) => {
    e.open = false;
  });
  await page.waitForTimeout(100);
  assert.equal(
    await page.locator("#native-mode").getAttribute("aria-pressed"),
    "true",
  );
  await page.locator("#research-details").evaluate((e) => {
    e.open = true;
  });
  report.checks.push(
    "unpacked release defaults to the explicit candidate mode; fixed display processing is not mislabeled as toggleable",
    "closing research details retains native candidate routing",
  );
  await page.locator("#speed").selectOption("1.5");
  for (const clip of index.clips) {
    await page.locator("#search").fill("");
    const button = page.locator(`#catalog-list button[data-id="${clip.id}"]`);
    await button.click();
    await clear();
    const start = performance.now();
    await page.locator("#play").click();
    await waitCurrent(clip.id);
    const event = await latest();
    assert.equal(event.item.source, "native");
    assert.equal(event.performance.precompiled, true);
    if (report.clips.length === 0 || clip.text === "我" || clip.text === "你") {
      await page.waitForFunction(
        () => window.__nativeQA.progress?.elapsed > 0.7,
        undefined,
        { timeout: 10000 },
      );
      await screenshot(
        `${report.clips.length}-${clip.text === "我" ? "me" : clip.text === "你" ? "you" : "first"}.png`,
      );
    }
    await page.waitForFunction(
      () => window.__nativeQA.events.some((e) => e.type === "FINISHED"),
      undefined,
      { timeout: Math.ceil((clip.frames / clip.fps / 1.5) * 1000) + 15000 },
    );
    const progress = await page.evaluate(() => window.__nativeQA.progress);
    assert.ok(progress && progress.elapsed > 0);
    report.clips.push({
      id: clip.id,
      text: clip.text,
      source: event.item.source,
      frames: clip.frames,
      fps: clip.fps,
      finished: true,
      lastProgressSeconds: progress.elapsed,
      elapsedWallMs: performance.now() - start,
      loadMs: event.performance.compileMs,
      cacheHit: event.performance.cacheHit,
      profile: event.presentation,
    });
    if (report.clips.length % 10 === 0)
      console.log(
        JSON.stringify({
          finished: report.clips.length,
          total: index.clips.length,
        }),
      );
  }
  report.checks.push(
    "every new candidate played to FINISHED with no source substitution",
  );
  const me = index.clips.find((c) => c.text === "我"),
    you = index.clips.find((c) => c.text === "你");
  assert.ok(me && you);
  for (const clip of [me, me]) {
    await page.locator("#input").fill(clip.text);
    await clear();
    await page.locator("#play").click();
    await waitCurrent(clip.id);
  }
  assert.equal((await latest()).performance.cacheHit, true);
  report.checks.push("repeated native playback hits the compiled-track cache");
  await page.locator("#stop").click();
  await clear();
  await page.locator("#input").fill(me.text);
  await page.locator("#play").click();
  await page.locator("#input").fill(you.text);
  const replacement = performance.now();
  await page.locator("#play").click();
  await waitCurrent(you.id);
  report.rapidReplacementMs = performance.now() - replacement;
  assert.equal((await latest()).item.id, you.id);
  await page.locator("#stop").click();
  const stopped = await page.evaluate(
    () => window.__nativeQA.events.at(-1)?.requestId,
  );
  await page.waitForTimeout(400);
  assert.equal(await page.locator("#pause").isDisabled(), true);
  report.checks.push(
    `rapid latest-request replacement ${report.rapidReplacementMs.toFixed(1)}ms; stop stays stopped (generation ${stopped})`,
  );
  const semantic = [];
  for (const text of ["我帮你", "你帮我", "我们帮助他"]) {
    await page.locator("#input").fill(text);
    await clear();
    await page.locator("#play").click();
    await page.waitForFunction(
      () => window.__nativeQA.events.some((e) => e.type === "FINISHED"),
      undefined,
      { timeout: 45000 },
    );
    const events = await page.evaluate(() =>
      window.__nativeQA.events.filter((e) => e.type === "CURRENT"),
    );
    assert.equal(events.length, 3);
    semantic.push({
      text,
      items: events.map((e) => ({
        id: e.item.id,
        source: e.item.source,
        role: e.item.semanticRole,
      })),
    });
  }
  assert.equal(semantic[0].items[0].id, me.id);
  assert.equal(semantic[0].items[2].id, you.id);
  assert.equal(semantic[1].items[0].id, you.id);
  assert.equal(semantic[1].items[2].id, me.id);
  assert.deepEqual(
    semantic[0].items.map((item) => item.role),
    ["actor", "predicate", "patient"],
  );
  assert.deepEqual(
    semantic[1].items.map((item) => item.role),
    ["actor", "predicate", "patient"],
  );
  assert.equal(semantic[2].items[0].source, "semantic");
  assert.equal(semantic[2].items[2].source, "semantic");
  report.roleCases = semantic;
  report.checks.push(
    "role swap preserved; he/we authored fallbacks remain explicitly labeled",
  );
  for (const text of ["我不想去", "我帮你但是明天取消", "未知内容啊"]) {
    await page.locator("#input").fill(text);
    assert.equal(await page.locator("#play").isDisabled(), true);
    assert.ok((await page.locator("#unknown").innerText()).includes(text));
  }
  report.checks.push(
    "unknown clauses and unsupported operator scope preserve input and disable playback",
  );
  await page.locator("#input").fill("我帮你");
  await screenshot("desktop-role-draft.png");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    true,
  );
  await screenshot("mobile-role-draft.png");
  report.checks.push("390px viewport has no horizontal document overflow");
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.networkFailures, []);
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
  await new Promise((r) => server.close(r));
}
console.log(
  JSON.stringify({
    status: report.status,
    clips: report.clips.length,
    checks: report.checks,
    rapidReplacementMs: report.rapidReplacementMs,
  }),
);
