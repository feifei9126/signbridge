import { join } from "node:path";

export function createReleaseReportLocation(root, now = new Date()) {
  const startedAt = now.toISOString();
  return {
    startedAt,
    directory: join(root, startedAt.replaceAll(":", "-")),
  };
}
