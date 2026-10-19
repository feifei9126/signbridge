import test from "node:test";
import assert from "node:assert/strict";
import { analyzeCslText, planCslText } from "../src/demo/csl-semantic-plan.js";

const roles = (text) => analyzeCslText(text).meaning;
test("semantic roles change when actor and recipient are exchanged", () => {
  assert.equal(roles("我帮你").actor.surface, "我");
  assert.equal(roles("我帮你").patient.surface, "你");
  assert.equal(roles("你帮我").actor.surface, "你");
  assert.equal(roles("你帮我").patient.surface, "我");
  assert.notEqual(
    analyzeCslText("我帮你").meaningKey,
    analyzeCslText("你帮我").meaningKey,
  );
});
test("equivalent time placement produces the same explicit meaning", () => {
  assert.equal(
    analyzeCslText("我今天去").meaningKey,
    analyzeCslText("今天我去").meaningKey,
  );
  const result = planCslText("我今天去");
  assert.equal(result.route, "analysis_only");
  assert.equal(result.canPreview, false);
  assert.deepEqual(
    result.draft.map((x) => x.motionId),
    ["csl_today", "csl_me", "csl_go"],
  );
  assert.equal(result.humanApproved, false);
  assert.equal(result.cslTranslationVerified, false);
});
test("negation, desire, permission and obligation never collapse into one meaning", () => {
  assert.equal(roles("我不去").negation.kind, "negation");
  assert.equal(roles("我没去").negation.kind, "nonoccurrence");
  assert.equal(roles("我想去").modality.kind, "desire");
  assert.equal(roles("我必须去").modality.kind, "obligation");
  assert.equal(roles("我可以去").modality.kind, "permission_or_ability");
  assert.equal(
    new Set(
      ["我去", "我不去", "我没去", "我想去", "我必须去", "我可以去"].map(
        (s) => analyzeCslText(s).meaningKey,
      ),
    ).size,
    6,
  );
  assert.equal(planCslText("我没去").canPreview, false);
  assert.equal(planCslText("我必须去").canPreview, false);
});
test("question nonmanuals and directional agreement require evidence, not guessed poses", () => {
  assert.equal(roles("你去吗？").question.kind, "yes_no");
  assert.equal(planCslText("你去吗？").canPreview, false);
  assert.ok(
    planCslText("你去吗？").blockers.includes("nonmanual_question_unavailable"),
  );
  assert.ok(
    planCslText("我帮你").blockers.includes("spatial_agreement_unavailable"),
  );
});
test("unknown objects, time and lexical distinctions cannot be silently dropped", () => {
  for (const text of [
    "我明天去医院",
    "我喜欢你",
    "我去🚀",
    "我去了",
    "我不知道怎么去",
  ]) {
    const plan = planCslText(text);
    assert.equal(plan.canPreview, false, text);
    assert.equal(plan.items.length, 0, text);
    assert.ok(plan.blockers.length > 0, text);
  }
  assert.equal(roles("我明天去医院").time.surface, "明天");
  assert.equal(roles("我明天去医院").goal.surface, "医院");
  assert.notEqual(
    analyzeCslText("我喜欢你").meaningKey,
    analyzeCslText("我爱你").meaningKey,
  );
});
test("unsupported clauses, negation scope and voice are not confidently parsed", () => {
  for (const text of [
    "如果下雨，我不去",
    "我不是不去",
    "你被我帮助",
    "我去，你来",
    "我不想去",
    "我不能不去",
    "我和你去",
  ]) {
    assert.equal(planCslText(text).canPreview, false, text);
    assert.ok(analyzeCslText(text).issues.length > 0, text);
  }
});
test("whole-utterance evidence never authorizes semantic playback", () => {
  const clip = {
    id: "full",
    text: "我帮你",
    aliases: ["我帮你"],
    experimental: true,
  };
  const reference = planCslText("我帮你", [clip]);
  assert.equal(reference.route, "analysis_only");
  assert.equal(reference.canPreview, false);
  assert.equal(reference.referenceEvidence[0].experimental, true);
  assert.deepEqual(reference.items, []);
  assert.equal(reference.cslTranslationVerified, false);
  assert.equal(planCslText("你帮我", [clip]).canPreview, false);
  assert.equal(planCslText("我帮你🚀", [clip]).referenceEvidence.length, 0);
});
test("bounds retain the complete unsupported tail without HTML evaluation", () => {
  const plan = planCslText("我去" + "宇".repeat(510));
  assert.equal(plan.truncated, true);
  assert.equal(plan.canPreview, false);
  assert.ok(plan.unmatched.endsWith("宇".repeat(12)));
  assert.equal(planCslText("<script>alert(1)</script>").canPreview, false);
});

test("semantic reference matching never erases internal sentence boundaries", () => {
  const clip = {
    id: "help",
    text: "我帮你",
    aliases: ["我帮你"],
    experimental: true,
  };
  assert.equal(planCslText("我帮。你", [clip]).referenceEvidence.length, 0);
  assert.equal(planCslText("我，帮你", [clip]).referenceEvidence.length, 0);
  assert.equal(planCslText("我帮你！", [clip]).referenceEvidence.length, 1);
});
test("time or negation outside supported scope cannot become a confident composition", () => {
  for (const text of [
    "我去今天",
    "不我去",
    "我今天今天去",
    "我去哪里",
    "他去",
  ]) {
    assert.equal(planCslText(text).canPreview, false, text);
  }
});
test("question punctuation cannot retrieve a declarative motion as an equivalent", () => {
  const declarative = { id: "go", text: "我去", aliases: ["我去"] };
  assert.equal(
    planCslText("我去？", [declarative]).referenceEvidence.length,
    0,
  );
  assert.equal(
    planCslText("我去！", [declarative]).referenceEvidence.length,
    1,
  );
});
