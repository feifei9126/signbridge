import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  symlinkSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  prepareBuildDirectory,
  resolveBuildProfile,
} from "../scripts/build-contract.mjs";

test("build refuses source roots, ancestors, symlink escapes and unowned directories", () => {
  const temp = mkdtempSync(join(tmpdir(), "sb-contract-"));
  try {
    const root = join(temp, "project", "signbridge");
    mkdirSync(join(root, "src"), { recursive: true });
    mkdirSync(join(root, "scripts"));
    mkdirSync(join(root, "tests"));
    mkdirSync(join(root, "node_modules"));
    mkdirSync(join(root, "tools"));
    writeFileSync(join(root, "src", "keep.js"), "protected");
    const evidence = join(temp, "evidence");
    mkdirSync(evidence);
    writeFileSync(join(evidence, "keep.json"), "evidence");
    symlinkSync(join(root, "src"), join(temp, "source-link"));
    for (const dest of [
      root,
      temp,
      join(temp, "project"),
      join(root, "src"),
      join(root, "src", "nested"),
      join(root, "node_modules", "nested"),
      join(temp, "source-link", "nested"),
      evidence,
    ])
      assert.throws(() => prepareBuildDirectory(root, dest));
    // The dependency directory may itself be a symlink (e.g. a worktree).
    rmSync(join(root, "node_modules"), { recursive: true });
    const shared = join(temp, "shared-dependencies");
    mkdirSync(shared);
    symlinkSync(shared, join(root, "node_modules"));
    assert.throws(() =>
      prepareBuildDirectory(root, join(root, "node_modules", "build")),
    );
    assert.equal(
      readFileSync(join(root, "src", "keep.js"), "utf8"),
      "protected",
    );
    assert.equal(readFileSync(join(evidence, "keep.json"), "utf8"), "evidence");
    assert.throws(() =>
      prepareBuildDirectory(root, join(temp, "input-build"), [
        join(temp, "input-build", "asset.json"),
      ]),
    );
    const output = join(temp, "new-build");
    prepareBuildDirectory(root, output);
    writeFileSync(join(output, "old.js"), "generated");
    prepareBuildDirectory(root, output);
    assert.throws(() => readFileSync(join(output, "old.js")));
    // A real source directory is forbidden even if a build marker is forged there.
    writeFileSync(
      join(root, "src", ".signbridge-build.json"),
      readFileSync(join(output, ".signbridge-build.json")),
    );
    assert.throws(() => prepareBuildDirectory(root, join(root, "src")));
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("public builds never auto-discover ignored research data; local builds require explicit assets", () => {
  assert.equal(resolveBuildProfile({}).name, "public-demo");
  assert.throws(() =>
    resolveBuildProfile({ SIGNBRIDGE_BUILD_PROFILE: "typo" }),
  );
  assert.throws(() =>
    resolveBuildProfile({ SIGNBRIDGE_DEMO_ASSET_DIR: "/private/assets" }),
  );
  assert.throws(() =>
    resolveBuildProfile({ SIGNBRIDGE_BUILD_PROFILE: "local-research" }),
  );
  const profile = resolveBuildProfile({
    SIGNBRIDGE_BUILD_PROFILE: "local-research",
    SIGNBRIDGE_DEMO_ASSET_DIR: "/assets",
    SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR: "/fits",
    SIGNBRIDGE_RESEARCH_ASSET_MANIFEST: "/manifest.json",
  });
  assert.equal(profile.name, "local-research");
  assert.equal(profile.assets, "/assets");
});

test("a failed research preflight preserves the previous output and validates file hashes first", async () => {
  const { execFileSync } = await import("node:child_process");
  const temp = mkdtempSync(join(tmpdir(), "sb-preflight-"));
  try {
    const assets = join(temp, "assets");
    mkdirSync(assets);
    writeFileSync(join(assets, "t08-motion.json"), "{}");
    const manifest = join(temp, "inputs.json");
    writeFileSync(
      manifest,
      JSON.stringify({
        schema: "signbridge-research-build-inputs-v1",
        demo: { "t08-motion.json": "0".repeat(64) },
        experimental: {},
      }),
    );
    const output = join(temp, "previous");
    mkdirSync(output);
    writeFileSync(join(output, "keep"), "evidence");
    assert.throws(
      () =>
        execFileSync(process.execPath, ["scripts/build.mjs"], {
          cwd: new URL("..", import.meta.url),
          env: {
            ...process.env,
            SIGNBRIDGE_BUILD_PROFILE: "local-research",
            SIGNBRIDGE_DEMO_ASSET_DIR: assets,
            SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR: assets,
            SIGNBRIDGE_RESEARCH_ASSET_MANIFEST: manifest,
            SIGNBRIDGE_BUILD_DIR: output,
          },
          stdio: "pipe",
        }),
      /digest differs/,
    );
    assert.equal(readFileSync(join(output, "keep"), "utf8"), "evidence");
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});
