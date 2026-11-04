import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { extname, join, resolve, sep } from "node:path";
import { createHash } from "node:crypto";
import { chromium } from "playwright";
const root = resolve(process.env.SIGNBRIDGE_CORE_QA_BUILD || ""),
  output = process.env.SIGNBRIDGE_CORE_QA_OUTPUT;
if (!output || !process.env.SIGNBRIDGE_CORE_QA_BUILD)
  throw new Error("Set unpacked build and NEW output");
await mkdir(output, { recursive: false });
const core = JSON.parse(await readFile(join(root, "demo/core-manifest.json"))),
  native = JSON.parse(await readFile(join(root, "demo/native-index.json"))),
  build = JSON.parse(await readFile(join(root, "BUILD.json")));
assert.equal(build.core_unit_count, core.units.length);
const fixture = JSON.parse(
  await readFile(new URL("./fixtures/core-sentence-v1.json", import.meta.url)),
);
const report = {
  status: "running",
  coreUnits: [],
  sentences: [],
  refusals: [],
  checks: [],
  errors: [],
  networkFailures: [],
  trainingStarted: false,
  humanApproved: false,
  cslAccuracy: "not_assessed",
  visualRegression: "inconclusive_no_baseline",
};
const server = createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(new URL(req.url, "http://local").pathname),
      p = resolve(join(root, name));
    if (!p.startsWith(root + sep)) throw new Error("Unsafe path");
    const b = await readFile(p);
    res.writeHead(200, {
      "Content-Type":
        {
          ".html": "text/html",
          ".js": "text/javascript",
          ".css": "text/css",
          ".json": "application/json",
          ".mp4": "video/mp4",
        }[extname(p)] || "application/octet-stream",
    });
    res.end(b);
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
page.on("pageerror", (e) => report.errors.push(e.message));
page.on("response", (r) => {
  if (r.status() >= 400 && !r.url().endsWith("favicon.ico"))
    report.networkFailures.push(r.url());
});
await page.addInitScript(() => {
  window.__coreQA = { events: [], progress: null };
  window.addEventListener("message", (e) => {
    if (e.data?.source !== "signbridge-demo-avatar") return;
    if (e.data.type === "PROGRESS") window.__coreQA.progress = e.data;
    else window.__coreQA.events.push(e.data);
  });
});
const clear = () =>
  page.evaluate(() => {
    window.__coreQA = { events: [], progress: null };
  });
async function playToEnd(expectedIds) {
  await clear();
  await page.locator("#play").click();
  await page.waitForFunction(
    () => window.__coreQA.events.some((e) => e.type === "FINISHED"),
    undefined,
    { timeout: 30000 },
  );
  const events = await page.evaluate(() =>
    window.__coreQA.events.filter((e) => e.type === "CURRENT"),
  );
  assert.deepEqual(
    events.map((e) => e.item.id),
    expectedIds,
  );
  assert.ok(
    events.every(
      (e) => e.item.source === "native" && e.performance.precompiled === true,
    ),
  );
  return events;
}
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/demo/index.html`);
  await page.waitForFunction(
    () =>
      document.querySelector("#core-mode")?.getAttribute("aria-pressed") ===
        "true" && !document.querySelector("#play").disabled,
    undefined,
    { timeout: 30000 },
  );
  assert.equal(
    await page.locator("#catalog-list button").count(),
    core.units.length,
  );
  assert.equal(
    await page.locator("#native-count").textContent(),
    String(native.clips.filter((c) => !c.core_unit_key).length),
  );
  assert.equal(
    await page.locator("#research-details").evaluate((e) => e.open),
    false,
  );
  report.checks.push(
    "default core catalog is separate from repaired research candidates and old T08/83 fits",
  );
  await page.locator("#speed").selectOption("1.5");
  for (const unit of core.units) {
    await page.locator(`#catalog-list button[data-id="${unit.id}"]`).click();
    const events = await playToEnd([unit.id]);
    const links = page.locator("#core-evidence-list a");
    assert.equal(await links.count(), 2);
    for (let i = 0; i < 2; i++) {
      const response = await page.request.get(
        new URL(await links.nth(i).getAttribute("href"), page.url()).href,
      );
      assert.equal(response.status(), 200);
      const bytes = await response.body();
      if (i === 0)
        assert.equal(
          createHash("sha256").update(bytes).digest("hex"),
          core.evidence_files[`core-evidence/${unit.key}/original.mp4`],
        );
      else {
        const record = JSON.parse(bytes);
        assert.equal(record.human_approved, false);
        assert.deepEqual(
          record.source_frame_range_1based,
          unit.source_frame_range_1based,
        );
      }
    }
    report.coreUnits.push({
      id: unit.id,
      text: unit.text,
      frames: unit.frames,
      source_frame_range_1based: unit.source_frame_range_1based,
      finished: true,
      event: events[0],
    });
  }
  for (const test of fixture.cases.filter((c) => c.play)) {
    await page.locator("#input").fill(test.text);
    assert.equal(await page.locator("#play").isDisabled(), false, test.text);
    const ids = test.units.map((k) => core.units.find((u) => u.key === k).id),
      events = await playToEnd(ids);
    report.sentences.push({
      text: test.text,
      items: events.map((e) => ({
        id: e.item.id,
        role: e.item.semanticRole,
        source: e.item.source,
      })),
      finished: true,
    });
  }
  for (const test of fixture.cases.filter((c) => !c.play)) {
    await page.locator("#input").fill(test.text);
    assert.equal(await page.locator("#play").isDisabled(), true, test.text);
    if (test.text)
      assert.ok((await page.locator("#unknown").innerText()).trim().length > 0);
    if (test.gap)
      assert.ok(
        (await page.locator("#unknown").innerText()).includes(test.gap),
      );
    report.refusals.push({
      text: test.text,
      blocked: true,
      message: await page.locator("#unknown").innerText(),
    });
  }
  await page.locator("#input").fill("我");
  await clear();
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    window.__coreQA.events.some((e) => e.type === "CURRENT"),
  );
  await page.locator("#input").fill("你");
  await clear();
  const replaced = performance.now();
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    window.__coreQA.events.some(
      (e) => e.type === "CURRENT" && e.item.label === "你",
    ),
  );
  report.rapidReplacementMs = performance.now() - replaced;
  await page.locator("#stop").click();
  assert.equal(await page.locator("#pause").isDisabled(), true);
  await page.locator("#input").fill("我");
  await clear();
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    window.__coreQA.events.some((e) => e.type === "CURRENT"),
  );
  assert.equal(
    (
      await page.evaluate(() =>
        window.__coreQA.events.find((e) => e.type === "CURRENT"),
      )
    ).performance.cacheHit,
    true,
  );
  await page.locator("#input").fill("未知尾句");
  assert.equal(await page.locator("#pause").isDisabled(), true);
  assert.equal(await page.locator("#play").isDisabled(), true);
  report.checks.push(
    "latest replacement, repeated cache, stop and edits to unsupported text cannot continue hidden old playback",
  );
  await page.locator("#research-details").evaluate((e) => {
    e.open = true;
  });
  await page.locator('[data-mode="dictionary"]').click();
  await page.locator("#input").fill("你好");
  await clear();
  await page.locator("#play").click();
  await page.waitForFunction(() =>
    window.__coreQA.events.some(
      (e) => e.type === "CURRENT" && e.item.source === "dictionary",
    ),
  );
  assert.ok(
    (await page.locator("#core-scope").innerText()).includes("研究对照"),
  );
  await page.locator("#research-details").evaluate((e) => {
    e.open = false;
  });
  await page.waitForFunction(
    () =>
      document.querySelector("#core-mode")?.getAttribute("aria-pressed") ===
      "true",
  );
  assert.equal(await page.locator("#play").isDisabled(), true);
  await page.locator("#research-details").evaluate((e) => {
    e.open = true;
  });
  await page.locator('[data-mode="native"]').click();
  assert.equal(await page.locator("#catalog-list button").count(), 151);
  await page.locator("#return-core").click();
  assert.equal(await page.locator("#catalog-list button").count(), 17);
  report.checks.push(
    "research dictionary remains explicit; closing research returns to core; full 151 candidates stay available only as research",
  );
  const broken = await browser.newPage();
  await broken.route("**/demo/native-index.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{broken-json",
    }),
  );
  await broken.goto(
    `http://127.0.0.1:${server.address().port}/demo/index.html`,
  );
  await broken.waitForFunction(
    () =>
      document.querySelector("#status")?.textContent.includes("核心动作来源"),
    undefined,
    { timeout: 30000 },
  );
  assert.equal(await broken.locator("#play").isDisabled(), true);
  await broken.close();
  report.checks.push(
    "malformed core/native data blocks default playback rather than falling back to legacy references",
  );
  await page.locator("#input").fill("我工作");
  await page.screenshot({
    path: join(output, "desktop-core.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.screenshot({
    path: join(output, "mobile-core.png"),
    fullPage: true,
  });
  const body = await page.locator("body").innerText();
  assert.ok(!body.includes("cslIssues.candidate_label_unverified"));
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
    coreUnits: report.coreUnits.length,
    sentences: report.sentences.length,
    refusals: report.refusals.length,
    rapidReplacementMs: report.rapidReplacementMs,
  }),
);
