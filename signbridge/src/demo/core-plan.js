// Bounded Chinese role parsing over source-bound core candidates. The planner
// never uses the authored dictionary or the whole-phrase research catalog.
const key = (value) =>
  String(value)
    .normalize("NFKC")
    .trim()
    .replace(/[。.!！]+$/u, "");
const unique = (values) => [...new Set(values)];
export function planCoreText(input, manifest) {
  const text = String(input),
    body = key(text),
    units = manifest?.units || [];
  const byText = new Map(units.map((u) => [key(u.text), u])),
    draft = [],
    issues = [],
    unknown = [];
  const meaning = {
    actor: null,
    predicate: null,
    patient: null,
    goal: null,
    time: null,
    negation: null,
    modality: null,
    question: null,
    degree: null,
    politeness: null,
  };
  const add = (surface, role, concept = surface) => {
    const unit = byText.get(key(surface));
    draft.push({
      id: unit?.id || null,
      surface,
      role,
      concept,
      source: unit ? "native" : null,
    });
    return { surface, kind: concept, concept };
  };
  const truncated = [...text].length > 500;
  if (truncated) issues.push("input_limit");
  if (!body) issues.push("empty_input");
  if (/[，,。.!！?？；;、]/u.test(body))
    issues.push("multiple_clauses_or_question");
  if (byText.has(body) && !issues.length) {
    const unit = byText.get(body);
    add(body, "unit", unit.key);
  } else if (["你好", "谢谢", "再见", "对不起"].includes(body) && !truncated) {
    add(body, "phrase");
  } else if (!truncated) {
    const participants = "我们|你们|他们|她们|他|她|我|你";
    const prefix = body.match(
      new RegExp(
        `^(今天|明天|昨天|现在)?(${participants})(今天|明天|昨天|现在)?(.*)$`,
        "u",
      ),
    );
    if (prefix) {
      const [, timeBefore, actor, timeAfter, tail] = prefix;
      if (timeBefore && timeAfter) issues.push("ambiguous_scope");
      if (timeBefore || timeAfter)
        meaning.time = add(timeBefore || timeAfter, "time");
      meaning.actor = add(
        actor,
        "actor",
        actor === "我" ? "speaker" : actor === "你" ? "addressee" : actor,
      );
      const absence = tail.match(/^(没有|有)(.+)$/u);
      const negated = tail.match(/^(不)?(工作|健康|放松|开车)$/u);
      const directional = tail.match(
        new RegExp(`^(帮助|帮)(${participants})$`, "u"),
      );
      const travel = tail.match(/^(去|来)(.*)$/u);
      if (absence) {
        const [, operator, object] = absence;
        if (operator === "没有")
          meaning.negation = add(operator, "negation", "absence");
        else add(operator, "predicate", "have");
        meaning.predicate = { surface: "有", concept: "have", kind: "have" };
        meaning.patient = add(object, "patient");
        if (["工作", "帮助", "开车", "放松"].includes(object))
          issues.push("ambiguous_scope");
      } else if (negated) {
        if (negated[1]) meaning.negation = add("不", "negation", "negation");
        meaning.predicate = add(
          negated[2],
          "predicate",
          byText.get(negated[2])?.key || negated[2],
        );
      } else if (directional) {
        meaning.predicate = add("帮助", "predicate", "help");
        meaning.patient = add(
          directional[2],
          "patient",
          directional[2] === "我"
            ? "speaker"
            : directional[2] === "你"
              ? "addressee"
              : directional[2],
        );
        issues.push("directional_motion_missing");
      } else if (travel) {
        meaning.predicate = add(
          travel[1],
          "predicate",
          travel[1] === "去" ? "go" : "come",
        );
        if (travel[2]) meaning.goal = add(travel[2], "goal");
      } else {
        issues.push("unsupported_predicate_structure");
        unknown.push({ surface: tail });
      }
    } else {
      add(body, "unknown");
      issues.push("unsupported_predicate_structure");
      unknown.push({ surface: body });
    }
  }
  const gaps = draft.filter((d) => !d.id);
  if (gaps.length) issues.push("motion_evidence_missing");
  if (unknown.length) issues.push("unknown_input");
  const blockers = unique(issues),
    canPreview = !blockers.length && draft.length > 0;
  const analysis = {
    schema: "signbridge-core-chinese-role-draft-v1",
    text,
    meaning,
    tokens: draft,
    unknown,
    issues: blockers,
    remainingText: truncated ? [...text].slice(500).join("") : "",
    parser: "bounded_core_chinese_rules_v1",
    meaningKey: JSON.stringify({
      meaning: Object.fromEntries(
        Object.entries(meaning).map(([k, v]) => [k, v?.concept || null]),
      ),
      issues: blockers,
    }),
    humanApproved: false,
    cslTranslationVerified: false,
    trainingReady: false,
  };
  return {
    schema: "signbridge-core-plan-v1",
    route: "core_candidate_plan",
    analysis,
    draft,
    gaps,
    blockers,
    warnings: ["candidate_label_unverified"],
    canPreview,
    items: canPreview
      ? draft.map((d) => ({
          id: d.id,
          source: "native",
          label: d.surface,
          matchedText: d.surface,
          semanticRole: d.role,
          concept: d.concept,
        }))
      : [],
    unmatched: canPreview ? "" : text,
    matchedCount: canPreview ? draft.length : 0,
    truncated,
    humanApproved: false,
    cslTranslationVerified: false,
    trainingReady: false,
    modelTrainingReady: false,
    authoredFallbackUsed: false,
    weightsUpdated: false,
  };
}
