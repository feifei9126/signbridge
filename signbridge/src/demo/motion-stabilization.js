// Display-only temporal filtering. Source fits and checkpoint outputs stay intact.
export const MOTION_SMOOTHING_PROFILE = "quaternion-temporal-v1";
export const ADAPTIVE_SMOOTHING_PROFILE = "quaternion-temporal-adaptive-v1";
export const MOTION_STABILIZATION_PROFILES = Object.freeze({
  [ADAPTIVE_SMOOTHING_PROFILE]: Object.freeze({
    strategy: "isolated-spike",
    minimumResidualDegrees: 2,
    neighborSpreadDegrees: 12,
    maximumCorrectionDegrees: 3,
    correctionGain: 0.75,
  }),
  "quaternion-temporal-v1": Object.freeze({
    armWindowMs: 45,
    fingerWindowMs: 30,
  }),
  "quaternion-temporal-recovery-v1": Object.freeze({
    armWindowMs: 100,
    fingerWindowMs: 30,
  }),
});

export function stabilizeQuaternionTrack(
  frames,
  fps,
  profile = MOTION_SMOOTHING_PROFILE,
) {
  if (
    !Array.isArray(frames) ||
    !frames.length ||
    !Number.isFinite(fps) ||
    fps <= 0 ||
    fps > 120 ||
    !Object.hasOwn(MOTION_STABILIZATION_PROFILES, profile)
  )
    throw new Error("demoInvalidRotation");
  const names = Object.keys(frames[0]);
  if (!names.length) throw new Error("demoInvalidRotation");
  const source = frames.map((frame) => {
    if (!frame || Object.keys(frame).length !== names.length)
      throw new Error("demoInvalidRotation");
    const copy = {};
    for (const name of names) {
      const q = frame[name];
      if (
        !q?.isQuaternion ||
        !q.toArray().every(Number.isFinite) ||
        q.lengthSq() < 1e-12
      )
        throw new Error("demoInvalidRotation");
      copy[name] = q.clone().normalize();
    }
    return copy;
  });
  const output = source.map((frame) =>
    Object.fromEntries(names.map((name) => [name, frame[name].clone()])),
  );
  for (const name of names) {
    // Fingers use a shorter window to retain quick handshape changes. Pairwise
    // shortest-arc means keep the window centered and tolerate q / -q encoding.
    const windowMs = /Thumb|Index|Middle|Ring|Little/.test(name)
      ? MOTION_STABILIZATION_PROFILES[profile].fingerWindowMs
      : MOTION_STABILIZATION_PROFILES[profile].armWindowMs;
    for (let frame = 1; frame < source.length - 1; frame++) {
      const settings = MOTION_STABILIZATION_PROFILES[profile];
      if (settings.strategy === "isolated-spike") {
        const previous = source[frame - 1][name];
        const current = source[frame][name];
        const next = source[frame + 1][name];
        const center = previous.clone().slerp(next, 0.5).normalize();
        const residual = center.angleTo(current);
        const spread = previous.angleTo(next);
        if (
          (residual * 180) / Math.PI >= settings.minimumResidualDegrees &&
          (spread * 180) / Math.PI <= settings.neighborSpreadDegrees
        ) {
          const correction = Math.min(
            (settings.maximumCorrectionDegrees * Math.PI) / 180,
            residual * settings.correctionGain,
          );
          output[frame][name] = current
            .clone()
            .slerp(center, correction / residual)
            .normalize();
        }
        continue;
      }
      // Centered neighbor speed preserves sustained fast movement while smoothing
      // alternating noise. Sharp real reversals can still resemble jitter.
      const speed =
        (source[frame - 1][name].angleTo(source[frame + 1][name]) * fps) / 2;
      const adaptiveWindow = settings.minimumWindowMs
        ? Math.max(
            settings.minimumWindowMs,
            windowMs / (1 + speed / settings.speedScaleRadiansPerSecond),
          )
        : windowMs;
      const sigma = (fps * adaptiveWindow) / 1000;
      const radius = Math.ceil(2.5 * sigma);
      const count = Math.min(radius, frame, source.length - frame - 1);
      let total = 1;
      const result = source[frame][name].clone();
      for (let offset = 1; offset <= count; offset++) {
        const weight = 2 * Math.exp(-0.5 * (offset / sigma) ** 2);
        const pair = source[frame - offset][name]
          .clone()
          .slerp(source[frame + offset][name], 0.5)
          .normalize();
        result.slerp(pair, weight / (total + weight)).normalize();
        total += weight;
      }
      output[frame][name] = result;
    }
  }
  return output;
}
