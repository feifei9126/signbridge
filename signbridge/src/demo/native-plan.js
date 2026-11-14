import { SIGNS } from "../avatar/sign-language-data.js";
import { planDemoSemanticText } from "./csl-semantic-plan.js";

// Exact candidate labels are search evidence, not verified lexical alignments.
const key = (text) =>
  String(text)
    .normalize("NFKC")
    .trim()
    .replace(/[。.!！]+$/u, "");
const knownSurface = (item) =>
  [
    item.surface,
    ...(SIGNS[item.id]?.aliases || []),
    SIGNS[item.id]?.gloss,
  ].filter(Boolean);
export function planNativeText(input, clips = [], { nativeId } = {}) {
  const text = String(input).normalize("NFKC"),
    bounded = [...text].length <= 500;
  const candidates = clips.filter((c) => c.source === "native");
  const exact = (c) =>
    [c.text, ...(c.aliases || [])].some((alias) => key(alias) === key(text));
  const selected =
    candidates.find((c) => c.id === nativeId && exact(c)) ||
    candidates.find(exact);
  const common = {
    humanApproved: false,
    cslTranslationVerified: false,
    trainingReady: false,
    modelTrainingReady: false,
    weightsUpdated: false,
  };
  if (selected && bounded)
    return {
      ...common,
      route: "native_exact_candidate",
      canPreview: true,
      items: [
        {
          id: selected.id,
          source: "native",
          label: selected.text,
          matchedText: text,
        },
      ],
      matchedCount: 1,
      unmatched: "",
      truncated: false,
      blockers: [],
      warnings: ["candidate_label_unverified"],
    };
  const authoredPronouns = {
    他: "csl_he",
    她: "csl_he",
    我们: "csl_we",
    咱们: "csl_we",
  };
  if (bounded && Object.hasOwn(authoredPronouns, key(text)))
    return {
      ...common,
      route: "native_authored_pronoun",
      canPreview: true,
      items: [
        {
          id: authoredPronouns[key(text)],
          source: "semantic",
          label: key(text),
          matchedText: text,
        },
      ],
      matchedCount: 1,
      unmatched: "",
      truncated: false,
      blockers: [],
      warnings: ["authored_unit_fallback", "spatial_agreement_approximated"],
    };
  const semantic = planDemoSemanticText(text);
  const transformed = semantic.draft.map((item) => {
    const surfaces = knownSurface(item).map(key);
    const clip = candidates.find((c) =>
      [c.text, ...(c.aliases || [])].some((alias) =>
        surfaces.includes(key(alias)),
      ),
    );
    const semanticRole =
      Object.entries(semantic.analysis.meaning).find(
        ([, slot]) =>
          slot && slot.start === item.start && slot.end === item.end,
      )?.[0] || item.role;
    return {
      ...item,
      id: clip?.id || item.id,
      source: clip ? "native" : "semantic",
      label: item.surface,
      matchedText: item.surface,
      semanticRole,
    };
  });
  // OOV/scope checks are shared with the bounded role planner. A candidate may
  // fill a missing motion only when the whole existing lexical surface matches.
  const blockers = semantic.blockers.filter(
    (b) => b !== "motion_evidence_missing",
  );
  if (semantic.analysis.meaning.negation && semantic.analysis.meaning.modality)
    blockers.push("ambiguous_scope");
  if (transformed.some((i) => !i.id)) blockers.push("motion_evidence_missing");
  const canPreview =
    bounded && blockers.length === 0 && transformed.length >= 2;
  return {
    ...semantic,
    ...common,
    route: "bounded_native_semantic",
    canPreview,
    items: canPreview ? transformed : [],
    draft: transformed,
    blockers,
    unmatched: canPreview ? "" : text,
    matchedCount: canPreview ? transformed.length : 0,
    warnings: [
      ...semantic.warnings,
      "candidate_label_unverified",
      ...(transformed.some((i) => i.source === "semantic")
        ? ["authored_unit_fallback"]
        : []),
    ],
  };
}
