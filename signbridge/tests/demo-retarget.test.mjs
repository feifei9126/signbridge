import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import * as THREE from "three";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
import {
  createT08Retarget,
  sourceWorldRotations,
} from "../src/demo/demo-retarget.js";
import { validateT08Bundle, planDemoText } from "../src/demo/demo-motion.js";

function skeletonFromGlb() {
  const b = readFileSync(new URL("../src/avatar/model.glb", import.meta.url));
  const json = JSON.parse(
    b
      .subarray(20, 20 + b.readUInt32LE(12))
      .toString("utf8")
      .replace(/\0+$/, ""),
  );
  const nodes = json.nodes.map((n) => {
    const o = new THREE.Bone();
    o.name = n.name || "";
    if (n.matrix) {
      new THREE.Matrix4()
        .fromArray(n.matrix)
        .decompose(o.position, o.quaternion, o.scale);
    } else {
      if (n.translation) o.position.fromArray(n.translation);
      if (n.rotation) o.quaternion.fromArray(n.rotation);
      if (n.scale) o.scale.fromArray(n.scale);
    }
    return o;
  });
  json.nodes.forEach((n, i) =>
    n.children?.forEach((c) => nodes[i].add(nodes[c])),
  );
  const root = new THREE.Object3D();
  json.scenes[json.scene || 0].nodes.forEach((i) => root.add(nodes[i]));
  root.updateMatrixWorld(true);
  return root;
}
const asset = new URL(
  "../../local-data/demo-20261012/t08-motion.json",
  import.meta.url,
);
const bundle = existsSync(asset)
  ? validateT08Bundle(JSON.parse(readFileSync(asset, "utf8")))
  : null;

test(
  "actual Godette hierarchy retargets SMPL-X REST without flipping its head or moving the root",
  { skip: !bundle },
  () => {
    const root = skeletonFromGlb(),
      rig = createHumanoidRig(root);
    const head = rig.bones.head.getWorldQuaternion(new THREE.Quaternion());
    const neck = rig.bones.neck.getWorldQuaternion(new THREE.Quaternion());
    const retarget = createT08Retarget(rig, root, bundle);
    const targets = retarget.compile({
      poses: [Array.from({ length: 55 }, () => [0, 0, 0])],
    })[0];
    rig.interpolate(targets, targets, 1);
    root.updateMatrixWorld(true);
    assert.ok(
      head.angleTo(rig.bones.head.getWorldQuaternion(new THREE.Quaternion())) <
        1e-6,
    );
    assert.ok(
      neck.angleTo(rig.bones.neck.getWorldQuaternion(new THREE.Quaternion())) <
        1e-6,
    );
    assert.ok(
      rig.rest.root.quaternion.angleTo(rig.bones.root.quaternion) < 1e-6,
    );
    for (const [side, joint, next] of [
      ["left", 16, 18],
      ["right", 16 + 1, 18 + 1],
      ["left", 18, 20],
      ["right", 19, 21],
    ]) {
      const a = rig.bones[
        side + (joint < 18 ? "UpperArm" : "LowerArm")
      ].getWorldPosition(new THREE.Vector3());
      const b = rig.bones[
        side + (joint < 18 ? "LowerArm" : "Hand")
      ].getWorldPosition(new THREE.Vector3());
      const source = new THREE.Vector3(...bundle.restJoints[next])
        .sub(new THREE.Vector3(...bundle.restJoints[joint]))
        .normalize();
      assert.ok(
        source.angleTo(b.sub(a).normalize()) < 0.04,
        `${side} joint ${joint} direction must align`,
      );
    }
  },
);
test(
  "all fourteen real token-decoded clips produce finite unit quaternions and leave the rig at REST",
  { skip: !bundle },
  () => {
    const root = skeletonFromGlb(),
      rig = createHumanoidRig(root),
      retarget = createT08Retarget(rig, root, bundle);
    assert.equal(retarget.mappedBones, 40);
    for (const clip of bundle.clips) {
      assert.equal(
        planDemoText(clip.text, "t08", bundle.clips).items[0].id,
        clip.id,
      );
      const tracks = retarget.compile(clip);
      assert.equal(tracks.length, clip.frames);
      for (const frame of tracks)
        for (const q of Object.values(frame)) {
          assert.ok(q.toArray().every(Number.isFinite));
          assert.ok(Math.abs(q.length() - 1) < 1e-5);
        }
      for (const [name, bone] of Object.entries(rig.bones))
        assert.deepEqual(
          bone.quaternion.toArray(),
          rig.rest[name].quaternion.toArray(),
          name,
        );
      assert.ok(clip.token_decode_parity_max < 1e-4);
    }
  },
);
test(
  "retarget arm segment follows source world rotation in an actual decoded pose",
  { skip: !bundle },
  () => {
    const root = skeletonFromGlb(),
      rig = createHumanoidRig(root),
      retarget = createT08Retarget(rig, root, bundle);
    const pose = bundle.clips[2].poses[60];
    const targets = retarget.compile({ poses: [pose] })[0];
    rig.interpolate(targets, targets, 1);
    root.updateMatrixWorld(true);
    const world = sourceWorldRotations(pose, bundle.parents);
    for (const [side, joint, next] of [
      ["left", 18, 20],
      ["right", 19, 21],
    ]) {
      const src = new THREE.Vector3(...bundle.restJoints[next])
        .sub(new THREE.Vector3(...bundle.restJoints[joint]))
        .applyQuaternion(world[joint])
        .normalize();
      const direction = rig.bones[side + "Hand"]
        .getWorldPosition(new THREE.Vector3())
        .sub(rig.bones[side + "LowerArm"].getWorldPosition(new THREE.Vector3()))
        .normalize();
      assert.ok(src.angleTo(direction) < 0.04, side);
    }
  },
);
