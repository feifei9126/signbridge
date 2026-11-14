// Preserve complete reference spans inside a subtitle before dictionary fallback.
import { planReferenceText } from "./reference-motion-plan.js";
import { translateText } from "./sign-language-data.js";

export function planRealtimeText(
  input,
  clips = [],
  matchers,
  nativeClips = [],
) {
  const chars = [...String(input).normalize("NFKC")];
  const end = Math.min(chars.length, 500);
  const references = planReferenceText(chars.slice(0, end).join(""), clips);
  const items = [],
    unmatched = [];
  let cursor = 0,
    cutoff = end;
  // Exact native-library matches win over dictionary poses at the same span,
  // mirroring the workbench's auto route. Longest alias first, ties by length.
  const nativeIndex = new Map();
  for (const clip of nativeClips) {
    for (const alias of [clip.text, ...(clip.aliases || [])]) {
      const k = String(alias).normalize("NFKC").trim();
      if (k && !nativeIndex.has(k)) nativeIndex.set(k, clip);
    }
  }
  const nativeAt = (start) => {
    let best = null;
    for (const [alias, clip] of nativeIndex) {
      const seq = [...alias];
      if (!seq.length || start + seq.length > end) continue;
      if (seq.every((ch, i) => chars[start + i] === ch)) {
        const width = seq.length;
        if (!best || width > best.width) best = { clip, width };
      }
    }
    return best;
  };
  function dictionary(start, stop) {
    if (start >= stop) return true;
    if (items.length >= 40) {
      cutoff = start;
      return false;
    }
    let cursor = start;
    while (cursor < stop) {
      if (items.length >= 40) {
        cutoff = cursor;
        return false;
      }
      const hit = nativeAt(cursor);
      if (hit) {
        const end = cursor + hit.width;
        items.push({
          id: hit.clip.id,
          source: "native",
          text: chars.slice(cursor, end).join(""),
          matchedText: chars.slice(cursor, end).join(""),
        });
        cursor = end;
        continue;
      }
      // No native match here: consume until the next native hit or segment end.
      let next = cursor + 1;
      while (next < stop && !nativeAt(next)) next += 1;
      const text = chars.slice(cursor, next).join("");
      const translation = translateText(text, 12, matchers);
      if (translation) {
        unmatched.push(...translation.unmatched);
        if (translation.remainingText)
          unmatched.push(translation.remainingText);
        if (translation.matches.length)
          items.push({ source: "dictionary", text, translation });
      }
      cursor = next;
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
