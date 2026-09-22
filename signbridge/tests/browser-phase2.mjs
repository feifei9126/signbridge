import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "test-results", "phase2-browser");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "signbridge-phase2-"));
const server = createServer((_request, response) => {
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(
    '<!doctype html><title>Motion pipeline test</title><h1>第二阶段动作共享验证</h1><video controls width="640" height="360"></video><p class="subtitle-text"></p>',
  );
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let context;
const errors = [];
const checks = [];
const logs = [];
async function eventually(check, description) {
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${description}`);
}
function observe(page, name) {
  page.on("pageerror", (error) => errors.push(`${name}: ${error.message}`));
  page.on("console", async (message) => {
    const args = await Promise.all(
      message.args().map((argument) => argument.jsonValue().catch(() => null)),
    );
    logs.push({ page: name, type: message.type(), text: message.text(), args });
    if (message.type() === "error") errors.push(`${name}: ${message.text()}`);
  });
  page.on("dialog", (dialog) => dialog.accept());
}
try {
  const extension = join(root, "dist");
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
    headless: true,
    locale: "zh-CN",
    viewport: { width: 1440, height: 1000 },
    args: [
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  const worker =
    context.serviceWorkers()[0] ||
    (await context.waitForEvent("serviceworker"));
  const extensionOrigin = `chrome-extension://${new URL(worker.url()).host}`;
  const prefix = "signbridge.motion.v1.";
  const saved = () =>
    worker.evaluate(
      async (prefix) =>
        Object.entries(await chrome.storage.local.get(null))
          .filter(([key]) => key.startsWith(prefix))
          .map(([, value]) => value),
      prefix,
    );
  const host = await context.newPage();
  observe(host, "host");
  await host.goto(`http://127.0.0.1:${server.address().port}/`);
  await host.locator("#signbridge-overlay iframe").waitFor();
  await host.waitForFunction(() => !document.getElementById("sb-loading"));
  await host.bringToFront();
  const tabId = await worker.evaluate(
    async () =>
      (await chrome.tabs.query({ active: true, currentWindow: true }))[0].id,
  );
  const send = (text) =>
    worker.evaluate(
      ({ tabId, text }) =>
        chrome.tabs.sendMessage(tabId, { action: "sendText", text }),
      { tabId, text },
    );

  const editor = await context.newPage();
  observe(editor, "editor");
  await editor.goto(`${extensionOrigin}/avatar/pose-editor.html`);
  await editor.locator("#motion-save").waitFor();
  await editor.locator("#preset-dd").selectOption("抬头");
  await editor.locator("#motion-name").fill("阶段二姿势样本");
  await editor.locator("#motion-texts").fill("phase two");
  await editor.locator("#motion-tags").fill("test");
  await editor.locator("#motion-save").click();
  await eventually(async () => (await saved()).length === 1, "draft saved");
  const original = (await saved())[0].asset;
  assert.ok(
    Math.abs(original.frames[0].value.head.x - (-43.9 * Math.PI) / 180) < 1e-8,
  );
  await send("phase two");
  await eventually(
    () => logs.some((line) => line.args[0] === "[SB] Translation coverage:"),
    "draft coverage",
  );
  assert.ok(
    !logs.some((line) => line.args[1]?.motionIds?.includes(original.id)),
  );
  checks.push(
    "editor captures calibrated REST deltas in radians; draft does not translate",
  );

  await editor.locator("#motion-preview").click();
  await editor.waitForTimeout(1000);
  await editor.locator("#motion-enable").click();
  await eventually(
    async () => (await saved())[0].enabled === true,
    "confirmed pose enabled",
  );
  await eventually(
    () =>
      logs.some(
        (line) =>
          line.args[0] === "[SB] Motion library:" &&
          line.args[1]?.enabled === 1,
      ),
    "avatar hot reload",
  );
  await host.bringToFront();
  await send("phase two");
  await eventually(
    () => logs.some((line) => line.args[1]?.motionIds?.includes(original.id)),
    "runtime matches approved asset",
  );
  await host.waitForTimeout(250);
  await host.screenshot({ path: join(output, "01-runtime-custom-pose.png") });
  checks.push(
    "explicit confirmation hot-loads the same custom motion into an already-open avatar",
  );

  const recorder = await context.newPage();
  observe(recorder, "recorder");
  await recorder.goto(`${extensionOrigin}/avatar/record-mode.html`);
  await recorder
    .locator(`#motion-list option[value="${original.id}"]`)
    .waitFor({ state: "attached" });
  await recorder.locator("#motion-list").selectOption(original.id);
  await recorder.locator("#motion-load").click();
  await recorder.locator("#btn-export-json").click();
  const readRecorder = async () =>
    JSON.parse(await recorder.locator("#export-box").inputValue());
  assert.deepEqual((await readRecorder()).frames, original.frames);
  await recorder.locator("#motion-import-file").setInputFiles({
    name: "pose.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(original)),
  });
  await recorder.locator("#btn-export-json").click();
  assert.deepEqual((await readRecorder()).frames, original.frames);
  assert.notEqual((await readRecorder()).id, original.id);
  checks.push(
    "editor → shared library → recorder and JSON import preserve all frame precision and duration",
  );

  await recorder.locator("#btn-stop-preview").click();
  await recorder.locator("#motion-frame-duration").fill("0.55");
  await recorder.locator("#sl_head_x").evaluate((slider) => {
    slider.value = "0.2";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await recorder.locator("#btn-add-keyframe").click();
  await recorder.locator("#motion-name").fill("阶段二双帧样本");
  await recorder.locator("#motion-texts").fill("phase two sequence");
  await recorder.locator("#motion-save").click();
  await eventually(async () => (await saved()).length === 2, "sequence saved");
  const clip = (await saved()).find(
    (entry) => entry.asset.id !== original.id,
  ).asset;
  assert.equal(clip.frames.length, 2);
  assert.equal(clip.frames[1].duration, 0.55);
  assert.equal(clip.frames[0].duration, original.frames[0].duration);
  await recorder.locator("#motion-preview").click();
  await recorder.waitForTimeout(1600);
  await recorder.locator("#motion-enable").click();
  await eventually(
    async () => (await saved()).every((entry) => entry.enabled),
    "sequence enabled",
  );
  await recorder.screenshot({ path: join(output, "02-recorder-library.png") });
  checks.push(
    "recorder saves variable-duration clips and previews with the shared motion player",
  );

  const bad = { ...clip, unit: "degrees" };
  await recorder.locator("#motion-import-file").setInputFiles({
    name: "bad.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(bad)),
  });
  await eventually(
    async () =>
      (await recorder.locator("#motion-status").textContent()).includes(
        "未完成",
      ),
    "bad unit rejected",
  );
  await recorder.locator("#btn-export-json").click();
  assert.deepEqual((await readRecorder()).frames, clip.frames);
  const incompatible = {
    ...clip,
    rig: { ...clip.rig, rest: "different model" },
  };
  await recorder.locator("#motion-import-file").setInputFiles({
    name: "other-rig.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(incompatible)),
  });
  await eventually(
    async () =>
      (await recorder.locator("#motion-status").textContent()).includes(
        "不一致",
      ),
    "model mismatch rejected",
  );
  checks.push(
    "invalid units and mismatched REST bindings are rejected without replacing current frames",
  );

  await editor
    .locator(`#motion-list option[value="${clip.id}"]`)
    .waitFor({ state: "attached" });
  await editor.locator("#motion-list").selectOption(clip.id);
  await editor.locator("#motion-load").click();
  await eventually(
    async () =>
      (await editor.locator("#motion-status").textContent()).includes(
        "多帧动画",
      ),
    "editor refuses to truncate a clip",
  );
  await editor.locator("#btn-export-json").click();
  const readEditor = async () =>
    JSON.parse(await editor.locator("#output-text").textContent());
  assert.equal((await readEditor()).id, original.id);
  assert.ok(
    Math.abs(
      (await readEditor()).frames[0].value.head.x -
        original.frames[0].value.head.x,
    ) < 1e-8,
  );
  checks.push(
    "single-pose editor refuses multi-frame loading rather than silently losing frames",
  );

  const beforeFrames = (await readEditor()).frames;
  const beforeView = await editor.locator("#viewer").screenshot();
  const bounds = await editor.locator("#viewer canvas").boundingBox();
  await editor.mouse.move(
    bounds.x + bounds.width / 2,
    bounds.y + bounds.height / 2,
  );
  await editor.mouse.down();
  await editor.mouse.move(
    bounds.x + bounds.width / 2 + 100,
    bounds.y + bounds.height / 2,
    { steps: 12 },
  );
  await editor.mouse.up();
  await editor.mouse.wheel(0, -180);
  await editor.waitForTimeout(400);
  assert.notDeepEqual(await editor.locator("#viewer").screenshot(), beforeView);
  await editor.locator("#btn-export-json").click();
  assert.deepEqual((await readEditor()).frames, beforeFrames);
  checks.push(
    "editor mouse rotation and zoom remain functional without changing bone data",
  );

  await editor.evaluate(() =>
    localStorage.setItem(
      "sb_gestures",
      JSON.stringify({
        "旧抬头 <img src=x>": {
          library: "历史",
          delta: { head: { x: -43.9, y: 0, z: 0 } },
          timestamp: "2026-09-01",
        },
      }),
    ),
  );
  await editor.locator("#motion-legacy").click();
  await eventually(
    async () => (await saved()).length === 3,
    "legacy degrees migrated",
  );
  const legacy = (await saved()).find((entry) =>
    entry.asset.gloss.startsWith("旧抬头"),
  );
  assert.equal(legacy.enabled, false);
  assert.equal(legacy.asset.frames[0].value.head.x, (-43.9 * Math.PI) / 180);
  assert.equal(await editor.locator("#motion-library img").count(), 0);
  assert.ok(await editor.evaluate(() => localStorage.getItem("sb_gestures")));
  await editor.screenshot({ path: join(output, "03-editor-migration.png") });
  checks.push(
    "legacy degrees migrate to drafts, original local data retained, names rendered as plain text",
  );

  await recorder.locator("#motion-save").click();
  await eventually(
    async () =>
      !(await saved()).find((entry) => entry.asset.id === clip.id).enabled,
    "edit revokes approval",
  );
  const startLogs = logs.length;
  await host.bringToFront();
  await host.waitForTimeout(250);
  await send("phase two sequence");
  await eventually(
    () =>
      logs
        .slice(startLogs)
        .some((line) => line.args[0] === "[SB] Translation coverage:"),
    "post-edit translation",
  );
  assert.ok(
    !logs
      .slice(startLogs)
      .some((line) => line.args[1]?.motionIds?.includes(clip.id)),
  );
  checks.push(
    "saving an edited clip revokes approval and removes it from the live translation catalog",
  );

  await recorder.locator('#keyframes [data-index="1"]').click();
  await recorder.locator("#motion-frame-duration").fill("0.4");
  await recorder.locator("#sl_head_x").evaluate((slider) => {
    slider.value = "0.3";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await recorder.locator("#btn-export-json").click();
  assert.deepEqual((await readRecorder()).frames, clip.frames);
  await recorder.locator("#btn-apply-keyframe").click();
  await recorder.locator("#btn-export-json").click();
  const updated = await readRecorder();
  assert.deepEqual(updated.frames[0], clip.frames[0]);
  assert.equal(updated.frames[1].duration, 0.4);
  assert.ok(
    Math.abs(
      updated.frames[1].value.head.x - clip.frames[1].value.head.x - 0.1,
    ) < 1e-8,
  );
  assert.deepEqual(
    (await saved()).find((entry) => entry.asset.id === clip.id).asset.frames,
    clip.frames,
  );
  await recorder.locator("#btn-delete-keyframe").click();
  assert.equal(
    await recorder.locator("#keyframes .active").getAttribute("data-index"),
    "0",
  );
  await recorder.locator("#btn-export-json").click();
  assert.deepEqual((await readRecorder()).frames, [clip.frames[0]]);
  await recorder.locator("#btn-delete-keyframe").click();
  assert.equal(await recorder.locator("#keyframes .kf").count(), 0);
  checks.push(
    "recorder updates only the selected frame on confirmation, preserves saved copies and selects the remaining frame after deletion",
  );

  await editor.locator("#preset-dd").selectOption("fist");
  await editor.locator("#sl_rightUpperArm_x").evaluate((slider) => {
    slider.value = "0.3";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await editor.locator("#btn-export-json").click();
  const handPose = await readEditor();
  assert.ok(Math.abs(handPose.frames[0].value.rightUpperArm.x) > 0.1);
  assert.ok(Math.abs(handPose.frames[0].value.rightIndexProximal.x) > 0.1);
  await recorder.locator("#motion-import-file").setInputFiles({
    name: "hand-pose.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(handPose)),
  });
  await recorder.locator("#btn-export-json").click();
  assert.deepEqual((await readRecorder()).frames, handPose.frames);
  await recorder.locator("#btn-apply-keyframe").click();
  await recorder.locator("#btn-export-json").click();
  const recapturedPose = (await readRecorder()).frames[0].value;
  for (const [bone, rotation] of Object.entries(handPose.frames[0].value)) {
    for (const axis of ["x", "y", "z"])
      assert.ok(
        Math.abs(recapturedPose[bone][axis] - rotation[axis]) < 1e-8,
        `${bone}.${axis}`,
      );
  }
  checks.push(
    "real model arm and full-finger preset retain REST deltas through editor export, recorder import and recapture",
  );

  const help = await context.newPage();
  observe(help, "help");
  await help.goto(`${extensionOrigin}/avatar/help.html`);
  await eventually(
    async () =>
      (await help.locator("#motion-help").textContent()).includes("保存草稿"),
    "localized motion help",
  );
  assert.ok(
    (await help.locator("#motion-help").textContent()).includes("预览"),
  );
  assert.ok(
    (await help.locator('[data-i18n="motionHelpAxes"]').textContent()).includes(
      "本地轴",
    ),
  );
  checks.push(
    "extension help loads the shared-library workflow and accurate local-axis guidance without inline scripts",
  );
  assert.deepEqual(errors, []);
  checks.push(
    "no page exceptions or console errors in editor, recorder or host",
  );
} catch (error) {
  errors.push(error.stack || String(error));
  if (context)
    for (const [index, page] of context.pages().entries()) {
      await page
        .screenshot({ path: join(output, `failure-${index}.png`) })
        .catch(() => {});
    }
  process.exitCode = 1;
} finally {
  await writeFile(
    join(output, "report.json"),
    JSON.stringify({ checks, errors, logs }, null, 2),
  );
  console.log(JSON.stringify({ checks, errors }, null, 2));
  await context?.close();
  await new Promise((resolve) => server.close(resolve));
  await rm(profile, { recursive: true, force: true });
}
