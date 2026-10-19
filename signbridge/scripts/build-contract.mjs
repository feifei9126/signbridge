import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

const MARKER = ".signbridge-build.json";
const within = (parent, child) => {
  const part = relative(parent, child);
  return (
    !part ||
    (part !== ".." && !part.startsWith(".." + sep) && !isAbsolute(part))
  );
};
function canonical(path) {
  const absolute = resolve(path);
  if (existsSync(absolute)) return realpathSync(absolute);
  return join(
    canonical(dirname(absolute)),
    relative(dirname(absolute), absolute),
  );
}
export function prepareBuildDirectory(root, destination, protectedInputs = []) {
  root = realpathSync(root);
  const output = resolve(destination),
    target = canonical(output),
    repo = dirname(root);
  const identity = createHash("sha256")
    .update(root + "\n" + target)
    .digest("hex");
  const protectedRoots = [
    root,
    ...["src", "scripts", "tests", "tools", "node_modules", "docs", ".git"].map(
      (p) => join(root, p),
    ),
    join(repo, "docs"),
    join(repo, ".git"),
    join(repo, ".venv-sign-data"),
    join(repo, ".venv-wilor"),
    join(root, "backups"),
  ].map(canonical);
  if (
    protectedRoots.some((p) => within(target, p)) ||
    protectedRoots.slice(1).some((p) => within(p, target)) ||
    target === join(repo, "local-data") ||
    target === join(repo, ".venv-sign-data")
  )
    throw new Error("Unsafe build output path");
  if (
    protectedInputs.some((input) => {
      const source = canonical(input);
      return within(target, source) || within(source, target);
    })
  )
    throw new Error("Build output overlaps research input");
  if (existsSync(output) && lstatSync(output).isSymbolicLink())
    throw new Error("Build output cannot be a symlink");
  if (existsSync(output)) {
    const marker = join(output, MARKER);
    if (!existsSync(marker)) {
      // Migrate only the fixed legacy dist, preserving it instead of deleting it.
      if (
        output !== join(root, "dist") ||
        !existsSync(join(output, "manifest.json")) ||
        JSON.parse(readFileSync(join(output, "manifest.json"), "utf8")).name !==
          "SignBridge"
      )
        throw new Error("Build output is unowned; choose a new directory");
      const backup = join(root, "backups", `legacy-dist-${Date.now()}`);
      mkdirSync(dirname(backup), { recursive: true });
      renameSync(output, backup);
    } else {
      if (lstatSync(marker).isSymbolicLink())
        throw new Error("Invalid build marker");
      const owner = JSON.parse(readFileSync(marker, "utf8"));
      if (
        owner.schema !== "signbridge-build-directory-v1" ||
        owner.identity !== identity
      )
        throw new Error("Build output marker does not match this directory");
      rmSync(output, { recursive: true, force: false });
    }
  }
  mkdirSync(output, { recursive: true });
  writeFileSync(
    join(output, MARKER),
    JSON.stringify({ schema: "signbridge-build-directory-v1", identity }) +
      "\n",
  );
  return output;
}
export function resolveBuildProfile(env) {
  const name = env.SIGNBRIDGE_BUILD_PROFILE || "public-demo";
  if (!["public-demo", "local-research"].includes(name))
    throw new Error("Unknown build profile");
  const assets = env.SIGNBRIDGE_DEMO_ASSET_DIR;
  const experimental = env.SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR;
  const manifest = env.SIGNBRIDGE_RESEARCH_ASSET_MANIFEST;
  if (name === "public-demo" && (assets || experimental || manifest))
    throw new Error("Research asset paths require local-research profile");
  if (
    name === "local-research" &&
    (!assets ||
      !experimental ||
      !isAbsolute(assets) ||
      !isAbsolute(experimental) ||
      !manifest ||
      !isAbsolute(manifest))
  )
    throw new Error(
      "local-research requires explicit absolute SIGNBRIDGE_DEMO_ASSET_DIR and SIGNBRIDGE_DEMO_EXPERIMENTAL_DIR and SIGNBRIDGE_RESEARCH_ASSET_MANIFEST",
    );
  return {
    name,
    assets: assets || null,
    experimental: experimental || null,
    manifest: manifest || null,
  };
}
