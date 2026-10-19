// Reference span matching is independent from semantic analysis and dictionary scanning.
export const T08_CHECKPOINT_SHA256 =
  "438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b";
const punctuation = /[\s\p{P}]/u;
export function demoTextKey(text) {
  return String(text)
    .normalize("NFKC")
    .replace(/[\s\p{P}]/gu, "")
    .toLocaleLowerCase();
}
export function motionSource(clip) {
  return clip.experimental
    ? "experimental"
    : clip.runtime_candidate
      ? "candidate"
      : "t08";
}
export function matchT08Reference(input, clips = []) {
  const key = demoTextKey(input);
  if (!key) return null;
  return (
    clips.find((clip) =>
      [clip.text, ...(clip.aliases || [])].some(
        (text) => demoTextKey(text) === key,
      ),
    ) || null
  );
}
export function planReferenceText(input, clips = []) {
  const chars = [...String(input).normalize("NFKC")].slice(0, 500);
  const entries = [];
  for (const c of clips)
    for (const text of c.aliases || [c.text])
      entries.push({
        id: c.id,
        text,
        key: demoTextKey(text),
        source: motionSource(c),
        label: c.text,
      });
  entries.sort(
    (a, b) =>
      [...b.key].length - [...a.key].length ||
      (a.source === b.source
        ? 0
        : { t08: 0, candidate: 1, experimental: 2, dictionary: 3 }[a.source] -
          { t08: 0, candidate: 1, experimental: 2, dictionary: 3 }[b.source]),
  );
  const items = [],
    unknown = [];
  let cursor = 0;
  while (cursor < chars.length) {
    if (punctuation.test(chars[cursor])) {
      cursor++;
      continue;
    }
    const remaining = demoTextKey(chars.slice(cursor).join(""));
    const match = entries.find((e) => e.key && remaining.startsWith(e.key));
    if (!match) {
      unknown.push(chars[cursor++]);
      continue;
    }
    let end = cursor,
      consumed = "";
    while (end < chars.length && consumed.length < match.key.length) {
      if (!punctuation.test(chars[end]))
        consumed += chars[end].toLocaleLowerCase();
      end++;
    }
    // English aliases must match a whole token, not prefixes inside unknown words.
    if (
      /^[a-z]+$/i.test(match.key) &&
      (/[a-z0-9]/i.test(chars[end] || "") ||
        /[a-z0-9]/i.test(chars[cursor - 1] || ""))
    ) {
      unknown.push(chars[cursor++]);
      continue;
    }
    items.push({
      ...match,
      matchedText: chars.slice(cursor, end).join(""),
      start: cursor,
      end,
    });
    cursor = end;
    if (items.length >= 40) {
      unknown.push(...chars.slice(cursor));
      break;
    }
  }
  return {
    items,
    unmatched: unknown.join(""),
    truncated: [...String(input)].length > 500,
    matchedCount: items.length,
  };
}
