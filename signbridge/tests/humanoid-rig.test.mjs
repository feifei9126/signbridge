import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import * as THREE from "three";

import {
  REQUIRED_SIGNING_BONES,
  createHumanoidRig,
} from "../src/avatar/humanoid-rig.js";

function readGlbNodeNames() {
  const bytes = readFileSync(
    new URL("../src/avatar/model.glb", import.meta.url),
  );
  const jsonLength = bytes.readUInt32LE(12);
  const json = JSON.parse(
    bytes
      .subarray(20, 20 + jsonLength)
      .toString("utf8")
      .replace(/\0+$/, ""),
  );
  return json.nodes.map((node) => node.name).filter(Boolean);
}

function createModelSkeleton() {
  const root = new THREE.Object3D();
  for (const name of readGlbNodeNames()) {
    const bone = new THREE.Bone();
    bone.name = name;
    root.add(bone);
  }
  return root;
}

test("Godette profile maps the complete signing skeleton", () => {
  const rig = createHumanoidRig(createModelSkeleton());
  assert.equal(rig.isSigningReady, true);
  assert.deepEqual(rig.missing, []);
  for (const name of REQUIRED_SIGNING_BONES) assert.ok(rig.bones[name], name);
});

test("rig accepts legacy pose names and resets to REST", () => {
  const rig = createHumanoidRig(createModelSkeleton());
  const bone = rig.bones.rightUpperArm;
  const restX = bone.rotation.x;
  rig.applyPose({ rUpperArm: { x: 0.4, y: 0, z: 0 } });
  assert.ok(Math.abs(bone.rotation.x - (restX + 0.4)) < 1e-6);
  assert.ok(Math.abs(rig.capturePose().rightUpperArm.x - 0.4) < 1e-6);
  rig.reset();
  assert.ok(Math.abs(bone.rotation.x - restX) < 1e-6);
});
