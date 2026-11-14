// Recheck exact lexical slices on the actual unchanged skinned avatar.
import { readFileSync, writeFileSync, existsSync, realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
  validateNativeIndex,
  decodeNativeClip,
  NATIVE_MODEL_SHA256,
} from "../demo/native-motion.js";
import { validateCoreManifest } from "../demo/core-motion.js";
import { loadSkinModel } from "./motion-skin-model.mjs";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createGeometryAudit } from "./motion-geometry.mjs";
import { REPAIR_GATES } from "./sign-native-repair.mjs";
const sha = (b) => createHash("sha256").update(b).digest("hex");
const risk = (q) =>
  q.torsoSkinRiskFrames.length +
  q.forearmCapsuleRiskFrames.length +
  q.handForearmRiskFrames.length;
export async function checkCoreGeometry(library, output, modelPath) {
  const root = realpathSync(library);
  if (existsSync(output)) throw new Error("Choose new report");
  const bytes = readFileSync(join(root, "native-index.json")),
    index = validateNativeIndex(JSON.parse(bytes));
  const core = validateCoreManifest(
    JSON.parse(readFileSync(join(root, "core-manifest.json"))),
    index,
  );
  if (sha(bytes) !== core.native_index_sha256)
    throw new Error("Core/native digest differs");
  if (sha(readFileSync(modelPath)) !== NATIVE_MODEL_SHA256)
    throw new Error("Target avatar differs");
  const model = await loadSkinModel(modelPath),
    rig = createHumanoidRig(model),
    rest = rig.capture(),
    audit = createGeometryAudit(model, rig),
    records = [];
  const read = (entry) => {
    const path = realpathSync(join(root, entry.asset));
    if (!path.startsWith(root + sep)) throw new Error("Core asset escaped");
    const bytes = readFileSync(path);
    if (sha(bytes) !== entry.sha256)
      throw new Error("Core resource hash differs");
    return JSON.parse(bytes);
  };
  for (const unit of core.units) {
    const entry = index.clips.find((c) => c.id === unit.id),
      clip = read(entry),
      parent = read(index.clips.find((c) => c.id === unit.parent_native_id));
    const [a, b] = unit.source_frame_range_1based;
    if (
      JSON.stringify(clip.quaternions) !==
      JSON.stringify(parent.quaternions.slice(a - 1, b))
    )
      throw new Error("Source rows differ");
    const frames = decodeNativeClip(clip, entry),
      quality = audit(frames),
      midpoints = [],
      transitions = [];
    for (let i = 0; i < frames.length - 1; i++)
      for (const t of [0.25, 0.5, 0.75])
        midpoints.push(
          Object.fromEntries(
            Object.keys(frames[i]).map((name) => [
              name,
              frames[i][name].clone().slerp(frames[i + 1][name], t),
            ]),
          ),
        );
    for (const target of frames)
      for (const t of [0.25, 0.5, 0.75])
        transitions.push(
          Object.fromEntries(
            Object.keys(target).map((name) => [
              name,
              rest[name].clone().slerp(target[name], t),
            ]),
          ),
        );
    for (const target of [frames[0], frames.at(-1)])
      for (let k = 0; k <= 10; k++)
        transitions.push(
          Object.fromEntries(
            Object.keys(target).map((name) => [
              name,
              rest[name].clone().slerp(target[name], k / 10),
            ]),
          ),
        );
    const interpolated = audit(midpoints),
      bridge = audit(transitions),
      g = REPAIR_GATES;
    const temporal =
      quality.wristMidpointCm.p95 <= g.wristP95Cm &&
      quality.wristMidpointCm.max <= g.wristMaxCm &&
      quality.fingerMidpointDegrees.p95 <= g.fingerP95Degrees &&
      quality.fingerMidpointDegrees.max <= g.fingerMaxDegrees &&
      quality.armMidpointDegrees.p95 <= g.armP95Degrees &&
      quality.armMidpointDegrees.max <= g.armMaxDegrees;
    records.push({
      id: unit.id,
      text: unit.text,
      frames: unit.frames,
      sourceRange: [a, b],
      exactSourceRows: true,
      quality,
      interpolated,
      bridge,
      intermediateSamples: midpoints.length,
      transitionSamples: transitions.length,
      passed:
        temporal &&
        risk(quality) === 0 &&
        risk(interpolated) === 0 &&
        risk(bridge) === 0,
    });
  }
  const r = {
    schema: "signbridge-core-geometry-v1",
    summary: {
      units: records.length,
      frames: records.reduce((n, r) => n + r.frames, 0),
      passed: records.filter((r) => r.passed).length,
      failed: records.filter((r) => !r.passed).length,
      intermediateSamples: records.reduce(
        (n, r) => n + r.intermediateSamples,
        0,
      ),
      transitionSamples: records.reduce((n, r) => n + r.transitionSamples, 0),
    },
    records,
    model_sha256: NATIVE_MODEL_SHA256,
    native_index_sha256: sha(bytes),
    human_approved: false,
    training_ready: false,
  };
  writeFileSync(output, JSON.stringify(r, null, 2) + "\n");
  console.log(JSON.stringify(r.summary));
  return r;
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const { values } = parseArgs({
    options: {
      library: { type: "string" },
      output: { type: "string" },
      model: {
        type: "string",
        default: fileURLToPath(new URL("../avatar/model.glb", import.meta.url)),
      },
    },
  });
  if (!values.library || !values.output)
    throw new Error("Provide library and NEW output");
  const r = await checkCoreGeometry(
    values.library,
    values.output,
    values.model,
  );
  process.exitCode = r.summary.failed ? 2 : 0;
}
