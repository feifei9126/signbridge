import test from "node:test";
import assert from "node:assert/strict";
import { basename } from "node:path";
import { createReleaseReportLocation } from "../scripts/release-report-location.mjs";

test("release report directory and startedAt share one timestamp", () => {
  const root = "/tmp/releases";
  const now = new Date("2026-10-19T12:34:56.789Z");
  const location = createReleaseReportLocation(root, now);
  assert.equal(location.startedAt, "2026-10-19T12:34:56.789Z");
  assert.equal(
    basename(location.directory),
    location.startedAt.replaceAll(":", "-"),
  );
});
