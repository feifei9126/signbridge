import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "test-results/phase6-browser");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "signbridge-phase6-"));
const checks = [];
const errors = [];
const requests = [];
let context;
const batchKey = "signbridge.vocabulary-batch.v1";
async function eventually(check, description) {
  const deadline = Date.now() + 20000;
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
  context.on("page", (page) => {
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
  });
  context.on("request", (request) => requests.push(request.url()));
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const origin = `chrome-extension://${new URL(worker.url()).host}`;
  const stored = () => worker.evaluate(() => chrome.storage.local.get(null));
  const motions = async () =>
    Object.fromEntries(
      Object.entries(await stored()).filter(([key]) =>
        key.startsWith("signbridge.motion.v1."),
      ),
    );
  const page = await context.newPage();
  await page.goto(`${origin}/tools/coverage.html`);
  await eventually(
    async () =>
      (await page.locator("#batch-status").textContent()).includes("清单为空"),
    "empty batch",
  );
  assert.equal((await stored())[batchKey], undefined);
  await page
    .locator("#coverage-text")
    .fill("你好 quasar quasar\n谢谢 neutrino\nprivate-marker");
  await page.locator("#coverage-analyze").click();
  await eventually(
    async () => !(await page.locator("#coverage-export").isDisabled()),
    "coverage complete",
  );
  const add = (target, word) =>
    target
      .locator("#coverage-unknown tr")
      .filter({
        has: target.getByRole("rowheader", { name: word, exact: true }),
      })
      .getByRole("button", { name: "加入本批", exact: true })
      .click();
  const row = (target, word) =>
    target.locator("#batch-rows tr").filter({
      has: target.getByRole("rowheader", { name: word, exact: true }),
    });
  const state = async (target, word, expected) =>
    eventually(
      async () =>
        (
          await row(target, word).locator(".batch-state").textContent()
        ).includes(expected),
      expected,
    );
  await add(page, "quasar");
  await state(page, "quasar", "待制作");
  assert.deepEqual((await stored())[batchKey], {
    version: 1,
    words: ["quasar"],
  });
  assert.deepEqual(await motions(), {});
  checks.push(
    "explicitly selecting a real coverage gap persists only the word, never source text or a fabricated motion",
  );

  await page.reload();
  await state(page, "quasar", "待制作");
  assert.equal(await page.locator("#coverage-text").inputValue(), "");
  const other = await context.newPage();
  await other.goto(`${origin}/tools/coverage.html`);
  await state(other, "quasar", "待制作");
  await other.locator("#coverage-text").fill("neutrino");
  await other.locator("#coverage-analyze").click();
  await eventually(
    async () => !(await other.locator("#coverage-export").isDisabled()),
    "other analysis",
  );
  await add(other, "neutrino");
  await state(page, "neutrino", "待制作");
  checks.push(
    "reload retains the batch but discards input; separate tool pages synchronize selections",
  );

  const editorOpened = context.waitForEvent("page");
  await row(page, "quasar")
    .getByRole("button", { name: "姿势编辑器", exact: true })
    .click();
  const editor = await editorOpened;
  await editor.locator("#motion-name").waitFor();
  assert.equal(await editor.locator("#motion-name").inputValue(), "quasar");
  assert.equal(await editor.locator("#motion-texts").inputValue(), "quasar");
  assert.deepEqual(await motions(), {});
  await editor.locator("#preset-dd").selectOption("抬头");
  await editor.locator("#motion-save").click();
  await state(page, "quasar", "已保存候选");
  await state(other, "quasar", "已保存候选");
  const draft = await motions();
  assert.equal(Object.values(draft)[0].enabled, false);
  checks.push(
    "handoff only prefills metadata; a saved test gesture appears as a draft on both pages without enabling translation",
  );

  await editor.locator("#motion-preview").click();
  await editor.waitForTimeout(1000);
  editor.once("dialog", (dialog) => dialog.accept());
  await editor.locator("#motion-enable").click();
  await state(page, "quasar", "可完全匹配");
  await state(other, "quasar", "可完全匹配");
  const downloadPending = page.waitForEvent("download");
  await page.locator("#batch-export").click();
  const download = await downloadPending;
  const progress = JSON.parse(await readFile(await download.path(), "utf8"));
  assert.equal(progress.format, "signbridge-vocabulary-batch");
  assert.equal(progress.linguisticReview, "not-assessed");
  assert.equal(progress.includesSourceText, false);
  assert.deepEqual(
    progress.items.map((item) => item.state),
    ["matched", "missing"],
  );
  assert.equal(JSON.stringify(progress).includes("private-marker"), false);
  assert.equal(
    progress.items[0].matches[0].id,
    Object.values(await motions())[0].asset.id,
  );
  await page.screenshot({
    path: join(output, "01-vocabulary-batch.png"),
    fullPage: true,
  });
  checks.push(
    "explicit human confirmation changes runtime matching status; fresh export contains real IDs and no claim of linguistic approval",
  );

  await editor.locator("#motion-save").click();
  await state(page, "quasar", "已保存候选");
  assert.equal(Object.values(await motions())[0].enabled, false);
  checks.push(
    "editing a saved action revokes approval and immediately returns the batch item to candidate status",
  );

  const beforeReview = await motions();
  const reviewOpened = context.waitForEvent("page");
  await page.locator("#batch-review").click();
  const review = await reviewOpened;
  await review.waitForURL(`${origin}/tools/motion-review.html`);
  await eventually(
    async () =>
      (await review.locator("#review-status").textContent()).includes("已就绪"),
    "review loads",
  );
  assert.deepEqual(await motions(), beforeReview);
  await review.close();
  checks.push(
    "batch opens the real motion-review tool without altering saved gestures",
  );

  const beforeRemoval = await motions();
  await row(page, "neutrino").getByRole("button", { name: "移出本批" }).click();
  await eventually(
    async () => (await other.locator("#batch-rows tr").count()) === 1,
    "removal sync",
  );
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.locator("#batch-clear").click();
  assert.deepEqual((await stored())[batchKey].words, ["quasar"]);
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#batch-clear").click();
  await eventually(
    async () =>
      (await other.locator("#batch-status").textContent()).includes("清单为空"),
    "clearing sync",
  );
  assert.deepEqual(await motions(), beforeRemoval);
  checks.push(
    "remove and confirmed clear affect only the worklist; cancelling leaves it intact",
  );

  await other.close();
  await worker.evaluate(
    (key) =>
      chrome.storage.local.set({ [key]: { version: 999, words: ["keep"] } }),
    batchKey,
  );
  await eventually(
    async () =>
      (await page.locator("#batch-status").textContent()).includes("数据无效"),
    "invalid batch rejected",
  );
  assert.equal(await page.locator("#batch-export").isDisabled(), true);
  assert.equal((await stored())[batchKey].version, 999);
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#batch-clear").click();
  await eventually(
    async () =>
      (await page.locator("#batch-status").textContent()).includes("清单为空"),
    "recover malformed batch",
  );
  checks.push(
    "corrupt lists block export without silent overwriting and recover only after an explicit clear",
  );

  await page.locator("#batch-word").fill("医院 挂号");
  await page.locator("#batch-add-form button").click();
  await eventually(
    async () => (await stored())[batchKey].words.length === 1,
    "manual phrase",
  );
  assert.deepEqual((await stored())[batchKey].words, ["医院 挂号"]);
  for (let index = 1; index <= 7; index++) {
    await page.locator("#batch-word").fill(`candidate${index}`);
    await page.locator("#batch-add-form button").click();
    await eventually(
      async () => (await stored())[batchKey].words.length === index + 1,
      "manual add",
    );
  }
  await page.locator("#batch-word").fill("ninth");
  await page.locator("#batch-add-form button").click();
  await eventually(
    async () =>
      (await page.locator("#batch-status").textContent()).includes("已满 8"),
    "batch limit",
  );
  assert.equal((await stored())[batchKey].words.length, 8);
  assert.equal(await page.locator("#batch-word").inputValue(), "ninth");
  assert.deepEqual(await motions(), beforeRemoval);
  checks.push(
    "manual phrases retain their boundaries; the eight-item limit rejects excess items without losing data",
  );

  await worker.evaluate(
    (key) =>
      chrome.storage.local.set({ [key]: { version: 1, words: ["quasar"] } }),
    batchKey,
  );
  const failure = await context.newPage();
  await failure.addInitScript(() => {
    const original = globalThis.fetch;
    globalThis.fetch = (...args) => {
      const url = args[0]?.url || String(args[0]);
      if (!url.endsWith("/avatar/model.glb")) return original(...args);
      globalThis.fetch = original;
      return Promise.resolve(
        new Response(
          JSON.stringify({ asset: { version: "2.0" }, scenes: [{}], scene: 0 }),
        ),
      );
    };
  });
  await failure.goto(`${origin}/tools/coverage.html`);
  await eventually(
    async () =>
      (await failure.locator("#batch-status").textContent()).includes(
        "无法核验",
      ),
    "model failure",
  );
  assert.equal(await failure.locator("#batch-export").isDisabled(), true);
  await state(failure, "quasar", "状态未核验");
  await failure.locator("#batch-refresh").click();
  await state(failure, "quasar", "已保存候选");
  assert.deepEqual(await motions(), beforeRemoval);
  checks.push(
    "model validation failure is not reported as missing vocabulary; retry recovers without modifying motions",
  );

  assert.deepEqual(
    requests.filter((url) => /^https?:/.test(url)),
    [],
  );
  assert.deepEqual(errors, []);
  checks.push(
    "no unexpected browser errors or external requests; all actions use isolated browser data",
  );
  await writeFile(
    join(output, "report.json"),
    JSON.stringify({ checks, errors }, null, 2),
  );
  console.log(JSON.stringify({ checks, errors }, null, 2));
} catch (error) {
  await writeFile(
    join(output, "failure.json"),
    JSON.stringify({ checks, errors, failure: error.stack }, null, 2),
  );
  for (const [index, page] of (context?.pages() || []).entries()) {
    await page
      .screenshot({
        path: join(output, `failure-${index}.png`),
        fullPage: true,
      })
      .catch(() => {});
  }
  throw error;
} finally {
  await context?.close();
  await rm(profile, { recursive: true, force: true });
}
