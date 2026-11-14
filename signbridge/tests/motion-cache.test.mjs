import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
const path = new URL("../src/demo/motion-cache.js", import.meta.url);
const frames = (count) =>
  Array.from({ length: count }, () => ({ hand: { isQuaternion: true } }));

test("motion cache hits reuse compilation, refresh recency and respect the numeric payload budget", async () => {
  assert.ok(existsSync(path), "bounded motion cache missing");
  const { createMotionCache } = await import(path.href);
  const cache = createMotionCache({ maxEntries: 2, maxValues: 20 });
  let calls = 0;
  const compile = () => {
    calls++;
    return frames(2);
  };
  const first = cache.get("a", compile);
  assert.equal(first.cacheHit, false);
  assert.equal(cache.get("a", compile).frames, first.frames);
  assert.equal(calls, 1);
  cache.get("b", compile);
  cache.get("a", compile);
  cache.get("c", compile);
  assert.equal(cache.get("a", compile).cacheHit, true);
  assert.equal(cache.get("b", compile).cacheHit, false);
  assert.ok(cache.stats().numericBytes <= 20 * 8);
  cache.clear();
  assert.equal(cache.stats().entries, 0);
});

test("oversized tracks stay usable without entering cache; failed compilation is never cached", async () => {
  assert.ok(existsSync(path));
  const { createMotionCache } = await import(path.href);
  const cache = createMotionCache({ maxValues: 4 });
  assert.equal(cache.get("large", () => frames(3)).frames.length, 3);
  assert.equal(cache.stats().entries, 0);
  assert.throws(() =>
    cache.get("bad", () => {
      throw new Error("decode failed");
    }),
  );
  assert.equal(cache.stats().entries, 0);
});
