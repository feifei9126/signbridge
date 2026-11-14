// Bounds numeric quaternion payload; object overhead and the active track are additional.
export function createMotionCache({ maxEntries = 8, maxValues = 350000 } = {}) {
  const entries = new Map();
  let values = 0;
  return {
    get(key, compile) {
      const start = performance.now();
      const existing = entries.get(key);
      if (existing) {
        entries.delete(key);
        entries.set(key, existing);
        return {
          frames: existing.frames,
          cacheHit: true,
          compileMs: performance.now() - start,
        };
      }
      const frames = compile();
      const size = frames.reduce(
        (sum, frame) => sum + Object.keys(frame).length * 4,
        0,
      );
      if (size <= maxValues && maxEntries > 0) {
        while (
          entries.size &&
          (entries.size >= maxEntries || values + size > maxValues)
        ) {
          const first = entries.keys().next().value;
          values -= entries.get(first).size;
          entries.delete(first);
        }
        entries.set(key, { frames, size });
        values += size;
      }
      return { frames, cacheHit: false, compileMs: performance.now() - start };
    },
    stats() {
      return {
        entries: entries.size,
        numericBytes: values * 8,
        budgetNumericBytes: maxValues * 8,
      };
    },
    clear() {
      entries.clear();
      values = 0;
    },
  };
}
