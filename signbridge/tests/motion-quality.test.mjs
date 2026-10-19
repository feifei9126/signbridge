import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { compareTracks, percentile } from "../src/tools/motion-quality.mjs";
test("roundoff in quaternion norm is not misreported as a changed endpoint", () => {
  const q = new THREE.Quaternion(0.2, 0.3, 0.4, 0.5).normalize();
  q.set(
    q.x * (1 - 1e-12),
    q.y * (1 - 1e-12),
    q.z * (1 - 1e-12),
    q.w * (1 - 1e-12),
  );
  const raw = [{ hand: q }, { hand: q.clone() }],
    shown = raw.map((f) => ({ hand: f.hand.clone().normalize() }));
  const positions = raw.map(() =>
    Array.from({ length: 12 }, () => new THREE.Vector3()),
  );
  const measurement = {
    positions,
    contacts: [5, 5],
    metrics: { wristRangeCm: [0, 0] },
  };
  assert.doesNotThrow(() =>
    compareTracks(raw, shown, measurement, measurement),
  );
  assert.equal(percentile([]), null);
  assert.equal(percentile([1, 2, 3, 4], 0.5), 3);
});
