import test from "node:test";
import assert from "node:assert/strict";
import { resolve } from "node:path";
import { resolveTestResultsDir } from "../scripts/test-results-dir.mjs";

test("browser evidence can use a dedicated directory without changing defaults", () => {
  const root = "/workspace/signbridge";
  assert.equal(
    resolveTestResultsDir(root, "local-data/release-round"),
    resolve(root, "local-data/release-round"),
  );
  assert.equal(
    resolveTestResultsDir(root, "/tmp/signbridge-release"),
    "/tmp/signbridge-release",
  );
  assert.equal(resolveTestResultsDir(root, ""), resolve(root, "test-results"));
});
