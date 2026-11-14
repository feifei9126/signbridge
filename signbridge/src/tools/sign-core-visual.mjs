// Actual avatar frame rendering matched to each proposed source-video interval.
import { build } from "esbuild";
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
const { values } = parseArgs({
  options: { library: { type: "string" }, output: { type: "string" } },
});
if (!values.library || !values.output)
  throw new Error("Provide library and new output");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../.."),
  output = resolve(values.output);
await mkdir(output, { recursive: false });
const script = await build({
  entryPoints: [join(root, "src/tools/native-repair-preview.js")],
  bundle: true,
  format: "esm",
  write: false,
});
const index = JSON.parse(
    await readFile(join(values.library, "native-index.json")),
  ),
  core = JSON.parse(await readFile(join(values.library, "core-manifest.json")));
const server = createServer(async (req, res) => {
  try {
    if (req.url === "/") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(
        '<!doctype html><style>body{margin:0}</style><script type="module" src="/preview.js"></script>',
      );
    } else if (req.url === "/preview.js") {
      res.writeHead(200, { "Content-Type": "text/javascript" });
      res.end(script.outputFiles[0].contents);
    } else if (req.url === "/model.glb") {
      res.writeHead(200);
      res.end(await readFile(join(root, "src/avatar/model.glb")));
    } else {
      res.writeHead(404);
      res.end();
    }
  } catch {
    res.writeHead(500);
    res.end();
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const browser = await chromium.launch({
  headless: true,
  args: ["--enable-unsafe-swiftshader"],
});
const page = await browser.newPage({ viewport: { width: 640, height: 600 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const records = [];
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => globalThis.__repairView?.ready, undefined, {
    timeout: 30000,
  });
  for (const unit of core.units) {
    const entry = index.clips.find((c) => c.id === unit.id),
      clip = JSON.parse(await readFile(join(values.library, entry.asset)));
    const folder = join(output, unit.key);
    await mkdir(folder);
    await page.evaluate((clip) => globalThis.__repairView.setClip(clip), clip);
    for (let frame = 0; frame < clip.frames; frame++) {
      const image = await page.evaluate(
        (frame) => globalThis.__repairView.render(frame),
        frame,
      );
      await writeFile(
        join(folder, `${String(frame + 1).padStart(6, "0")}.jpg`),
        Buffer.from(image.image, "base64"),
      );
    }
    records.push({
      id: unit.id,
      key: unit.key,
      text: unit.text,
      frames: clip.frames,
      fps: clip.fps,
      source_frame_range_1based: unit.source_frame_range_1based,
    });
    console.log(
      JSON.stringify({ captured: records.length, total: core.units.length }),
    );
  }
  if (errors.length) throw new Error(errors.join("\n"));
} finally {
  await writeFile(
    join(output, "report.json"),
    JSON.stringify(
      {
        records,
        errors,
        source: "actual_skinned_Godette_WebGL_render",
        human_approved: false,
      },
      null,
      2,
    ) + "\n",
  );
  await browser.close();
  await new Promise((r) => server.close(r));
}
