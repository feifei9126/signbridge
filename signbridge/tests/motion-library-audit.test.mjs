import test from "node:test";
import assert from "node:assert/strict";
import {
  analyzeMotionClip,
  buildMotionLibrary,
} from "../src/tools/motion-library-audit.mjs";
import { readPublicMotionAssets } from "../scripts/public-motion-assets.mjs";

const pose = (angle) =>
  Array.from({ length: 55 }, (_, joint) =>
    joint === 20 ? [0, angle, 0] : [0, 0, 0],
  );

test("motion audit rejects non-finite and incomplete pose tracks", () => {
  const clip = {
    id: "invalid",
    text: "测试",
    aliases: ["测试"],
    fps: 25,
    frames: 3,
    poses: [pose(0), pose(0.1), [[0, 0, 0]]],
  };
  const report = analyzeMotionClip(clip, "experimental");
  assert.equal(report.metrics.finite, false);
  assert.equal(report.stability, "reject");
  assert.ok(report.issues.includes("incomplete_pose"));
});

test("motion audit identifies a bounded isolated spike without mutating poses", () => {
  const poses = [pose(0), pose(0.01), pose(2.5), pose(0.02), pose(0.03)];
  const before = JSON.stringify(poses);
  const report = analyzeMotionClip(
    {
      id: "spike",
      text: "测试",
      aliases: ["测试"],
      fps: 25,
      frames: poses.length,
      poses,
    },
    "experimental",
  );
  assert.equal(JSON.stringify(poses), before);
  assert.equal(report.metrics.finite, true);
  assert.ok(report.metrics.isolated_spike_count >= 1);
  assert.equal(report.stability, "needs_review");
});

test("public motion library contains 14 references, 3 candidates and 83 approved fits", () => {
  const assets = readPublicMotionAssets();
  const library = buildMotionLibrary({
    motion: assets.motion,
    candidates: assets.candidates,
    experimental: assets.experimental,
    experimentalFiles: assets.fileBytes.experimental,
  });
  assert.equal(library.schema, "signbridge-motion-library-v2");
  assert.equal(library.entries.length, 100);
  assert.deepEqual(library.summary.bySource, {
    t08: 14,
    candidate: 3,
    experimental: 83,
  });
  assert.equal(new Set(library.entries.map((entry) => entry.id)).size, 100);
  assert.ok(
    library.entries.every((entry) => entry.semantic_status === "unverified"),
  );
  assert.ok(library.entries.every((entry) => entry.training_ready === false));
  assert.ok(
    library.entries.every((entry) => entry.model_training_ready === false),
  );
  assert.ok(library.entries.every((entry) => entry.metrics.frame_count > 1));
});

test("motion audit uses shortest rotation arcs for repeated equivalent poses", () => {
  const frames = Array.from({ length: 3 }, () =>
    Array.from({ length: 55 }, () => [0, 0, 0]),
  );
  frames[0][20] = [0, 0.4, 0];
  frames[1][20] = [0, 0.4, 0];
  frames[2][20] = [0, 0.4, 0];
  const report = analyzeMotionClip(
    {
      id: "quaternion-sign",
      text: "测试",
      aliases: ["测试"],
      fps: 25,
      frames: frames.length,
      poses: frames,
    },
    "experimental",
  );
  assert.ok(report.metrics.max_adjacent_rotation_degrees < 1e-6);
});
