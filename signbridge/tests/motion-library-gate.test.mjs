import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import * as THREE from "three";
import {
  experimentalPoseDigestInput,
  EXPERIMENTAL_MODEL_SHA256,
} from "../src/demo/experimental-motion.js";

// Keep the red phase an assertion failure while the new tool does not exist.
let gate;
try {
  gate = await import("../src/tools/sign-motion-library-gate.mjs");
} catch (error) {
  if (error.code !== "ERR_MODULE_NOT_FOUND") throw error;
}
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const encode = (value) => Buffer.from(JSON.stringify(value));
const q = (angle = 0) =>
  new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), angle);

function measurement() {
  return {
    metrics: {
      angularMidpointP95Degrees: 1,
      armMidpointP95Degrees: 1,
      fingerMidpointP95Degrees: 1,
      wristMidpointP95Cm: 1,
      wristRangeCm: [10, 10],
    },
    minimumWristRangeRetention: 0.9,
    fingerEndJointDisplacementP95Cm: 4.7,
    poseDeviationP95Degrees: 1,
    nearHandFrames: 0,
    nearHandDistanceChangeP95Cm: null,
    invariants: {
      finiteUnitQuaternions: true,
      exactFrames: true,
      exactBoneSets: true,
      endpointsPreserved: true,
    },
  };
}
function baseline() {
  const value = measurement();
  value.metrics.wristMidpointP95Cm = 1.2;
  value.fingerEndJointDisplacementP95Cm = 4.5;
  return value;
}

function fixture() {
  const metadata = {
    id: "approved-example",
    text: "测试",
    aliases: ["测试"],
    fps: 25,
    frames: 4,
    experimental: true,
    model_output: "smplx_fit_demo",
    training_data_member: false,
    training_ready: false,
    model_training_ready: false,
    human_approved: true,
    motion_review_status: "approved_for_demo_motion",
    motion_approval_id: "source-motion-approval",
    mirror_status: "unknown",
    signer_id: "unconfirmed",
    source_sha256: "a".repeat(64),
    feature_sha256: "b".repeat(64),
    fitted_sha256: "c".repeat(64),
    quality_warning: true,
  };
  const clip = {
    schema: "signbridge-experimental-clip-v1",
    ...metadata,
    poses: Array.from({ length: 4 }, () =>
      Array.from({ length: 55 }, () => [0, 0, 0]),
    ),
  };
  const approval = {
    schema: "signbridge-human-motion-approval-v1",
    id: metadata.motion_approval_id,
    scope: "motion_quality_only",
    declaration: "Existing source motion approval only",
    basis: "explicit_user_statement_in_current_conversation",
    captured_at_utc: "2026-10-22T07:55:41.877Z",
    source_index_sha256: "d".repeat(64),
    clips: [
      {
        id: clip.id,
        reviewed_asset_sha256: "e".repeat(64),
        source_sha256: clip.source_sha256,
        fitted_sha256: clip.fitted_sha256,
        poses_sha256: sha(experimentalPoseDigestInput(clip.poses)),
      },
    ],
  };
  const index = {
    schema: "signbridge-experimental-motion-index-v1",
    representation: "effective-smplx-55-axis-angle",
    smplx_rest_model_sha256: EXPERIMENTAL_MODEL_SHA256,
    training_weights_updated: false,
    text_to_sign_trained: false,
    training_ready: false,
    model_training_ready: false,
    research_only: true,
    parents: [-1, ...Array.from({ length: 54 }, (_, i) => i)],
    restJoints: Array.from({ length: 55 }, () => [0, 0, 0]),
    provenance_limitations: ["Legacy input hashes unavailable"],
    motion_approval: {
      schema: "signbridge-human-motion-approval-ref-v1",
      id: approval.id,
      scope: approval.scope,
      asset: "experimental/motion-approval.json",
      sha256: sha(encode(approval)),
    },
    clips: [
      {
        ...metadata,
        asset: "experimental/approved-example.json",
        sha256: sha(encode(clip)),
      },
    ],
  };
  return { clip, approval, index };
}
async function loadFixture(data, overrides = {}) {
  assert.ok(gate?.verifyApprovedSource, "approved-source verifier is missing");
  const indexBytes = encode(data.index);
  return gate.verifyApprovedSource({
    indexBytes,
    expectedIndexSha256: sha(indexBytes),
    expectedClips: 1,
    readAsset: (path) =>
      encode(
        path === data.index.motion_approval.asset ? data.approval : data.clip,
      ),
    ...overrides,
  });
}

test("fixed absolute gate rejects relative improvements that still exceed 1 cm", () => {
  assert.ok(gate?.evaluateDisplayCandidate, "fixed library gate is missing");
  const candidate = measurement();
  assert.equal(
    gate.evaluateDisplayCandidate(candidate, baseline()).passed,
    true,
  );
  candidate.metrics.wristMidpointP95Cm = 1.001;
  const result = gate.evaluateDisplayCandidate(candidate, baseline());
  assert.equal(result.passed, false);
  assert.ok(result.failures.includes("wristMidpointP95Cm"));
  assert.deepEqual(gate.LIBRARY_GATE, {
    maximumWristMidpointP95Cm: 1,
    minimumWristRangeRetention: 0.9,
    maximumFingerIncreaseOverCurrentCm: 0.2,
    maximumEndpointAngleDegrees: 0.00001,
    maximumQuaternionNormError: 0.00001,
  });
  assert.ok(Object.isFrozen(gate.LIBRARY_GATE));
});

test("range and finger gates are inclusive and cannot be traded for lower wrist noise", () => {
  assert.ok(gate?.evaluateDisplayCandidate);
  for (const [key, value] of [
    ["minimumWristRangeRetention", 0.899999],
    ["fingerEndJointDisplacementP95Cm", 4.700001],
  ]) {
    const candidate = measurement();
    candidate[key] = value;
    assert.equal(
      gate.evaluateDisplayCandidate(candidate, baseline()).passed,
      false,
    );
  }
  const current = baseline();
  current.metrics.wristMidpointP95Cm = 0.8;
  assert.ok(
    gate
      .evaluateDisplayCandidate(measurement(), current)
      .failures.includes("noWristRegression"),
  );
});

test("nonfinite metrics, missing evidence and broken frame/endpoint invariants fail closed", () => {
  assert.ok(gate?.evaluateDisplayCandidate);
  for (const key of Object.keys(measurement().invariants)) {
    const candidate = measurement();
    candidate.invariants[key] = false;
    assert.equal(
      gate.evaluateDisplayCandidate(candidate, baseline()).passed,
      false,
    );
  }
  for (const value of [NaN, Infinity, undefined, null]) {
    const candidate = measurement();
    candidate.fingerEndJointDisplacementP95Cm = value;
    assert.equal(
      gate.evaluateDisplayCandidate(candidate, baseline()).passed,
      false,
    );
  }
  const candidate = measurement();
  candidate.metrics.armMidpointP95Degrees = NaN;
  assert.equal(
    gate.evaluateDisplayCandidate(candidate, baseline()).passed,
    false,
  );
  assert.equal(gate.evaluateDisplayCandidate({}, baseline()).passed, false);
  assert.equal(gate.evaluateDisplayCandidate(measurement(), {}).passed, false);
});

test("invariants check every frame, complete bone sets and quaternion endpoints", () => {
  assert.ok(gate?.inspectTrackInvariants);
  const raw = Array.from({ length: 4 }, (_, i) => ({
    leftHand: q(i / 10),
    rightHand: q(i / 20),
  }));
  const display = raw.map((frame) =>
    Object.fromEntries(
      Object.entries(frame).map(([name, value]) => [name, value.clone()]),
    ),
  );
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(gate.inspectTrackInvariants(raw, display, 4)).filter(
        ([, value]) => typeof value === "boolean",
      ),
    ),
    {
      finiteUnitQuaternions: true,
      exactFrames: true,
      exactBoneSets: true,
      endpointsPreserved: true,
    },
  );
  display[1].leftHand.x = NaN;
  assert.equal(
    gate.inspectTrackInvariants(raw, display, 4).finiteUnitQuaternions,
    false,
  );
  display[1].leftHand = q(0.1);
  display[0].leftHand = q(0.1);
  assert.equal(
    gate.inspectTrackInvariants(raw, display, 4).endpointsPreserved,
    false,
  );
  delete display[2].rightHand;
  assert.equal(
    gate.inspectTrackInvariants(raw, display, 4).exactBoneSets,
    false,
  );
  assert.equal(
    gate.inspectTrackInvariants(raw, display.slice(1), 4).exactFrames,
    false,
  );
});

test("valid source approval and quantized pose digest are preserved without a new approval", async () => {
  const data = fixture();
  const result = await loadFixture(data);
  assert.equal(result.records.length, 1);
  const record = result.records[0];
  assert.equal(record.verification.passed, true);
  assert.equal(record.source_motion_human_approved, true);
  assert.equal(record.source_motion_approval.scope, "motion_quality_only");
  assert.equal(
    record.source_motion_approval.poses_sha256,
    data.approval.clips[0].poses_sha256,
  );
  assert.equal(
    record.source_motion_approval.reviewed_asset_sha256,
    "e".repeat(64),
  );
  assert.equal(record.quality_warning, true);
  assert.deepEqual(
    result.index.provenance_limitations,
    data.index.provenance_limitations,
  );
});

test("source index and approval bytes are checked before accepting any clips", async () => {
  const data = fixture();
  await assert.rejects(
    loadFixture(data, { expectedIndexSha256: "0".repeat(64) }),
    /index.*digest/i,
  );
  data.approval.declaration += " changed";
  await assert.rejects(loadFixture(data), /approval.*digest/i);
});

test("clip byte tampering is retained as a per-clip verification failure", async () => {
  const data = fixture();
  data.clip.poses[0][0][0] = 0.2;
  const result = await loadFixture(data);
  assert.equal(result.records[0].verification.passed, false);
  assert.match(result.records[0].verification.error, /digest/i);
});

test("rehashed pose tampering cannot bypass the existing approval loader", async () => {
  const data = fixture();
  data.clip.poses[0][0][0] = 0.2;
  data.index.clips[0].sha256 = sha(encode(data.clip));
  const result = await loadFixture(data);
  assert.equal(result.records[0].verification.passed, false);
  assert.match(
    result.records[0].verification.error,
    /pose|demoInvalidExperimentalAsset/i,
  );
});

test("approval provenance, approved count and scope cannot be invented", async () => {
  const data = fixture();
  await assert.rejects(loadFixture(data, { expectedClips: 83 }), /count/i);
  data.approval.clips[0].fitted_sha256 = "f".repeat(64);
  data.index.motion_approval.sha256 = sha(encode(data.approval));
  await assert.rejects(loadFixture(data), /demoInvalidExperimentalAsset/);
  const other = fixture();
  other.index.motion_approval.scope = "semantics_and_training";
  await assert.rejects(loadFixture(other), /demoInvalidExperimentalAsset/);
});

test("selection prefers a passing current profile and never promotes failures or approval", () => {
  assert.ok(gate?.selectDisplayCandidate);
  const current = measurement();
  const recovery = measurement();
  recovery.metrics.wristMidpointP95Cm = 0.4;
  const profiles = { current, recovery };
  assert.equal(gate.selectDisplayCandidate(profiles), "current");
  current.metrics.wristMidpointP95Cm = 1.2;
  assert.equal(gate.selectDisplayCandidate(profiles), "recovery");
  recovery.minimumWristRangeRetention = 0.8;
  assert.equal(gate.selectDisplayCandidate(profiles), null);
});

test("stable index references source assets and keeps display processing unapproved", async () => {
  assert.ok(gate?.createLibraryArtifacts);
  const source = await loadFixture(fixture());
  const records = source.records.map((record) => ({
    ...record,
    profiles: {
      raw: { ...measurement(), profile: null },
      current: { ...measurement(), profile: "quaternion-temporal-v1" },
      recovery: {
        ...measurement(),
        profile: "quaternion-temporal-recovery-v1",
      },
    },
  }));
  const args = {
    source,
    records,
    sourceAssetsPath: "local-data/approved-assets",
    inputs: [],
  };
  const first = gate.createLibraryArtifacts(args);
  assert.deepEqual(gate.createLibraryArtifacts(args), first);
  assert.equal(first.report.summary.displayCandidates, 1);
  assert.equal(first.index.clips.length, 1);
  const candidate = first.index.clips[0];
  assert.equal(candidate.source_motion_human_approved, true);
  assert.equal(candidate.derived_display_human_approved, false);
  assert.equal(
    candidate.display_stabilization_profile,
    "quaternion-temporal-v1",
  );
  assert.equal(
    candidate.source_asset.path,
    "local-data/approved-assets/experimental/approved-example.json",
  );
  assert.equal(candidate.source_motion_approval.scope, "motion_quality_only");
  assert.equal(candidate.quality_warning, true);
  for (const artifact of [first.report, first.index]) {
    const serialized = JSON.stringify(artifact);
    assert.equal(serialized.includes('"poses":'), false);
    assert.equal(serialized.includes('"human_approved":'), false);
    assert.equal(artifact.training_ready, false);
    assert.equal(artifact.model_training_ready, false);
    assert.equal(artifact.automatic_playback_enabled, false);
  }
  records[0].verification = { passed: false, error: "source digest differs" };
  const rejected = gate.createLibraryArtifacts(args);
  assert.equal(rejected.index.clips.length, 0);
  assert.equal(rejected.report.records[0].source_motion_human_approved, true);
  assert.equal(rejected.report.records[0].selected_display, null);
});
