import { canonicalizePose } from "./humanoid-rig.js";
import {
  createMotionAsset,
  serializeMotionAsset,
  validateMotionAsset,
} from "./motion-asset.js";

const REVIEW_PROTOCOL = "signbridge-visual-review-v1";
const MAX_REVIEW_BATCH = 8;
const MAX_REVIEW_SAMPLES = 12;
const REVIEW_CELL = Object.freeze({ width: 320, height: 360 });
const REVIEW_VIEWS = Object.freeze(["front", "right", "left"]);

function prepareReviewMotion(entry, rig) {
  if (!entry?.motion?.id || !["custom", "builtin"].includes(entry.source))
    throw new Error("motionInvalidData");
  if (
    entry.source === "builtin" &&
    (!Array.isArray(entry.motion.frames) ||
      entry.motion.frames.some(
        (frame) =>
          !frame?.value ||
          typeof frame.value !== "object" ||
          Array.isArray(frame.value),
      ))
  )
    throw new Error("motionInvalidData");
  const asset =
    entry.source === "custom"
      ? validateMotionAsset(entry.motion, rig)
      : createMotionAsset(
          rig,
          entry.motion.frames?.map((frame) => ({
            value: canonicalizePose(frame.value),
            duration: frame.duration,
          })),
          {
            id: "custom_visual_review",
            gloss: entry.motion.gloss,
            texts: entry.motion.texts || [],
            tags: entry.motion.tags || [],
          },
        );
  return {
    key: `${entry.source}:${entry.motion.id}`,
    id: entry.motion.id,
    source: entry.source,
    enabled: entry.enabled === true,
    asset,
    totalDuration: asset.frames.reduce((sum, frame) => sum + frame.duration, 0),
    usedBones: [
      ...new Set(asset.frames.flatMap((frame) => Object.keys(frame.value))),
    ].sort(),
  };
}

function sampleFrameIndices(count, limit = MAX_REVIEW_SAMPLES) {
  if (
    !Number.isInteger(count) ||
    count < 1 ||
    count > 240 ||
    !Number.isInteger(limit) ||
    limit < 2 ||
    limit > MAX_REVIEW_SAMPLES
  )
    throw new Error("reviewInvalidSamples");
  if (count <= limit) return Array.from({ length: count }, (_, index) => index);
  return Array.from({ length: limit }, (_, index) =>
    Math.round((index * (count - 1)) / (limit - 1)),
  );
}

async function reviewHash(value) {
  const bytes =
    value instanceof ArrayBuffer || ArrayBuffer.isView(value)
      ? value
      : new globalThis.TextEncoder().encode(serializeMotionAsset(value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function comparePixels(current, baseline, channelTolerance = 16) {
  if (
    current.length !== baseline.length ||
    !current.length ||
    current.length % 4
  )
    throw new Error("reviewImageMismatch");
  let changedPixels = 0;
  let totalDifference = 0;
  for (let offset = 0; offset < current.length; offset += 4) {
    let maximum = 0;
    for (let channel = 0; channel < 3; channel++) {
      const difference = Math.abs(
        current[offset + channel] - baseline[offset + channel],
      );
      totalDifference += difference;
      maximum = Math.max(maximum, difference);
    }
    if (maximum > channelTolerance) changedPixels += 1;
  }
  const pixels = current.length / 4;
  return {
    changedPixels,
    changedRatio: changedPixels / pixels,
    meanDifference: totalDifference / (pixels * 3),
    channelTolerance,
  };
}

function baselineCompatibility(current, baseline) {
  if (!baseline) return "missing";
  if (
    baseline.protocol !== REVIEW_PROTOCOL ||
    baseline.environmentHash !== current.environmentHash
  )
    return "incompatible";
  if (baseline.motionHash !== current.motionHash) return "motionChanged";
  return "comparable";
}

export {
  REVIEW_PROTOCOL,
  MAX_REVIEW_BATCH,
  MAX_REVIEW_SAMPLES,
  REVIEW_CELL,
  REVIEW_VIEWS,
  prepareReviewMotion,
  sampleFrameIndices,
  reviewHash,
  comparePixels,
  baselineCompatibility,
};
