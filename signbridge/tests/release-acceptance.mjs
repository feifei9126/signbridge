import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdir,
  readFile,
  readdir,
  copyFile,
  writeFile,
} from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import { createReleaseReportLocation } from "../scripts/release-report-location.mjs";
import { resolveTestResultsDir } from "../scripts/test-results-dir.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const resultsRoot = resolveTestResultsDir(root);
const reportLocation = createReleaseReportLocation(
  join(resultsRoot, "releases"),
);
const reportDir = reportLocation.directory;
const reportPath = join(reportDir, "release-acceptance.json");
const report = {
  format: "signbridge-release-acceptance",
  version: 1,
  startedAt: reportLocation.startedAt,
  automatedStatus: "running",
  publishReady: false,
  stages: [],
  manualChecks: [
    {
      id: "csl-meaning-handshape-orientation-location-timing",
      status: "pending",
    },
    {
      id: "real-websites-subtitles-seek-pause-and-navigation",
      status: "pending",
    },
    { id: "tab-audio-local-whisper-and-cloud-provider", status: "pending" },
    { id: "small-batch-user-feedback-and-rollback", status: "pending" },
    { id: "asset-licenses-privacy-and-release-notes", status: "pending" },
  ],
};

async function save() {
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n");
}

function run(command, args, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      env,
      stdio: "inherit",
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve();
      else
        reject(
          new Error(
            `${command} ${args.join(" ")}: exit=${code}, signal=${signal}`,
          ),
        );
    });
  });
}

async function fingerprint(paths) {
  const entries = [];
  async function collect(path) {
    for (const entry of (
      await readdir(join(root, path), { withFileTypes: true })
    ).sort((first, second) => first.name.localeCompare(second.name))) {
      if (entry.name === "__pycache__") continue;
      const child = join(path, entry.name);
      if (entry.isDirectory()) await collect(child);
      else if (entry.isFile() && !entry.name.endsWith(".pyc"))
        entries.push(child);
      else throw new Error(`Unsupported release input: ${child}`);
    }
  }
  for (const path of paths.directories) await collect(path);
  entries.push(...paths.files);
  const files = [];
  for (const path of entries.sort()) {
    const content = await readFile(join(root, path));
    files.push({
      path,
      bytes: content.length,
      sha256: createHash("sha256").update(content).digest("hex"),
    });
  }
  return {
    sha256: createHash("sha256").update(JSON.stringify(files)).digest("hex"),
    files,
  };
}

const sourcePaths = {
  directories: ["src", "tools", "scripts", "tests"],
  files: [
    "manifest.json",
    "package.json",
    "package-lock.json",
    "eslint.config.mjs",
  ],
};
const distPaths = { directories: ["dist"], files: [] };
await mkdir(dirname(reportPath), { recursive: true });
await save();
try {
  const { chromium } = await import(
    process.env.SIGNBRIDGE_PLAYWRIGHT_MODULE || "playwright"
  );
  process.env.SIGNBRIDGE_CHROMIUM_PATH ||= chromium.executablePath();
  if (!existsSync(process.env.SIGNBRIDGE_CHROMIUM_PATH))
    throw new Error(
      "Chromium missing. Run: npx playwright install chromium (Linux CI: npx playwright install --with-deps chromium)",
    );
  const source = await fingerprint(sourcePaths);
  await run(process.platform === "win32" ? "npm.cmd" : "npm", [
    "run",
    "verify",
  ]);
  if ((await fingerprint(sourcePaths)).sha256 !== source.sha256)
    throw new Error(
      "Source changed during verification; rerun against a stable working tree.",
    );
  report.stages.push({ id: "build-lint-js-python-format", status: "passed" });
  report.source = source;
  report.build = await fingerprint(distPaths);
  report.extensionVersion = JSON.parse(
    await readFile(join(root, "dist/manifest.json"), "utf8"),
  ).version;
  await save();
  const browserEnv = {
    ...process.env,
    SIGNBRIDGE_TEST_RESULTS_DIR: resultsRoot,
    SIGNBRIDGE_AUDIT_QA_DIR: join(resultsRoot, "audit-browser"),
    SIGNBRIDGE_FEATURE_QA_DIR: join(resultsRoot, "feature-browser"),
  };
  for (let phase = 1; phase <= 6; phase++) {
    const evidence = join(resultsRoot, `phase${phase}-browser/report.json`);

    await run(
      process.execPath,
      [`tests/browser-phase${phase}.mjs`],
      browserEnv,
    );
    const result = JSON.parse(await readFile(evidence, "utf8"));
    if (
      !Array.isArray(result.checks) ||
      !result.checks.length ||
      !Array.isArray(result.errors) ||
      result.errors.length
    )
      throw new Error(`Invalid or failed phase ${phase} evidence`);
    await copyFile(evidence, join(reportDir, `phase${phase}.json`));
    report.stages.push({
      id: `browser-phase${phase}`,
      status: "passed",
      checks: result.checks,
      evidence: relative(root, evidence),
    });
    await save();
  }
  await run(process.execPath, ["tests/audit-browser-qa.mjs"], browserEnv);
  await copyFile(
    join(resultsRoot, "audit-browser/report.json"),
    join(reportDir, "audit-browser.json"),
  );
  report.stages.push({
    id: "audit-browser-analysis-and-boundaries",
    status: "passed",
  });
  await run(process.execPath, ["tests/feature-browser-qa.mjs"], browserEnv);
  await copyFile(
    join(resultsRoot, "feature-browser/report.json"),
    join(reportDir, "feature-browser.json"),
  );
  report.stages.push({
    id: "feature-simplification-browser",
    status: "passed",
  });
  if (
    (await fingerprint(sourcePaths)).sha256 !== report.source.sha256 ||
    (await fingerprint(distPaths)).sha256 !== report.build.sha256
  )
    throw new Error(
      "Source or built files changed during browser verification; results must not be reused.",
    );
  report.automatedStatus = "passed";
  report.buildProfile = JSON.parse(
    await readFile(join(root, "dist/BUILD.json"), "utf8"),
  ).profile;
} catch (error) {
  report.automatedStatus = "failed";
  report.failure =
    error.code === "ERR_MODULE_NOT_FOUND"
      ? "Playwright missing. Run npm ci before verify:release."
      : error.message;
  process.exitCode = 1;
} finally {
  report.finishedAt = new Date().toISOString();
  await save();
  await copyFile(reportPath, join(resultsRoot, "release-acceptance.json"));
  console.log(
    `\nAutomated acceptance: ${report.automatedStatus}. Human acceptance remains pending.\n${reportPath}`,
  );
}
