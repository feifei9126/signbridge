import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";

test("thin private extension contains no motion, corpus, weights, lexicon or public editor", () => {
  const root = mkdtempSync(join(tmpdir(), "signbridge-private-build-"));
  try {
    const output = join(root, "client");
    execFileSync(process.execPath, ["scripts/build-private.mjs"], {
      cwd: new URL("..", import.meta.url),
      env: { ...process.env, SIGNBRIDGE_PRIVATE_BUILD_DIR: output },
      stdio: "pipe",
    });
    const files = readdirSync(output, { recursive: true })
      .filter((x) => !["private"].includes(x))
      .sort();
    assert.deepEqual(files, [
      "BUILD.json",
      "manifest.json",
      "private/client.css",
      "private/client.js",
      "private/index.html",
      "worker.js",
    ]);
    const manifest = JSON.parse(
      readFileSync(join(output, "manifest.json"), "utf8"),
    );
    assert.equal(manifest.manifest_version, 3);
    assert.deepEqual(manifest.host_permissions, ["http://127.0.0.1/*"]);
    assert.equal("web_accessible_resources" in manifest, false);
    assert.equal("permissions" in manifest, false);
    const bundle = readFileSync(join(output, "private/client.js"), "utf8");
    assert.doesNotMatch(
      bundle,
      /csl_me|csl_hello|experimental-index|tokenizer-smoke|restJoints|left_hand_pose|localStorage|sessionStorage/,
    );
    const report = JSON.parse(readFileSync(join(output, "BUILD.json"), "utf8"));
    assert.equal(report.private_assets_included, false);
    for (const [file, sha] of Object.entries(report.files))
      assert.equal(
        createHash("sha256")
          .update(readFileSync(join(output, file)))
          .digest("hex"),
        sha,
      );
    // Refuse a reused directory; never delete evidence on a mistaken path.
    assert.throws(() =>
      execFileSync(process.execPath, ["scripts/build-private.mjs"], {
        cwd: new URL("..", import.meta.url),
        env: { ...process.env, SIGNBRIDGE_PRIVATE_BUILD_DIR: output },
        stdio: "pipe",
      }),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
