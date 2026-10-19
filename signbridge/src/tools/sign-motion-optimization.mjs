import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createT08Retarget } from "../demo/demo-retarget.js";
import {
  validateExperimentalIndex,
  validateExperimentalClip,
} from "../demo/experimental-motion.js";
import {
  stabilizeQuaternionTrack,
  ADAPTIVE_SMOOTHING_PROFILE,
  MOTION_SMOOTHING_PROFILE,
} from "../demo/motion-stabilization.js";
import { createMotionCache } from "../demo/motion-cache.js";
import {
  loadSkeleton,
  measureTrack,
  compareTracks,
  percentile,
} from "./motion-quality.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const { values } = parseArgs({
  options: {
    assets: { type: "string" },
    extra: { type: "string" },
    output: { type: "string" },
    limit: { type: "string" },
  },
});
if (!values.assets || !values.output || existsSync(values.output))
  throw new Error("Provide assets and a new output directory");
const output = resolve(values.output),
  inputs = [];
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
function json(path) {
  const bytes = readFileSync(path);
  inputs.push({ path, sha256: sha(bytes) });
  return JSON.parse(bytes);
}
for (const path of [
  fileURLToPath(import.meta.url),
  join(root, "src/tools/motion-quality.mjs"),
  join(root, "src/demo/demo-retarget.js"),
  join(root, "src/demo/motion-stabilization.js"),
  join(root, "src/demo/motion-cache.js"),
  join(root, "src/avatar/model.glb"),
])
  inputs.push({ path, sha256: sha(readFileSync(path)) });
const model = loadSkeleton(join(root, "src/avatar/model.glb")),
  rig = createHumanoidRig(model),
  records = [];
let previous = null;
for (const directory of [values.assets, values.extra].filter(Boolean)) {
  const assets = resolve(directory),
    index = validateExperimentalIndex(
      json(join(assets, "experimental-index.json")),
    ),
    retarget = createT08Retarget(rig, model, index);
  for (const entry of index.clips.slice(
    0,
    values.limit ? Number(values.limit) : undefined,
  )) {
    const path = join(assets, entry.asset),
      bytes = readFileSync(path);
    if (sha(bytes) !== entry.sha256) throw new Error("Clip digest differs");
    const clip = validateExperimentalClip(json(path), entry);
    const start = performance.now(),
      raw = retarget.compile(clip, { stabilize: false }),
      rawCompileMs = performance.now() - start;
    const before = measureTrack(raw, rig, model),
      profiles = {};
    for (const [name, profile] of [
      [
        "existing",
        entry.display_stabilization_profile || MOTION_SMOOTHING_PROFILE,
      ],
      ["adaptive", ADAPTIVE_SMOOTHING_PROFILE],
    ]) {
      const began = performance.now(),
        display = stabilizeQuaternionTrack(raw, clip.fps, profile),
        filterMs = performance.now() - began;
      const measured = measureTrack(display, rig, model),
        deviation = compareTracks(raw, display, before, measured);
      profiles[name] = {
        profile,
        filterMs,
        metrics: measured.metrics,
        ...deviation,
      };
    }
    const cache = createMotionCache();
    const first = cache.get(clip.id, () => retarget.compile(clip));
    const warm = cache.get(clip.id, () => {
      throw new Error("Cache miss on repeated compile");
    });
    const boundary = previous
      ? percentile(
          Object.keys(raw[0]).map(
            (name) => (previous[name].angleTo(raw[0][name]) * 180) / Math.PI,
          ),
        )
      : null;
    const existing = profiles.existing,
      adaptive = profiles.adaptive;
    const numericGuard =
      adaptive.minimumWristRangeRetention >= 0.9 &&
      adaptive.fingerEndJointDisplacementP95Cm <=
        existing.fingerEndJointDisplacementP95Cm + 0.2 &&
      adaptive.metrics.wristMidpointP95Cm <=
        existing.metrics.wristMidpointP95Cm;
    records.push({
      id: clip.id,
      text: clip.text,
      frames: clip.frames,
      fps: clip.fps,
      rawCompileMs,
      raw: before.metrics,
      profiles,
      cache: {
        coldMs: first.compileMs,
        warmMs: warm.compileMs,
        warmHit: warm.cacheHit,
        ...cache.stats(),
      },
      boundaryFromPreviousP95Degrees: boundary,
      adaptivePassesNumericComparison: numericGuard,
      deployment: "research_option_only_no_automatic_promotion",
      human_approved: false,
      training_ready: false,
    });
    previous = raw.at(-1);
    console.log(JSON.stringify({ id: clip.id, measured: records.length }));
  }
}
for (const input of inputs)
  if (sha(readFileSync(input.path)) !== input.sha256)
    throw new Error("Input changed while measuring");
const mean = (array) => array.reduce((a, b) => a + b, 0) / array.length;
const summary = {
  clips: records.length,
  numericComparisonPass: records.filter(
    (r) => r.adaptivePassesNumericComparison,
  ).length,
  existingWristMidpointP95MeanCm: mean(
    records.map((r) => r.profiles.existing.metrics.wristMidpointP95Cm),
  ),
  adaptiveWristMidpointP95MeanCm: mean(
    records.map((r) => r.profiles.adaptive.metrics.wristMidpointP95Cm),
  ),
  existingMinimumRangeRetention: Math.min(
    ...records.map((r) => r.profiles.existing.minimumWristRangeRetention),
  ),
  adaptiveMinimumRangeRetention: Math.min(
    ...records.map((r) => r.profiles.adaptive.minimumWristRangeRetention),
  ),
  meanColdCompileMs: mean(records.map((r) => r.cache.coldMs)),
  meanWarmLookupMs: mean(records.map((r) => r.cache.warmMs)),
  maximumCacheNumericBytes: Math.max(
    ...records.map((r) => r.cache.numericBytes),
  ),
};
mkdirSync(output);
const report = {
  schema: "signbridge-motion-optimization-v1",
  createdAt: new Date().toISOString(),
  summary,
  records,
  inputs,
  sourceAssetsUnchanged: true,
  frameSetsUnchanged: true,
  model_training_ready: false,
  limitations: [
    "These are target-avatar stability proxies, not CSL accuracy or measured real-world contact.",
    "Finger end joints are bone origins, not measured fingertip skin contacts.",
    "Near-hand distance is an avatar screening proxy on frames below 3cm in raw mode; not ground truth contact.",
    "Clip ordering in this report is diagnostic, not an approved sentence construction. Filters preserve endpoint jumps; no new compositional playback is approved.",
    "Numeric cache bytes exclude JavaScript object overhead, active tracks, renderer and decoded source poses.",
    "Comparisons use all available selected clips, not an independent held-out quality test. Default asset profiles remain unchanged.",
  ],
};
writeFileSync(
  join(output, "report.json"),
  JSON.stringify(report, null, 2) + "\n",
);
writeFileSync(
  join(output, "SHA256SUMS"),
  `${sha(readFileSync(join(output, "report.json")))}  report.json\n`,
);
console.log(JSON.stringify(summary));
