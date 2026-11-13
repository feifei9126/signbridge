import { scanDictionaryText } from "../avatar/sign-language-data.js";
import { planCslText, planDemoSemanticText } from "./csl-semantic-plan.js";
import { planReferenceText } from "../avatar/reference-motion-plan.js";
export {
  T08_CHECKPOINT_SHA256,
  demoTextKey,
  motionSource,
  matchT08Reference,
} from "../avatar/reference-motion-plan.js";

export function planDemoText(input, mode = "auto", clips = []) {
  if (mode === "semantic") return planCslText(input, clips);
  if (!["auto", "t08", "dictionary"].includes(mode))
    throw new Error("demoInvalidMode");
  if (mode === "t08") return planReferenceText(input, clips);
  const full = [...String(input).normalize("NFKC")];
  const chars = full.slice(0, 500);
  const refs =
    mode === "dictionary" ? [] : planReferenceText(chars.join(""), clips).items;
  if (mode === "auto" && refs.length === 0) {
    const semantic = planDemoSemanticText(chars.join(""));
    if (semantic.canPreview) return semantic;
    if (semantic.analysis.meaning.predicate) return semantic;
  }
  const items = [],
    unknown = [];
  let cursor = 0,
    cutoff = chars.length;
  function gap(start, end) {
    const result = scanDictionaryText(
      chars.slice(start, end).join(""),
      40 - items.length,
    );
    unknown.push(...result.unmatched);
    for (const match of result.matches)
      items.push({
        id: match.id,
        source: "dictionary",
        label: match.gloss,
        matchedText: chars
          .slice(start + match.start, start + match.end)
          .join(""),
        start: start + match.start,
        end: start + match.end,
      });
    if (result.truncated) {
      cutoff = end - [...result.remainingText].length;
      return false;
    }
    return true;
  }
  for (const reference of refs) {
    if (!gap(cursor, reference.start)) break;
    if (items.length >= 40) {
      cutoff = reference.start;
      break;
    }
    items.push(reference);
    cursor = reference.end;
  }
  if (cutoff === chars.length) gap(cursor, chars.length);
  if (cutoff < chars.length) unknown.push(...chars.slice(cutoff));
  return {
    items,
    unmatched: unknown.join(""),
    truncated: cutoff < full.length,
    remainingText: full.slice(cutoff).join(""),
    matchedCount: items.length,
  };
}

export {
  validateT08Bundle,
  validateT08CandidateBundle,
} from "../avatar/reference-motion-asset.js";

// Auto mode must consult the native motion library before falling back to the
// builtin hand-authored dictionary, otherwise every word that exists in both
// plays the dictionary pose and the native recordings are never shown.
export function planAutoText(input, clips = [], nativeClips = []) {
  const plan = planDemoText(input, "auto", clips);
  if (!nativeClips.length) return plan;
  const key = (text) =>
    String(text)
      .normalize("NFKC")
      .trim()
      .replace(/[。.!！]+$/u, "");
  const byText = new Map();
  for (const clip of nativeClips) {
    for (const alias of [clip.text, ...(clip.aliases || [])]) {
      const k = key(alias);
      if (k && !byText.has(k)) byText.set(k, clip);
    }
  }
  let remapped = 0;
  const items = plan.items.map((item) => {
    const clip = byText.get(key(item.matchedText));
    if (!clip || clip.id === item.id) return item;
    remapped += 1;
    return { ...item, id: clip.id, source: "native", label: clip.text };
  });
  if (!remapped) return plan;
  return {
    ...plan,
    items,
    route: "native_auto_mix",
    warnings: [...(plan.warnings || []), "candidate_label_unverified"],
  };
}
