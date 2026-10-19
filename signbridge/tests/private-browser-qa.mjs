// Explicit integration run: receives ephemeral service credentials over stdin only.
// Never persist request headers, input tokens, console values or browser traces.
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
let source = "";
for await (const chunk of process.stdin) source += chunk;
const config = JSON.parse(source);
source = "";
const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const launch = {
  headless: true,
  ...(process.env.SIGNBRIDGE_CHROME
    ? { executablePath: process.env.SIGNBRIDGE_CHROME }
    : {}),
};
const profile = config.extension
  ? await mkdtemp(join(tmpdir(), "signbridge-private-qa-"))
  : null;
const browser = config.extension ? null : await chromium.launch(launch);
const context = config.extension
  ? await chromium.launchPersistentContext(profile, {
      ...launch,
      channel: "chromium",
      args: [
        `--disable-extensions-except=${config.extension}`,
        `--load-extension=${config.extension}`,
      ],
    })
  : await browser.newContext();
const page = await context.newPage();
await page.setViewportSize({ width: 1280, height: 1050 });
const errors = [];
page.on("pageerror", () => errors.push("page_script_error"));
const cases = [];
try {
  await page.goto(config.url);
  if (config.endpoint) await page.locator("#endpoint").fill(config.endpoint);
  if (config.handoff) {
    assert.equal(await page.locator("#open-local-service").isVisible(), true);
    await page.locator("#open-local-service").click();
    await page.waitForURL(config.endpoint + "/private/index.html");
    assert.equal(await page.locator("#token").inputValue(), "");
  }
  await page.locator("#token").fill(config.token);
  async function analyze(text, expected) {
    await page.locator("#sentence").fill(text);
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/v1/understand") && r.request().method() === "POST",
    );
    await page.locator("#analyze").click();
    const body = await (await response).json();
    assert.equal(body.status, expected);
    await page.locator("#analyze").waitFor({ state: "visible" });
    await page.waitForFunction(
      () => !document.querySelector("#analyze").disabled,
    );
    cases.push({ text, status: body.status, roles: body.roles });
    return body;
  }
  const a = await analyze("我帮你", "parsed");
  const b = await analyze("你帮我", "parsed");
  assert.equal(a.roles.actor, "我");
  assert.equal(a.roles.patient, "你");
  assert.equal(b.roles.actor, "你");
  assert.equal(b.roles.patient, "我");
  assert.notEqual(a.meaning_key, b.meaning_key);
  const c = await analyze("我今天去学校", "parsed");
  const d = await analyze("今天我去学校", "parsed");
  assert.equal(c.meaning_key, d.meaning_key);
  await analyze("你去吗", "parsed");
  await analyze("我没有去", "parsed");
  for (const sentence of ["我不想去", "我去火星", "如果你来我就去", "我喝书"])
    await analyze(sentence, "abstained");
  await page.locator("#token").fill("x".repeat(43));
  await page.locator("#sentence").fill("我帮你");
  await page.locator("#analyze").click();
  await page.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("口令无效"),
  );
  assert.equal(await page.locator("#output").textContent(), "");
  await page.locator("#token").fill(config.token);
  await analyze("你帮我", "parsed");
  assert.match(await page.locator("#output").textContent(), /施事/);
  assert.match(await page.locator("#status").textContent(), /尚需/);
  // Ensure even malicious response strings render as text, never DOM markup.
  await page.route("**/v1/understand", (route) =>
    route.fulfill({
      json: {
        status: "parsed",
        roles: { actor: "<img src=x onerror=alert(1)>" },
        model_id: "test-xss",
        csl_translation_trained: false,
      },
    }),
  );
  await analyze("我帮你", "parsed");
  assert.equal(await page.locator("#output img").count(), 0);
  assert.match(await page.locator("#output").textContent(), /<img/);
  await page.unroute("**/v1/understand");
  await analyze("你今天帮助我吗", "parsed");
  await mkdir(config.output, { recursive: true });
  await page.locator("#token").fill("");
  await page.screenshot({
    path: join(config.output, "private-desktop.png"),
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
    path: join(config.output, "private-mobile.png"),
    fullPage: true,
  });
  await page.locator("#disconnect").click();
  assert.equal(await page.locator("#token").inputValue(), "");
  assert.equal(await page.locator("#output").textContent(), "");
  assert.deepEqual(errors, []);
  await writeFile(
    join(config.output, "browser-report.json"),
    JSON.stringify(
      {
        status: "passed",
        browser: (browser || context.browser()).version(),
        client_context: config.handoff
          ? "extension_to_local_service"
          : config.extension
            ? "chrome_extension"
            : "local_web_page",
        cases,
        errors,
        checked: [
          "learned role swap",
          "time paraphrase",
          "negation and question",
          "abstention",
          "auth failure",
          "no stale results after failure",
          "text-only rendering",
          "disconnect clears memory",
          "desktop and mobile",
        ],
        csl_motion_accuracy: "not_assessed",
        credentials_persisted: false,
      },
      null,
      2,
    ) + "\n",
  );
  console.log("Private browser QA passed; no credentials persisted.");
} finally {
  config.token = "";
  await context.close();
  if (browser) await browser.close();
  if (profile) await rm(profile, { recursive: true, force: true });
}
