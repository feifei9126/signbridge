import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import * as experimental from "../src/demo/experimental-motion.js";
import { planDemoText } from "../src/demo/demo-motion.js";
import { buildDemoPhraseCatalog } from "../src/demo/phrase-catalog.js";
import { LOCALES } from "../src/i18n/locales.js";

const metadata = {
  id: "source4-example",
  text: "认识你很高兴",
  aliases: ["认识你很高兴"],
  fps: 25,
  frames: 4,
  experimental: true,
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
};
const asset = {
  schema: "signbridge-experimental-clip-v1",
  ...metadata,
  poses: Array.from({ length: 4 }, () =>
    Array.from({ length: 55 }, () => [0, 0, 0]),
  ),
};
const bytes = JSON.stringify(asset);
const entry = {
  ...metadata,
  asset: "experimental/source4-example.json",
  sha256: createHash("sha256").update(bytes).digest("hex"),
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
  clips: [entry],
};
const approvalId = "motion-approval-user-declaration-v1";
const poseDigest = (poses) =>
  createHash("sha256")
    .update(
      poses
        .flat(2)
        .map((v) => String(Math.round(v * 1e6)))
        .join(","),
    )
    .digest("hex");
const approvedAsset = {
  ...asset,
  human_approved: true,
  motion_review_status: "approved_for_demo_motion",
  motion_approval_id: approvalId,
};
const approvedBytes = JSON.stringify(approvedAsset);
const approvedEntry = {
  ...entry,
  human_approved: true,
  motion_review_status: "approved_for_demo_motion",
  motion_approval_id: approvalId,
  sha256: createHash("sha256").update(approvedBytes).digest("hex"),
};
const approvalRecord = {
  schema: "signbridge-human-motion-approval-v1",
  id: approvalId,
  scope: "motion_quality_only",
  declaration: "验证过了，现候选的83条实验拟合动作已获人工批准",
  basis: "explicit_user_statement_in_current_conversation",
  captured_at_utc: "2026-10-20T00:00:00.000Z",
  source_index_sha256: "d".repeat(64),
  clips: [
    {
      id: entry.id,
      reviewed_asset_sha256: entry.sha256,
      source_sha256: entry.source_sha256,
      fitted_sha256: entry.fitted_sha256,
      poses_sha256: poseDigest(asset.poses),
    },
  ],
};
const approvalBytes = JSON.stringify(approvalRecord);
const approvedIndex = {
  ...index,
  motion_approval: {
    schema: "signbridge-human-motion-approval-ref-v1",
    id: approvalId,
    scope: "motion_quality_only",
    asset: "experimental/motion-approval.json",
    sha256: createHash("sha256").update(approvalBytes).digest("hex"),
  },
  clips: [approvedEntry],
};

test("experimental reconstruction routes separately from token-trained references", () => {
  assert.equal(
    planDemoText(metadata.text, "auto", [entry]).items[0].source,
    "experimental",
  );
  assert.equal(
    planDemoText(metadata.text, "t08", [entry]).items[0].source,
    "experimental",
  );
  assert.ok(
    planDemoText(metadata.text, "dictionary", [entry]).items.every(
      (i) => i.source === "dictionary",
    ),
  );
});

test("catalog deduplicates normalized text, preferring existing reference evidence", () => {
  const catalog = buildDemoPhraseCatalog([
    entry,
    { id: "reference", text: metadata.text + "！", aliases: [metadata.text] },
    { ...entry, id: "second", text: "我爱你" },
  ]);
  assert.equal(
    catalog.filter((c) => c.text.startsWith(metadata.text)).length,
    1,
  );
  assert.equal(catalog.find((c) => c.id === "reference").source, "t08");
  assert.equal(catalog.filter((c) => c.text === "我爱你").length, 1);
  assert.equal(catalog.find((c) => c.text === "我爱你").source, "experimental");
});

test("experimental contracts reject invented approvals, malformed frames and unsafe asset paths", () => {
  assert.equal(experimental.validateExperimentalIndex(index), index);
  assert.equal(experimental.validateExperimentalClip(asset, entry), asset);
  for (const change of [
    { training_ready: true },
    { human_approved: true },
    { asset: "../checkpoint.json" },
    { sha256: "bad" },
    { frames: 0 },
    { aliases: [123] },
    { source_sha256: "bad" },
    { display_stabilization_profile: "unregistered-profile" },
  ])
    assert.throws(() =>
      experimental.validateExperimentalIndex({
        ...index,
        clips: [{ ...entry, ...change }],
      }),
    );
  assert.throws(() =>
    experimental.validateExperimentalIndex({ ...index, clips: [entry, entry] }),
  );
  assert.throws(() =>
    experimental.validateExperimentalIndex({
      ...index,
      parents: Array(55).fill(55),
    }),
  );
  assert.throws(() =>
    experimental.validateExperimentalClip(
      { ...asset, poses: asset.poses.slice(1) },
      entry,
    ),
  );
  assert.throws(() =>
    experimental.validateExperimentalClip({ ...asset, text: "other" }, entry),
  );
  const broken = structuredClone(asset);
  broken.poses[0][0][0] = NaN;
  assert.throws(() => experimental.validateExperimentalClip(broken, entry));
});

test("motion approval requires a matching review record and keeps training gates closed", async () => {
  assert.equal(
    experimental.validateExperimentalIndex(approvedIndex),
    approvedIndex,
  );
  assert.equal(
    experimental.validateExperimentalClip(approvedAsset, approvedEntry),
    approvedAsset,
  );
  assert.equal(approvedIndex.training_ready, false);
  assert.equal(approvedIndex.model_training_ready, false);
  assert.equal(approvedEntry.training_data_member, false);
  assert.equal(approvedAsset.text_verified, undefined);

  const loader = experimental.createExperimentalLoader(
    approvedIndex,
    async (path) =>
      new Response(
        path === approvedIndex.motion_approval.asset
          ? approvalBytes
          : approvedBytes,
      ),
  );
  assert.equal((await loader.load(approvedEntry.id)).human_approved, true);

  assert.throws(() =>
    experimental.validateExperimentalIndex({
      ...index,
      clips: [
        {
          ...entry,
          human_approved: true,
          motion_review_status: "approved_for_demo_motion",
          motion_approval_id: approvalId,
        },
      ],
    }),
  );

  const mismatchedApproval = {
    ...approvalRecord,
    clips: [{ ...approvalRecord.clips[0], fitted_sha256: "e".repeat(64) }],
  };
  const mismatchBytes = JSON.stringify(mismatchedApproval);
  const mismatchIndex = {
    ...approvedIndex,
    motion_approval: {
      ...approvedIndex.motion_approval,
      sha256: createHash("sha256").update(mismatchBytes).digest("hex"),
    },
  };
  const mismatchLoader = experimental.createExperimentalLoader(
    mismatchIndex,
    async (path) =>
      new Response(
        path === mismatchIndex.motion_approval.asset
          ? mismatchBytes
          : approvedBytes,
      ),
  );
  await assert.rejects(mismatchLoader.load(approvedEntry.id));
});

test("approved fitted motion cannot change after its pose digest was reviewed", async () => {
  const changed = structuredClone(approvedAsset);
  changed.poses[0][0][0] = 0.2;
  const changedBytes = JSON.stringify(changed);
  const changedIndex = {
    ...approvedIndex,
    clips: [
      {
        ...approvedEntry,
        sha256: createHash("sha256").update(changedBytes).digest("hex"),
      },
    ],
  };
  const loader = experimental.createExperimentalLoader(
    changedIndex,
    async (path) =>
      new Response(
        path === changedIndex.motion_approval.asset
          ? approvalBytes
          : changedBytes,
      ),
  );
  await assert.rejects(loader.load(approvedEntry.id));
});

test("experimental clips bind an allowlisted display recovery profile", () => {
  const recovery = {
    ...entry,
    display_stabilization_profile: "quaternion-temporal-recovery-v1",
  };
  const recovered = {
    ...asset,
    ...recovery,
    poses: asset.poses,
  };
  assert.equal(
    experimental.validateExperimentalIndex({ ...index, clips: [recovery] })
      .clips[0],
    recovery,
  );
  assert.equal(
    experimental.validateExperimentalClip(recovered, recovery),
    recovered,
  );
  assert.throws(() => experimental.validateExperimentalClip(recovered, entry));
});

test("source-6 preview labels and provenance cannot be promoted or stripped", () => {
  const preview = {
    ...entry,
    source_batch: "source-6",
    preview_only: true,
    text_verified: "",
    semantics_approved: false,
    boundaries_approved: false,
    temporal_interpolation: false,
    source_annotation_id: "source6-example",
    source_clip_sha256: "d".repeat(64),
    source_frames_sha256: "e".repeat(64),
    source_fit_manifest_sha256: "f".repeat(64),
    boundary_review_flags: ["near_source_end"],
  };
  const clip = { ...asset, ...preview };
  assert.equal(
    experimental.validateExperimentalIndex({ ...index, clips: [preview] })
      .clips[0],
    preview,
  );
  assert.equal(experimental.validateExperimentalClip(clip, preview), clip);
  for (const change of [
    { text_verified: metadata.text },
    { semantics_approved: true },
    { boundaries_approved: true },
    { preview_only: false },
    { temporal_interpolation: true },
    { source_frames_sha256: "bad" },
  ]) {
    assert.throws(() =>
      experimental.validateExperimentalIndex({
        ...index,
        clips: [{ ...preview, ...change }],
      }),
    );
    assert.throws(() =>
      experimental.validateExperimentalClip({ ...clip, ...change }, preview),
    );
  }
  const stripped = { ...clip };
  delete stripped.source_batch;
  delete stripped.preview_only;
  assert.throws(() => experimental.validateExperimentalClip(stripped, preview));
});

test("a separate source-6 preview starts with its real clip and preserves typed input", () => {
  assert.equal(typeof experimental.experimentalPreviewSample, "function");
  const clips = [{ text: "新视频动作", preview_only: true }];
  assert.equal(
    experimental.experimentalPreviewSample(clips, "旧示例", "旧示例"),
    "新视频动作",
  );
  assert.equal(
    experimental.experimentalPreviewSample(clips, "正在输入的内容", "旧示例"),
    "正在输入的内容",
  );
  assert.equal(
    experimental.experimentalPreviewSample([metadata], "旧示例", "旧示例"),
    "旧示例",
  );
  assert.equal(
    experimental.experimentalPreviewSample([], "旧示例", "旧示例"),
    "旧示例",
  );
});

test("lazy loader checks digest, retries failures and bounds its cache", async () => {
  let calls = 0;
  const loader = experimental.createExperimentalLoader(index, async () => {
    calls++;
    return new Response(calls === 1 ? bytes + " " : bytes);
  });
  await assert.rejects(loader.load(entry.id));
  assert.equal((await loader.load(entry.id)).id, entry.id);
  await loader.load(entry.id);
  assert.equal(calls, 2);
  loader.clear();
  await loader.load(entry.id);
  assert.equal(calls, 3);
  await assert.rejects(loader.load("missing"));
});

test("lazy loader shares concurrent requests and evicts old pose arrays", async () => {
  let calls = 0;
  const clips = Array.from({ length: 8 }, (_, i) => {
    const clip = { ...asset, id: `clip-${i}` };
    const body = JSON.stringify(clip);
    return {
      ...entry,
      id: clip.id,
      asset: `experimental/${clip.id}.json`,
      sha256: createHash("sha256").update(body).digest("hex"),
      body,
    };
  });
  const loader = experimental.createExperimentalLoader(
    { ...index, clips },
    async (path) => {
      calls++;
      return new Response(clips.find((c) => c.asset === path).body);
    },
  );
  await Promise.all([loader.load("clip-0"), loader.load("clip-0")]);
  assert.equal(calls, 1);
  for (const clip of clips.slice(1)) await loader.load(clip.id);
  assert.equal(calls, 8);
  await loader.load("clip-0");
  assert.equal(calls, 9);
});

test("experimental source labels exist in every supported locale", () => {
  for (const dictionary of Object.values(LOCALES)) {
    for (const key of [
      "demoExperimental",
      "demoExperimentalBadge",
      "demoExperimentalWarningBadge",
      "demoExperimentalToken",
      "demoExperimentalWarning",
      "demoExperimentalApprovedWarning",
      "demoExperimentalMixedWarning",
      "demoExperimentalPreviewWarning",
      "demoInvalidExperimentalAsset",
      "demoSmoothing",
      "demoExperimentalSmoothedBadge",
      "demoExperimentalSmoothedWarningBadge",
      "demoExperimentalRawBadge",
    ])
      assert.ok(dictionary[key], key);
  }
});
