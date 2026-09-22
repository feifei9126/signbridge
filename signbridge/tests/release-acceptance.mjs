import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const reportPath = join(root, "test-results/release-acceptance.json");
const report = {
  format: "signbridge-release-acceptance",
  version: 1,
  startedAt: new Date().toISOString(),
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

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: root, stdio: "inherit" });
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
      const child = join(path, entry.name);
      if (entry.isDirectory()) await collect(child);
      else if (entry.isFile()) entries.push(child);
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
  const source = await fingerprint(sourcePaths);
  await run(process.platform === "win32" ? "npm.cmd" : "npm", [
    "run",
    "verify",
  ]);
  if ((await fingerprint(sourcePaths)).sha256 !== source.sha256)
    throw new Error(
      "Source changed during verification; rerun against a stable working tree.",
    );
  report.stages.push({ id: "build-lint-unit-format", status: "passed" });
  report.source = source;
  report.build = await fingerprint(distPaths);
  report.extensionVersion = JSON.parse(
    await readFile(join(root, "dist/manifest.json"), "utf8"),
  ).version;
  await save();
  for (let phase = 1; phase <= 6; phase++) {
    const evidence = join(
      root,
      `test-results/phase${phase}-browser/report.json`,
    );
    await rm(evidence, { force: true });
    await rm(join(dirname(evidence), "failure.json"), { force: true });
    await run(process.execPath, [`tests/browser-phase${phase}.mjs`]);
    const result = JSON.parse(await readFile(evidence, "utf8"));
    if (
      !Array.isArray(result.checks) ||
      !result.checks.length ||
      !Array.isArray(result.errors) ||
      result.errors.length
    )
      throw new Error(`Invalid or failed phase ${phase} evidence`);
    report.stages.push({
      id: `browser-phase${phase}`,
      status: "passed",
      checks: result.checks,
      evidence: relative(root, evidence),
    });
    await save();
  }
  if (
    (await fingerprint(sourcePaths)).sha256 !== report.source.sha256 ||
    (await fingerprint(distPaths)).sha256 !== report.build.sha256
  )
    throw new Error(
      "Source or built files changed during browser verification; results must not be reused.",
    );
  report.automatedStatus = "passed";
} catch (error) {
  report.automatedStatus = "failed";
  report.failure = error.message;
  process.exitCode = 1;
} finally {
  report.finishedAt = new Date().toISOString();
  await save();
  console.log(
    `\nAutomated acceptance: ${report.automatedStatus}. Human acceptance remains pending.\n${reportPath}`,
  );
}
