import { createHash } from "node:crypto";
import { readFileSync, lstatSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { readResearchAssets } from "./research-assets.mjs";

export const PUBLIC_MOTION_ROOT = fileURLToPath(
  new URL("../assets/public-motion-v1/", import.meta.url),
);
// Updating this lock requires a new, explicitly authorized publication review.
const MANIFEST_SHA256 =
  "243e4345dd07d33af6f16b0e2cec300f731e3feae5ed48da779b95c2585ba946";

export function readPublicMotionAssets(root = PUBLIC_MOTION_ROOT) {
  const path = join(root, "manifest.json");
  if (lstatSync(root).isSymbolicLink() || lstatSync(path).isSymbolicLink())
    throw new Error("Public motion input symlink rejected");
  const bytes = readFileSync(path);
  if (createHash("sha256").update(bytes).digest("hex") !== MANIFEST_SHA256)
    throw new Error("Public motion manifest digest differs");
  const manifest = JSON.parse(bytes);
  const result = readResearchAssets({
    name: "public-motion-demo",
    assets: root,
    experimental: root,
    manifest: path,
  });
  if (
    result.manifestSha256 !== MANIFEST_SHA256 ||
    result.motion.clips.length !== 14 ||
    result.candidates.clips.length !== 3 ||
    result.experimental.clips.length !== 83 ||
    result.research.length !== 0 ||
    !result.experimental.clips.every((clip) => clip.human_approved === true)
  )
    throw new Error("Public motion release scope differs");
  return { ...result, publication: manifest.publication };
}
