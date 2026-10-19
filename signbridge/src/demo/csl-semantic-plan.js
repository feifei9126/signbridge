// Bounded Chinese meaning analysis and an explicitly unverified CSL display draft.
// No rule below is a claim about universal CSL word order or language fluency.
const definitions = [];
function words(kind, concept, surfaces, motionId = null) {
  for (const surface of surfaces)
    definitions.push({ kind, concept, surface, motionId });
}
for (const [concept, surfaces, motion] of [
  ["speaker", ["我"], "csl_me"],
  ["addressee", ["你", "您"], "csl_you"],
  ["speaker_group", ["我们", "咱们"], "csl_we"],
  ["male_third", ["他"], "csl_he"],
  ["female_third", ["她"], "csl_he"],
])
  words("person", concept, surfaces, motion);
for (const [concept, surfaces, motion] of [
  ["today", ["今天", "今日"], "csl_today"],
  ["tomorrow", ["明天", "明日"], null],
  ["yesterday", ["昨天", "昨日"], null],
  ["now", ["现在"], "csl_now"],
])
  words("time", concept, surfaces, motion);
for (const [concept, surfaces, motion] of [
  ["go", ["去"], "csl_go"],
  ["come", ["来"], "csl_come"],
  ["help", ["帮助", "帮"], "csl_help"],
  ["love", ["爱"], "csl_love"],
  ["like", ["喜欢"], null],
  ["know", ["知道"], "csl_know"],
  ["be_acquainted", ["认识"], null],
  ["happy", ["开心", "高兴"], "csl_happy"],
  ["see", ["看"], "csl_see"],
  ["do", ["做"], "csl_do"],
  ["have", ["有"], "csl_have"],
])
  words("predicate", concept, surfaces, motion);
words("negation", "negation", ["不"], "csl_no");
words("negation", "nonoccurrence", ["没", "没有"]);
words("negation", "prohibition", ["别", "不要"]);
words("modal", "desire", ["想"], "csl_want");
words("modal", "obligation", ["必须", "应该"]);
words("modal", "ability", ["能", "能够"]);
words("modal", "permission_or_ability", ["可以"]);
words("modal", "want_or_obligation", ["要"]);
words("degree", "high", ["很", "非常"], "csl_very");
words("question", "yes_no", ["吗", "么", "是否"]);
words("question", "location", ["哪里", "哪儿"]);
words("question", "person", ["谁"]);
words("question", "object", ["什么", "啥"]);
words("question", "manner", ["怎么", "怎样"]);
for (const surface of ["医院", "学校", "家", "公园", "图书馆", "北京"])
  words("location", surface, [surface]);
for (const surface of ["书", "水", "工作", "朋友"])
  words("object", surface, [surface]);
words("politeness", "request", ["请"], "csl_please");
definitions.sort((a, b) => b.surface.length - a.surface.length);
const punctuation = /[\s，,。.!！?？；;、]/u;
const unique = (values) => [...new Set(values)];
function tokenize(input) {
  const chars = [...input],
    tokens = [],
    unknown = [];
  for (let i = 0; i < chars.length;) {
    if (punctuation.test(chars[i])) {
      i++;
      continue;
    }
    const token = definitions.find((d) =>
      chars.slice(i).join("").startsWith(d.surface),
    );
    if (token) {
      const end = i + [...token.surface].length;
      tokens.push({ ...token, start: i, end });
      i = end;
    } else {
      unknown.push({ surface: chars[i], start: i, end: i + 1 });
      i++;
    }
  }
  return { tokens, unknown };
}
export function analyzeCslText(input) {
  const full = String(input).normalize("NFKC"),
    chars = [...full];
  const text = chars.slice(0, 500).join("");
  const { tokens, unknown } = tokenize(text),
    issues = [];
  const get = (kind) => tokens.filter((t) => t.kind === kind);
  const predicates = get("predicate"),
    people = get("person"),
    times = get("time");
  const negations = get("negation"),
    modals = get("modal"),
    questions = get("question");
  const predicate = predicates.length === 1 ? predicates[0] : null;
  if (!text.trim()) issues.push("empty_input");
  if (unknown.length) issues.push("unknown_input");
  if (predicates.length !== 1) issues.push("unsupported_predicate_structure");
  if (
    times.length > 1 ||
    modals.length > 1 ||
    negations.length > 1 ||
    questions.length > 1
  )
    issues.push("ambiguous_scope");
  const actor = predicate ? people.find((p) => p.end <= predicate.start) : null;
  const afterPeople = predicate
    ? people.filter((p) => p.start >= predicate.end)
    : [];
  const patient = afterPeople[0] || get("object")[0] || null;
  const goal = ["go", "come"].includes(predicate?.concept)
    ? get("location")[0] || null
    : null;
  if (!actor) issues.push("actor_unresolved");
  if (
    people.filter((p) => p.end <= (predicate?.start ?? 0)).length > 1 ||
    afterPeople.length > 1
  )
    issues.push("ambiguous_participants");
  if (negations[0] && modals[0] && negations[0].start < modals[0].start)
    issues.push("ambiguous_scope");
  if (questions.length && questions[0].concept !== "yes_no")
    issues.push("question_role_unresolved");
  if (
    predicate &&
    ((negations[0]?.start ?? -1) > predicate.start ||
      (modals[0]?.start ?? -1) > predicate.start)
  )
    issues.push("unsupported_operator_order");
  if (
    predicate &&
    (patient || get("location").length) &&
    ![
      "go",
      "come",
      "help",
      "love",
      "like",
      "know",
      "be_acquainted",
      "see",
      "do",
      "have",
    ].includes(predicate.concept)
  )
    issues.push("unsupported_predicate_arguments");
  if (["go", "come"].includes(predicate?.concept) && patient)
    issues.push("goal_unresolved");
  if (get("location").length && !goal) issues.push("goal_unresolved");
  if (predicate && times[0]?.start >= predicate.end)
    issues.push("unsupported_operator_order");
  if (
    actor &&
    ((negations[0]?.start ?? Infinity) < actor.start ||
      (modals[0]?.start ?? Infinity) < actor.start)
  )
    issues.push("unsupported_operator_order");
  // No multi-clause punctuation may be swallowed to create a one-clause meaning.
  if (
    /[，,。.!！?？；;、].*\S/u.test(
      text.replace(/[，,。.!！?？；;、]+\s*$/u, ""),
    )
  )
    issues.push("multiple_clauses");
  const selected = [
    actor,
    times[0],
    predicate,
    patient,
    goal,
    negations[0],
    modals[0],
    questions[0],
    get("degree")[0],
    get("politeness")[0],
  ].filter(Boolean);
  if (selected.length !== tokens.length) issues.push("unassigned_meaning");
  if (get("degree").length && predicate?.concept !== "happy")
    issues.push("unsupported_degree_scope");
  const field = (token) => (token ? { ...token, kind: token.concept } : null);
  const meaning = {
    actor: actor || null,
    predicate,
    patient,
    goal,
    time: times[0] || null,
    negation: field(negations[0]),
    modality: field(modals[0]),
    question: questions[0]
      ? field(questions[0])
      : /[?？]/u.test(text)
        ? { kind: "unspecified", surface: "?" }
        : null,
    degree: get("degree")[0] || null,
    politeness: get("politeness")[0] || null,
  };
  const key = Object.entries(meaning).map(([role, value]) => [
    role,
    value?.concept || value?.kind || null,
  ]);
  return {
    schema: "signbridge-csl-meaning-draft-v1",
    text,
    meaning,
    meaningKey: JSON.stringify({
      slots: key,
      unknown: unknown.map((u) => u.surface).join(""),
      issues: unique(issues),
    }),
    tokens,
    unknown,
    issues: unique(issues),
    truncated: chars.length > 500,
    remainingText: chars.slice(500).join(""),
    parser: "bounded_chinese_rules_v1",
    targetLanguage: "CSL",
    humanApproved: false,
    cslTranslationVerified: false,
    trainingReady: false,
  };
}
const referenceKey = (text) =>
  String(text)
    .normalize("NFKC")
    .replace(/\s/gu, "")
    .replace(/[.!?。！？，]+$/u, "")
    .toLowerCase();
export function planCslText(input, clips = []) {
  const analysis = analyzeCslText(input),
    m = analysis.meaning;
  const key = referenceKey(analysis.text);
  const questionMarked = /[?？]/u.test(analysis.text);
  const referenceEvidence =
    !analysis.truncated && !questionMarked && key
      ? clips
          .filter((c) =>
            [c.text, ...(c.aliases || [])].some(
              (alias) => referenceKey(alias) === key,
            ),
          )
          .map((c) => ({
            id: c.id,
            text: c.text,
            experimental: c.experimental === true,
            humanApproved: c.human_approved === true,
          }))
      : [];
  const draft = [
    m.time,
    m.politeness,
    m.actor,
    m.modality,
    m.negation,
    m.degree,
    m.predicate,
    m.patient,
    m.goal,
    m.question,
  ]
    .filter(Boolean)
    .map((slot) => ({
      surface: slot.surface,
      concept: slot.concept || slot.kind,
      motionId: slot.motionId || null,
      start: slot.start ?? null,
      end: slot.end ?? null,
    }));
  const blockers = [...analysis.issues];
  const gaps = draft.filter((s) => !s.motionId);
  if (gaps.length) blockers.push("motion_evidence_missing");
  if (m.question) blockers.push("nonmanual_question_unavailable");
  if (m.predicate?.concept === "help" && m.patient)
    blockers.push("spatial_agreement_unavailable");
  if (
    [m.actor, m.patient].some(
      (p) => p && ["male_third", "female_third"].includes(p.concept),
    )
  )
    blockers.push("spatial_agreement_unavailable");
  if (m.modality && m.modality.kind !== "desire")
    blockers.push("modal_interpretation_unreviewed");
  if (analysis.truncated) blockers.push("input_limit");
  // Semantic analysis is never a playback authorization. Whole-clip evidence
  // and authored word drafts do not establish CSL alignment or language review.
  blockers.push("csl_alignment_unreviewed");
  return {
    schema: "signbridge-csl-semantic-plan-v1",
    analysis,
    draft,
    gaps,
    blockers: unique(blockers),
    route: "analysis_only",
    canPreview: false,
    items: [],
    referenceEvidence,
    unmatched: [analysis.text, analysis.remainingText].join(""),
    truncated: analysis.truncated,
    matchedCount: 0,
    representation: "semantic_roles_then_candidate_units",
    wordOrderStatus: "assistant_proposal_not_csl_grammar_validation",
    humanApproved: false,
    cslTranslationVerified: false,
    trainingReady: false,
    modelTrainingReady: false,
    weightsUpdated: false,
    nonmanualsGenerated: false,
  };
}
