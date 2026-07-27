import * as esbuild from "esbuild";
import {
  copyFileSync,
  mkdirSync,
  writeFileSync,
  existsSync,
  readFileSync,
  rmSync,
} from "fs";
import { deflateSync } from "zlib";
import { createHash } from "crypto";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const DIST = join(ROOT, "dist");
const TOOLS = join(ROOT, "tools");

function dp(...parts) {
  const p = join(DIST, ...parts);
  mkdirSync(dirname(p), { recursive: true });
  return p;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const name = Buffer.from(type);
  const body = Buffer.concat([name, data]);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(body), 0);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  return Buffer.concat([length, body, checksum]);
}

function createIconPng(size) {
  const rowSize = size * 4;
  const pixels = Buffer.alloc(size * (rowSize + 1));
  for (let y = 0; y < size; y += 1) {
    const row = y * (rowSize + 1);
    pixels[row] = 0;
    for (let x = 0; x < size; x += 1) {
      const offset = row + 1 + x * 4;
      const inset =
        x > size * 0.18 &&
        x < size * 0.82 &&
        y > size * 0.18 &&
        y < size * 0.82;
      pixels[offset] = inset ? 255 : 79;
      pixels[offset + 1] = inset ? 255 : 70;
      pixels[offset + 2] = inset ? 255 : 229;
      pixels[offset + 3] = 255;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8;
  header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(pixels)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function genIcons() {
  for (const s of [16, 48, 128]) {
    writeFileSync(dp(`icons/icon${s}.png`), createIconPng(s));
  }
}

async function bundle(entry, outfile, opts = {}) {
  await esbuild.build({
    entryPoints: [join(ROOT, "src", entry)],
    outfile: dp(outfile),
    bundle: true,
    format: opts.format || "esm",
    globalName: opts.globalName,
    platform: "browser",
    target: "es2022",
    sourcemap: false,
    minify: true,
    legalComments: "none",
  });
  console.log(`  ✓ ${entry} → ${outfile}`);
}

async function build() {
  console.log("\n🔵 SignBridge Build\n");
  rmSync(DIST, { recursive: true, force: true });
  mkdirSync(DIST, { recursive: true });

  copyFileSync(join(ROOT, "manifest.json"), dp("manifest.json"));
  console.log("  ✓ manifest.json");
  genIcons();
  console.log("  ✓ icons");

  await bundle("background/worker.js", "background/worker.js");
  await bundle("content/injector.js", "content/injector.js", {
    format: "iife",
  });
  const css = join(ROOT, "src/content/overlay.css");
  if (existsSync(css)) copyFileSync(css, dp("content/overlay.css"));
  console.log("  ✓ content/overlay.css");

  // === Avatar: official THREE ES modules ===

  // Copy three.module.js (untouched, no esbuild)
  copyFileSync(
    join(ROOT, "node_modules/three/build/three.module.js"),
    dp("avatar/three.module.js"),
  );
  console.log("  ✓ three.module.js");

  // Copy & patch GLTFLoader.js — replace bare "three" import with relative path
  const gltfSrc = readFileSync(
    join(ROOT, "node_modules/three/examples/jsm/loaders/GLTFLoader.js"),
    "utf8",
  );
  mkdirSync(dp("avatar/jsm/loaders"), { recursive: true });
  writeFileSync(
    dp("avatar/jsm/loaders/GLTFLoader.js"),
    gltfSrc.replace(/from\s+['"]three['"]/g, "from '../../three.module.js'"),
  );
  console.log("  ✓ jsm/loaders/GLTFLoader.js");

  // Copy & patch BufferGeometryUtils.js
  const bguSrc = readFileSync(
    join(ROOT, "node_modules/three/examples/jsm/utils/BufferGeometryUtils.js"),
    "utf8",
  );
  mkdirSync(dp("avatar/jsm/utils"), { recursive: true });
  writeFileSync(
    dp("avatar/jsm/utils/BufferGeometryUtils.js"),
    bguSrc.replace(/from\s+['"]three['"]/g, "from '../../three.module.js'"),
  );
  console.log("  ✓ jsm/utils/BufferGeometryUtils.js");

  // iframe-bundle.js — BUNDLED with gesture data to avoid Chrome ES module caching
  const iframeSrc = join(ROOT, "src/avatar/iframe-bundle.js");
  if (existsSync(iframeSrc)) {
    await esbuild.build({
      entryPoints: [iframeSrc],
      outfile: dp("avatar/iframe-bundle.js"),
      bundle: true,
      external: ["./three.module.js", "./jsm/loaders/GLTFLoader.js"],
      format: "esm",
      platform: "browser",
      target: "es2022",
      sourcemap: false,
      minify: false,
      legalComments: "none",
    });
    console.log("  ✓ iframe-bundle.js (bundled with gesture data)");
  }

  const model = join(ROOT, "src/avatar/model.glb");
  if (!existsSync(model)) {
    throw new Error("Missing model.glb. Put it in src/avatar/model.glb.");
  }
  copyFileSync(model, dp("avatar/model.glb"));
  console.log(`  ✓ ${model.replace(`${ROOT}/`, "")} → avatar/model.glb`);

  // avatar-frame.html
  const frameSrc = join(ROOT, "src/avatar/avatar-frame.html");
  if (existsSync(frameSrc)) {
    let html = readFileSync(frameSrc, "utf8");
    const iframeHash = createHash("sha256")
      .update(readFileSync(join(DIST, "avatar/iframe-bundle.js")))
      .digest("hex")
      .slice(0, 12);
    html = html.replace(
      /src="iframe-bundle\.js(?:\?[^\"]*)?"/,
      `src="iframe-bundle.js?v=${iframeHash}"`,
    );
    writeFileSync(dp("avatar/avatar-frame.html"), html);
  }
  console.log("  ✓ avatar/avatar-frame.html");

  // Page agent
  await bundle("avatar/page-agent.js", "avatar/page-agent.js", {
    format: "iife",
  });

  // Popup
  const ph = join(ROOT, "src/popup/index.html");
  if (existsSync(ph)) copyFileSync(ph, dp("popup/index.html"));
  const pc = join(ROOT, "src/popup/popup.css");
  if (existsSync(pc)) copyFileSync(pc, dp("popup/popup.css"));
  console.log("  ✓ popup/{index.html,popup.css}");
  await bundle("popup/popup.js", "popup/popup.js");

  const optionsDir = join(ROOT, "src/options");
  copyFileSync(
    join(optionsDir, "asr-settings.html"),
    dp("options/asr-settings.html"),
  );
  copyFileSync(
    join(optionsDir, "asr-settings.css"),
    dp("options/asr-settings.css"),
  );
  await bundle("options/asr-settings.js", "options/asr-settings.js");
  console.log("  ✓ options/asr-settings.{html,css,js}");

  copyFileSync(
    join(ROOT, "src/offscreen/audio-capture.html"),
    dp("offscreen/audio-capture.html"),
  );
  await bundle("offscreen/audio-capture.js", "offscreen/audio-capture.js");
  const transformersDist = join(
    ROOT,
    "node_modules/@huggingface/transformers/dist",
  );
  for (const asset of [
    "ort-wasm-simd-threaded.jsep.mjs",
    "ort-wasm-simd-threaded.jsep.wasm",
  ]) {
    copyFileSync(join(transformersDist, asset), dp(`asr/${asset}`));
  }
  console.log("  ✓ offscreen/audio-capture.{html,js}");

  await buildPoseEditor();
  await buildRecordMode();

  const helpSrc = join(ROOT, "src/avatar/help.html");
  if (existsSync(helpSrc)) {
    copyFileSync(helpSrc, dp("avatar/help.html"));
    console.log("  ✓ avatar/help.html");
  }

  console.log("\n✅ Build complete!\n");
}

async function buildPoseEditor() {
  const htmlSrc = join(TOOLS, "pose-editor.html");
  const entry = join(TOOLS, "editor-full-entry.js");
  if (!existsSync(htmlSrc) || !existsSync(entry)) {
    throw new Error("Pose editor sources are missing.");
  }
  let html = readFileSync(htmlSrc, "utf8");
  html = html.replace(
    /\s*<script type="importmap">[\s\S]*?<\/script>\s*/m,
    "\n",
  );
  html = html.replace(
    '<script type="module" src="./editor-bundle.js"></script>',
    '<script type="module" src="pose-editor-bundle.js"></script>',
  );
  writeFileSync(dp("avatar/pose-editor.html"), html);
  await esbuild.build({
    entryPoints: [entry],
    outfile: dp("avatar/pose-editor-bundle.js"),
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    sourcemap: false,
    minify: false,
    legalComments: "none",
  });
  console.log("  ✓ avatar/pose-editor.html + pose-editor-bundle.js");
}

async function buildRecordMode() {
  const source = readFileSync(join(TOOLS, "record-mode.html"), "utf8");
  const match = source.match(/<script type="module">([\s\S]*?)<\/script>/m);
  if (!match) throw new Error("Record mode module script is missing.");
  const script = match[1]
    .replace(
      'from "../dist/avatar/jsm/loaders/GLTFLoader.js"',
      'from "three/examples/jsm/loaders/GLTFLoader.js"',
    )
    .replace(
      'const modelUrl = "../dist/avatar/model.glb";',
      'const modelUrl = "./model.glb";',
    );
  let html = source.replace(
    match[0],
    '<script type="module" src="record-bundle.js"></script>',
  );
  html = html.replace(
    /\s*<script type="importmap">[\s\S]*?<\/script>\s*/m,
    "\n",
  );
  html = html
    .replaceAll("../dist/avatar/", "./")
    .replaceAll("../signbridge/dist/avatar/", "./");
  writeFileSync(dp("avatar/record-mode.html"), html);
  await esbuild.build({
    stdin: {
      contents: script,
      resolveDir: TOOLS,
      sourcefile: "record-mode-entry.js",
      loader: "js",
    },
    outfile: dp("avatar/record-bundle.js"),
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    sourcemap: false,
    minify: false,
    legalComments: "none",
  });
  console.log("  ✓ avatar/record-mode.html + record-bundle.js");
}

build().catch((e) => {
  console.error("Build failed:", e);
  process.exit(1);
});
