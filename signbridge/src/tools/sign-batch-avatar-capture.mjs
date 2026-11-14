import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { parseArgs } from "node:util";
import { build } from "esbuild";

const { values } = parseArgs({
  options: {
    evidence: { type: "string" },
    avatar: { type: "string" },
    output: { type: "string" },
    playwright: { type: "string" },
    chrome: { type: "string" },
  },
});
const output = resolve(values.output),
  project = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
if (existsSync(output)) throw new Error("New evidence directory required");
mkdirSync(output);
mkdirSync(join(output, "frames"));
const bundle = await build({
  entryPoints: [
    resolve(project, "signbridge/src/tools/batch-audit-renderer.js"),
  ],
  bundle: true,
  format: "esm",
  write: false,
});
const source = bundle.outputFiles[0].text,
  errors = [],
  requests = [];
const model = readFileSync(join(project, "signbridge/src/avatar/model.glb"));
const server = createServer((req, res) => {
  requests.push(req.url);
  if (req.url === "/") {
    res.setHeader("Content-Type", "text/html");
    res.end(
      '<!doctype html><html lang="en"><title>SignBridge offline motion audit</title><body style="margin:0"><script type="module" src="/renderer.js"></script></body></html>',
    );
  } else if (req.url === "/renderer.js") {
    res.setHeader("Content-Type", "text/javascript");
    res.end(source);
  } else if (req.url === "/model.glb") {
    res.setHeader("Content-Type", "model/gltf-binary");
    res.end(model);
  } else if (req.url === "/favicon.ico") {
    res.writeHead(204);
    res.end();
  } else {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const { chromium } = await import(values.playwright);
let browser;
const records = [],
  evidence = JSON.parse(readFileSync(values.evidence)),
  avatar = JSON.parse(readFileSync(values.avatar));
try {
  browser = await chromium.launch({
    executablePath: values.chrome,
    headless: true,
    args: ["--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 640, height: 520 } });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("requestfailed", (r) =>
    errors.push(r.url() + ": " + r.failure()?.errorText),
  );
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => !!window.startAuditRenderer);
  await page.evaluate(
    async (input) => {
      await window.startAuditRenderer(input, "/model.glb");
    },
    { parents: evidence.parents, restJoints: evidence.restJoints },
  );
  for (const record of evidence.records.filter((r) => r.kind === "runtime")) {
    const job = evidence.pose_jobs.find((r) => r.uid === record.uid),
      metric = avatar.records.find((r) => r.uid === record.uid);
    const clip = JSON.parse(readFileSync(job.asset)),
      peak =
        metric.used.worstWristFrames[0]?.frame_1based ||
        Math.ceil(clip.frames / 2);
    const samples = [
      ...new Set([
        Math.max(1, peak - 1),
        peak,
        Math.min(clip.frames, peak + 1),
      ]),
    ];
    const captures = await page.evaluate(
      ({ clip, samples }) => window.captureAuditFrames(clip, samples),
      { clip, samples },
    );
    const files = [];
    for (const capture of captures) {
      const bytes = Buffer.from(capture.image.split(",")[1], "base64");
      const name = `${record.uid}--${capture.mode}--${capture.frame_1based}.jpg`;
      writeFileSync(join(output, "frames", name), bytes);
      files.push({
        path: "frames/" + name,
        mode: capture.mode,
        frame_1based: capture.frame_1based,
        sha256: createHash("sha256").update(bytes).digest("hex"),
      });
    }
    records.push({
      uid: record.uid,
      text: record.text,
      sample_frames: samples,
      files,
      scope:
        "Three exact frames around peak current-display wrist residual; not full human video review",
    });
    if (records.length % 20 === 0)
      console.log(JSON.stringify({ captured: records.length, total: 112 }));
  }
  await page.evaluate(() => window.disposeAuditRenderer());
} finally {
  if (browser) await browser.close();
  await new Promise((done) => server.close(done));
}
writeFileSync(
  join(output, "capture-report.json"),
  JSON.stringify(
    {
      records,
      errors,
      requests,
      renderer_source_sha256: createHash("sha256").update(source).digest("hex"),
      model_sha256: createHash("sha256").update(model).digest("hex"),
      human_approved: false,
    },
    null,
    2,
  ) + "\n",
);
if (errors.length) throw new Error(JSON.stringify(errors));
console.log(
  JSON.stringify({
    clips: records.length,
    image_frames: records.reduce((n, r) => n + r.files.length, 0),
    errors: errors.length,
  }),
);
