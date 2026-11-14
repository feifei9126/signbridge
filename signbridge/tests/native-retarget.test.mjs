import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { readFileSync, existsSync } from "node:fs";
import { loadSkeleton } from "../src/tools/motion-quality.mjs";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
let api;
try {
  api = await import("../src/demo/native-retarget.js");
} catch (error) {
  if (error.code !== "ERR_MODULE_NOT_FOUND") throw error;
}

test("two-bone solution reaches the target with exact lengths and stable preferred elbow plane", () => {
  assert.ok(api);
  const v = (x, y, z = 0) => new THREE.Vector3(x, y, z);
  const result = api.solveArm(v(0, 0), v(0.3, 0), v(0.1, 0.2), 0.2, 0.2);
  assert.ok(result.elbow.y > 0);
  assert.ok(Math.abs(result.elbow.length() - 0.2) < 1e-9);
  assert.ok(Math.abs(result.elbow.distanceTo(result.wrist) - 0.2) < 1e-9);
  assert.ok(result.wrist.distanceTo(v(0.3, 0)) < 1e-9);
  const far = api.solveArm(v(0, 0), v(1, 0), v(0, 1), 0.2, 0.2);
  assert.ok(far.wrist.length() < 0.4);
});

test(
  "native IK preserves the model pose after compile and binds source wrist geometry",
  {
    skip: !existsSync(
      new URL(
        "../../local-data/demo-20261012/t08-motion.json",
        import.meta.url,
      ),
    ),
  },
  () => {
    assert.ok(api);
    const bundle = JSON.parse(
      readFileSync(
        new URL(
          "../../local-data/demo-20261012/t08-motion.json",
          import.meta.url,
        ),
      ),
    );
    const model = loadSkeleton(
      new URL("../src/avatar/model.glb", import.meta.url),
    );
    const rig = createHumanoidRig(model),
      snapshot = rig.capture();
    const retarget = api.createNativeRetarget(rig, model, bundle);
    const clip = {
      poses: bundle.clips[0].poses.slice(0, 4),
      fps: 25,
      frames: 4,
    };
    const result = retarget.compile(clip);
    assert.equal(result.length, 4);
    for (const frame of result) assert.equal(Object.keys(frame).length, 40);
    for (const [name, q] of Object.entries(snapshot))
      assert.deepEqual(rig.capture()[name].toArray(), q.toArray());
    for (let i = 0; i < result.length; i++) {
      const targets = retarget.wristTargets(clip.poses[i]);
      rig.interpolate(result[i], result[i], 1);
      model.updateMatrixWorld(true);
      for (const side of ["left", "right"]) {
        const actual = rig.bones[side + "Hand"].getWorldPosition(
          new THREE.Vector3(),
        );
        assert.ok(actual.distanceTo(targets[side]) < 0.01);
      }
    }
  },
);
