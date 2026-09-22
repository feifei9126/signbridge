import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "test-results/phase4-browser");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "signbridge-phase4-"));
const checks = [];
const errors = [];
const requests = [];
let context;
let acceptDialogs = true;
function observe(page) {
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("dialog", (dialog) =>
    acceptDialogs ? dialog.accept() : dialog.dismiss(),
  );
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
  const prefix = "signbridge.motion.v1.";
  const saved = () =>
    worker.evaluate(
      async (prefix) =>
        Object.fromEntries(
          Object.entries(await chrome.storage.local.get(null)).filter(([key]) =>
            key.startsWith(prefix),
          ),
        ),
      prefix,
    );
  const editor = await context.newPage();
  await editor.goto(`${origin}/avatar/pose-editor.html`);
  await editor.locator("#motion-save").waitFor();
  await editor.locator("#preset-dd").selectOption("抬头");
  await editor.locator("#motion-name").fill("已验收测试姿势");
  await editor.locator("#motion-texts").fill("quasar");
  await editor.locator("#motion-save").click();
  await eventually(
    async () => Object.keys(await saved()).length === 1,
    "saved original",
  );
  await editor.locator("#motion-preview").click();
  await editor.waitForTimeout(1100);
  await editor.locator("#motion-enable").click();
  await eventually(
    async () => Object.values(await saved())[0].enabled,
    "original approved",
  );
  const originalRecord = Object.values(await saved())[0];
  await editor.locator("#motion-name").fill("未保存的编辑不应进入备份");
  await worker.evaluate(() =>
    chrome.storage.local.set({ packTestSecret: "private-asr-key-marker" }),
  );
  await editor.locator("#motion-pack summary").click();
  const downloadPending = editor.waitForEvent("download");
  await editor.locator("#motion-pack-export").click();
  const download = await downloadPending;
  const json = await readFile(await download.path(), "utf8");
  const pack = JSON.parse(json);
  assert.equal(pack.type, "signbridge-motion-pack");
  assert.equal(pack.motions.length, 1);
  assert.deepEqual(pack.motions[0].asset, originalRecord.asset);
  assert.equal(pack.motions[0].wasEnabled, true);
  assert.equal(json.includes("private-asr-key-marker"), false);
  assert.equal(json.includes("未保存的编辑"), false);
  checks.push(
    "real editor exports exact saved motion data and informational status, not unsaved work or unrelated secrets",
  );

  const clip = structuredClone(originalRecord.asset);
  clip.id = "custom_phase4_imported";
  clip.gloss = "<img src=x onerror=alert(1)>测试多帧";
  clip.texts = ["nebula"];
  clip.frames = [
    { value: { head: { x: -0.432156781923, y: 0, z: 0 } }, duration: 0.7 },
    { value: { head: { x: 0.223456789123, y: 0, z: 0 } }, duration: 1.4 },
  ];
  const transfer = {
    ...pack,
    motions: [
      ...pack.motions,
      {
        asset: clip,
        wasEnabled: true,
        enabled: true,
        review: { trusted: true },
      },
    ],
  };
  const recorder = await context.newPage();
  await recorder.goto(`${origin}/avatar/record-mode.html`);
  await recorder.locator("#motion-pack").waitFor();
  await recorder.locator("#motion-name").fill("保留当前编辑");
  await recorder.locator("#motion-pack summary").click();
  const input = async (value, page = recorder) => {
    await page.locator("#motion-pack-file").setInputFiles({
      name: "library.motion-pack.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        typeof value === "string" ? value : JSON.stringify(value),
      ),
    });
  };
  const statusIncludes = (text, page = recorder) =>
    eventually(
      async () =>
        (await page.locator("#motion-pack-status").textContent()).includes(
          text,
        ),
      text,
    );
  const before = await saved();
  await input(transfer);
  await statusIncludes("预检完成");
  assert.equal(
    await recorder.locator('#motion-pack-results tr[data-state="new"]').count(),
    1,
  );
  assert.equal(
    await recorder
      .locator('#motion-pack-results tr[data-state="existing"]')
      .count(),
    1,
  );
  assert.equal(await recorder.locator("#motion-pack-results img").count(), 0);
  assert.match(
    await recorder.locator("#motion-pack-results").textContent(),
    /<img src=x/,
  );
  assert.deepEqual(await saved(), before);
  assert.equal(
    await recorder.locator("#motion-name").inputValue(),
    "保留当前编辑",
  );
  checks.push(
    "pack selection is read-only preflight; new and identical IDs are distinguished and names render safely",
  );
  acceptDialogs = false;
  await recorder.locator("#motion-pack-import").click();
  acceptDialogs = true;
  assert.deepEqual(await saved(), before);
  await recorder.locator("#motion-pack-clear").click();
  assert.equal(
    await recorder.locator("#motion-pack-import").isDisabled(),
    true,
  );
  assert.equal(
    await recorder.locator("#motion-pack-results").isVisible(),
    false,
  );
  assert.deepEqual(await saved(), before);
  checks.push(
    "dismissing confirmation or clearing the file writes nothing and preserves current editing fields",
  );
  await input(transfer);
  await statusIncludes("预检完成");
  await recorder.locator("#motion-pack-import").click();
  await statusIncludes("已新增 1 个草稿");
  const imported = await saved();
  assert.deepEqual(imported[prefix + originalRecord.asset.id], originalRecord);
  assert.deepEqual(imported[prefix + clip.id].asset, clip);
  assert.equal(imported[prefix + clip.id].enabled, false);
  assert.equal(imported[prefix + clip.id].review, null);
  assert.equal(
    await recorder.locator("#motion-name").inputValue(),
    "保留当前编辑",
  );
  await recorder.locator("#motion-list").selectOption(clip.id);
  await recorder.locator("#motion-load").click();
  await recorder.locator("#btn-export-json").click();
  assert.deepEqual(
    JSON.parse(await recorder.locator("#export-box").inputValue()).frames,
    clip.frames,
  );
  checks.push(
    "confirmation imports exact multi-frame drafts once, keeps existing approval and does not auto-load or trust foreign approval",
  );

  const coverage = await context.newPage();
  await coverage.goto(`${origin}/tools/coverage.html`);
  await coverage.locator("#coverage-text").fill("nebula");
  const measure = async () => {
    await coverage.locator("#coverage-analyze").click();
    await eventually(
      async () => !(await coverage.locator("#coverage-export").isDisabled()),
      "coverage analysis",
    );
    const pending = coverage.waitForEvent("download");
    await coverage.locator("#coverage-export").click();
    const result = await pending;
    return JSON.parse(await readFile(await result.path(), "utf8"));
  };
  assert.equal((await measure()).summary.coverage, 0);
  await recorder.locator("#motion-preview").click();
  await recorder.waitForTimeout(2400);
  await recorder.locator("#motion-enable").click();
  await eventually(
    async () => (await saved())[prefix + clip.id].enabled,
    "individual approval",
  );
  assert.equal((await measure()).summary.coverage, 1);
  checks.push(
    "imported draft is excluded from coverage until the normal per-motion preview and confirmation workflow",
  );

  await input(transfer);
  await statusIncludes("预检完成");
  assert.equal(
    await recorder
      .locator('#motion-pack-results tr[data-state="existing"]')
      .count(),
    2,
  );
  assert.equal(
    await recorder.locator("#motion-pack-import").isDisabled(),
    true,
  );
  const confirmed = await saved();
  const conflict = structuredClone(transfer);
  conflict.motions[1].asset.gloss = "same ID, different content";
  conflict.motions.push({
    asset: { ...clip, id: "custom_should_not_import" },
    wasEnabled: false,
  });
  await input(conflict);
  await statusIncludes("整包导入已阻止");
  assert.equal(
    await recorder.locator("#motion-pack-import").isDisabled(),
    true,
  );
  assert.deepEqual(await saved(), confirmed);
  checks.push(
    "repeated imports are no-ops; a changed duplicate ID blocks the whole batch without overwriting or dropping approval",
  );

  const fresh = {
    ...pack,
    motions: [
      {
        asset: { ...clip, id: "custom_new_draft", texts: ["hello---"] },
        wasEnabled: false,
      },
    ],
  };
  await input(fresh);
  await statusIncludes("预检完成");
  assert.match(
    await recorder.locator("#motion-pack-results").textContent(),
    /匹配文字可能重复/,
  );
  await editor.locator("#motion-save").click();
  await statusIncludes("旧预检失效");
  assert.equal(
    await recorder.locator("#motion-pack-import").isDisabled(),
    true,
  );
  await recorder.locator("#motion-pack-inspect").click();
  await statusIncludes("预检完成");
  assert.equal(
    await recorder.locator("#motion-pack-import").isDisabled(),
    false,
  );
  await recorder.screenshot({ path: join(output, "01-pack-preflight.png") });
  checks.push(
    "another page's save expires preflight; rerun restores it and built-in alias collisions are visibly warned",
  );

  const unchanged = await saved();
  const incompatible = structuredClone(fresh);
  incompatible.motions[0].asset.rig.rest = "wrong-model";
  const duplicate = { ...fresh, motions: [fresh.motions[0], fresh.motions[0]] };
  for (const [value, error] of [
    ["{", "不是有效"],
    [incompatible, "模型骨骼"],
    [duplicate, "重复 ID"],
  ]) {
    await input(value);
    await statusIncludes(error);
    assert.equal(
      await recorder.locator("#motion-pack-import").isDisabled(),
      true,
    );
    assert.deepEqual(await saved(), unchanged);
  }
  for (const [bytes, error] of [
    [Buffer.from([0xff, 0x01]), "UTF-8"],
    [Buffer.alloc(8 * 1024 * 1024 + 1), "超过限制"],
  ]) {
    await recorder.locator("#motion-pack-file").setInputFiles({
      name: "bad.json",
      mimeType: "application/json",
      buffer: bytes,
    });
    await statusIncludes(error);
    assert.deepEqual(await saved(), unchanged);
  }
  checks.push(
    "invalid JSON, incompatible rig, duplicate IDs, oversized files and invalid UTF-8 all fail without writes",
  );

  await recorder.evaluate(() => {
    const original = File.prototype.arrayBuffer;
    File.prototype.arrayBuffer = function () {
      const pending = original.call(this);
      File.prototype.arrayBuffer = original;
      return new Promise((resolve) => {
        window.finishPackRead = async () => resolve(await pending);
      });
    };
  });
  await input(fresh);
  await recorder.waitForFunction(
    () => typeof window.finishPackRead === "function",
  );
  await recorder.locator("#motion-pack-clear").click();
  await recorder.evaluate(() => window.finishPackRead());
  await recorder.waitForTimeout(200);
  assert.equal(
    await recorder.locator("#motion-pack-results").isVisible(),
    false,
  );
  assert.equal(
    await recorder.locator("#motion-pack-import").isDisabled(),
    true,
  );
  assert.deepEqual(await saved(), unchanged);
  checks.push(
    "a late file read cannot resurrect a cancelled preflight or write to storage",
  );

  await recorder.reload();
  await recorder.locator("#motion-pack").waitFor();
  assert.equal(
    await recorder.locator("#motion-pack-results").isVisible(),
    false,
  );
  assert.equal(await recorder.locator("#motion-pack-file").inputValue(), "");
  const help = await context.newPage();
  await help.goto(`${origin}/avatar/help.html`);
  assert.match(
    await help.locator('[data-i18n="motionPackHelp"]').textContent(),
    /同 ID 同内容跳过/,
  );
  assert.deepEqual(
    requests.filter((url) => /^https?:/.test(url)),
    [],
  );
  assert.deepEqual(errors, []);
  checks.push(
    "pending files are not persisted, help is localized, no external requests or page/console errors occur",
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
