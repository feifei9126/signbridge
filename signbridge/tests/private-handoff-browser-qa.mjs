import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { extname, resolve, sep, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(
  process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(
  process.env.SIGNBRIDGE_PRIVATE_CLIENT_DIR || join(root, "dist-private"),
);
const output = resolve(
  process.env.SIGNBRIDGE_PRIVATE_HANDOFF_QA_DIR ||
    join(root, "test-results/private-handoff-browser"),
);
const report = { status: "running", checks: [], errors: [] };
const types = {
  ".css": "text/css",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".json": "application/json",
};

function makeServer({ healthOrigin = null, servicePage = false } = {}) {
  return createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(
        new URL(request.url, "http://localhost").pathname,
      );
      if (pathname === "/health") {
        if (!healthOrigin || request.headers.origin !== healthOrigin) {
          response.writeHead(403);
          response.end();
          return;
        }
        response.writeHead(200, {
          "Access-Control-Allow-Origin": healthOrigin,
          "Cache-Control": "no-store",
          "Content-Type": "application/json",
        });
        response.end(JSON.stringify({ status: "ok" }));
        return;
      }
      const file = resolve(dist, `.${pathname}`);
      if (!file.startsWith(dist + sep) || !(await stat(file)).isFile()) {
        response.writeHead(404);
        response.end();
        return;
      }
      let body = await readFile(file);
      if (pathname === "/private/index.html") {
        body = body
          .toString()
          .replace("data-workbench hidden", "data-workbench");
        if (servicePage)
          body = body.replace("<html", '<html data-signbridge-service="true"');
      }
      response.writeHead(200, {
        "Cache-Control": "no-store",
        "Content-Type": types[extname(file)] || "application/octet-stream",
      });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
}

function listen(server) {
  return new Promise((resolveListen) =>
    server.listen(0, "127.0.0.1", () => resolveListen(server.address().port)),
  );
}

const pageServer = makeServer();
const pagePort = await listen(pageServer);
const pageOrigin = `http://127.0.0.1:${pagePort}`;
const serviceServer = makeServer({
  healthOrigin: pageOrigin,
  servicePage: true,
});
const servicePort = await listen(serviceServer);
const serviceOrigin = `http://127.0.0.1:${servicePort}`;
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.SIGNBRIDGE_CHROMIUM_PATH || undefined,
  args: ["--enable-unsafe-swiftshader"],
});

try {
  const page = await browser.newPage();
  page.on("pageerror", (error) => report.errors.push(error.message));
  await page.goto(`${pageOrigin}/private/index.html?scope=1`);
  assert.equal(await page.locator("#open-local-service").isVisible(), true);
  await page.locator("#endpoint").fill("http://127.0.0.1:1");
  const originalUrl = page.url();
  await page.locator("#open-local-service").click();
  await page.waitForFunction(
    () => !document.querySelector("#local-service-unavailable").hidden,
  );
  assert.equal(page.url(), originalUrl);
  assert.equal(await page.locator("#token").inputValue(), "");
  assert.match(
    await page.locator("#local-service-unavailable").innerText(),
    /sign-private-serve.py/,
  );
  report.checks.push(
    "unavailable service stays on the current page and shows the exact local startup command",
  );

  await page.locator("#endpoint").fill(serviceOrigin);
  await page.locator("#open-local-service").click();
  await page.waitForURL(`${serviceOrigin}/private/index.html?scope=1`);
  assert.equal(await page.locator("#endpoint").inputValue(), serviceOrigin);
  assert.equal(await page.locator("#token").inputValue(), "");
  assert.equal(new URL(page.url()).search, "?scope=1");
  report.checks.push(
    "healthy local service opens the scoped analysis page without token or text in navigation",
  );
  assert.deepEqual(report.errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = String(error);
  throw error;
} finally {
  await mkdir(output, { recursive: true });
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  await browser.close();
  await new Promise((resolveClose) => pageServer.close(resolveClose));
  await new Promise((resolveClose) => serviceServer.close(resolveClose));
}
console.log(
  JSON.stringify({ status: report.status, checks: report.checks, output }),
);
