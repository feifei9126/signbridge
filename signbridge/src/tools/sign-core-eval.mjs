import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { parseArgs } from "node:util";
import { planCoreText } from "../demo/core-plan.js";
export function evaluateCoreCases(manifest, fixture) {
  const cases = [
    ...fixture.cases,
    ...manifest.units.map((unit) => ({
      text: unit.text,
      play: true,
      units: [unit.key],
    })),
  ];
  const records = cases.map((test) => {
    const p = planCoreText(test.text, manifest),
      failures = [];
    if (p.canPreview !== test.play) failures.push("playback_decision");
    if (
      test.play &&
      JSON.stringify(
        p.items.map((i) => manifest.units.find((u) => u.id === i.id)?.key),
      ) !== JSON.stringify(test.units)
    )
      failures.push("unit_sequence");
    for (const role of ["actor", "predicate", "patient"])
      if (test[role] && p.analysis.meaning[role]?.surface !== test[role])
        failures.push("role_" + role);
    if (test.gap && !p.gaps.some((g) => g.surface === test.gap))
      failures.push("missing_gap");
    if (test.blocker && !p.blockers.includes(test.blocker))
      failures.push("missing_blocker");
    if (!test.play && (p.items.length !== 0 || p.unmatched !== test.text))
      failures.push("refusal_or_input_loss");
    if (p.authoredFallbackUsed !== false || p.cslTranslationVerified !== false)
      failures.push("source_or_approval_promotion");
    return { test, passed: failures.length === 0, failures, plan: p };
  });
  return {
    schema: "signbridge-core-sentence-eval-v1",
    scope: fixture.supervision,
    summary: {
      cases: records.length,
      passed: records.filter((r) => r.passed).length,
      failed: records.filter((r) => !r.passed).length,
      expectedPlayable: records.filter((r) => r.test.play).length,
      expectedRefusals: records.filter((r) => !r.test.play).length,
      unexpectedAcceptance: records.filter(
        (r) => !r.test.play && r.plan.canPreview,
      ).length,
      incorrectRefusal: records.filter((r) => r.test.play && !r.plan.canPreview)
        .length,
    },
    records,
    cslAccuracy: "not_assessed",
    heldOutGeneralization: "not_assessed_fixed_development_contract",
    human_approved: false,
    training_started: false,
  };
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const { values } = parseArgs({
    options: {
      manifest: { type: "string" },
      output: { type: "string" },
      fixture: { type: "string" },
    },
  });
  if (!values.manifest || !values.output || existsSync(values.output))
    throw new Error("Provide manifest and NEW output JSON");
  const bytes = readFileSync(values.manifest),
    fixtureBytes = readFileSync(
      values.fixture ||
        new URL("../../tests/fixtures/core-sentence-v1.json", import.meta.url),
    );
  const r = evaluateCoreCases(JSON.parse(bytes), JSON.parse(fixtureBytes));
  r.manifest_sha256 = createHash("sha256").update(bytes).digest("hex");
  r.fixture_sha256 = createHash("sha256").update(fixtureBytes).digest("hex");
  writeFileSync(values.output, JSON.stringify(r, null, 2) + "\n");
  console.log(JSON.stringify(r.summary));
  process.exitCode = r.summary.failed ? 2 : 0;
}
