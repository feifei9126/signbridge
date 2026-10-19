// Measurements on the actual target skeleton. These are stability proxies, not CSL accuracy.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as THREE from "three";

export function loadSkeleton(path) {
  const bytes = readFileSync(path);
  const gltf = JSON.parse(
    bytes
      .subarray(20, 20 + bytes.readUInt32LE(12))
      .toString("utf8")
      .replace(/\0+$/, ""),
  );
  const nodes = gltf.nodes.map((node) => {
    const bone = new THREE.Bone();
    bone.name = node.name || "";
    if (node.matrix)
      new THREE.Matrix4()
        .fromArray(node.matrix)
        .decompose(bone.position, bone.quaternion, bone.scale);
    else {
      if (node.translation) bone.position.fromArray(node.translation);
      if (node.rotation) bone.quaternion.fromArray(node.rotation);
      if (node.scale) bone.scale.fromArray(node.scale);
    }
    return bone;
  });
  gltf.nodes.forEach((node, i) =>
    node.children?.forEach((j) => nodes[i].add(nodes[j])),
  );
  const model = new THREE.Object3D();
  gltf.scenes[gltf.scene || 0].nodes.forEach((i) => model.add(nodes[i]));
  model.updateMatrixWorld(true);
  return model;
}
export function percentile(values, fraction = 0.95) {
  if (!values.length) return null;
  const sorted = values.toSorted((a, b) => a - b);
  return sorted[
    Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))
  ];
}
export function measureTrack(frames, rig, model) {
  const angular = [],
    arm = [],
    finger = [],
    wrists = [],
    positions = [],
    contacts = [];
  const names = Object.keys(frames[0]);
  const ends = ["left", "right"].flatMap((side) =>
    ["Thumb", "Index", "Middle", "Ring", "Little"].map(
      (f) => side + f + "Distal",
    ),
  );
  const boxes = [new THREE.Box3(), new THREE.Box3()];
  for (let i = 0; i < frames.length; i++) {
    for (const value of Object.values(frames[i]))
      assert.ok(
        value.toArray().every(Number.isFinite) &&
          Math.abs(value.length() - 1) < 1e-5,
      );
    rig.interpolate(frames[i], frames[i], 1);
    model.updateMatrixWorld(true);
    const current = ["leftHand", "rightHand", ...ends].map((name) =>
      rig.bones[name].getWorldPosition(new THREE.Vector3()),
    );
    for (let side = 0; side < 2; side++)
      boxes[side].expandByPoint(current[side]);
    positions.push(current);
    let nearest = Infinity;
    for (let a = 2; a < 7; a++)
      for (let b = 7; b < 12; b++)
        nearest = Math.min(nearest, current[a].distanceTo(current[b]) * 100);
    contacts.push(nearest);
    if (i > 0 && i < frames.length - 1)
      for (const name of names) {
        const angle =
          (frames[i - 1][name]
            .clone()
            .slerp(frames[i + 1][name], 0.5)
            .angleTo(frames[i][name]) *
            180) /
          Math.PI;
        angular.push(angle);
        (/Thumb|Index|Middle|Ring|Little/.test(name) ? finger : arm).push(
          angle,
        );
      }
  }
  for (let i = 1; i < positions.length - 1; i++)
    for (let side = 0; side < 2; side++)
      wrists.push(
        positions[i][side].distanceTo(
          positions[i - 1][side].clone().lerp(positions[i + 1][side], 0.5),
        ) * 100,
      );
  rig.reset();
  model.updateMatrixWorld(true);
  return {
    metrics: {
      angularMidpointP95Degrees: percentile(angular),
      armMidpointP95Degrees: percentile(arm),
      fingerMidpointP95Degrees: percentile(finger),
      wristMidpointP95Cm: percentile(wrists),
      wristRangeCm: boxes.map(
        (b) => b.getSize(new THREE.Vector3()).length() * 100,
      ),
    },
    positions,
    contacts,
  };
}
export function compareTracks(raw, display, before, after) {
  assert.equal(raw.length, display.length);
  const pose = [],
    ends = [],
    close = [];
  for (let i = 0; i < raw.length; i++) {
    for (const name of Object.keys(raw[i])) {
      const difference =
        (raw[i][name]
          .clone()
          .normalize()
          .angleTo(display[i][name].clone().normalize()) *
          180) /
        Math.PI;
      pose.push(difference);
      if (i === 0 || i === raw.length - 1) assert.ok(difference < 1e-5);
    }
    for (let j = 2; j < 12; j++)
      ends.push(before.positions[i][j].distanceTo(after.positions[i][j]) * 100);
    if (before.contacts[i] < 3)
      close.push(Math.abs(before.contacts[i] - after.contacts[i]));
  }
  return {
    poseDeviationP95Degrees: percentile(pose),
    fingerEndJointDisplacementP95Cm: percentile(ends),
    nearHandFrames: close.length,
    nearHandDistanceChangeP95Cm: percentile(close),
    minimumWristRangeRetention: Math.min(
      ...before.metrics.wristRangeCm.map((value, i) =>
        value > 1e-6 ? after.metrics.wristRangeCm[i] / value : 1,
      ),
    ),
  };
}
