import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const scripts = JSON.parse(
  readFileSync(join(root, "package.json"), "utf8"),
).scripts;

test("full verification runs JavaScript and Python suites with one build", () => {
  assert.equal(scripts["test:js"], "node --test tests/*.test.mjs");
  assert.equal(scripts["test:python"], "node scripts/run-python-tests.mjs");
  assert.match(scripts.verify, /npm run build/);
  assert.match(scripts.verify, /npm run test:js/);
  assert.match(scripts.verify, /npm run test:python/);
  assert.equal((scripts.verify.match(/npm run build/g) || []).length, 1);
});
