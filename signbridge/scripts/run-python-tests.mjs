import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "..");
const venvPython =
  process.platform === "win32"
    ? join(repositoryRoot, ".venv-sign-data", "Scripts", "python.exe")
    : join(repositoryRoot, ".venv-sign-data", "bin", "python");
const python =
  process.env.SIGNBRIDGE_PYTHON ||
  (existsSync(venvPython)
    ? venvPython
    : process.platform === "win32"
      ? "python"
      : "python3");
const result = spawnSync(
  python,
  [join(packageRoot, "src/tools/sign-test-suite.py")],
  {
    cwd: packageRoot,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    stdio: "inherit",
  },
);

if (result.error) {
  console.error(
    `Unable to run Python tests with ${python}: ${result.error.message}`,
  );
  process.exitCode = 1;
} else {
  process.exitCode = result.status ?? 1;
}
