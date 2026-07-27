import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");

test("build creates every runtime asset", () => {
  const required = [
    "manifest.json",
    "content/injector.js",
    "avatar/avatar-frame.html",
    "avatar/iframe-bundle.js",
    "avatar/model.glb",
    "offscreen/audio-capture.html",
    "offscreen/audio-capture.js",
    "options/asr-settings.html",
    "options/asr-settings.css",
    "options/asr-settings.js",
    "asr/ort-wasm-simd-threaded.jsep.mjs",
    "asr/ort-wasm-simd-threaded.jsep.wasm",
    "avatar/pose-editor.html",
    "avatar/pose-editor-bundle.js",
    "avatar/record-mode.html",
    "avatar/record-bundle.js",
    "avatar/help.html",
    "popup/index.html",
  ];
  for (const relativePath of required) {
    assert.ok(existsSync(join(dist, relativePath)), `missing ${relativePath}`);
  }
});

test("build excludes obsolete development assets", () => {
  const obsolete = [
    "avatar/animations/wave.fbx",
    "avatar/jsm/loaders/FBXLoader.js",
    "avatar/sign-language-data.js",
    "avatar/pose-engine.js",
    "utils/config.js",
    "i18n/locales.js",
  ];
  for (const relativePath of obsolete) {
    assert.equal(existsSync(join(dist, relativePath)), false, relativePath);
  }
});

test("generated extension pages do not use inline event handlers", () => {
  for (const name of ["pose-editor.html", "record-mode.html"]) {
    const html = readFileSync(join(dist, "avatar", name), "utf8");
    assert.doesNotMatch(html, /\son(?:click|change|input)=/i);
    assert.doesNotMatch(html, /<script type="module">/i);
  }
});

test("recording tool has no unresolved bare module imports", () => {
  const bundle = readFileSync(join(dist, "avatar/record-bundle.js"), "utf8");
  assert.doesNotMatch(bundle, /from\s+["']three["']/);
  assert.doesNotMatch(bundle, /\.\.\/dist\/avatar/);
});

test("recording tool exports REST deltas in the runtime motion space", () => {
  const bundle = readFileSync(join(dist, "avatar/record-bundle.js"), "utf8");
  assert.match(bundle, /capturePose\(\)/);
  assert.doesNotMatch(bundle, /makePose\(/);
});

test("recording tool bundles mouse rotation and zoom controls", () => {
  const bundle = readFileSync(join(dist, "avatar/record-bundle.js"), "utf8");
  assert.match(bundle, /OrbitControls/);
  assert.match(bundle, /enableDamping/);
  assert.match(bundle, /minDistance/);
  assert.match(bundle, /maxDistance/);
});

test("tab audio capture and ASR run in extension contexts", () => {
  const popup = readFileSync(join(dist, "popup/popup.js"), "utf8");
  const worker = readFileSync(join(dist, "background/worker.js"), "utf8");
  const offscreen = readFileSync(
    join(dist, "offscreen/audio-capture.js"),
    "utf8",
  );
  const avatar = readFileSync(join(dist, "avatar/iframe-bundle.js"), "utf8");
  assert.doesNotMatch(popup, /tabCapture/);
  assert.match(worker, /tabCapture/);
  assert.match(worker, /offscreen/);
  assert.match(worker, /TRUSTED_CONTEXTS/);
  assert.match(offscreen, /chromeMediaSource/);
  assert.match(offscreen, /MediaRecorder/);
  assert.match(offscreen, /automatic-speech-recognition/);
  assert.match(offscreen, /useBrowserCache/);
  assert.match(offscreen, /decodeAudioData/);
  assert.doesNotMatch(offscreen, /127\.0\.0\.1/);
  assert.doesNotMatch(offscreen, /local-asr/);
  assert.doesNotMatch(offscreen, /chrome\.storage/);
  assert.doesNotMatch(avatar, /SpeechRecognition/);
  assert.doesNotMatch(avatar, /MIC_ENABLE/);
});

test("runtime bundles the shared full-finger humanoid profile", () => {
  const bundle = readFileSync(join(dist, "avatar/iframe-bundle.js"), "utf8");
  assert.match(bundle, /rightIndexProximal/);
  assert.match(bundle, /rightIndexIntermediate/);
  assert.match(bundle, /rightIndexDistal/);
  assert.doesNotMatch(bundle, /BONE_SHORT/);
});

test("pose editor does not reference removed loading elements", () => {
  const bundle = readFileSync(
    join(dist, "avatar/pose-editor-bundle.js"),
    "utf8",
  );
  assert.doesNotMatch(bundle, /load-status/);
});

test("generated png icons have a valid PNG signature", () => {
  const signature = readFileSync(join(dist, "icons/icon16.png")).subarray(0, 8);
  assert.deepEqual([...signature], [137, 80, 78, 71, 13, 10, 26, 10]);
});

test("avatar cache key is derived from the built bundle", () => {
  const html = readFileSync(join(dist, "avatar/avatar-frame.html"), "utf8");
  assert.match(html, /iframe-bundle\.js\?v=[a-f0-9]{12}/);
});

test("manifest relies on one static content-script registration", () => {
  const manifest = JSON.parse(
    readFileSync(join(dist, "manifest.json"), "utf8"),
  );
  assert.equal(manifest.content_scripts.length, 1);
  assert.equal(manifest.permissions.includes("scripting"), false);
  assert.equal(manifest.permissions.includes("tabCapture"), true);
  assert.equal(manifest.permissions.includes("offscreen"), true);
  assert.match(
    manifest.content_security_policy.extension_pages,
    /wasm-unsafe-eval/,
  );
  assert.equal("host_permissions" in manifest, false);
  assert.deepEqual(manifest.web_accessible_resources[0].resources, [
    "avatar/avatar-frame.html",
    "avatar/iframe-bundle.js",
    "avatar/three.module.js",
    "avatar/jsm/loaders/GLTFLoader.js",
    "avatar/jsm/utils/BufferGeometryUtils.js",
    "avatar/model.glb",
    "avatar/page-agent.js",
  ]);
});

test("popup controls are inside the app and avoid inline styles", () => {
  const html = readFileSync(join(dist, "popup/index.html"), "utf8");
  const appStart = html.indexOf('<div id="app"');
  const scriptStart = html.indexOf('<script type="module"');
  const audioButton = html.indexOf('id="btnAudio"');
  assert.ok(
    appStart >= 0 && audioButton > appStart && audioButton < scriptStart,
  );
  assert.doesNotMatch(html, /\sstyle=/i);
});

test("local Whisper is deployed inside the extension", () => {
  const settings = readFileSync(
    join(dist, "options/asr-settings.html"),
    "utf8",
  );
  const worker = readFileSync(join(dist, "background/worker.js"), "utf8");
  assert.match(settings, /id="btnDeploy"/);
  assert.doesNotMatch(settings, /downloadInstaller|localEndpoint|\.zip/);
  assert.match(worker, /ASR_LOCAL_DEPLOY/);
  assert.equal(existsSync(join(dist, "local-asr")), false);
});
