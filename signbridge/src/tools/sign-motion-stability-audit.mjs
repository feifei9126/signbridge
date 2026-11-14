import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import * as THREE from "three";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createT08Retarget } from "../demo/demo-retarget.js";
import {
  validateExperimentalIndex,
  validateExperimentalClip,
} from "../demo/experimental-motion.js";
import {
  validateT08Bundle,
  validateT08CandidateBundle,
} from "../demo/demo-motion.js";
import { MOTION_SMOOTHING_PROFILE } from "../demo/motion-stabilization.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const { values } = parseArgs({
  options: {
    assets: { type: "string", default: join(root, "dist/demo") },
    output: { type: "string" },
  },
});
if (!values.output || existsSync(values.output))
  throw new Error("Choose a new --output directory; preserve old evidence");
const assets = resolve(values.assets),
  output = resolve(values.output);
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const evidence = [];
for (const relative of [
  "src/demo/demo-retarget.js",
  "src/demo/motion-stabilization.js",
  "src/tools/sign-motion-stability-audit.mjs",
]) {
  const path = join(root, relative);
  evidence.push({ path, sha256: sha(readFileSync(path)) });
}
function json(path) {
  const bytes = readFileSync(path);
  evidence.push({ path, sha256: sha(bytes) });
  return JSON.parse(bytes.toString("utf8"));
}
function skeleton() {
  const path = join(root, "src/avatar/model.glb");
  const bytes = readFileSync(path);
  evidence.push({ path, sha256: sha(bytes) });
  // Read the glTF node hierarchy; the audit needs bone transforms, not textures.
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
  const result = new THREE.Object3D();
  gltf.scenes[gltf.scene || 0].nodes.forEach((i) => result.add(nodes[i]));
  result.updateMatrixWorld(true);
  return result;
}
function percentile(values, fraction = 0.95) {
  const sorted = values.toSorted((a, b) => a - b);
  return (
    sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))] ||
    0
  );
}
function measure(frames, rig, model) {
  const angular = [],
    wrists = [],
    positions = [],
    boxes = [new THREE.Box3(), new THREE.Box3()];
  for (let i = 0; i < frames.length; i++) {
    for (const q of Object.values(frames[i]))
      assert.ok(
        q.toArray().every(Number.isFinite) && Math.abs(q.length() - 1) < 1e-5,
      );
    rig.interpolate(frames[i], frames[i], 1);
    model.updateMatrixWorld(true);
    const current = ["leftHand", "rightHand"].map((name, side) => {
      const position = rig.bones[name].getWorldPosition(new THREE.Vector3());
      boxes[side].expandByPoint(position);
      return position;
    });
    positions.push(current);
    if (i > 0 && i < frames.length - 1)
      for (const name of Object.keys(frames[i])) {
        angular.push(
          (frames[i - 1][name]
            .clone()
            .normalize()
            .slerp(frames[i + 1][name].clone().normalize(), 0.5)
            .angleTo(frames[i][name].clone().normalize()) *
            180) /
            Math.PI,
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
    localQuaternionMidpointResidualP95Degrees: percentile(angular),
    wristMidpointResidualP95Cm: percentile(wrists),
    wristRangeCm: boxes.map(
      (box) => box.getSize(new THREE.Vector3()).length() * 100,
    ),
  };
}
const model = skeleton(),
  rig = createHumanoidRig(model),
  records = [];
const reference = validateT08Bundle(json(join(assets, "t08-motion.json")));
const candidates = validateT08CandidateBundle(
  json(join(assets, "t08-candidates.json")),
);
const index = validateExperimentalIndex(
  json(join(assets, "experimental-index.json")),
);
for (const [source, bundle] of [
  ["t08", reference],
  ["candidate", candidates],
  ["experimental", index],
]) {
  const retarget = createT08Retarget(rig, model, bundle);
  for (const entry of bundle.clips) {
    const clip =
      source === "experimental"
        ? validateExperimentalClip(json(join(assets, entry.asset)), entry)
        : entry;
    if (entry.asset)
      assert.equal(sha(readFileSync(join(assets, entry.asset))), entry.sha256);
    const raw = retarget.compile(clip, { stabilize: false }),
      display = retarget.compile(clip);
    assert.equal(raw.length, clip.frames);
    assert.equal(display.length, clip.frames);
    const deviations = [];
    for (let i = 0; i < raw.length; i++)
      for (const name of Object.keys(raw[i])) {
        const distance = raw[i][name]
          .clone()
          .normalize()
          .angleTo(display[i][name].clone().normalize());
        deviations.push((distance * 180) / Math.PI);
        if (i === 0 || i === raw.length - 1 || source !== "experimental")
          assert.ok(distance < 1e-6);
      }
    const before = measure(raw, rig, model),
      after = measure(display, rig, model);
    records.push({
      source,
      id: clip.id,
      text: clip.text,
      frames: clip.frames,
      fps: clip.fps,
      duration: clip.frames / clip.fps,
      before,
      after,
      poseDeviationP95Degrees: percentile(deviations),
      angularResidualRatio:
        after.localQuaternionMidpointResidualP95Degrees /
        before.localQuaternionMidpointResidualP95Degrees,
      wristResidualRatio:
        after.wristMidpointResidualP95Cm / before.wristMidpointResidualP95Cm,
      wristRangeRatio:
        after.wristRangeCm.reduce((a, b) => a + b, 0) /
        before.wristRangeCm.reduce((a, b) => a + b, 0),
    });
  }
}
for (const input of evidence)
  assert.equal(sha(readFileSync(input.path)), input.sha256);
const experimental = records.filter(
  (record) => record.source === "experimental",
);
for (const record of experimental) {
  assert.ok(
    record.angularResidualRatio < 0.6,
    `Insufficient high-frequency reduction: ${record.id}`,
  );
  assert.ok(
    record.wristRangeRatio > 0.5,
    `Gesture excursion collapsed: ${record.id}`,
  );
}
const mean = (values) =>
  values.reduce((sum, value) => sum + value, 0) / values.length;
const summary = {
  clips: experimental.length,
  meanAngularResidualBefore: mean(
    experimental.map((r) => r.before.localQuaternionMidpointResidualP95Degrees),
  ),
  meanAngularResidualAfter: mean(
    experimental.map((r) => r.after.localQuaternionMidpointResidualP95Degrees),
  ),
  meanWristResidualBeforeCm: mean(
    experimental.map((r) => r.before.wristMidpointResidualP95Cm),
  ),
  meanWristResidualAfterCm: mean(
    experimental.map((r) => r.after.wristMidpointResidualP95Cm),
  ),
  minimumWristRangeRatio: Math.min(
    ...experimental.map((r) => r.wristRangeRatio),
  ),
  maximumAngularResidualRatio: Math.max(
    ...experimental.map((r) => r.angularResidualRatio),
  ),
};
mkdirSync(output, { recursive: false });
writeFileSync(
  join(output, "report.json"),
  JSON.stringify(
    {
      schema: "signbridge-motion-stability-audit-v1",
      profile: MOTION_SMOOTHING_PROFILE,
      createdAt: new Date().toISOString(),
      sourceAssetsUnchanged: true,
      frameCountsAndTimingUnchanged: true,
      originalT08AndCandidatesUnchanged: true,
      trainingReady: false,
      semanticAccuracy: "not-assessed",
      limitations: [
        "Temporal smoothing is display postprocessing, not verified signing or corrected source detections.",
        "Fast meaningful movement can be softened; review against raw mode and original video.",
      ],
      summary,
      records,
      evidence,
    },
    null,
    2,
  ) + "\n",
);
console.log(JSON.stringify({ output, summary }, null, 2));
