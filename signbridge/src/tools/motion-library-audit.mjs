import * as THREE from "three";

export const MOTION_LIBRARY_SCHEMA = "signbridge-motion-library-v2";
export const MOTION_STABILITY = Object.freeze({
  STABLE: "stable",
  NEEDS_REVIEW: "needs_review",
  REJECT: "reject",
});

// These five display-only overrides came from the bounded 35-profile offline
// sweep in local-data/motion-library-quality-review-20261028-v1/window-sweep.json.
// They are not semantic approvals, source-pose edits, or new human approvals.
export const MOTION_DISPLAY_OVERRIDES = Object.freeze({
  "new-2940f3252f6cf6c2-cap-0021": "quaternion-temporal-recovery-85-10-v1",
  "new-2f7f92954492c2b6-cap-0034": "quaternion-temporal-recovery-45-10-v1",
  "new-cb8ac953180a2b6e-cap-0025": "quaternion-temporal-recovery-75-10-v1",
  "new-d437b3c3b3857c1a-cap-0016": "quaternion-temporal-recovery-65-10-v1",
  "new-fdefdb3258332397-cap-0048": "quaternion-temporal-recovery-55-10-v1",
});

export function displayProfileForEntry(clip, source, stability) {
  if (
    source === "experimental" &&
    stability === MOTION_STABILITY.NEEDS_REVIEW
  ) {
    return (
      MOTION_DISPLAY_OVERRIDES[clip?.id] || "quaternion-temporal-recovery-v1"
    );
  }
  return stability === MOTION_STABILITY.NEEDS_REVIEW
    ? "quaternion-temporal-recovery-v1"
    : "quaternion-temporal-v1";
}

const SPIKE_THRESHOLD_DEGREES = 8;
const REVIEW_P95_ADJACENT_DEGREES = 20;
const REVIEW_MAX_ADJACENT_DEGREES = 120;

function finiteAxisAngle(value) {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every((component) => Number.isFinite(component))
  );
}

function toQuaternion(value) {
  if (!finiteAxisAngle(value)) return null;
  const vector = new THREE.Vector3(...value);
  const angle = vector.length();
  if (angle < 1e-12) return new THREE.Quaternion();
  return new THREE.Quaternion().setFromAxisAngle(
    vector.divideScalar(angle),
    angle,
  );
}

function percentile(values, fraction = 0.95) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(fraction * sorted.length) - 1),
  );
  return sorted[index];
}

function degrees(radians) {
  return (radians * 180) / Math.PI;
}

function summarize(values) {
  return {
    max: values.length ? Math.max(...values) : null,
    p95: percentile(values),
  };
}

function sourceMetadata(source, clip) {
  if (source === "experimental") {
    return {
      source: "experimental",
      source_asset: clip.asset || `experimental/${clip.id}.json`,
      quality_status: "approved_motion_only",
      semantic_status: "unverified",
      human_approved: clip.human_approved === true,
      motion_review_status: clip.motion_review_status || "unconfirmed",
    };
  }
  if (source === "candidate") {
    return {
      source: "candidate",
      source_asset: "demo/t08-candidates.json",
      quality_status: "candidate_motion",
      semantic_status: "unverified",
      human_approved: false,
      motion_review_status: "candidate_only",
    };
  }
  return {
    source: "t08",
    source_asset: "demo/t08-motion.json",
    quality_status: "reference_motion",
    semantic_status: "unverified",
    human_approved: clip.human_motion_quality_approved === true,
    motion_review_status: clip.human_motion_quality_approved
      ? "approved_motion_only"
      : "unconfirmed",
  };
}

export function analyzeMotionClip(clip, source) {
  const poses = Array.isArray(clip?.poses) ? clip.poses : [];
  const expectedFrames = Number.isInteger(clip?.frames) ? clip.frames : null;
  const issues = [];
  const frameShapeValid = poses.every(
    (frame) =>
      Array.isArray(frame) &&
      frame.length === 55 &&
      frame.every(finiteAxisAngle),
  );
  if (poses.length < 2) issues.push("insufficient_frames");
  if (expectedFrames !== null && expectedFrames !== poses.length)
    issues.push("frame_count_mismatch");
  if (!frameShapeValid) issues.push("incomplete_pose");

  const frameQuaternions = frameShapeValid
    ? poses.map((frame) => frame.map(toQuaternion))
    : [];
  const finite =
    frameShapeValid &&
    frameQuaternions.every((frame) => frame.every((q) => q !== null));
  if (!finite && !issues.includes("incomplete_pose")) issues.push("non_finite");

  const adjacent = [];
  const spikes = [];
  if (finite) {
    for (let frame = 1; frame < frameQuaternions.length; frame += 1) {
      for (let joint = 0; joint < 55; joint += 1) {
        adjacent.push(
          degrees(
            frameQuaternions[frame - 1][joint].angleTo(
              frameQuaternions[frame][joint],
            ),
          ),
        );
      }
    }
    for (let frame = 1; frame < frameQuaternions.length - 1; frame += 1) {
      for (let joint = 0; joint < 55; joint += 1) {
        const center = frameQuaternions[frame - 1][joint]
          .clone()
          .slerp(frameQuaternions[frame + 1][joint], 0.5)
          .normalize();
        const residual = degrees(
          center.angleTo(frameQuaternions[frame][joint]),
        );
        if (residual >= SPIKE_THRESHOLD_DEGREES) spikes.push(residual);
      }
    }
  }

  const adjacentSummary = summarize(adjacent);
  const spikeSummary = summarize(spikes);
  const metrics = {
    finite,
    frame_count: poses.length,
    joint_count: frameShapeValid ? 55 : null,
    expected_frame_count: expectedFrames,
    max_adjacent_rotation_degrees: adjacentSummary.max,
    p95_adjacent_rotation_degrees: adjacentSummary.p95,
    max_angular_speed_degrees_per_second:
      adjacentSummary.max === null || !Number.isFinite(clip?.fps)
        ? null
        : adjacentSummary.max * clip.fps,
    isolated_spike_count: spikes.length,
    max_isolated_spike_degrees: spikeSummary.max,
    p95_isolated_spike_degrees: spikeSummary.p95,
  };

  let stability = MOTION_STABILITY.STABLE;
  if (!finite || issues.length) stability = MOTION_STABILITY.REJECT;
  else if (
    metrics.p95_adjacent_rotation_degrees > REVIEW_P95_ADJACENT_DEGREES ||
    metrics.max_adjacent_rotation_degrees > REVIEW_MAX_ADJACENT_DEGREES ||
    clip?.quality_warning === true
  ) {
    stability = MOTION_STABILITY.NEEDS_REVIEW;
  }

  const metadata = sourceMetadata(source, clip);
  return {
    ...metadata,
    id: clip.id,
    text: clip.text,
    aliases: clip.aliases || [],
    fps: clip.fps,
    frames: clip.frames,
    duration: clip.duration ?? clip.frames / clip.fps,
    stability,
    display_stabilization_profile: displayProfileForEntry(
      clip,
      source,
      stability,
    ),
    metrics,
    issues,
    training_data_member: clip.training_data_member === true,
    training_ready: false,
    model_training_ready: false,
  };
}

function entriesFor(source, bundle, files) {
  const clips = (bundle?.clips || []).map((clip) => {
    if (source !== "experimental" || !files?.get(clip.asset)) return clip;
    return JSON.parse(files.get(clip.asset).toString("utf8"));
  });
  return clips.map((clip) => analyzeMotionClip(clip, source));
}

export function buildMotionLibrary({
  motion,
  candidates,
  experimental,
  experimentalFiles,
}) {
  const entries = [
    ...entriesFor("t08", motion),
    ...entriesFor("candidate", candidates),
    ...entriesFor("experimental", experimental, experimentalFiles),
  ].sort((a, b) => a.id.localeCompare(b.id));
  const bySource = Object.fromEntries(
    ["t08", "candidate", "experimental"].map((source) => [
      source,
      entries.filter((entry) => entry.source === source).length,
    ]),
  );
  const byStability = Object.fromEntries(
    Object.values(MOTION_STABILITY).map((stability) => [
      stability,
      entries.filter((entry) => entry.stability === stability).length,
    ]),
  );
  return {
    schema: MOTION_LIBRARY_SCHEMA,
    version: 2,
    representation: "source-specific-axis-angle-with-display-quaternion-policy",
    entries,
    summary: {
      total: entries.length,
      bySource,
      byStability,
    },
    semantic_status: "unverified",
    training_ready: false,
    model_training_ready: false,
    deployment_ready: false,
  };
}
