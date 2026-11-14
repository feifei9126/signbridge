import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { resolveBuildProfile } from "../scripts/build-contract.mjs";
import { createHash } from "node:crypto";

test("public motion profile rejects all private asset overrides", () => {
  const env = { SIGNBRIDGE_BUILD_PROFILE: "public-motion-demo" };
  assert.equal(resolveBuildProfile(env).name, "public-motion-demo");
  for (const key of [
    "SIGNBRIDGE_DEMO_ASSET_DIR",
    "SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR",
    "SIGNBRIDGE_RESEARCH_ASSET_MANIFEST",
  ]) {
    assert.throws(
      () => resolveBuildProfile({ ...env, [key]: "/private/new-library" }),
      /local-research/,
    );
  }
  assert.equal(resolveBuildProfile({}).name, "public-demo");
});

test("frozen public release contains exactly 14 references, 3 candidates and 83 approved fits", async () => {
  const { readPublicMotionAssets } =
    await import("../scripts/public-motion-assets.mjs");
  const result = readPublicMotionAssets();
  assert.equal(result.motion.clips.length, 14);
  assert.equal(result.candidates.clips.length, 3);
  assert.equal(result.experimental.clips.length, 83);
  assert.equal(
    new Set(
      [
        ...result.motion.clips,
        ...result.candidates.clips,
        ...result.experimental.clips,
      ].map((c) => c.id),
    ).size,
    100,
  );
  assert.deepEqual(result.research, []);
  assert.equal(result.fileBytes.demo.size, 3);
  assert.equal(result.fileBytes.experimental.size, 85);
  assert.ok(
    result.experimental.clips.every(
      (c) =>
        c.human_approved === true &&
        c.training_ready === false &&
        c.model_training_ready === false,
    ),
  );
  assert.equal(result.publication.future_assets_public, false);
});

test("public manifest mutation fails before looking for any new assets", async () => {
  const { readPublicMotionAssets, PUBLIC_MOTION_ROOT } =
    await import("../scripts/public-motion-assets.mjs");
  const dir = mkdtempSync(join(tmpdir(), "sb-public-lock-"));
  try {
    const manifest = JSON.parse(
      readFileSync(join(PUBLIC_MOTION_ROOT, "manifest.json")),
    );
    manifest.experimental["experimental/future-private.json"] = "0".repeat(64);
    writeFileSync(join(dir, "manifest.json"), JSON.stringify(manifest));
    assert.throws(
      () => readPublicMotionAssets(dir),
      /Public motion manifest digest differs/,
    );
  } finally {
    rmSync(dir, { recursive: true });
  }
});

test("unchanged manifest cannot hide changed motion bytes", async () => {
  const { readPublicMotionAssets, PUBLIC_MOTION_ROOT } =
    await import("../scripts/public-motion-assets.mjs");
  const dir = mkdtempSync(join(tmpdir(), "sb-public-bytes-"));
  try {
    writeFileSync(
      join(dir, "manifest.json"),
      readFileSync(join(PUBLIC_MOTION_ROOT, "manifest.json")),
    );
    writeFileSync(join(dir, "t08-motion.json"), "{}");
    assert.throws(
      () => readPublicMotionAssets(dir),
      /Research asset digest differs/,
    );
  } finally {
    rmSync(dir, { recursive: true });
  }
});

test("public download bytes and all landing links bind the shipped motion release", () => {
  const assets = new URL("../../docs/assets/", import.meta.url);
  const name = "signbridge-chrome-extension-1.0.7-public-motion-20261027.zip";
  const bytes = readFileSync(new URL(name, assets));
  const digest = createHash("sha256").update(bytes).digest("hex");
  const inventory = JSON.parse(
    readFileSync(new URL(name + ".contents.json", assets)),
  );
  assert.equal(inventory.archive_sha256, digest);
  assert.equal(inventory.archive_bytes, bytes.length);
  assert.equal(
    readFileSync(new URL(name + ".sha256", assets), "utf8").trim(),
    digest + "  " + name,
  );
  const html = readFileSync(
    new URL("../../docs/index.html", import.meta.url),
    "utf8",
  );
  assert.ok(html.includes('href="assets/' + name + '"'));
  assert.ok(html.includes("100 个动作片段"));
  assert.equal(inventory.training_ready, false);
  assert.equal(inventory.model_training_ready, false);
  assert.equal(inventory.deployment_ready, false);
});
