import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import * as THREE from "three";
import { createHumanoidRig } from "../avatar/humanoid-rig.js";
import { createT08Retarget } from "../demo/demo-retarget.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
export function percentile(values, fraction = 0.95) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[
    Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))
  ];
}
export function angularMetrics(frames) {
  const adjacent = [],
    residual = [],
    scores = [];
  for (let i = 0; i < frames.length; i++) {
    let worst = 0;
    for (const [name, q] of Object.entries(frames[i])) {
      assert.ok(
        q.toArray().every(Number.isFinite) && Math.abs(q.length() - 1) < 1e-5,
      );
      if (i > 0)
        adjacent.push((frames[i - 1][name].angleTo(q) * 180) / Math.PI);
      if (i > 0 && i < frames.length - 1) {
        const angle =
          (frames[i - 1][name]
            .clone()
            .slerp(frames[i + 1][name], 0.5)
            .angleTo(q) *
            180) /
          Math.PI;
        residual.push(angle);
        worst = Math.max(worst, angle);
      }
    }
    if (i > 0 && i < frames.length - 1)
      scores.push({ frame_1based: i + 1, residual_max_deg: worst });
  }
  return {
    adjacentP95Deg: percentile(adjacent),
    adjacentMaxDeg: adjacent.length ? Math.max(...adjacent) : null,
    residualP95Deg: percentile(residual),
    spikeFramesOver30Deg: scores
      .filter((x) => x.residual_max_deg > 30)
      .map((x) => x.frame_1based),
    worstFrames: scores
      .sort((a, b) => b.residual_max_deg - a.residual_max_deg)
      .slice(0, 5),
  };
}
function skeleton() {
  const bytes = readFileSync(join(root, "src/avatar/model.glb"));
  const gltf = JSON.parse(
    bytes
      .subarray(20, 20 + bytes.readUInt32LE(12))
      .toString("utf8")
      .replace(/\0+$/, ""),
  );
  const nodes = gltf.nodes.map((n) => {
    const bone = new THREE.Bone();
    bone.name = n.name || "";
    if (n.matrix)
      new THREE.Matrix4()
        .fromArray(n.matrix)
        .decompose(bone.position, bone.quaternion, bone.scale);
    else {
      if (n.translation) bone.position.fromArray(n.translation);
      if (n.rotation) bone.quaternion.fromArray(n.rotation);
      if (n.scale) bone.scale.fromArray(n.scale);
    }
    return bone;
  });
  gltf.nodes.forEach((n, i) =>
    n.children?.forEach((j) => nodes[i].add(nodes[j])),
  );
  const model = new THREE.Object3D();
  gltf.scenes[gltf.scene || 0].nodes.forEach((i) => model.add(nodes[i]));
  model.updateMatrixWorld(true);
  return model;
}
function measure(frames, rig, model) {
  const angular = angularMetrics(frames),
    positions = [],
    boxes = [new THREE.Box3(), new THREE.Box3()];
  for (const frame of frames) {
    rig.interpolate(frame, frame, 1);
    model.updateMatrixWorld(true);
    positions.push(
      ["leftHand", "rightHand"].map((name, side) => {
        const p = rig.bones[name].getWorldPosition(new THREE.Vector3());
        boxes[side].expandByPoint(p);
        return p;
      }),
    );
  }
  const residual = [],
    scores = [];
  for (let i = 1; i < positions.length - 1; i++) {
    const values = positions[i].map(
      (p, side) =>
        p.distanceTo(
          positions[i - 1][side].clone().lerp(positions[i + 1][side], 0.5),
        ) * 100,
    );
    residual.push(...values);
    scores.push({
      frame_1based: i + 1,
      wristResidualMaxCm: Math.max(...values),
    });
  }
  rig.reset();
  model.updateMatrixWorld(true);
  return {
    ...angular,
    wristResidualP95Cm: percentile(residual),
    wristRangeCm: boxes.map(
      (b) => b.getSize(new THREE.Vector3()).length() * 100,
    ),
    worstWristFrames: scores
      .sort((a, b) => b.wristResidualMaxCm - a.wristResidualMaxCm)
      .slice(0, 5),
  };
}
export function auditAvatar(report, output) {
  if (existsSync(output)) throw new Error("Use a new output directory");
  mkdirSync(output);
  const bytes = readFileSync(report),
    input = JSON.parse(bytes),
    model = skeleton(),
    rig = createHumanoidRig(model);
  const retarget = createT08Retarget(rig, model, input),
    records = [];
  for (const job of input.pose_jobs) {
    try {
      const bytes = readFileSync(job.asset),
        clip = JSON.parse(bytes);
      assert.equal(clip.poses.length, clip.frames);
      const raw = retarget.compile(clip, { stabilize: false }),
        smooth = retarget.compile(clip, { stabilize: true });
      const before = measure(raw, rig, model),
        after = measure(smooth, rig, model),
        deviations = [];
      for (let i = 0; i < raw.length; i++)
        for (const name of Object.keys(raw[i]))
          deviations.push(
            (raw[i][name].angleTo(smooth[i][name]) * 180) / Math.PI,
          );
      const used = job.default_smoothing ? after : before;
      const risk_flags = [];
      if (used.residualP95Deg > 10)
        risk_flags.push("avatar_angular_residual_p95_over_10deg");
      if (used.wristResidualP95Cm > 2)
        risk_flags.push("avatar_wrist_residual_p95_over_2cm");
      if (used.adjacentMaxDeg > 90)
        risk_flags.push("avatar_adjacent_rotation_over_90deg");
      records.push({
        ...job,
        text: clip.text,
        frames: clip.frames,
        fps: clip.fps,
        asset_sha256: sha(bytes),
        before,
        after,
        used,
        risk_flags,
        errors: [],
        poseDeviationP95Deg: percentile(deviations),
        wristRangeRatio:
          after.wristRangeCm.reduce((a, b) => a + b, 0) /
          before.wristRangeCm.reduce((a, b) => a + b, 0),
      });
    } catch (error) {
      records.push({ ...job, errors: [error.message], risk_flags: [] });
    }
    if (records.length % 20 === 0)
      console.log(
        JSON.stringify({ done: records.length, total: input.pose_jobs.length }),
      );
  }
  const dependencies = [
    "src/avatar/model.glb",
    "src/demo/demo-retarget.js",
    "src/demo/motion-stabilization.js",
    "src/avatar/humanoid-rig.js",
    "src/tools/sign-batch-avatar-audit.mjs",
  ];
  const result = {
    schema: "signbridge-six-batch-avatar-audit-v1",
    input_sha256: sha(bytes),
    records,
    dependencies: dependencies.map((name) => ({
      path: join(root, name),
      sha256: sha(readFileSync(join(root, name))),
    })),
    thresholdsAreTriageNotSignAccuracy: true,
    human_approved: false,
    training_ready: false,
    model_training_ready: false,
  };
  writeFileSync(
    join(output, "avatar-review.json"),
    JSON.stringify(result, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      records: records.length,
      errors: records.filter((r) => r.errors.length).length,
      runtimeRisks: records.filter(
        (r) => r.kind === "runtime" && r.risk_flags.length,
      ).length,
    }),
  );
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  const { values } = parseArgs({
    options: { report: { type: "string" }, output: { type: "string" } },
  });
  auditAvatar(resolve(values.report), resolve(values.output));
}
