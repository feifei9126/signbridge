import {
  MOTION_SMOOTHING_PROFILE,
  RECOVERY_SMOOTHING_PROFILE,
  MOTION_STABILIZATION_PROFILES,
} from "./motion-stabilization.js";

const LEARNED_SOURCES = new Set(["t08", "candidate", "experimental"]);

export function isLearnedMotionSource(source) {
  return LEARNED_SOURCES.has(source);
}

export function resolveMotionDisplayPolicy(
  clip = {},
  source,
  indexedEntry = null,
) {
  if (!isLearnedMotionSource(source)) return { enabled: false, profile: null };
  const requested =
    indexedEntry?.display_stabilization_profile ||
    clip.display_stabilization_profile ||
    (clip.quality_warning
      ? RECOVERY_SMOOTHING_PROFILE
      : MOTION_SMOOTHING_PROFILE);
  return {
    enabled: true,
    profile: Object.hasOwn(MOTION_STABILIZATION_PROFILES, requested)
      ? requested
      : MOTION_SMOOTHING_PROFILE,
  };
}
