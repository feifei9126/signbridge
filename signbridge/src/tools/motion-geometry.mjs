// Conservative collision screening against the actual model's rest torso skin
// and finite-radius limb capsules. Ambiguous contacts stay review risks.
import * as THREE from "three";
import { segmentDistance } from "./sign-native-library.mjs";
import { percentile } from "./motion-quality.mjs";

const pointLine = (p, a, b) => segmentDistance(p, p, a, b).distance;
function hull(points) {
  const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [],
    upper = [];
  for (const v of p) {
    while (lower.length > 1 && cross(lower.at(-2), lower.at(-1), v) <= 0)
      lower.pop();
    lower.push(v);
  }
  for (const v of p.toReversed()) {
    while (upper.length > 1 && cross(upper.at(-2), upper.at(-1), v) <= 0)
      upper.pop();
    upper.push(v);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}
export function polygonDepth(point, polygon) {
  if (polygon.length < 3) return null;
  let inside = true,
    min = Infinity;
  for (let i = 0; i < polygon.length; i++) {
    const a = polygon[i],
      b = polygon[(i + 1) % polygon.length],
      dx = b[0] - a[0],
      dy = b[1] - a[1];
    if (dx * (point[1] - a[1]) - dy * (point[0] - a[0]) < 0) inside = false;
    const t = Math.max(
      0,
      Math.min(
        1,
        ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) /
          (dx * dx + dy * dy || 1),
      ),
    );
    min = Math.min(
      min,
      Math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy),
    );
  }
  return inside ? min : -min;
}
export function createGeometryAudit(model, rig) {
  rig.reset();
  model.updateMatrixWorld(true);
  let mesh;
  model.traverse((o) => {
    if (o.isSkinnedMesh) mesh = o;
  });
  if (!mesh) throw new Error("Actual skinned mesh required");
  mesh.skeleton.update();
  const torso = [],
    hands = { left: [], right: [] },
    position = new THREE.Vector3();
  const owners = new Map(
    Object.entries(rig.bones).map(([name, bone]) => [bone, name]),
  );
  const owner = (bone) => {
    for (let p = bone; p; p = p.parent) if (owners.has(p)) return owners.get(p);
    return null;
  };
  for (
    let vertex = 0;
    vertex < mesh.geometry.attributes.position.count;
    vertex++
  ) {
    const indices = mesh.geometry.attributes.skinIndex,
      weights = mesh.geometry.attributes.skinWeight;
    let biggest = -1,
      bone;
    for (let j = 0; j < 4; j++)
      if (weights.getComponent(vertex, j) > biggest) {
        biggest = weights.getComponent(vertex, j);
        bone = mesh.skeleton.bones[indices.getComponent(vertex, j)];
      }
    const name = owner(bone);
    mesh.getVertexPosition(vertex, position);
    mesh.localToWorld(position);
    if (["spine", "chest", "upperChest"].includes(name))
      torso.push(position.clone());
    for (const side of ["left", "right"])
      if (
        name?.startsWith(side) &&
        /Hand|Thumb|Index|Middle|Ring|Little/.test(name)
      )
        hands[side].push(vertex);
  }
  if (torso.length < 100 || hands.left.length < 100 || hands.right.length < 100)
    throw new Error("Skin segmentation incomplete");
  const slices = new Map();
  for (let band = 95; band <= 139; band++) {
    const y = band / 100,
      points = torso
        .filter((p) => Math.abs(p.y - y) < 0.015)
        .map((p) => [p.x, p.z]);
    if (points.length > 6) slices.set(band, hull(points));
  }
  const selected = Object.fromEntries(
    Object.entries(hands).map(([side, ids]) => [
      side,
      ids.filter((_, i) => i % 8 === 0),
    ]),
  );
  return function measure(frames) {
    const torsoFrames = [],
      armFrames = [],
      handArmFrames = [],
      wristResidual = [],
      fingerResidual = [],
      armResidual = [];
    const wristPositions = [];
    let deepest = 0,
      minimumArm = Infinity;
    for (let i = 0; i < frames.length; i++) {
      rig.interpolate(frames[i], frames[i], 1);
      model.updateMatrixWorld(true);
      mesh.skeleton.update();
      const p = (name) => rig.bones[name].getWorldPosition(new THREE.Vector3());
      const limbs = Object.fromEntries(
        ["left", "right"].map((side) => [
          side,
          {
            shoulder: p(side + "UpperArm"),
            elbow: p(side + "LowerArm"),
            wrist: p(side + "Hand"),
          },
        ]),
      );
      let armRisk = false;
      for (const a of [
        [limbs.left.shoulder, limbs.left.elbow],
        [limbs.left.elbow, limbs.left.wrist],
      ])
        for (const b of [
          [limbs.right.shoulder, limbs.right.elbow],
          [limbs.right.elbow, limbs.right.wrist],
        ]) {
          const cross = segmentDistance(...a, ...b);
          minimumArm = Math.min(minimumArm, cross.distance);
          if (
            cross.distance < 0.045 &&
            cross.s > 0.05 &&
            cross.s < 0.95 &&
            cross.t > 0.05 &&
            cross.t < 0.95
          )
            armRisk = true;
        }
      if (armRisk) armFrames.push(i + 1);
      let inside = false,
        penetration = false;
      for (const side of ["left", "right"])
        for (const id of selected[side]) {
          const v = mesh.localToWorld(
            mesh.getVertexPosition(id, new THREE.Vector3()),
          );
          const polygon = slices.get(Math.round(v.y * 100));
          const depth = polygon ? polygonDepth([v.x, v.z], polygon) : null;
          if (depth !== null && depth > 0.006) {
            inside = true;
            deepest = Math.max(deepest, depth);
          }
          const opposite = limbs[side === "left" ? "right" : "left"];
          for (const [a, b] of [
            [opposite.elbow, opposite.wrist],
            [opposite.shoulder, opposite.elbow],
          ]) {
            const direction = b.clone().sub(a),
              t = v.clone().sub(a).dot(direction) / direction.lengthSq();
            if (t > 0.08 && t < 0.92 && pointLine(v, a, b) < 0.018)
              penetration = true;
          }
        }
      if (inside) torsoFrames.push(i + 1);
      if (penetration) handArmFrames.push(i + 1);
      wristPositions.push([limbs.left.wrist, limbs.right.wrist]);
      if (i > 0 && i < frames.length - 1)
        for (const name of Object.keys(frames[i])) {
          const residual =
            (frames[i - 1][name]
              .clone()
              .slerp(frames[i + 1][name], 0.5)
              .angleTo(frames[i][name]) *
              180) /
            Math.PI;
          (/Thumb|Index|Middle|Ring|Little/.test(name)
            ? fingerResidual
            : armResidual
          ).push(residual);
        }
    }
    for (let i = 1; i < wristPositions.length - 1; i++)
      for (let j = 0; j < 2; j++)
        wristResidual.push(
          wristPositions[i][j].distanceTo(
            wristPositions[i - 1][j]
              .clone()
              .lerp(wristPositions[i + 1][j], 0.5),
          ) * 100,
        );
    rig.reset();
    model.updateMatrixWorld(true);
    const stats = (values) => ({
      p95: percentile(values),
      max: values.length ? Math.max(...values) : null,
    });
    return {
      torsoSkinRiskFrames: torsoFrames,
      forearmCapsuleRiskFrames: armFrames,
      handForearmRiskFrames: handArmFrames,
      deepestTorsoSkinCm: deepest * 100,
      minimumForearmCenterlineCm: minimumArm * 100,
      wristMidpointCm: stats(wristResidual),
      fingerMidpointDegrees: stats(fingerResidual),
      armMidpointDegrees: stats(armResidual),
      contract:
        "Actual hand skin sampled every eighth dominant-hand vertex vs rest-torso sectional convex hulls (6mm inset); forearm interior capsules 45mm separation; opposite forearm interior 18mm penetration. Conservative review risks, not semantic judgements or exact triangle-triangle certification.",
    };
  };
}
