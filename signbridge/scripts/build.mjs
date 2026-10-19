import * as esbuild from "esbuild";
import {
  copyFileSync,
  mkdirSync,
  writeFileSync,
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
} from "fs";
import { deflateSync } from "zlib";
import { createHash } from "crypto";
import { join, dirname, resolve } from "path";
import { fileURLToPath } from "url";
import {
  prepareBuildDirectory,
  resolveBuildProfile,
} from "./build-contract.mjs";
import { readResearchAssets } from "./research-assets.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const DIST = resolve(process.env.SIGNBRIDGE_BUILD_DIR || join(ROOT, "dist"));
const TOOLS = join(ROOT, "tools");
const requestedProfile = process.argv
  .find((arg) => arg.startsWith("--profile="))
  ?.split("=")[1];
const profile = resolveBuildProfile({
  ...process.env,
  ...(requestedProfile ? { SIGNBRIDGE_BUILD_PROFILE: requestedProfile } : {}),
});
const researchInputs = readResearchAssets(profile);

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
  prepareBuildDirectory(
    ROOT,
    DIST,
    [profile.assets, profile.experimental, profile.manifest].filter(Boolean),
  );

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
      plugins: [
        {
          name: "runtime-three-module",
          setup(build) {
            build.onResolve({ filter: /^three$/ }, () => ({
              path: "./three.module.js",
              external: true,
            }));
          },
        },
      ],
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
  copyFileSync(
    join(ROOT, "src/avatar/motion-library.css"),
    dp("avatar/motion-library.css"),
  );
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

  await buildDemo();
  await buildPoseEditor();
  await buildRecordMode();
  for (const tool of ["coverage", "motion-review"]) {
    for (const extension of ["html", "css"]) {
      copyFileSync(
        join(ROOT, `src/tools/${tool}.${extension}`),
        dp(`tools/${tool}.${extension}`),
      );
    }
    await bundle(`tools/${tool}.js`, `tools/${tool}.js`);
  }

  const helpSrc = join(ROOT, "src/avatar/help.html");
  if (existsSync(helpSrc)) {
    copyFileSync(helpSrc, dp("avatar/help.html"));
    await bundle("avatar/help.js", "avatar/help.js");
    console.log("  ✓ avatar/help.html");
  }

  const files = {};
  function collect(dir) {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) collect(path);
      else if (name !== ".signbridge-build.json")
        files[path.slice(DIST.length + 1).replaceAll("\\", "/")] = createHash(
          "sha256",
        )
          .update(readFileSync(path))
          .digest("hex");
    }
  }
  collect(DIST);
  const sourceHashes = {};
  function sourceFiles(dir) {
    for (const name of readdirSync(dir).sort()) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) sourceFiles(path);
      else if (/\.(js|mjs|html|css|glb)$/.test(name))
        sourceHashes[path.slice(ROOT.length + 1).replaceAll("\\", "/")] =
          createHash("sha256").update(readFileSync(path)).digest("hex");
    }
  }
  sourceFiles(join(ROOT, "src"));
  sourceFiles(join(ROOT, "scripts"));
  for (const name of ["manifest.json", "package.json", "package-lock.json"])
    sourceHashes[name] = createHash("sha256")
      .update(readFileSync(join(ROOT, name)))
      .digest("hex");
  const sourceDigest = createHash("sha256")
    .update(JSON.stringify(sourceHashes))
    .digest("hex");
  writeFileSync(
    dp("BUILD.json"),
    JSON.stringify(
      {
        schema: "signbridge-build-v1",
        profile: profile.name,
        source_sha256: sourceDigest,
        authored_dictionary_included: true,
        research_assets_included: Boolean(researchInputs),
        research_asset_manifest_sha256: researchInputs?.manifestSha256 || null,
        training_ready: false,
        csl_translation_trained: false,
        files,
      },
      null,
      2,
    ) + "\n",
  );
  console.log("\n✅ Build complete: " + profile.name + "\n");
}

async function buildDemo() {
  copyFileSync(join(ROOT, "src/tools/sign-demo-serve.py"), dp("start-demo.py"));
  writeFileSync(
    dp("start-demo.command"),
    '#!/bin/zsh\ncd -- "$(dirname -- "$0")"\nexec /usr/bin/python3 start-demo.py\n',
    { mode: 0o755 },
  );

  for (const file of ["index.html", "demo.css", "avatar.html", "avatar.css"]) {
    copyFileSync(join(ROOT, "src/demo", file), dp("demo", file));
  }
  await bundle("demo/demo.js", "demo/demo.js");
  await bundle("demo/demo-avatar.js", "demo/demo-avatar.js");

  let runtimeIndex = {
    schema: "signbridge-t08-runtime-index-v1",
    checkpoint_sha256: "",
    clips: [],
  };
  let candidateAsset = {
    schema: "signbridge-t08-motion-candidates-v1",
    training_checkpoint_sha256: "",
    training_weights_updated: false,
    training_ready: false,
    text_to_sign_trained: false,
    research_only: true,
    clips: [],
  };
  if (researchInputs) {
    writeFileSync(
      dp("demo/t08-motion.json"),
      researchInputs.fileBytes.demo.get("t08-motion.json"),
    );
    const source = researchInputs.motion;
    runtimeIndex = {
      schema: "signbridge-t08-runtime-index-v1",
      checkpoint_sha256: source.checkpoint_sha256,
      clips: source.clips.map(({ id, text, aliases, fps, frames }) => ({
        id,
        text,
        aliases,
        fps,
        frames,
        runtime_candidate: false,
      })),
    };
    console.log("  ✓ demo/T08 local reference motions");
  } else {
    writeFileSync(
      dp("demo/t08-motion.json"),
      JSON.stringify({ unavailable: true }),
    );
    console.log(
      "  ℹ T08 assets absent; Demo dictionary mode remains available (see docs/demo.md)",
    );
  }
  if (researchInputs) {
    writeFileSync(
      dp("demo/t08-candidates.json"),
      researchInputs.fileBytes.demo.get("t08-candidates.json"),
    );
    candidateAsset = researchInputs.candidates;
    runtimeIndex.clips.push(
      ...candidateAsset.clips.map(
        ({ id, text, aliases, fps, frames, runtime_candidate }) => ({
          id,
          text,
          aliases,
          fps,
          frames,
          runtime_candidate,
        }),
      ),
    );
  } else {
    writeFileSync(
      dp("demo/t08-candidates.json"),
      JSON.stringify(candidateAsset),
    );
  }
  writeFileSync(dp("avatar/t08-index.json"), JSON.stringify(runtimeIndex));
  if (researchInputs) {
    for (const [name, bytes] of researchInputs.fileBytes.experimental)
      writeFileSync(dp("demo", name), bytes);
    console.log(
      `  ✓ ${researchInputs.experimental.clips.length} experimental fitted motions (explicit local assets)`,
    );
  } else {
    writeFileSync(
      dp("demo/experimental-index.json"),
      JSON.stringify({ unavailable: true }),
    );
  }
  const research = researchInputs?.research || [];
  for (const item of research)
    writeFileSync(
      dp("demo", item.image),
      researchInputs.fileBytes.demo.get(item.image),
    );
  writeFileSync(dp("demo/research.json"), JSON.stringify(research));
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
  let html = source.replace(
    '<script type="module" src="../src/tools/record-mode.js"></script>',
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
    entryPoints: [join(ROOT, "src/tools/record-mode.js")],
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
