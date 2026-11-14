import test from "node:test";
import assert from "node:assert/strict";
import * as scenario from "../src/demo/core-scenario.js";
const { buildCoreScenario } = scenario;
const labels = [
  "我",
  "你",
  "工作",
  "开车",
  "跑步",
  "洗澡",
  "回家",
  "听",
  "没有",
  "围巾",
  "帽子",
  "袜子",
  "大米",
  "醋",
];
const manifest = {
  units: labels.map((text, i) => ({
    id: "native_core_" + i,
    text,
    key: "test" + i,
  })),
};
test("frozen daily scenario accepts every intended display and keeps gaps unplayable", () => {
  const r = buildCoreScenario(manifest);
  assert.equal(r.examples.length, 10);
  assert.ok(r.examples.every((c) => c.plan.canPreview));
  assert.equal(r.gaps.length, 3);
  assert.ok(r.gaps.every((c) => !c.plan.canPreview));
  assert.ok(
    r.examples.every((c) => c.plan.items.every((i) => i.source === "native")),
  );
});
test("scenario catalog cannot pretend missing assets are available", () => {
  const r = buildCoreScenario({ units: [] });
  assert.ok(r.examples.every((c) => !c.plan.canPreview));
});
test("blocked direction and missing assets never present a ready-to-play status", () => {
  const s = buildCoreScenario(manifest);
  assert.equal(typeof scenario.corePlaybackStatus, "function");
  const ready = { ready: true };
  assert.equal(
    scenario.corePlaybackStatus(s.gaps[2].plan, ready).key,
    "coreDirectionUnavailable",
  );
  assert.equal(
    scenario.corePlaybackStatus(s.gaps[0].plan, ready).key,
    "coreGap",
  );
  assert.equal(
    scenario.corePlaybackStatus(s.examples[0].plan, ready).key,
    "coreReadyToPlay",
  );
  assert.equal(
    scenario.corePlaybackStatus(s.gaps[2].plan, { ready: false }).key,
    "demoLoading",
  );
  assert.equal(
    scenario.corePlaybackStatus(s.examples[0].plan, {
      ready: true,
      failed: true,
    }).key,
    "coreInvalidAsset",
  );
});
