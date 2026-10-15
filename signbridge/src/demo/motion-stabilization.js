// Display-only temporal filtering. Source fits and checkpoint outputs stay intact.
export const MOTION_SMOOTHING_PROFILE = "quaternion-temporal-v1";

export function stabilizeQuaternionTrack(frames, fps) {
  if (
    !Array.isArray(frames) ||
    !frames.length ||
    !Number.isFinite(fps) ||
    fps <= 0 ||
    fps > 120
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
    const sigma =
      fps * (/Thumb|Index|Middle|Ring|Little/.test(name) ? 0.03 : 0.045);
    const radius = Math.ceil(2.5 * sigma);
    for (let frame = 1; frame < source.length - 1; frame++) {
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
