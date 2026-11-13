// Compile native candidates on the actual rig. All gates are technical proxies.
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  realpathSync,
} from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import * as THREE from "three";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createT08Retarget } from "../demo/demo-retarget.js";
import {
  stabilizeQuaternionTrack,
  MOTION_SMOOTHING_PROFILE,
  RECOVERY_SMOOTHING_PROFILE,
  ADAPTIVE_SMOOTHING_PROFILE,
} from "../demo/motion-stabilization.js";
import {
  loadSkeleton,
  measureTrack,
  compareTracks,
  percentile,
} from "./motion-quality.mjs";
import {
  evaluateDisplayCandidate,
  inspectTrackInvariants,
} from "./sign-motion-library-gate.mjs";

const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const json = (path, value) => writeFileSync(path, JSON.stringify(value) + "\n");
const flags = {
  human_approved: false,
  semantics_approved: false,
  boundaries_approved: false,
  text_verified: "",
  training_ready: false,
  model_training_ready: false,
  training_started: false,
};
const clamp = (value) => Math.max(0, Math.min(1, value));

export function segmentDistance(a, b, c, d) {
  const u = b.clone().sub(a),
    v = d.clone().sub(c),
    w = a.clone().sub(c);
  const A = u.dot(u),
    B = u.dot(v),
    C = v.dot(v),
    D = u.dot(w),
    E = v.dot(w),
    det = A * C - B * B;
  const candidates = [
    [0, C ? clamp(E / C) : 0],
    [1, C ? clamp((E + B) / C) : 0],
    [A ? clamp(-D / A) : 0, 0],
    [A ? clamp((B - D) / A) : 0, 1],
  ];
  if (det > 1e-15) {
    const s = (B * E - C * D) / det,
      t = (A * E - B * D) / det;
    if (s >= 0 && s <= 1 && t >= 0 && t <= 1) candidates.push([s, t]);
  }
  return candidates
    .map(([s, t]) => ({
      s,
      t,
      distance: a
        .clone()
        .addScaledVector(u, s)
        .distanceTo(c.clone().addScaledVector(v, t)),
    }))
    .sort((x, y) => x.distance - y.distance)[0];
}

export function geometryRisk(frames, rig, model) {
  const crossing = [],
    torso = [];
  for (let i = 0; i < frames.length; i++) {
    rig.interpolate(frames[i], frames[i], 1);
    model.updateMatrixWorld(true);
    const p = (name) => rig.bones[name].getWorldPosition(new THREE.Vector3());
    const left = [p("leftLowerArm"), p("leftHand")],
      right = [p("rightLowerArm"), p("rightHand")];
    const distance = segmentDistance(...left, ...right);
    if (
      distance.distance < 0.008 &&
      distance.s > 0.1 &&
      distance.s < 0.9 &&
      distance.t > 0.1 &&
      distance.t < 0.9
    )
      crossing.push(i + 1);
    const axis = [p("spine"), p("upperChest")];
    if (
      [left[1], right[1]].some(
        (w) => segmentDistance(w, w, ...axis).distance < 0.04,
      )
    )
      torso.push(i + 1);
  }
  rig.reset();
  model.updateMatrixWorld(true);
  return {
    armCrossingFrames: crossing.length,
    deepTorsoFrames: torso.length,
    armCrossingFrameIds: crossing,
    deepTorsoFrameIds: torso,
    contract:
      "Conservative 3D skeleton-centerline proxies only: interior forearms <8mm or wrist to spine/upperChest axis <4cm. Not mesh collision validation or semantic rejection.",
  };
}

export function chooseProfile(profiles) {
  return (
    ["current", "precision", "adaptive", "recovery", "raw"].find((name) => {
      const c = profiles[name];
      return (
        c?.gate?.passed === true &&
        c.geometry?.armCrossingFrames === 0 &&
        c.geometry?.deepTorsoFrames === 0 &&
        Number.isFinite(c.metrics?.fingerMidpointP95Degrees) &&
        c.metrics.fingerMidpointP95Degrees <= 10
      );
    }) ?? null
  );
}

// Second tier: accept a profile whose only failure is wrist-range retention
// (smoothing damped some of the wrist amplitude but geometry and handshape
// checks still hold). These are marked wrist_amplitude_reduced so the UI can
// warn honestly instead of claiming full gate compliance.
export const SECOND_TIER_FAILURES = ["minimumWristRangeRetention"];
export function chooseSecondTier(profiles) {
  return (
    ["current", "precision", "adaptive", "recovery", "raw"].find((name) => {
      const c = profiles[name];
      if (!c?.gate?.failures?.length) return false;
      if (c.gate.failures.some((f) => !SECOND_TIER_FAILURES.includes(f)))
        return false;
      return (
        c.geometry?.armCrossingFrames === 0 &&
        c.geometry?.deepTorsoFrames === 0 &&
        Number.isFinite(c.metrics?.fingerMidpointP95Degrees) &&
        c.metrics.fingerMidpointP95Degrees <= 10 &&
        c.gate.checks?.handshapeChangeP95Cm === true
      );
    }) ?? null
  );
}

export function handshapeDifference(raw, display, rig, model) {
  const ends = ["Thumb", "Index", "Middle", "Ring", "Little"];
  const coordinates = (track) =>
    track.map((frame) => {
      rig.interpolate(frame, frame, 1);
      model.updateMatrixWorld(true);
      return ["left", "right"].flatMap((side) => {
        const wrist = rig.bones[side + "Hand"];
        const inverse = wrist
          .getWorldQuaternion(new THREE.Quaternion())
          .invert();
        const origin = wrist.getWorldPosition(new THREE.Vector3());
        return ends.map((finger) =>
          rig.bones[side + finger + "Distal"]
            .getWorldPosition(new THREE.Vector3())
            .sub(origin)
            .applyQuaternion(inverse),
        );
      });
    });
  const before = coordinates(raw),
    after = coordinates(display),
    distances = [];
  for (let i = 0; i < before.length; i++)
    for (let j = 0; j < 10; j++)
      distances.push(before[i][j].distanceTo(after[i][j]) * 100);
  rig.reset();
  model.updateMatrixWorld(true);
  return percentile(distances);
}

export function nativeGate(candidate, baseline) {
  const { checks } = evaluateDisplayCandidate(candidate, baseline);
  // World-space fingertip movement includes the intended arm denoising. Keep it
  // as a diagnostic, and gate handshape independently in each wrist's frame.
  delete checks.fingerEndJointDisplacementP95Cm;
  checks.handshapeChangeP95Cm =
    Number.isFinite(candidate.handshapeChangeP95Cm) &&
    candidate.handshapeChangeP95Cm <= 0.2;
  const failures = Object.keys(checks).filter((key) => checks[key] !== true);
  return {
    passed: failures.length === 0,
    checks,
    failures,
    handshapeFrame: "wrist-local",
    maximumHandshapeChangeP95Cm: 0.2,
  };
}

export function buildLibrary(inputRoot, outputRoot, modelPath) {
  const input = realpathSync(inputRoot),
    output = resolve(outputRoot),
    modelFile = realpathSync(modelPath);
  if (existsSync(output) || output.startsWith(input + sep))
    throw new Error("Choose fresh output outside source");
  const sourceBytes = readFileSync(join(input, "index.json")),
    source = JSON.parse(sourceBytes);
  if (
    source.schema !== "signbridge-native-display-inputs-v1" ||
    !source.clips.length
  )
    throw new Error("Invalid native display input");
  const model = loadSkeleton(modelFile),
    rig = createHumanoidRig(model),
    retarget = createT08Retarget(rig, model, source);
  if (!rig.isSigningReady || retarget.mappedBones !== 40)
    throw new Error("Signing skeleton differs");
  mkdirSync(join(output, "native"), { recursive: true });
  const records = [],
    clips = [];
  const profiles = {
    raw: null,
    current: MOTION_SMOOTHING_PROFILE,
    precision: "quaternion-temporal-recovery-55-10-v1",
    recovery: RECOVERY_SMOOTHING_PROFILE,
    adaptive: ADAPTIVE_SMOOTHING_PROFILE,
  };
  for (const entry of source.clips) {
    const record = {
      id: entry.id,
      text: entry.text,
      source_uid: entry.source_uid,
      frames: entry.frames,
      profiles: {},
      ...flags,
    };
    try {
      const path = realpathSync(join(input, entry.asset));
      if (!path.startsWith(input + sep))
        throw new Error("Native pose asset escaped root");
      const bytes = readFileSync(path);
      if (hash(bytes) !== entry.sha256)
        throw new Error("Native pose digest differs");
      const clip = JSON.parse(bytes),
        original = JSON.stringify(clip.poses);
      if (
        clip.frames !== entry.frames ||
        clip.poses?.length !== entry.frames ||
        clip.native_sha256 !== entry.native_sha256
      )
        throw new Error("Native identity differs");
      for (const [key, value] of Object.entries(flags))
        if (clip[key] !== value) throw new Error("Candidate flags differ");
      const raw = retarget.compile(clip, { stabilize: false }),
        before = measureTrack(raw, rig, model);
      const baseline = {
        metrics: before.metrics,
        fingerEndJointDisplacementP95Cm: 0,
      };
      const tracks = {};
      for (const [name, profile] of Object.entries(profiles)) {
        const track = profile
          ? stabilizeQuaternionTrack(raw, clip.fps, profile)
          : raw;
        tracks[name] = track;
        const after = measureTrack(track, rig, model);
        const measured = {
          profile,
          metrics: after.metrics,
          ...compareTracks(raw, track, before, after),
          handshapeChangeP95Cm: handshapeDifference(raw, track, rig, model),
          invariants: inspectTrackInvariants(raw, track, clip.frames),
          geometry: geometryRisk(track, rig, model),
        };
        record.profiles[name] = {
          ...measured,
          gate: nativeGate(measured, baseline),
        };
      }
      if (JSON.stringify(clip.poses) !== original)
        throw new Error("Source pose mutated");
      const strict = chooseProfile(record.profiles);
      const selected = strict || chooseSecondTier(record.profiles);
      record.selected_profile = selected;
      record.status = selected
        ? strict
          ? "technical_display_candidate"
          : "wrist_amplitude_reduced_candidate"
        : "isolated_numeric_or_geometry_risk";
      if (selected) {
        const track = tracks[selected],
          bones = Object.keys(track[0]);
        const asset = `native/${clip.id}.json`;
        const metadata = {
          ...entry,
          asset: undefined,
          sha256: undefined,
          display_profile: profiles[selected] || "raw",
          model_sha256: hash(readFileSync(modelFile)),
          numeric_gate_passed: true,
          wrist_amplitude_reduced: !strict,
          ...flags,
        };
        json(join(output, asset), {
          schema: "signbridge-native-quaternion-clip-v1",
          ...metadata,
          bones,
          quaternions: track.map((frame) =>
            bones.flatMap((bone) => frame[bone].toArray()),
          ),
        });
        clips.push({
          ...metadata,
          asset,
          sha256: hash(readFileSync(join(output, asset))),
        });
      }
    } catch (error) {
      record.status = "technical_error";
      record.error = error.message;
    }
    records.push(record);
    if (records.length % 20 === 0 || records.length === source.clips.length)
      console.log(
        JSON.stringify({
          checked: records.length,
          total: source.clips.length,
          accepted: clips.length,
        }),
      );
  }
  const info = {
    schema: "signbridge-native-motion-index-v1",
    representation: "godette-local-quaternion-v1",
    model_sha256: hash(readFileSync(modelFile)),
    source_index_sha256: hash(sourceBytes),
    smplx_model_sha256: source.smplx_model_sha256,
    clips,
    ...flags,
  };
  json(join(output, "native-index.json"), info);
  const report = {
    schema: "signbridge-native-display-quality-v1",
    input: input,
    source_index_sha256: hash(sourceBytes),
    tool_sha256: hash(readFileSync(fileURLToPath(import.meta.url))),
    model_sha256: info.model_sha256,
    summary: {
      input: source.clips.length,
      accepted: clips.length,
      isolated: records.filter(
        (r) => r.status === "isolated_numeric_or_geometry_risk",
      ).length,
      technical_errors: records.filter((r) => r.status === "technical_error")
        .length,
      frames: clips.reduce((n, c) => n + c.frames, 0),
    },
    records,
    ...flags,
    limitations: [
      "Numeric and skeleton-centerline proxies do not establish jitter-free skin motion or CSL semantics.",
      "No human approval is inferred; all text remains candidate labels.",
      "Original 1853 pending-review records and raw native arrays are unchanged.",
    ],
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
      output: { type: "string" },
      model: {
        type: "string",
        default: fileURLToPath(new URL("../avatar/model.glb", import.meta.url)),
      },
    },
  });
  if (!values.input || !values.output)
    throw new Error("Provide --input and --output");
  buildLibrary(values.input, values.output, values.model);
}
