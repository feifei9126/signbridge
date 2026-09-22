import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "test-results/phase3-browser");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "signbridge-phase3-"));
const checks = [];
const errors = [];
const requests = [];
let context;
function observe(page) {
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("dialog", (dialog) => dialog.accept());
}
async function eventually(check, description) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${description}`);
}
try {
  const extension = join(root, "dist");
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
    headless: true,
    locale: "zh-CN",
    viewport: { width: 1440, height: 1050 },
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  context.on("page", observe);
  context.on("request", (request) => requests.push(request.url()));
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const origin = `chrome-extension://${new URL(worker.url()).host}`;
  const popup = await context.newPage();
  await popup.goto(`${origin}/popup/index.html`);
  const newPage = context.waitForEvent("page");
  await popup.locator("#btnCoverage").click();
  const page = await newPage;
  await page.waitForURL(`${origin}/tools/coverage.html`);
  await eventually(
    async () =>
      (await page.locator("#coverage-status").textContent()).includes(
        "首次分析",
      ),
    "coverage ready",
  );
  checks.push("popup opens the built, CSP-safe, localized coverage page");

  const analyze = async () => {
    await page.locator("#coverage-analyze").click();
    await eventually(
      async () => !(await page.locator("#coverage-export").isDisabled()),
      "analysis finished",
    );
  };
  const readReport = async (includeText = true) => {
    await page.locator("#coverage-include-text").setChecked(includeText);
    const pending = page.waitForEvent("download");
    await page.locator("#coverage-export").click();
    const download = await pending;
    return JSON.parse(await readFile(await download.path(), "utf8"));
  };
  await page.evaluate(() => {
    const original = globalThis.fetch;
    globalThis.fetch = (...args) => {
      const requestUrl = args[0]?.url || String(args[0]);
      if (!requestUrl.endsWith("/avatar/model.glb")) return original(...args);
      globalThis.fetch = original;
      return Promise.resolve(
        new Response(
          JSON.stringify({ asset: { version: "2.0" }, scenes: [{}], scene: 0 }),
        ),
      );
    };
  });
  await page.locator("#coverage-text").fill("你好 quasar quasar\n谢谢 quasar");
  await page.locator("#coverage-analyze").click();
  await eventually(
    async () =>
      (await page.locator("#coverage-status").textContent()).includes(
        "无法核验",
      ),
    "model validation failure",
  );
  assert.equal(await page.locator("#coverage-export").isDisabled(), true);
  await analyze();
  let result = await readReport();
  assert.equal(result.summary.coverage, 0.4);
  assert.equal(result.unknown[0].count, 3);
  assert.equal(result.unknown[0].segmentCount, 2);
  assert.match(
    await page.locator("#coverage-catalog").textContent(),
    /52 内置词条 \/ 172 查找别名 \/ 16 单字/,
  );
  checks.push(
    "model failure blocks incomplete reports; retry loads the real rig and counts real runtime matches",
  );

  const editorPromise = context.waitForEvent("page");
  await page
    .locator("#coverage-unknown tr")
    .first()
    .getByRole("button", { name: "姿势编辑器", exact: true })
    .click();
  const editor = await editorPromise;
  await editor.locator("#motion-name").waitFor();
  assert.equal(await editor.locator("#motion-name").inputValue(), "quasar");
  assert.equal(await editor.locator("#motion-texts").inputValue(), "quasar");
  assert.match(
    await editor.locator("#motion-status").textContent(),
    /不是该词的已验证动作/,
  );
  const stored = () =>
    worker.evaluate(async () =>
      Object.entries(await chrome.storage.local.get(null))
        .filter(([key]) => key.startsWith("signbridge.motion.v1."))
        .map(([, entry]) => entry),
    );
  assert.equal((await stored()).length, 0);
  await editor.locator("#preset-dd").selectOption("抬头");
  await editor.locator("#motion-save").click();
  await eventually(async () => (await stored()).length === 1, "draft saved");
  await eventually(
    async () => await page.locator("#coverage-export").isDisabled(),
    "catalog change invalidated old export",
  );
  await analyze();
  result = await readReport();
  assert.equal(result.summary.coverage, 0.4);
  assert.deepEqual(result.customMotionIds, []);
  checks.push(
    "unknown-word handoff pre-fills metadata without creating or approving motion; saved drafts remain uncovered",
  );

  await editor.locator("#motion-preview").click();
  await editor.waitForTimeout(1000);
  await editor.locator("#motion-enable").click();
  await eventually(async () => (await stored())[0]?.enabled, "asset enabled");
  await eventually(
    async () => await page.locator("#coverage-export").isDisabled(),
    "approval invalidates report",
  );
  await analyze();
  result = await readReport();
  assert.equal(result.summary.coverage, 1);
  assert.equal(result.customMotionIds.length, 1);
  assert.ok(
    result.details[0].matches.some(
      (match) => match.id === result.customMotionIds[0],
    ),
  );
  const safe = await readReport(false);
  assert.equal("details" in safe, false);
  assert.equal(safe.includesSourceText, false);
  await page.screenshot({
    path: join(output, "01-confirmed-coverage.png"),
    fullPage: true,
  });
  checks.push(
    "only reviewed enabled assets improve coverage; source details require explicit export opt-in",
  );

  await editor.locator("#motion-disable").click();
  await eventually(
    async () => await page.locator("#coverage-export").isDisabled(),
    "disable invalidates report",
  );
  await analyze();
  assert.equal((await readReport()).summary.coverage, 0.4);
  const recorderPromise = context.waitForEvent("page");
  await page
    .locator("#coverage-unknown tr")
    .first()
    .getByRole("button", { name: "录制工具", exact: true })
    .click();
  const recorder = await recorderPromise;
  await recorder.locator("#motion-name").waitFor();
  assert.equal(await recorder.locator("#motion-name").inputValue(), "quasar");
  assert.equal((await stored()).length, 1);
  checks.push(
    "disabling removes coverage; recorder handoff preserves existing library and does not auto-save",
  );

  const inputFile = (name, text) =>
    page.locator("#coverage-file").setInputFiles({
      name,
      mimeType: "text/plain",
      buffer: Buffer.from(text),
    });
  await inputFile(
    "fixture.srt",
    "1\n00:00:00,000 --> 00:00:02,000\n<b>你好</b> quasar\n\n2\n00:00:02,000 --> 00:00:04,000\n谢谢",
  );
  await eventually(
    async () => (await page.locator("#coverage-format").inputValue()) === "srt",
    "SRT import complete",
  );
  await analyze();
  result = await readReport();
  assert.equal(result.summary.segments, 2);
  assert.equal(result.summary.unknownTokens, 1);
  assert.deepEqual(
    result.details.map((detail) => detail.text),
    ["你好 quasar", "谢谢"],
  );
  await inputFile(
    "fixture.vtt",
    "WEBVTT\n\nNOTE private-comment\nignore-this\n\n00:00.000 --> 00:01.000\n<v Speaker>你好 <00:00.300>谢谢",
  );
  await eventually(
    async () => (await page.locator("#coverage-format").inputValue()) === "vtt",
    "VTT import complete",
  );
  await analyze();
  result = await readReport();
  assert.equal(result.summary.coverage, 1);
  assert.equal(result.details[0].text, "你好 谢谢");
  checks.push(
    "UTF-8 SRT and WebVTT import excludes timeline, styling, comments and voice labels",
  );

  await page.locator("#coverage-format").selectOption("text");
  await page
    .locator("#coverage-text")
    .fill("你好 ".repeat(13) + "quasar\n<img src=x onerror=alert(1)>");
  await analyze();
  result = await readReport();
  assert.equal(result.summary.runtimeTruncatedSegments, 1);
  assert.equal(await page.locator("#coverage-details img").count(), 0);
  assert.match(
    await page.locator("#coverage-details").textContent(),
    /<img src=x/,
  );
  await page.screenshot({
    path: join(output, "02-gaps-and-playback-limit.png"),
    fullPage: true,
  });
  checks.push(
    "playback cutoff is shown separately; untrusted source content renders as text, not HTML",
  );

  await page.locator("#coverage-text").fill("changed");
  assert.equal(await page.locator("#coverage-export").isDisabled(), true);
  assert.equal(await page.locator("#coverage-results").isVisible(), false);
  await inputFile("bad.srt", "broken timeline");
  await eventually(
    async () =>
      (await page.locator("#coverage-text").inputValue()) === "broken timeline",
    "bad import read",
  );
  await page.locator("#coverage-analyze").click();
  await eventually(
    async () =>
      (await page.locator("#coverage-status").textContent()).includes(
        "字幕格式无效",
      ),
    "bad format rejected",
  );
  assert.equal(await page.locator("#coverage-export").isDisabled(), true);
  await page.locator("#coverage-file").setInputFiles({
    name: "bad.txt",
    mimeType: "text/plain",
    buffer: Buffer.from([0xff, 0xfe, 0x11]),
  });
  await eventually(
    async () =>
      (await page.locator("#coverage-status").textContent()).includes("UTF-8"),
    "invalid encoding rejected",
  );
  assert.equal(
    await page.locator("#coverage-text").inputValue(),
    "broken timeline",
  );
  await inputFile("large.txt", "a".repeat(256 * 1024 + 1));
  await eventually(
    async () =>
      (await page.locator("#coverage-status").textContent()).includes(
        "超过材料",
      ),
    "large import rejected",
  );
  checks.push(
    "editing invalidates old output; malformed, oversized and non-UTF-8 imports fail without replacing existing text",
  );

  await page.locator("#coverage-clear").click();
  assert.equal(await page.locator("#coverage-text").inputValue(), "");
  await page.reload();
  await page.locator("#coverage-analyze").waitFor();
  assert.equal(await page.locator("#coverage-text").inputValue(), "");
  assert.equal(await page.locator("#coverage-results").isVisible(), false);
  const storage = await worker.evaluate(async () =>
    chrome.storage.local.get(null),
  );
  assert.ok(!Object.keys(storage).some((key) => key.includes("coverage")));
  assert.deepEqual(
    requests.filter((url) => /^https?:/.test(url)),
    [],
  );
  assert.deepEqual(errors, []);
  checks.push(
    "analysis is memory-only with no remote requests or new stored transcripts; no page exceptions or console errors",
  );
  await writeFile(
    join(output, "report.json"),
    JSON.stringify({ passed: checks.length, checks, errors }, null, 2),
  );
  console.log(
    JSON.stringify({ passed: checks.length, checks, errors }, null, 2),
  );
} catch (error) {
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(
      { passed: checks.length, checks, errors, failure: error.stack },
      null,
      2,
    ),
  );
  throw error;
} finally {
  await context?.close();
  await rm(profile, { recursive: true, force: true });
}
