// Offline, display-only bounded quaternion denoising. Unlike the legacy
// profiles, noisy endpoints are filtered too; source arrays are never edited.
import * as THREE from "three";

export const REPAIR_PROFILES = Object.freeze({
  "native-repair-100-60-v1": Object.freeze({ armMs: 100, fingerMs: 60 }),
  "native-repair-120-80-v1": Object.freeze({ armMs: 120, fingerMs: 80 }),
});
function meanRotations(values, weights, seed) {
  let center = seed.clone().normalize();
  for (let pass = 0; pass < 3; pass++) {
    const step = new THREE.Vector3();
    let total = 0;
    for (let i = 0; i < values.length; i++) {
      const delta = center.clone().invert().multiply(values[i]).normalize();
      if (delta.w < 0) delta.set(-delta.x, -delta.y, -delta.z, -delta.w);
      const sine = Math.hypot(delta.x, delta.y, delta.z),
        angle = 2 * Math.atan2(sine, delta.w);
      if (sine > 1e-9)
        step.addScaledVector(
          new THREE.Vector3(delta.x, delta.y, delta.z),
          (weights[i] * angle) / sine,
        );
      total += weights[i];
    }
    step.divideScalar(total);
    const angle = step.length();
    if (angle < 1e-10) break;
    center
      .multiply(
        new THREE.Quaternion().setFromAxisAngle(
          step.divideScalar(angle),
          angle,
        ),
      )
      .normalize();
  }
  return center;
}
export function repairQuaternionTrack(
  frames,
  fps,
  profile = "native-repair-100-60-v1",
) {
  if (
    !REPAIR_PROFILES[profile] ||
    !Array.isArray(frames) ||
    frames.length < 4 ||
    !Number.isFinite(fps) ||
    fps <= 0
  )
    throw new Error("nativeInvalidAsset");
  const names = Object.keys(frames[0]);
  for (const frame of frames) {
    if (
      Object.keys(frame).length !== names.length ||
      names.some(
        (name) =>
          !frame[name]?.isQuaternion ||
          !frame[name].toArray().every(Number.isFinite) ||
          Math.abs(frame[name].length() - 1) > 1e-4,
      )
    )
      throw new Error("nativeInvalidAsset");
  }
  return frames.map((frame, index) =>
    Object.fromEntries(
      names.map((name) => {
        const ms = /Thumb|Index|Middle|Ring|Little/.test(name)
          ? REPAIR_PROFILES[profile].fingerMs
          : REPAIR_PROFILES[profile].armMs;
        const sigma = (fps * ms) / 1000,
          radius = Math.ceil(sigma * 2.5),
          values = [],
          weights = [];
        for (let offset = -radius; offset <= radius; offset++) {
          const k = index + offset;
          if (k < 0 || k >= frames.length) continue;
          values.push(frames[k][name]);
          weights.push(Math.exp(-0.5 * (offset / sigma) ** 2));
        }
        return [name, meanRotations(values, weights, frame[name])];
      }),
    ),
  );
}
