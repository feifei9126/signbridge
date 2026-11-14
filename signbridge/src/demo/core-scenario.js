import { planCoreText } from "./core-plan.js";
export const DAILY_SCENARIO = Object.freeze({
  id: "daily-travel-v1",
  titleKey: "coreScenarioTitle",
  examples: Object.freeze([
    "我工作",
    "你开车",
    "我跑步",
    "你洗澡",
    "我回家",
    "你回家",
    "我没有帽子",
    "你没有袜子",
    "我没有大米",
    "你没有醋",
  ]),
  gaps: Object.freeze(["我们去医院", "今天我工作", "我帮你"]),
});
export function buildCoreScenario(manifest) {
  return {
    ...DAILY_SCENARIO,
    examples: DAILY_SCENARIO.examples.map((text) => ({
      text,
      plan: planCoreText(text, manifest),
    })),
    gaps: DAILY_SCENARIO.gaps.map((text) => ({
      text,
      plan: planCoreText(text, manifest),
    })),
    cslTranslationVerified: false,
    trainingStarted: false,
  };
}
export function corePlaybackStatus(
  plan,
  { ready = false, failed = false } = {},
) {
  if (failed) return { key: "coreInvalidAsset", args: {} };
  if (!ready) return { key: "demoLoading", args: {} };
  if (plan?.canPreview)
    return { key: "coreReadyToPlay", args: { count: plan.items.length } };
  if (plan?.blockers?.includes("directional_motion_missing"))
    return { key: "coreDirectionUnavailable", args: {} };
  if (plan?.gaps?.length)
    return {
      key: "coreGap",
      args: { words: [...new Set(plan.gaps.map((g) => g.surface))].join("、") },
    };
  return { key: "coreBlocked", args: {} };
}
