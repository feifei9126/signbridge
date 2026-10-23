import { readFileSync, writeFileSync, mkdirSync, realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createT08Retarget } from "../demo/demo-retarget.js";
import {
  createExperimentalLoader,
  experimentalPoseDigestInput,
  validateExperimentalIndex,
  validateExperimentalApprovalRecord,
} from "../demo/experimental-motion.js";
import {
  MOTION_SMOOTHING_PROFILE,
  MOTION_STABILIZATION_PROFILES,
  stabilizeQuaternionTrack,
} from "../demo/motion-stabilization.js";
import {
  loadSkeleton,
  measureTrack,
  compareTracks,
} from "./motion-quality.mjs";

export const LIBRARY_GATE = Object.freeze({
  maximumWristMidpointP95Cm: 1,
  minimumWristRangeRetention: 0.9,
  maximumFingerIncreaseOverCurrentCm: 0.2,
  maximumEndpointAngleDegrees: 0.00001,
  maximumQuaternionNormError: 0.00001,
});
const RECOVERY_PROFILE = "quaternion-temporal-recovery-v1";
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const jsonBytes = (value) => JSON.stringify(value, null, 2) + "\n";
const finiteNonnegative = (value) => Number.isFinite(value) && value >= 0;

export function evaluateDisplayCandidate(candidate, current) {
  const metrics = candidate?.metrics;
  const checks = {
    finiteMetrics:
      [
        metrics?.angularMidpointP95Degrees,
        metrics?.armMidpointP95Degrees,
        metrics?.fingerMidpointP95Degrees,
        metrics?.wristMidpointP95Cm,
        candidate?.minimumWristRangeRetention,
        candidate?.fingerEndJointDisplacementP95Cm,
        candidate?.poseDeviationP95Degrees,
        current?.metrics?.wristMidpointP95Cm,
        current?.fingerEndJointDisplacementP95Cm,
      ].every(finiteNonnegative) &&
      metrics?.wristRangeCm?.length === 2 &&
      metrics.wristRangeCm.every(finiteNonnegative) &&
      Number.isInteger(candidate?.nearHandFrames) &&
      candidate.nearHandFrames >= 0 &&
      (candidate.nearHandFrames === 0
        ? candidate.nearHandDistanceChangeP95Cm === null
        : finiteNonnegative(candidate.nearHandDistanceChangeP95Cm)),
    wristMidpointP95Cm:
      finiteNonnegative(metrics?.wristMidpointP95Cm) &&
      metrics.wristMidpointP95Cm <= LIBRARY_GATE.maximumWristMidpointP95Cm,
    noWristRegression:
      finiteNonnegative(metrics?.wristMidpointP95Cm) &&
      finiteNonnegative(current?.metrics?.wristMidpointP95Cm) &&
      metrics.wristMidpointP95Cm <= current.metrics.wristMidpointP95Cm,
    minimumWristRangeRetention:
      finiteNonnegative(candidate?.minimumWristRangeRetention) &&
      candidate.minimumWristRangeRetention >=
        LIBRARY_GATE.minimumWristRangeRetention,
    fingerEndJointDisplacementP95Cm:
      finiteNonnegative(candidate?.fingerEndJointDisplacementP95Cm) &&
      finiteNonnegative(current?.fingerEndJointDisplacementP95Cm) &&
      candidate.fingerEndJointDisplacementP95Cm <=
        current.fingerEndJointDisplacementP95Cm +
          LIBRARY_GATE.maximumFingerIncreaseOverCurrentCm,
  };
  for (const name of [
    "finiteUnitQuaternions",
    "exactFrames",
    "exactBoneSets",
    "endpointsPreserved",
  ])
    checks[name] = candidate?.invariants?.[name] === true;
  const failures = Object.keys(checks).filter((name) => checks[name] !== true);
  return { passed: failures.length === 0, checks, failures };
}

export function inspectTrackInvariants(raw, display, expectedFrames) {
  const names = Object.keys(raw?.[0] || {});
  const tracks = [raw, display];
  const exactFrames = tracks.every(
    (track) => Array.isArray(track) && track.length === expectedFrames,
  );
  const exactBoneSets =
    names.length > 0 &&
    tracks.every(
      (track) =>
        Array.isArray(track) &&
        track.every(
          (frame) =>
            frame &&
            Object.keys(frame).length === names.length &&
            names.every((name) => Object.hasOwn(frame, name)),
        ),
    );
  const finiteUnitQuaternions =
    exactBoneSets &&
    tracks.every((track) =>
      track.every((frame) =>
        names.every((name) => {
          const value = frame[name];
          return (
            value?.isQuaternion === true &&
            value.toArray().every(Number.isFinite) &&
            Math.abs(value.length() - 1) <=
              LIBRARY_GATE.maximumQuaternionNormError
          );
        }),
      ),
    );
  let maximumEndpointAngleDegrees = null;
  if (exactFrames && finiteUnitQuaternions && expectedFrames > 0) {
    maximumEndpointAngleDegrees = Math.max(
      ...[0, expectedFrames - 1].flatMap((i) =>
        names.map(
          (name) =>
            (raw[i][name]
              .clone()
              .normalize()
              .angleTo(display[i][name].clone().normalize()) *
              180) /
            Math.PI,
        ),
      ),
    );
  }
  return {
    finiteUnitQuaternions,
    exactFrames,
    exactBoneSets,
    endpointsPreserved:
      maximumEndpointAngleDegrees !== null &&
      maximumEndpointAngleDegrees <= LIBRARY_GATE.maximumEndpointAngleDegrees,
    maximumEndpointAngleDegrees,
    frameCount: display?.length ?? null,
    expectedFrames,
    mappedBones: names.length,
  };
}

export async function verifyApprovedSource({
  indexBytes,
  expectedIndexSha256,
  expectedClips,
  readAsset,
}) {
  const indexSha256 = sha(indexBytes);
  if (indexSha256 !== expectedIndexSha256)
    throw new Error("Source index digest differs");
  const index = validateExperimentalIndex(JSON.parse(indexBytes));
  if (
    index.clips.length !== expectedClips ||
    index.clips.some((entry) => entry.human_approved !== true)
  )
    throw new Error("Approved source count differs");
  if (!index.motion_approval) throw new Error("Source approval is required");
  const approvalBytes = await readAsset(index.motion_approval.asset);
  if (sha(approvalBytes) !== index.motion_approval.sha256)
    throw new Error("Source approval digest differs");
  const approval = JSON.parse(approvalBytes);
  const items = validateExperimentalApprovalRecord(index, approval);
  const loader = createExperimentalLoader(
    index,
    async (path) => new Response(await readAsset(path)),
  );
  const clips = new Map(),
    records = [];
  for (const entry of index.clips) {
    const item = items.get(entry.id);
    const record = {
      id: entry.id,
      text: entry.text,
      aliases: entry.aliases,
      frames: entry.frames,
      fps: entry.fps,
      asset: entry.asset,
      sha256: entry.sha256,
      source_motion_human_approved: entry.human_approved,
      source_motion_approval: {
        ...item,
        id: approval.id,
        scope: approval.scope,
        basis: approval.basis,
        declaration: approval.declaration,
        captured_at_utc: approval.captured_at_utc,
        approval_record_sha256: index.motion_approval.sha256,
        reviewed_source_index_sha256: approval.source_index_sha256,
      },
      source_sha256: entry.source_sha256,
      feature_sha256: entry.feature_sha256,
      fitted_sha256: entry.fitted_sha256,
      quality_warning: entry.quality_warning,
      max_adjacent_rotation_degrees:
        entry.max_adjacent_rotation_degrees ?? null,
      mirror_status: entry.mirror_status,
      signer_id: entry.signer_id,
      semantics_approved: entry.semantics_approved ?? null,
      boundaries_approved: entry.boundaries_approved ?? null,
      current_display_profile:
        entry.display_stabilization_profile || MOTION_SMOOTHING_PROFILE,
    };
    try {
      const bytes = await readAsset(entry.asset);
      if (sha(bytes) !== entry.sha256)
        throw new Error("Source clip digest differs");
      const clip = await loader.load(entry.id);
      const poseSha256 = sha(experimentalPoseDigestInput(clip.poses));
      if (poseSha256 !== item.poses_sha256)
        throw new Error("Source pose digest differs");
      clips.set(entry.id, clip);
      record.verification = {
        passed: true,
        asset_sha256: sha(bytes),
        poses_sha256: poseSha256,
        loader_validated: true,
      };
    } catch (error) {
      record.verification = { passed: false, error: error.message };
    }
    records.push(record);
  }
  loader.clear();
  return { index, indexSha256, approval, records, clips };
}

export function selectDisplayCandidate(profiles) {
  for (const name of ["current", "recovery"])
    if (evaluateDisplayCandidate(profiles?.[name], profiles?.current).passed)
      return name;
  return null;
}

const limitations = [
  "Numeric target-avatar proxies do not prove jitter-free motion, sign-language correctness, semantics or boundaries.",
  "Finger end joints are bone origins, not measured skin fingertips or ground-truth contacts; near-hand distances only screen raw frames below 3 cm.",
  "Source human approval remains motion_quality_only; derived display processing has no new human approval. A failed proxy gate does not revoke source approval.",
  "No source poses are copied or rewritten. The stable index only references original assets and existing display profiles.",
  "Endpoint rotations are preserved, including existing endpoint jumps. No cross-clip transitions, automatic language-to-motion composition or browser autoplay are evaluated or enabled.",
  "All 83 source clips are screened, not a held-out quality validation set. Mirror status and signer identity remain unconfirmed.",
  "The reviewed pre-approval asset hash differs from the approved asset byte hash after metadata promotion; the loader binds source/fitted hashes and the existing quantized pose digest, not a reconstructed pre-approval file.",
];

export function createLibraryArtifacts({
  source,
  records,
  sourceAssetsPath,
  inputs,
}) {
  const evaluated = records.map((record) => {
    const profiles = Object.fromEntries(
      Object.entries(record.profiles || {}).map(([name, value]) => [
        name,
        {
          ...value,
          gate: evaluateDisplayCandidate(value, record.profiles.current),
        },
      ]),
    );
    const selected =
      record.verification.passed && record.source_motion_human_approved === true
        ? selectDisplayCandidate(profiles)
        : null;
    return {
      ...record,
      profiles,
      selected_display: selected,
      derived_display_human_approved: false,
      display_candidate_status: selected
        ? "numeric_proxy_candidate_only"
        : "excluded_by_fixed_gate_or_verification",
    };
  });
  const shared = {
    gate: LIBRARY_GATE,
    selection_policy:
      "prefer_passing_current_else_passing_recovery_no_threshold_search",
    source_index: {
      path: `${sourceAssetsPath}/experimental-index.json`,
      sha256: source.indexSha256,
    },
    source_approval: {
      path: `${sourceAssetsPath}/${source.index.motion_approval.asset}`,
      sha256: source.index.motion_approval.sha256,
      id: source.approval.id,
      scope: source.approval.scope,
    },
    source_provenance_limitations: source.index.provenance_limitations || [],
    limitations,
    training_ready: false,
    model_training_ready: false,
    training_weights_updated: false,
    text_to_sign_trained: false,
    automatic_playback_enabled: false,
    derived_display_human_approved: false,
  };
  const candidates = evaluated.filter((record) => record.selected_display);
  const failureCounts = {};
  for (const name of ["raw", "current", "recovery"]) {
    failureCounts[name] = {};
    for (const record of evaluated)
      for (const failure of record.profiles[name]?.gate.failures || [])
        failureCounts[name][failure] = (failureCounts[name][failure] || 0) + 1;
  }
  const summary = {
    clips: evaluated.length,
    verifiedSources: evaluated.filter((r) => r.verification.passed).length,
    sourceVerificationFailures: evaluated.filter((r) => !r.verification.passed)
      .length,
    profileGatePasses: Object.fromEntries(
      ["raw", "current", "recovery"].map((name) => [
        name,
        evaluated.filter((r) => r.profiles[name]?.gate.passed).length,
      ]),
    ),
    displayCandidates: candidates.length,
    excluded: evaluated.length - candidates.length,
    selectedProfiles: Object.fromEntries(
      ["current", "recovery"].map((name) => [
        name,
        candidates.filter((r) => r.selected_display === name).length,
      ]),
    ),
    sourceQualityWarnings: evaluated.filter((r) => r.quality_warning).length,
    candidateSourceQualityWarnings: candidates.filter((r) => r.quality_warning)
      .length,
    failureCounts,
  };
  return {
    report: {
      schema: "signbridge-motion-library-gate-report-v1",
      ...shared,
      source_assets_unchanged: true,
      summary,
      inputs,
      records: evaluated,
    },
    index: {
      schema: "signbridge-stable-display-candidate-index-v1",
      ...shared,
      count: candidates.length,
      clips: candidates.map((r) => ({
        id: r.id,
        text: r.text,
        aliases: r.aliases,
        frames: r.frames,
        fps: r.fps,
        source_asset: {
          path: `${sourceAssetsPath}/${r.asset}`,
          sha256: r.sha256,
        },
        source_motion_human_approved: r.source_motion_human_approved,
        source_motion_approval: r.source_motion_approval,
        derived_display_human_approved: false,
        display_candidate_status: r.display_candidate_status,
        display_stabilization_profile: r.profiles[r.selected_display].profile,
        quality_warning: r.quality_warning,
        mirror_status: r.mirror_status,
        signer_id: r.signer_id,
        verification: r.verification,
        numeric_evidence: r.profiles[r.selected_display],
      })),
    },
  };
}

async function main() {
  const { values } = parseArgs({
    options: {
      assets: { type: "string" },
      output: { type: "string" },
      "index-sha256": { type: "string" },
    },
  });
  if (
    !values.assets ||
    !values.output ||
    !/^[a-f0-9]{64}$/.test(values["index-sha256"] || "")
  )
    throw new Error(
      "Provide --assets, a new --output directory and pinned --index-sha256",
    );
  const repository = resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../../..",
  );
  const assets = realpathSync(resolve(values.assets));
  const output = resolve(values.output);
  if (output === assets || output.startsWith(assets + sep))
    throw new Error("Output must be outside source assets");
  const inputHashes = new Map();
  const readInput = (path) => {
    const bytes = readFileSync(path),
      digest = sha(bytes);
    if (inputHashes.has(path) && inputHashes.get(path) !== digest)
      throw new Error("Input changed during measurement: " + path);
    inputHashes.set(path, digest);
    return bytes;
  };
  const readAsset = (path) => {
    const resolved = realpathSync(join(assets, path));
    if (!resolved.startsWith(assets + sep))
      throw new Error("Asset escapes source root");
    return readInput(resolved);
  };
  for (const path of [
    "signbridge/src/tools/sign-motion-library-gate.mjs",
    "signbridge/src/tools/motion-quality.mjs",
    "signbridge/src/avatar/humanoid-rig.js",
    "signbridge/src/avatar/model.glb",
    "signbridge/src/demo/demo-retarget.js",
    "signbridge/src/demo/experimental-motion.js",
    "signbridge/src/demo/motion-stabilization.js",
    "signbridge/package.json",
    "signbridge/package-lock.json",
    "signbridge/node_modules/three/build/three.module.js",
    "signbridge/node_modules/three/package.json",
  ])
    readInput(join(repository, path));
  const source = await verifyApprovedSource({
    indexBytes: readAsset("experimental-index.json"),
    expectedIndexSha256: values["index-sha256"],
    expectedClips: 83,
    readAsset,
  });
  const model = loadSkeleton(
    join(repository, "signbridge/src/avatar/model.glb"),
  );
  const rig = createHumanoidRig(model);
  const retarget = createT08Retarget(rig, model, source.index);
  const records = [];
  for (const record of source.records) {
    const result = { ...record, profiles: {} };
    if (record.verification.passed) {
      try {
        const clip = source.clips.get(record.id);
        const raw = retarget.compile(clip, { stabilize: false });
        const before = measureTrack(raw, rig, model);
        for (const [name, profile] of [
          ["raw", null],
          ["current", record.current_display_profile],
          ["recovery", RECOVERY_PROFILE],
        ]) {
          const display = profile
            ? stabilizeQuaternionTrack(raw, clip.fps, profile)
            : raw;
          const after = profile ? measureTrack(display, rig, model) : before;
          result.profiles[name] = {
            profile,
            settings: profile ? MOTION_STABILIZATION_PROFILES[profile] : null,
            metrics: after.metrics,
            ...compareTracks(raw, display, before, after),
            invariants: inspectTrackInvariants(raw, display, clip.frames),
          };
        }
      } catch (error) {
        result.measurement_error = error.message;
      }
    }
    records.push(result);
    source.clips.delete(record.id);
    console.log(
      JSON.stringify({
        measured: records.length,
        total: 83,
        id: record.id,
        error: result.measurement_error || null,
      }),
    );
  }
  for (const [path, digest] of inputHashes)
    if (sha(readFileSync(path)) !== digest)
      throw new Error("Input changed during measurement: " + path);
  const inputs = [...inputHashes].map(([path, sha256]) => ({
    path: relative(repository, path),
    sha256,
  }));
  const sourceAssetsPath = relative(repository, assets);
  const { report, index } = createLibraryArtifacts({
    source,
    records,
    sourceAssetsPath,
    inputs,
  });
  report.environment = {
    node: process.version,
    three: JSON.parse(
      readFileSync(
        join(repository, "signbridge/node_modules/three/package.json"),
      ),
    ).version,
  };
  const command = `node signbridge/src/tools/sign-motion-library-gate.mjs --assets ${sourceAssetsPath} --index-sha256 ${source.indexSha256} --output local-data/unified-library-20261023-motion-v1/reproduced`;
  const files = {
    "report.json": jsonBytes(report),
    "stable-library-index.json": jsonBytes(index),
    "REPRODUCE.md": `# Fixed motion display candidate gate\n\nRun from the repository root with the recorded Node/Three versions and unchanged inputs:\n\n~~~sh\n${command}\n~~~\n\nOutput must be a new directory. Compare report.json and stable-library-index.json SHA256 to this run. Input hashes are recorded in report.json. No timing or wall-clock values enter the report.\n\nGate: wrist midpoint P95 <= 1 cm and no regression versus current; minimum wrist range retention >= 0.9; finger end-joint displacement P95 <= current + 0.2 cm; finite unit rotations, complete bone sets, exact frame count, endpoints within 0.00001 degrees. Current is preferred when it passes; otherwise recovery is considered.\n\n${limitations.map((item) => "- " + item).join("\n")}\n`,
  };
  mkdirSync(output);
  for (const [name, bytes] of Object.entries(files))
    writeFileSync(join(output, name), bytes, { flag: "wx" });
  writeFileSync(
    join(output, "SHA256SUMS"),
    Object.entries(files)
      .map(([name, bytes]) => `${sha(bytes)}  ${name}\n`)
      .join(""),
    { flag: "wx" },
  );
  console.log(JSON.stringify(report.summary));
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  await main();
