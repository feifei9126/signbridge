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
      "demoInvalidExperimentalAsset",
      "demoSmoothing",
      "demoExperimentalSmoothedBadge",
      "demoExperimentalSmoothedWarningBadge",
      "demoExperimentalRawBadge",
    ])
      assert.ok(dictionary[key], key);
  }
});
