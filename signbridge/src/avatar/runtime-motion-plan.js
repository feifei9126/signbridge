// Preserve complete reference spans inside a subtitle before dictionary fallback.
import { planReferenceText } from "./reference-motion-plan.js";
import { translateText } from "./sign-language-data.js";

export function planRealtimeText(input, clips = [], matchers) {
  const chars = [...String(input).normalize("NFKC")];
  const end = Math.min(chars.length, 500);
  const references = planReferenceText(chars.slice(0, end).join(""), clips);
  const items = [],
    unmatched = [];
  let cursor = 0,
    cutoff = end;
  function dictionary(start, stop) {
    if (start >= stop) return true;
    if (items.length >= 40) {
      cutoff = start;
      return false;
    }
    const text = chars.slice(start, stop).join("");
    const translation = translateText(text, 12, matchers);
    if (translation) {
      unmatched.push(...translation.unmatched);
      if (translation.remainingText) unmatched.push(translation.remainingText);
      if (translation.matches.length)
        items.push({ source: "dictionary", text, translation });
    }
    return true;
  }
  for (const reference of references.items) {
    if (!dictionary(cursor, reference.start)) break;
    if (items.length >= 40) {
      cutoff = reference.start;
      break;
    }
    items.push({ ...reference, text: reference.matchedText });
    cursor = reference.end;
  }
  if (cutoff === end) dictionary(cursor, end);
  return {
    items,
    unmatched,
    truncated: cutoff < chars.length,
    remainingText: chars.slice(cutoff).join(""),
  };
}
