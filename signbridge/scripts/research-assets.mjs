import { createHash } from "node:crypto";
import { readFileSync, lstatSync, realpathSync } from "node:fs";
import { join, sep } from "node:path";
import {
  validateT08Bundle,
  validateT08CandidateBundle,
} from "../src/avatar/reference-motion-asset.js";
import {
  validateExperimentalIndex,
  validateExperimentalClip,
} from "../src/demo/experimental-motion.js";
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");

// This snapshot binds current asset bytes, not historical approvals or training provenance.
export function readResearchAssets(profile) {
  if (profile.name === "public-demo") return null;
  if (
    [profile.assets, profile.experimental, profile.manifest].some((p) =>
      lstatSync(p).isSymbolicLink(),
    )
  )
    throw new Error("Research input roots and manifest must not be symlinks");
  const manifestBytes = readFileSync(profile.manifest);
  const manifest = JSON.parse(manifestBytes);
  if (manifest.schema !== "signbridge-research-build-inputs-v1")
    throw new Error("Invalid research build manifest");
  const consumed = { demo: [], experimental: [] };
  const fileBytes = { demo: new Map(), experimental: new Map() };
  function read(group, name) {
    if (name.includes("..") || name.startsWith("/") || name.includes("\\"))
      throw new Error("Unsafe research asset path");
    const path = join(
      group === "demo" ? profile.assets : profile.experimental,
      name,
    );
    if (lstatSync(path).isSymbolicLink())
      throw new Error("Research asset symlink rejected");
    const root = realpathSync(
      group === "demo" ? profile.assets : profile.experimental,
    );
    if (!realpathSync(path).startsWith(root + sep))
      throw new Error("Research asset leaves its root");
    const bytes = readFileSync(path);
    if (
      !/^[a-f0-9]{64}$/.test(manifest[group]?.[name] || "") ||
      hash(bytes) !== manifest[group][name]
    )
      throw new Error("Research asset digest differs: " + name);
    consumed[group].push(name);
    fileBytes[group].set(name, bytes);
    return bytes;
  }
  const motion = validateT08Bundle(JSON.parse(read("demo", "t08-motion.json")));
  const candidates = validateT08CandidateBundle(
    JSON.parse(read("demo", "t08-candidates.json")),
  );
  const research = JSON.parse(read("demo", "research.json"));
  if (!Array.isArray(research))
    throw new Error("Invalid research image manifest");
  for (const item of research) {
    if (!/^research\/[a-zA-Z0-9_-]+\.jpg$/.test(item.image))
      throw new Error("Invalid research image path");
    if (hash(read("demo", item.image)) !== item.sha256)
      throw new Error("Research image digest differs");
  }
  const experimental = validateExperimentalIndex(
    JSON.parse(read("experimental", "experimental-index.json")),
  );
  for (const entry of experimental.clips) {
    const bytes = read("experimental", entry.asset);
    if (hash(bytes) !== entry.sha256)
      throw new Error("Experimental clip digest differs");
    validateExperimentalClip(JSON.parse(bytes), entry);
  }
  for (const group of ["demo", "experimental"]) {
    if (Object.keys(manifest[group] || {}).length !== consumed[group].length)
      throw new Error("Unexpected research manifest entries: " + group);
  }
  return {
    fileBytes,
    motion,
    candidates,
    research,
    experimental,
    manifestSha256: hash(manifestBytes),
  };
}
