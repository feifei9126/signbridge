import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import * as THREE from "three";
import { createHumanoidRig } from "../src/avatar/humanoid-rig.js";
import {
  createT08Retarget,
  sourceWorldRotations,
} from "../src/demo/demo-retarget.js";
import {
  validateT08Bundle,
  validateT08CandidateBundle,
  planDemoText,
} from "../src/demo/demo-motion.js";

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
const candidateAsset = new URL(
  "../../local-data/demo-20261012/t08-candidates.json",
  import.meta.url,
);
const candidateBundle = existsSync(candidateAsset)
  ? validateT08CandidateBundle(JSON.parse(readFileSync(candidateAsset, "utf8")))
  : null;

test(
  "three candidate sequences retarget finite unit quaternions without changing their review status",
  { skip: !candidateBundle },
  () => {
    const root = skeletonFromGlb();
    const rig = createHumanoidRig(root);
    const retarget = createT08Retarget(rig, root, candidateBundle);
    for (const clip of candidateBundle.clips) {
      assert.equal(clip.runtime_candidate, true);
      assert.equal(clip.training_ready, false);
      const tracks = retarget.compile(clip);
      assert.equal(tracks.length, clip.frames);
      for (const frame of tracks)
        for (const q of Object.values(frame)) {
          assert.ok(q.toArray().every(Number.isFinite));
          assert.ok(Math.abs(q.length() - 1) < 1e-5);
        }
    }
  },
);

test(
  "recovery profile asset selects stronger display filtering without changing source poses",
  { skip: !candidateBundle },
  async () => {
    const module = await import("../src/demo/motion-stabilization.js");
    const experimental = await import("../src/demo/experimental-motion.js");
    const recovery = {
      id: "recovery-fixture",
      text: "测试",
      aliases: ["测试"],
      fps: 25,
      frames: 4,
      experimental: true,
      display_stabilization_profile: "quaternion-temporal-recovery-v1",
      model_output: "smplx_fit_demo",
      training_data_member: false,
      training_ready: false,
      model_training_ready: false,
      human_approved: false,
      motion_review_status: "needs_review",
      mirror_status: "unknown",
      signer_id: "unconfirmed",
      source_sha256: "a".repeat(64),
      feature_sha256: "b".repeat(64),
      fitted_sha256: "c".repeat(64),
      quality_warning: false,
      asset: "experimental/recovery-fixture.json",
      sha256: "d".repeat(64),
    };
    const index = {
      schema: "signbridge-experimental-motion-index-v1",
      representation: "effective-smplx-55-axis-angle",
      smplx_rest_model_sha256:
        "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992",
      training_weights_updated: false,
      text_to_sign_trained: false,
      training_ready: false,
      model_training_ready: false,
      research_only: true,
      restJoints: Array.from({ length: 55 }, () => [0, 0, 0]),
      parents: [-1, ...Array.from({ length: 54 }, (_, i) => i)],
      clips: [recovery],
    };
    assert.equal(
      experimental.validateExperimentalIndex(index).clips[0],
      recovery,
    );
    const source = Array.from({ length: 100 }, (_, i) => ({
      arm: new THREE.Quaternion().setFromAxisAngle(
        new THREE.Vector3(0, 1, 0),
        i * 0.004 + (i % 2 ? 0.12 : -0.12),
      ),
    }));
    const saved = source.map((frame) => frame.arm.toArray());
    const raw = module.stabilizeQuaternionTrack(
      source,
      25,
      module.MOTION_SMOOTHING_PROFILE,
    );
    const display = module.stabilizeQuaternionTrack(
      source,
      25,
      recovery.display_stabilization_profile,
    );
    const amount = (track) =>
      track.slice(1, -1).reduce(
        (sum, frame, i) =>
          sum +
          track[i].arm
            .clone()
            .slerp(track[i + 2].arm, 0.5)
            .angleTo(frame.arm),
        0,
      );
    assert.ok(amount(display) < amount(raw) * 0.8);
    assert.deepEqual(
      source.map((frame) => frame.arm.toArray()),
      saved,
    );
  },
);

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

test(
  "lazy retarget calibration uses REST even after dictionary playback",
  { skip: !bundle },
  () => {
    const root = skeletonFromGlb(),
      rig = createHumanoidRig(root);
    const pose = { poses: [bundle.clips[2].poses[60]] };
    const expected = createT08Retarget(rig, root, bundle).compile(pose)[0];
    const raised = rig.createTargets({
      leftUpperArm: { x: 1, y: 0.3, z: 0.5 },
      rightLowerArm: { x: 0.7, y: 0.3, z: 0 },
    });
    rig.interpolate(raised, raised, 1);
    const playingPose = rig.capture();
    const retarget = createT08Retarget(rig, root, bundle);
    for (const [name, value] of Object.entries(playingPose))
      assert.deepEqual(
        rig.bones[name].quaternion.toArray(),
        value.toArray(),
        `calibration must preserve playing pose: ${name}`,
      );
    const actual = retarget.compile(pose)[0];
    for (const [name, value] of Object.entries(playingPose))
      assert.deepEqual(
        rig.bones[name].quaternion.toArray(),
        value.toArray(),
        `compilation must preserve playing pose: ${name}`,
      );
    for (const name of Object.keys(expected))
      assert.ok(
        actual[name]
          .clone()
          .normalize()
          .angleTo(expected[name].clone().normalize()) < 1e-6,
        `calibration drift after dictionary playback: ${name}`,
      );
  },
);

test(
  "experimental clips are stabilized by default while raw and T08 tracks remain available",
  { skip: !bundle },
  () => {
    const root = skeletonFromGlb(),
      rig = createHumanoidRig(root);
    const retarget = createT08Retarget(rig, root, bundle);
    const clip = {
      experimental: true,
      fps: 25,
      poses: Array.from({ length: 40 }, (_, i) => {
        const pose = Array.from({ length: 55 }, () => [0, 0, 0]);
        pose[18] = [0, 0, i * 0.003 + (i % 2 ? 0.12 : -0.12)];
        return pose;
      }),
    };
    const raw = retarget.compile(clip, { stabilize: false });
    const filtered = retarget.compile(clip);
    const energy = (frames) =>
      frames.slice(1, -1).reduce(
        (sum, f, i) =>
          sum +
          frames[i].leftLowerArm
            .clone()
            .slerp(frames[i + 2].leftLowerArm, 0.5)
            .angleTo(f.leftLowerArm),
        0,
      );
    assert.ok(energy(filtered) < energy(raw) * 0.2);
    const reference = retarget.compile({ ...clip, experimental: false });
    for (let i = 0; i < raw.length; i++)
      assert.deepEqual(
        reference[i].leftLowerArm.toArray(),
        raw[i].leftLowerArm.toArray(),
      );
  },
);
