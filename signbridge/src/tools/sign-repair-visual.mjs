import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
const { values } = parseArgs({
  options: {
    previous: { type: "string" },
    repaired: { type: "string" },
    output: { type: "string" },
    video: { type: "boolean" },
  },
});
if (!values.previous || !values.repaired || !values.output)
  throw new Error("Provide previous/repaired/new output");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../.."),
  output = resolve(values.output);
await mkdir(output, { recursive: false });
const script = await build({
  entryPoints: [join(root, "src/tools/native-repair-preview.js")],
  bundle: true,
  format: "esm",
  write: false,
});
const previous = JSON.parse(
    await readFile(join(values.previous, "native-index.json")),
  ),
  repaired = JSON.parse(
    await readFile(join(values.repaired, "native-index.json")),
  );
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
  const selected = values.video
    ? repaired.clips.filter((c) =>
        ["围巾", "我", "你", "帮助", "对待", "医保卡"].includes(c.text),
      )
    : repaired.clips;
  for (const entry of selected) {
    const folder = join(output, entry.id);
    await mkdir(folder);
    const record = {
      id: entry.id,
      text: entry.text,
      frames: entry.frames,
      images: [],
    };
    for (const [kind, dir, index] of [
      ["before", values.previous, previous],
      ["after", values.repaired, repaired],
    ]) {
      const old = index.clips.find((c) => c.id === entry.id),
        clip = JSON.parse(await readFile(join(dir, old.asset)));
      await page.evaluate(
        (clip) => globalThis.__repairView.setClip(clip),
        clip,
      );
      const ids = values.video
        ? Array.from({ length: clip.frames }, (_, i) => i)
        : [
            ...new Set([
              0,
              Math.floor(clip.frames * 0.25),
              Math.floor(clip.frames * 0.5),
              Math.floor(clip.frames * 0.75),
              clip.frames - 1,
            ]),
          ];
      const target = join(folder, kind);
      await mkdir(target);
      for (const i of ids) {
        const image = await page.evaluate(
          (i) => globalThis.__repairView.render(i),
          i,
        );
        const name = `${String(i + 1).padStart(6, "0")}.jpg`;
        await writeFile(join(target, name), Buffer.from(image.image, "base64"));
        record.images.push({
          kind,
          frame: i + 1,
          path: join(entry.id, kind, name),
          wrists: image.wrists,
        });
      }
    }
    records.push(record);
    if (records.length % 10 === 0 || records.length === selected.length)
      console.log(
        JSON.stringify({
          captured: records.length,
          total: selected.length,
          video: values.video || false,
        }),
      );
  }
  assert.deepEqual(errors, []);
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
