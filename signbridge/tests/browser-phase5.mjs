import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const output = join(root, "test-results/phase5-browser");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(join(tmpdir(), "signbridge-phase5-"));
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
async function eventually(check, description, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${description}`);
}
async function baselines(page, changes = null) {
  return page.evaluate(async (changes) => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open("signbridge-visual-review", 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("baselines", { keyPath: "key" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      return await new Promise((resolve, reject) => {
        const transaction = database.transaction(
          "baselines",
          changes ? "readwrite" : "readonly",
        );
        const store = transaction.objectStore("baselines");
        const request = store.getAll();
        request.onsuccess = () => {
          if (changes) {
            const target = request.result.find(
              (record) => record.key === changes.key,
            );
            store.put({ ...target, ...changes });
          }
        };
        transaction.oncomplete = () =>
          resolve(
            request.result.map(({ image, ...record }) => ({
              ...record,
              bytes: image.size,
            })),
          );
        transaction.onabort = () => reject(transaction.error);
      });
    } finally {
      database.close();
    }
  }, changes);
}

try {
  const extension = join(root, "dist");
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
    headless: true,
    locale: "zh-CN",
    viewport: { width: 1440, height: 1100 },
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
  const storage = () => worker.evaluate(() => chrome.storage.local.get(null));
  await worker.evaluate(() =>
    chrome.storage.local.set({ reviewTestPrivate: "private-test-marker" }),
  );
  const originalStorage = await storage();
  const popup = await context.newPage();
  await popup.goto(`${origin}/popup/index.html`);
  const workspaceOpened = context.waitForEvent("page");
  await popup.locator("#btnDemo").click();
  const workspace = await workspaceOpened;
  await workspace.waitForURL(`${origin}/demo/index.html`);
  await workspace.locator("#research-details > summary").click();
  const opened = context.waitForEvent("page");
  await workspace.locator("#btnMotionReview").click();
  const page = await opened;
  await page.waitForURL(`${origin}/tools/motion-review.html`);
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("已就绪"),
    "actual model ready",
  );
  assert.equal(await page.locator("#review-catalog input").count(), 52);
  await page.screenshot({
    path: join(output, "01-review-ready.png"),
    fullPage: true,
  });
  checks.push(
    "workspace opens localized CSP-safe review page, real model and 52 unique built-in signs",
  );
  const select = async (keys) => {
    while (await page.locator("#review-catalog input:checked").count())
      await page.locator("#review-catalog input:checked").first().uncheck();
    for (const key of keys)
      await page.locator(`#review-catalog input[value="${key}"]`).check();
  };
  const capture = async () => {
    await page.locator("#review-capture").click();
    await eventually(
      async () =>
        !(await page.locator("#review-export").isDisabled()) &&
        (await page.locator("#review-stop").isDisabled()),
      "capture complete",
      45000,
    );
  };
  const report = async () => {
    const pending = page.waitForEvent("download");
    await page.locator("#review-export").click();
    const download = await pending;
    return JSON.parse(await readFile(await download.path(), "utf8"));
  };
  const helloCard = page.locator('.review-card[data-key="builtin:csl_hello"]');
  await select(["builtin:csl_hello", "builtin:csl_thanks"]);
  await capture();
  const initial = await report();
  assert.equal(initial.motions.length, 2);
  assert.equal(
    initial.environment.modelHash,
    "97c3bcc37aeb0212203376ba3e69c4c7346357dcef8e2b626768e96ecfe1dc69",
  );
  assert.equal(initial.motions[0].width, 960);
  assert.equal(initial.motions[0].height, 720);
  assert.deepEqual(initial.views, ["front", "right", "left"]);
  assert.equal(initial.linguisticApproval, false);
  assert.equal(JSON.stringify(initial).includes("private-test-marker"), false);
  assert.ok(
    initial.motions.every(
      (item) => item.usedBones.length > 0 && item.comparison === "missing",
    ),
  );
  const pngPending = page.waitForEvent("download");
  await helloCard.locator('[data-action="download"]').click();
  const png = await pngPending;
  await png.saveAs(join(output, "02-hello-three-views.png"));
  assert.ok((await readFile(await png.path())).length > 10000);
  await page.screenshot({
    path: join(output, "03-capture-results.png"),
    fullPage: true,
  });
  checks.push(
    "three fixed views and exact keyframes produce nonempty PNG and sanitized diagnostic report",
  );

  await select(["builtin:csl_hello"]);
  const restingImage = await page.locator("#review-canvas").screenshot();
  await page.locator("#review-play").click();
  await page.waitForTimeout(230);
  const animatedImage = await page.locator("#review-canvas").screenshot();
  assert.notDeepEqual(restingImage, animatedImage);
  await eventually(
    async () => await page.locator("#review-stop").isDisabled(),
    "playback ends",
  );
  checks.push(
    "real shared player visibly moves the model and finishes without a permanent rendering loop",
  );

  acceptDialogs = false;
  await helloCard.locator('[data-action="save"]').click();
  await eventually(
    async () => !(await helloCard.locator('[data-action="save"]').isDisabled()),
    "cancel confirmation",
  );
  assert.equal((await baselines(page)).length, 0);
  acceptDialogs = true;
  await helloCard.locator('[data-action="save"]').click();
  await eventually(
    async () => (await baselines(page)).length === 1,
    "saved baseline",
  );
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes(
        "视觉基准已保存",
      ),
    "save finished",
  );
  const savedBaseline = (await baselines(page))[0];
  assert.deepEqual(await storage(), originalStorage);
  checks.push(
    "baseline save requires confirmation, cancellation writes nothing, and saving never changes translation storage",
  );

  await capture();
  const identical = (await report()).motions[0];
  assert.equal(identical.comparison, "comparable");
  assert.equal(identical.difference.changedRatio, 0);
  assert.equal(identical.imageHash, savedBaseline.imageHash);
  await page.reload();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("已就绪"),
    "reopened review",
  );
  await select(["builtin:csl_hello"]);
  await capture();
  assert.equal((await report()).motions[0].difference.changedRatio, 0);
  checks.push(
    "identical captures compare at zero pixel difference; confirmed baseline persists across reload",
  );

  await baselines(page, {
    key: "builtin:csl_hello",
    imageHash: "corrupt-reference",
  });
  await capture();
  const corruptReference = (await report()).motions[0];
  assert.equal(corruptReference.comparison, "unavailable");
  assert.equal(corruptReference.difference, null);
  assert.equal(
    await helloCard.locator('[data-action="save"]').isEnabled(),
    true,
  );
  await baselines(page, {
    key: "builtin:csl_hello",
    imageHash: savedBaseline.imageHash,
  });
  await capture();
  checks.push(
    "corrupt reference fingerprints show a comparison error instead of false success or blocking capture",
  );

  await baselines(page, {
    key: "builtin:csl_hello",
    token: "concurrent-page-change",
  });
  await helloCard.locator('[data-action="save"]').click();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("另一页面"),
    "concurrent baseline blocked",
  );
  assert.equal((await baselines(page))[0].token, "concurrent-page-change");
  await capture();
  await baselines(page, {
    key: "builtin:csl_hello",
    environmentHash: "different-renderer",
  });
  await capture();
  assert.equal((await report()).motions[0].comparison, "incompatible");
  checks.push(
    "concurrent baseline overwrites are blocked and incompatible renderer metadata disables numeric comparison",
  );

  const editor = await context.newPage();
  await editor.goto(`${origin}/avatar/pose-editor.html`);
  await editor.locator("#motion-save").waitFor();
  await editor.locator("#preset-dd").selectOption("抬头");
  await editor.locator("#motion-name").fill("目视测试");
  await editor.locator("#motion-texts").fill("review-isolated-test");
  await editor.locator("#motion-save").click();
  const prefix = "signbridge.motion.v1.";
  await eventually(
    async () =>
      Object.keys(await storage()).some((key) => key.startsWith(prefix)),
    "editor saved draft",
  );
  const [motionKey, motionRecord] = Object.entries(await storage()).find(
    ([key]) => key.startsWith(prefix),
  );
  const longMotion = structuredClone(motionRecord);
  longMotion.asset.gloss = "<img src=x onerror=alert(1)> long motion";
  longMotion.asset.frames = Array.from({ length: 16 }, (_, index) => ({
    value: { head: { x: index * -0.035, y: 0, z: 0 } },
    duration: 0.3,
  }));
  await worker.evaluate(
    ({ motionKey, longMotion }) =>
      chrome.storage.local.set({ [motionKey]: longMotion }),
    { motionKey, longMotion },
  );
  await eventually(
    async () =>
      (await page.locator("#review-count").textContent()).includes("53"),
    "new custom motion visible",
  );
  assert.equal(await page.locator("#review-results").isVisible(), false);
  assert.equal(await page.locator("#review-catalog img").count(), 0);
  await select([`custom:${longMotion.asset.id}`]);
  await capture();
  const longReport = (await report()).motions[0];
  assert.equal(longReport.indices.length, 12);
  assert.equal(longReport.indices.at(-1), 15);
  assert.equal(longReport.enabled, false);
  const customCard = page.locator(
    `.review-card[data-key="custom:${longMotion.asset.id}"]`,
  );
  await customCard.locator('[data-action="save"]').click();
  await eventually(
    async () => (await baselines(page)).length === 2,
    "custom baseline saved",
  );
  await eventually(
    async () => await page.locator("#review-stop").isDisabled(),
    "custom save idle",
  );
  const changed = structuredClone(longMotion);
  changed.asset.frames[0].duration += 0.1;
  await worker.evaluate(
    ({ motionKey, changed }) =>
      chrome.storage.local.set({ [motionKey]: changed }),
    { motionKey, changed },
  );
  await eventually(
    async () => !(await page.locator("#review-results").isVisible()),
    "motion change invalidates old capture",
  );
  await capture();
  assert.equal((await report()).motions[0].comparison, "motionChanged");
  assert.equal((await storage())[motionKey].enabled, false);
  checks.push(
    "custom drafts stay disabled, hostile names are escaped, long motions sample first/last, and exact duration edits invalidate results",
  );

  await page.locator("#review-play").click();
  await page.waitForTimeout(150);
  await page.locator("#review-stop").click();
  await eventually(
    async () => await page.locator("#review-stop").isDisabled(),
    "cancel playback",
  );
  assert.equal((await baselines(page)).length, 2);
  await page.locator("#review-capture").click();
  await page.locator("#review-stop").click();
  await eventually(
    async () => await page.locator("#review-stop").isDisabled(),
    "cancel capture",
  );
  assert.equal(await page.locator("#review-results").isVisible(), false);
  checks.push(
    "playback and capture cancellation stop work without writing or deleting visual references",
  );

  await select(
    Object.keys((await import("../src/avatar/sign-language-data.js")).SIGNS)
      .slice(0, 9)
      .map((id) => `builtin:${id}`),
  );
  assert.equal(await page.locator("#review-capture").isDisabled(), true);
  assert.equal(await page.locator("#review-play").isDisabled(), true);
  await select(["builtin:csl_hello"]);
  const beforeRetry = await storage();
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.fetch = (input, ...options) => {
      if (String(input).endsWith("/avatar/model.glb"))
        return Promise.reject(new Error("reviewModelError"));
      return originalFetch(input, ...options);
    };
    window.restoreReviewTestFetch = () => {
      window.fetch = originalFetch;
    };
  });
  await page.locator("#review-load").click();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("验收失败"),
    "visible load failure",
  );
  assert.equal(await page.locator("#review-capture").isDisabled(), true);
  await page.evaluate(() => window.restoreReviewTestFetch());
  await page.locator("#review-load").click();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("已就绪"),
    "load retry",
  );
  await capture();
  assert.deepEqual(await storage(), beforeRetry);
  checks.push(
    "batch limits are enforced, model failure is visible and retryable, no translation state is changed",
  );

  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.fetch = (input, options) => {
      if (String(input).endsWith("/avatar/model.glb"))
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener(
            "abort",
            () => reject(options.signal.reason),
            { once: true },
          );
        });
      return originalFetch(input, options);
    };
    window.restoreReviewTestFetch = () => {
      window.fetch = originalFetch;
    };
  });
  await page.locator("#review-load").click();
  await eventually(
    async () => !(await page.locator("#review-stop").isDisabled()),
    "loading can be cancelled",
  );
  await page.locator("#review-stop").click();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("已停止"),
    "cancelled model load is visible",
  );
  assert.equal(await page.locator("#review-capture").isDisabled(), true);
  await page.evaluate(() => window.restoreReviewTestFetch());
  await page.locator("#review-load").click();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("已就绪"),
    "retry after cancelled load",
  );
  await capture();
  assert.deepEqual(await storage(), beforeRetry);
  checks.push(
    "pending model loads can be cancelled and retried without stale ready state or translation changes",
  );

  await helloCard.locator('[data-action="delete"]').click();
  await eventually(
    async () => (await baselines(page)).length === 1,
    "baseline deletion",
  );
  assert.deepEqual(await storage(), beforeRetry);
  await page.evaluate(async () => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open("signbridge-visual-review", 1);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      await new Promise((resolve, reject) => {
        const transaction = database.transaction("baselines", "readwrite");
        const store = transaction.objectStore("baselines");
        for (let index = 0; index < 99; index++) {
          store.put({
            key: `test-quota:${index}`,
            token: `test-quota:${index}`,
            image: new Blob(["test"]),
          });
        }
        transaction.oncomplete = resolve;
        transaction.onabort = () => reject(transaction.error);
      });
    } finally {
      database.close();
    }
  });
  await helloCard.locator('[data-action="save"]').click();
  await eventually(
    async () =>
      (await page.locator("#review-status").textContent()).includes("100"),
    "baseline capacity visibly enforced",
  );
  assert.equal((await baselines(page)).length, 100);
  assert.equal(
    (await baselines(page)).some(
      (record) => record.key === "builtin:csl_hello",
    ),
    false,
  );
  assert.deepEqual(await storage(), beforeRetry);
  checks.push(
    "reference capacity rejects new writes without silently deleting existing baselines or touching motion storage",
  );
  assert.equal(
    requests.some((url) => /^https?:/.test(url)),
    false,
  );
  assert.deepEqual(errors, []);
  checks.push(
    "explicit deletion affects only a visual reference; tool makes no external requests and has no unexpected browser errors",
  );
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(
      {
        checks,
        errors,
        externalRequests: requests.filter((url) => /^https?:/.test(url)),
      },
      null,
      2,
    ),
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
    console.error(
      await page
        .locator("body")
        .innerText()
        .catch(() => "closed page"),
    );
  }
  throw error;
} finally {
  await context?.close();
  await rm(profile, { recursive: true, force: true });
}
