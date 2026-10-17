import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, existsSync } from "node:fs";

const docs = new URL("../../docs/", import.meta.url);
test("public research downloads match their reviewed hashes and scope", () => {
  const release = JSON.parse(
    readFileSync(new URL("assets/research-release.json", docs), "utf8"),
  );
  assert.equal(release.original_video_included, false);
  assert.equal(release.weights_included, false);
  assert.equal(release.full_motion_library_included, false);
  assert.deepEqual(Object.keys(release.artifacts).sort(), [
    "signbridge-csl-research-kit-20261018.zip",
    "signbridge-research-client-0.1.0.zip",
  ]);
  for (const [name, entry] of Object.entries(release.artifacts)) {
    const bytes = readFileSync(new URL("assets/" + name, docs));
    assert.equal(bytes.length, entry.bytes);
    assert.equal(
      createHash("sha256").update(bytes).digest("hex"),
      entry.sha256,
    );
  }
});
test("research landing section links only shipped local assets and states local inference limits", () => {
  const html = readFileSync(new URL("index.html", docs), "utf8");
  assert.match(html, /id="research"/);
  assert.match(html, /不提供公网在线推理/);
  assert.match(html, /高分不代表中国手语准确率/);
  for (const match of html.matchAll(/(?:href|src)="(assets\/[^"#?]+)"/g))
    assert.ok(existsSync(new URL(match[1], docs)), match[1]);
  const readme = readFileSync(new URL("research-demo.md", docs), "utf8");
  assert.match(readme, /6355训练、881验证、764测试/);
  assert.match(readme, /human|复核|核验/);
});
