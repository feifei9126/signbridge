// Rebuild only the 154 user-reported display candidates. Other review sets stay frozen.
import { createHash } from "node:crypto";
import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  existsSync,
  realpathSync,
} from "node:fs";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import * as THREE from "three";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createNativeRetarget } from "../demo/native-retarget.js";
import {
  repairQuaternionTrack,
  REPAIR_PROFILES,
} from "../demo/motion-repair.js";
import {
  decodeNativeClip,
  validateNativeIndex,
  NATIVE_FLAGS,
  NATIVE_MODEL_SHA256,
} from "../demo/native-motion.js";
import { measureTrack, percentile } from "./motion-quality.mjs";
import { createGeometryAudit } from "./motion-geometry.mjs";
import { loadSkinModel } from "./motion-skin-model.mjs";
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const json = (file, obj) => writeFileSync(file, JSON.stringify(obj) + "\n");
export const REPAIR_GATES = Object.freeze({
  wristP95Cm: 0.4,
  wristMaxCm: 0.8,
  fingerP95Degrees: 1.5,
  fingerMaxDegrees: 6,
  armP95Degrees: 1.2,
  armMaxDegrees: 5,
  activeRangeRetention: 0.85,
  activeRangeMinimumCm: 5,
  idleRangeLossCm: 1,
  rotationDeviationP95Degrees: 12,
});
export function trajectoryRange(positions, fps) {
  // Noise spikes are not an intentional movement envelope. Compare the same
  // 100ms low-frequency, P5..P95 trajectory definition before and after repair.
  return [0, 1].map((side) => {
    const radius = Math.ceil(fps * 0.25),
      smooth = positions.map((_, i) => {
        const sum = new THREE.Vector3();
        let total = 0;
        for (
          let k = Math.max(0, i - radius);
          k <= Math.min(positions.length - 1, i + radius);
          k++
        ) {
          const weight = Math.exp(-0.5 * ((k - i) / (fps * 0.1)) ** 2);
          sum.addScaledVector(positions[k][side], weight);
          total += weight;
        }
        return sum.divideScalar(total);
      });
    return Math.hypot(
      ...["x", "y", "z"].map(
        (axis) =>
          (percentile(
            smooth.map((p) => p[axis]),
            0.95,
          ) -
            percentile(
              smooth.map((p) => p[axis]),
              0.05,
            )) *
          100,
      ),
    );
  });
}
export function repairGate(measured) {
  const g = REPAIR_GATES,
    q = measured.quality;
  const checks = {
    wristP95: q.wristMidpointCm.p95 <= g.wristP95Cm,
    wristMaximum: q.wristMidpointCm.max <= g.wristMaxCm,
    fingerP95: q.fingerMidpointDegrees.p95 <= g.fingerP95Degrees,
    fingerMaximum: q.fingerMidpointDegrees.max <= g.fingerMaxDegrees,
    armP95: q.armMidpointDegrees.p95 <= g.armP95Degrees,
    armMaximum: q.armMidpointDegrees.max <= g.armMaxDegrees,
    noTorsoSkinPenetration: q.torsoSkinRiskFrames.length === 0,
    noArmCapsulePenetration: q.forearmCapsuleRiskFrames.length === 0,
    noHandArmPenetration: q.handForearmRiskFrames.length === 0,
    boundedRotationChange:
      measured.rotationDeviationP95Degrees <= g.rotationDeviationP95Degrees,
    retainsMovement: measured.wristRangeBefore.every((r, i) =>
      r >= g.activeRangeMinimumCm
        ? measured.wristRangeAfter[i] >= r * g.activeRangeRetention
        : measured.wristRangeAfter[i] >= r - g.idleRangeLossCm,
    ),
    finiteUnit: measured.finiteUnit === true,
  };
  if (
    [
      q.wristMidpointCm.p95,
      q.wristMidpointCm.max,
      q.fingerMidpointDegrees.p95,
      q.fingerMidpointDegrees.max,
      q.armMidpointDegrees.p95,
      q.armMidpointDegrees.max,
      measured.rotationDeviationP95Degrees,
    ].some((v) => !Number.isFinite(v))
  )
    checks.finiteMetrics = false;
  const failures = Object.keys(checks).filter((k) => checks[k] !== true);
  return { passed: failures.length === 0, checks, failures };
}
export async function repairLibrary({ input, previous, output, modelPath }) {
  input = realpathSync(input);
  previous = realpathSync(previous);
  output = resolve(output);
  if (
    existsSync(output) ||
    output.startsWith(input + sep) ||
    output.startsWith(previous + sep)
  )
    throw new Error("New output required outside evidence");
  const oldBytes = readFileSync(join(previous, "native-index.json")),
    old = validateNativeIndex(JSON.parse(oldBytes));
  const sourceBytes = readFileSync(join(input, "index.json")),
    source = JSON.parse(sourceBytes);
  const modelBytes = readFileSync(modelPath);
  if (sha(modelBytes) !== NATIVE_MODEL_SHA256)
    throw new Error("Model hash differs");
  const model = await loadSkinModel(modelPath),
    rig = createHumanoidRig(model),
    geometry = createGeometryAudit(model, rig),
    retarget = createNativeRetarget(rig, model, source);
  mkdirSync(join(output, "native"), { recursive: true });
  const records = [],
    clips = [];
  for (const entry of old.clips) {
    const record = {
      id: entry.id,
      text: entry.text,
      source_uid: entry.source_uid,
      profiles: {},
      ...NATIVE_FLAGS,
    };
    try {
      const priorBytes = readFileSync(join(previous, entry.asset));
      if (sha(priorBytes) !== entry.sha256)
        throw new Error("Old track bytes differ");
      const prior = decodeNativeClip(JSON.parse(priorBytes), entry);
      record.previousQuality = geometry(prior);
      const e = source.clips.find((c) => c.id === entry.id);
      if (!e || e.native_sha256 !== entry.native_sha256)
        throw new Error("Source native identity differs");
      const poseBytes = readFileSync(join(input, e.asset));
      if (sha(poseBytes) !== e.sha256) throw new Error("Source poses differ");
      const pose = JSON.parse(poseBytes),
        raw = retarget.compile(pose),
        before = measureTrack(raw, rig, model);
      let chosen = null,
        chosenTrack;
      for (const profile of Object.keys(REPAIR_PROFILES)) {
        const track = repairQuaternionTrack(raw, pose.fps, profile),
          after = measureTrack(track, rig, model),
          quality = geometry(track),
          deviations = [];
        for (let i = 0; i < raw.length; i++)
          for (const bone of Object.keys(raw[i]))
            deviations.push(
              (raw[i][bone].angleTo(track[i][bone]) * 180) / Math.PI,
            );
        const measured = {
          quality,
          rawExtremaRangeBefore: before.metrics.wristRangeCm,
          rawExtremaRangeAfter: after.metrics.wristRangeCm,
          wristRangeBefore: trajectoryRange(before.positions, pose.fps),
          wristRangeAfter: trajectoryRange(after.positions, pose.fps),
          rotationDeviationP95Degrees: percentile(deviations),
          finiteUnit:
            track.length === pose.frames &&
            track.every((f) =>
              Object.values(f).every(
                (q) =>
                  q.toArray().every(Number.isFinite) &&
                  Math.abs(q.length() - 1) < 1e-5,
              ),
            ),
        };
        record.profiles[profile] = { ...measured, gate: repairGate(measured) };
        if (!chosen && record.profiles[profile].gate.passed) {
          chosen = profile;
          chosenTrack = track;
        }
      }
      record.selected_profile = chosen;
      record.status = chosen
        ? "repaired_candidate"
        : "isolated_after_strict_check";
      if (chosen) {
        const half = chosenTrack
          .slice(0, -1)
          .map((frame, i) =>
            Object.fromEntries(
              Object.keys(frame).map((name) => [
                name,
                frame[name].clone().slerp(chosenTrack[i + 1][name], 0.5),
              ]),
            ),
          );
        const between = geometry(half);
        record.interpolatedGeometry = between;
        if (
          between.torsoSkinRiskFrames.length ||
          between.forearmCapsuleRiskFrames.length ||
          between.handForearmRiskFrames.length
        ) {
          chosen = null;
          record.selected_profile = null;
          record.status = "isolated_interpolated_geometry_risk";
        }
      }
      if (chosen) {
        const bones = Object.keys(chosenTrack[0]),
          asset = `native/${entry.id}.json`;
        const metadata = {
          ...entry,
          asset: undefined,
          sha256: undefined,
          display_profile: chosen,
          repair_method:
            "task_space_wrist_ik_and_all_joint_quaternion_denoising",
          previous_display_sha256: entry.sha256,
          source_pose_sha256: e.sha256,
          repair_gate: REPAIR_GATES,
          source_parameters_modified: false,
          ...NATIVE_FLAGS,
        };
        json(join(output, asset), {
          schema: "signbridge-native-quaternion-clip-v1",
          ...metadata,
          bones,
          quaternions: chosenTrack.map((f) =>
            bones.flatMap((bone) => f[bone].toArray()),
          ),
        });
        clips.push({
          ...metadata,
          asset,
          sha256: sha(readFileSync(join(output, asset))),
        });
      }
    } catch (error) {
      record.status = "technical_error";
      record.error = error.stack;
    }
    records.push(record);
    if (records.length % 10 === 0 || records.length === old.clips.length)
      console.log(
        JSON.stringify({
          checked: records.length,
          total: old.clips.length,
          accepted: clips.length,
        }),
      );
  }
  const index = {
    ...old,
    source_index_sha256: sha(oldBytes),
    clips,
    repair_version: "native-repair-v1",
    gates: REPAIR_GATES,
    ...NATIVE_FLAGS,
  };
  json(join(output, "native-index.json"), index);
  const report = {
    schema: "signbridge-native-repair-report-v1",
    inputs: {
      previous_index_sha256: sha(oldBytes),
      pose_index_sha256: sha(sourceBytes),
      model_sha256: sha(modelBytes),
    },
    gates: REPAIR_GATES,
    retarget_scale: retarget.scale,
    summary: {
      input: old.clips.length,
      accepted: clips.length,
      isolated: records.filter((r) => r.status.startsWith("isolated")).length,
      technical_errors: records.filter((r) => r.status === "technical_error")
        .length,
      frames: clips.reduce((n, c) => n + c.frames, 0),
    },
    records,
    limitations: [
      "Changed display endpoints are recorded; source parameters remain unchanged.",
      "Spatial IK corrects cartoon/SMPL-X proportions, not sign semantics.",
      "Torso hulls and skin/capsule checks are conservative proxies; ambiguous contacts excluded.",
      "The 1853 original review cases and 105 prior isolated cases stay untouched.",
    ],
    ...NATIVE_FLAGS,
  };
  json(join(output, "report.json"), report);
  console.log(JSON.stringify(report.summary));
  return report;
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const { values } = parseArgs({
    options: {
      input: { type: "string" },
      previous: { type: "string" },
      output: { type: "string" },
      model: {
        type: "string",
        default: fileURLToPath(new URL("../avatar/model.glb", import.meta.url)),
      },
    },
  });
  await repairLibrary({
    input: values.input,
    previous: values.previous,
    output: values.output,
    modelPath: values.model,
  });
}
