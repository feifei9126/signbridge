// Task-space upper-body retarget. Source positions constrain avatar wrists;
// original rotations still determine palms/fingers. No changes to source fits.
import * as THREE from "three";
import { createT08Retarget, sourceWorldRotations } from "./demo-retarget.js";

export function sourceJointPositions(pose, bundle) {
  const world = sourceWorldRotations(pose, bundle.parents),
    positions = [];
  for (let joint = 0; joint < 55; joint++) {
    const rest = new THREE.Vector3(...bundle.restJoints[joint]);
    positions[joint] =
      joint === 0
        ? rest
        : rest
            .sub(new THREE.Vector3(...bundle.restJoints[bundle.parents[joint]]))
            .applyQuaternion(world[bundle.parents[joint]])
            .add(positions[bundle.parents[joint]]);
  }
  return positions;
}
export function solveArm(
  shoulder,
  target,
  preferredElbow,
  upperLength,
  lowerLength,
) {
  const delta = target.clone().sub(shoulder),
    distance = delta.length();
  const direction =
    distance > 1e-8 ? delta.divideScalar(distance) : new THREE.Vector3(0, 0, 1);
  const reach = Math.max(
    Math.abs(upperLength - lowerLength) + 1e-5,
    Math.min(upperLength + lowerLength - 1e-5, distance),
  );
  const along =
    (upperLength * upperLength - lowerLength * lowerLength + reach * reach) /
    (2 * reach);
  const radius = Math.sqrt(
    Math.max(0, upperLength * upperLength - along * along),
  );
  const plane = preferredElbow.clone().sub(shoulder);
  plane.addScaledVector(direction, -plane.dot(direction));
  if (plane.lengthSq() < 1e-10) {
    plane.set(0, -1, 0).addScaledVector(direction, direction.y);
    if (plane.lengthSq() < 1e-10)
      plane.set(0, 0, 1).addScaledVector(direction, -direction.z);
  }
  plane.normalize();
  return {
    elbow: shoulder
      .clone()
      .addScaledVector(direction, along)
      .addScaledVector(plane, radius),
    wrist: shoulder.clone().addScaledVector(direction, reach),
  };
}
export function createNativeRetarget(rig, model, bundle) {
  const rotationRetarget = createT08Retarget(rig, model, bundle),
    snapshot = rig.capture();
  rig.reset();
  model.updateMatrixWorld(true);
  const rest = bundle.restJoints.map((v) => new THREE.Vector3(...v));
  const position = (name) =>
    rig.bones[name].getWorldPosition(new THREE.Vector3());
  const center = position("leftUpperArm")
    .add(position("rightUpperArm"))
    .multiplyScalar(0.5);
  const sourceCenter = rest[16].clone().add(rest[17]).multiplyScalar(0.5);
  const lengths = {},
    ratios = [];
  for (const [side, shoulder, elbow, wrist] of [
    ["left", 16, 18, 20],
    ["right", 17, 19, 21],
  ]) {
    const upper = position(side + "UpperArm").distanceTo(
        position(side + "LowerArm"),
      ),
      lower = position(side + "LowerArm").distanceTo(position(side + "Hand"));
    lengths[side] = { upper, lower };
    ratios.push(
      (upper + lower) /
        (rest[shoulder].distanceTo(rest[elbow]) +
          rest[elbow].distanceTo(rest[wrist])),
    );
  }
  const scale = (ratios[0] + ratios[1]) * 0.5;
  rig.interpolate(snapshot, snapshot, 1);
  model.updateMatrixWorld(true);
  const map = (p) =>
    p.clone().sub(sourceCenter).multiplyScalar(scale).add(center);
  function wristTargets(pose) {
    const points = sourceJointPositions(pose, bundle);
    return { left: map(points[20]), right: map(points[21]) };
  }
  function aim(name, child, target) {
    const bone = rig.bones[name],
      origin = position(name),
      current = position(child).sub(origin).normalize();
    const desired = target.clone().sub(origin).normalize();
    const world = bone
      .getWorldQuaternion(new THREE.Quaternion())
      .premultiply(new THREE.Quaternion().setFromUnitVectors(current, desired));
    bone.quaternion.copy(
      bone.parent
        .getWorldQuaternion(new THREE.Quaternion())
        .invert()
        .multiply(world)
        .normalize(),
    );
    bone.updateWorldMatrix(false, true);
  }
  function compile(clip) {
    const before = rig.capture();
    try {
      const frames = rotationRetarget.compile(clip, { stabilize: false });
      return frames.map((frame, index) => {
        rig.interpolate(frame, frame, 1);
        model.updateMatrixWorld(true);
        const points = sourceJointPositions(clip.poses[index], bundle);
        for (const [side, e, w] of [
          ["left", 18, 20],
          ["right", 19, 21],
        ]) {
          const palm = rig.bones[side + "Hand"].getWorldQuaternion(
            new THREE.Quaternion(),
          );
          const solved = solveArm(
            position(side + "UpperArm"),
            map(points[w]),
            map(points[e]),
            lengths[side].upper,
            lengths[side].lower,
          );
          aim(side + "UpperArm", side + "LowerArm", solved.elbow);
          aim(side + "LowerArm", side + "Hand", solved.wrist);
          const hand = rig.bones[side + "Hand"];
          hand.quaternion.copy(
            hand.parent
              .getWorldQuaternion(new THREE.Quaternion())
              .invert()
              .multiply(palm)
              .normalize(),
          );
          hand.updateWorldMatrix(false, true);
        }
        return Object.fromEntries(
          Object.keys(frame).map((name) => [
            name,
            rig.bones[name].quaternion.clone().normalize(),
          ]),
        );
      });
    } finally {
      rig.interpolate(before, before, 1);
      model.updateMatrixWorld(true);
    }
  }
  return { compile, wristTargets, mappedBones: 40, scale };
}
