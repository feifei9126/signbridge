import { resolve } from "node:path";

export function resolveTestResultsDir(
  root,
  configured = process.env.SIGNBRIDGE_TEST_RESULTS_DIR,
) {
  return resolve(root, configured || "test-results");
}
