import * as THREE from "three";
export function axisAngleQuaternion(vector) {
  if (vector?.length !== 3 || !vector.every(Number.isFinite))
    throw new Error("demoInvalidRotation");
  const v = new THREE.Vector3(...vector),
    angle = v.length();
  return angle < 1e-9
    ? new THREE.Quaternion()
    : new THREE.Quaternion().setFromAxisAngle(v.divideScalar(angle), angle);
}
export function sourceWorldRotations(pose, parents) {
  const world = [];
  pose.forEach((v, i) => {
    const q = axisAngleQuaternion(v);
    if (i > 0) q.premultiply(world[parents[i]]);
    world.push(q);
  });
  return world;
}
export function boneFrame(direction, normal) {
  if (
    !direction.toArray().every(Number.isFinite) ||
    direction.lengthSq() < 1e-12 ||
    !normal.toArray().every(Number.isFinite)
  )
    throw new Error("demoInvalidRotation");
  const y = direction.clone().normalize(),
    z = normal.clone().addScaledVector(y, -normal.dot(y));
  if (z.lengthSq() < 1e-8) z.set(0, 1, 0).addScaledVector(y, -y.y);
  if (z.lengthSq() < 1e-8) z.set(1, 0, 0).addScaledVector(y, -y.x);
  z.normalize();
  const x = new THREE.Vector3().crossVectors(y, z).normalize();
  z.crossVectors(x, y);
  return new THREE.Quaternion().setFromRotationMatrix(
    new THREE.Matrix4().makeBasis(x, y, z),
  );
}
const links = [
  ["neck", 12, 15],
  ["head", 15, null],
  ["leftShoulder", 13, 16],
  ["rightShoulder", 14, 17],
  ["leftUpperArm", 16, 18],
  ["rightUpperArm", 17, 19],
  ["leftLowerArm", 18, 20],
  ["rightLowerArm", 19, 21],
  ["leftHand", 20, 28],
  ["rightHand", 21, 43],
];
for (const [side, starts] of [
  ["left", [37, 25, 28, 34, 31]],
  ["right", [52, 40, 43, 49, 46]],
]) {
  for (const [i, finger] of [
    "Thumb",
    "Index",
    "Middle",
    "Ring",
    "Little",
  ].entries()) {
    const names =
      i === 0
        ? ["Metacarpal", "Proximal", "Distal"]
        : ["Proximal", "Intermediate", "Distal"];
    for (let j = 0; j < 3; j++)
      links.push([
        side + finger + names[j],
        starts[i] + j,
        j < 2 ? starts[i] + j + 1 : null,
      ]);
  }
}
export function createT08Retarget(rig, modelRoot, bundle) {
  const playingPose = rig.capture();
  let binding;
  try {
    rig.reset();
    modelRoot.updateMatrixWorld(true);
    const rest = bundle.restJoints.map((v) => new THREE.Vector3(...v));
    const palmNormals = {};
    for (const [side, w, index, little] of [
      ["left", 20, 25, 31],
      ["right", 21, 40, 46],
    ])
      palmNormals[side] = new THREE.Vector3()
        .crossVectors(
          rest[index].clone().sub(rest[w]),
          rest[little].clone().sub(rest[w]),
        )
        .normalize();
    const targetPalm = {};
    for (const side of ["left", "right"]) {
      const w = rig.bones[side + "Hand"].getWorldPosition(new THREE.Vector3());
      const index = rig.bones[side + "IndexProximal"]
        .getWorldPosition(new THREE.Vector3())
        .sub(w);
      const little = rig.bones[side + "LittleProximal"]
        .getWorldPosition(new THREE.Vector3())
        .sub(w);
      targetPalm[side] = new THREE.Vector3()
        .crossVectors(index, little)
        .normalize();
    }
    binding = links.map(([name, joint, next]) => {
      const bone = rig.bones[name];
      if (!bone) throw new Error("demoMissingBone");
      const restWorld = bone.getWorldQuaternion(new THREE.Quaternion());
      const restPosition = bone.getWorldPosition(new THREE.Vector3());
      const sourceDir =
        next !== null
          ? rest[next].clone().sub(rest[joint])
          : rest[joint].clone().sub(rest[bundle.parents[joint]]);
      let targetChild;
      if (name.endsWith("UpperArm"))
        targetChild = rig.bones[name.replace("UpperArm", "LowerArm")];
      else if (name.endsWith("LowerArm"))
        targetChild = rig.bones[name.replace("LowerArm", "Hand")];
      else if (name.endsWith("Shoulder"))
        targetChild = rig.bones[name.replace("Shoulder", "UpperArm")];
      else if (name.endsWith("Hand"))
        targetChild = rig.bones[name.replace("Hand", "MiddleProximal")];
      else if (name === "neck") targetChild = rig.bones.head;
      else if (next !== null) targetChild = bone.children.find((c) => c.isBone);
      const targetDir = targetChild
        ? targetChild.getWorldPosition(new THREE.Vector3()).sub(restPosition)
        : restPosition
            .clone()
            .sub(bone.parent.getWorldPosition(new THREE.Vector3()));
      const side = name.startsWith("left")
        ? "left"
        : name.startsWith("right")
          ? "right"
          : null;
      const isFinger = joint >= 25 || name.endsWith("Hand");
      const sourceNormal = isFinger
        ? palmNormals[side]
        : new THREE.Vector3(0, 0, 1);
      const targetNormal = isFinger
        ? targetPalm[side]
        : new THREE.Vector3(0, 0, 1);
      const correction = boneFrame(sourceDir, sourceNormal).multiply(
        boneFrame(targetDir, targetNormal).invert(),
      );
      // Neck/head are already upright in both skeletons; face/hair child offsets
      // are not segment directions and must not rotate the avatar's head at REST.
      const alignedRest =
        name === "neck" || name === "head"
          ? restWorld
          : correction.multiply(restWorld);
      return { name, bone, joint, alignedRest };
    });
  } finally {
    rig.interpolate(playingPose, playingPose, 1);
    modelRoot.updateMatrixWorld(true);
  }
  function poseTargets(pose) {
    rig.reset();
    modelRoot.updateMatrixWorld(true);
    const world = [];
    pose.forEach((v, i) => {
      const q = axisAngleQuaternion(v);
      if (i > 0) q.premultiply(world[bundle.parents[i]]);
      world.push(q);
    });
    const targets = {};
    for (const b of binding) {
      const desired = world[b.joint].clone().multiply(b.alignedRest);
      const parentWorld = b.bone.parent.getWorldQuaternion(
        new THREE.Quaternion(),
      );
      b.bone.quaternion.copy(parentWorld.invert().multiply(desired));
      b.bone.updateWorldMatrix(false, true);
      targets[b.name] = b.bone.quaternion.clone();
    }
    // Jaw values belong to SMPL-X, whose axes differ; hold avatar face at rest for this prototype.
    rig.reset();
    modelRoot.updateMatrixWorld(true);
    return targets;
  }
  function compile(clip) {
    const snapshot = rig.capture();
    try {
      return clip.poses.map((p) => poseTargets(p));
    } finally {
      rig.interpolate(snapshot, snapshot, 1);
      modelRoot.updateMatrixWorld(true);
    }
  }
  return { compile, mappedBones: binding.length };
}
