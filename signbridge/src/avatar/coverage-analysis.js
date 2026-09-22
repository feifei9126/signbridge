import {
  compileTranslationMatchers,
  translateText,
  translationAliasKey,
} from "./sign-language-data.js";

const MAX_COVERAGE_BYTES = 256 * 1024;
const MAX_COVERAGE_CHARS = 50000;
const MAX_COVERAGE_SEGMENTS = 1000;
const MAX_SEGMENT_CHARS = 2000;

function fail(key) {
  throw new Error(key);
}

function cueText(text) {
  const entities = { amp: "&", lt: "<", gt: ">", nbsp: " ", lrm: "", rlm: "" };
  return text
    .replace(/<[^>]*>/g, "")
    .replace(
      /&(#x[0-9a-f]+|#\d+|amp|lt|gt|nbsp|lrm|rlm);/gi,
      (match, entity) => {
        const key = entity.toLowerCase();
        if (!key.startsWith("#")) return entities[key];
        const code = key.startsWith("#x")
          ? Number.parseInt(key.slice(2), 16)
          : Number.parseInt(key.slice(1), 10);
        return code > 0 &&
          code <= 0x10ffff &&
          !(code >= 0xd800 && code <= 0xdfff)
          ? String.fromCodePoint(code)
          : match;
      },
    )
    .replace(/\s+/g, " ")
    .trim();
}

function timestamp(value, format) {
  const pattern =
    format === "srt"
      ? /^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$/
      : /^(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})$/;
  const parts = value.match(pattern);
  if (!parts) fail("coverageInvalidSubtitles");
  return (
    Number(parts[1] || 0) * 3600 +
    Number(parts[2]) * 60 +
    Number(parts[3]) +
    Number(parts[4]) / 1000
  );
}

function parseCoverageInput(input, format = "text") {
  if (typeof input !== "string" || input.length > MAX_COVERAGE_CHARS)
    fail("coverageTooLarge");
  const text = input
    .replace(/^\uFEFF/, "")
    .replace(/\r\n?/g, "\n")
    .trim();
  if (!text) fail("coverageEmpty");
  if (!["text", "srt", "vtt"].includes(format)) fail("coverageInvalidFormat");
  let segments;
  if (format === "text") {
    segments = text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  } else {
    const blocks = text.split(/\n[\t ]*\n+/);
    if (format === "vtt") {
      if (!/^WEBVTT(?:[\t ]|\n|$)/.test(blocks[0]))
        fail("coverageInvalidSubtitles");
      if (blocks[0].includes("-->")) fail("coverageInvalidSubtitles");
      blocks.shift();
    }
    segments = [];
    for (const block of blocks) {
      if (
        format === "vtt" &&
        /^(?:NOTE(?:[\t ]|\n|$)|STYLE(?:\n|$)|REGION(?:\n|$))/.test(block)
      )
        continue;
      const lines = block.split("\n");
      if (lines.filter((line) => line.includes("-->")).length !== 1)
        fail("coverageInvalidSubtitles");
      const timingIndex = lines.findIndex((line) => line.includes("-->"));
      if (
        timingIndex < 0 ||
        timingIndex > 1 ||
        (format === "srt" && timingIndex === 1 && !/^\d+$/.test(lines[0]))
      )
        fail("coverageInvalidSubtitles");
      const times = lines[timingIndex]
        .trim()
        .match(/^(\S+)\s+-->\s+(\S+)(?:[\t ]+.*)?$/);
      if (!times || timestamp(times[2], format) <= timestamp(times[1], format))
        fail("coverageInvalidSubtitles");
      const value = cueText(lines.slice(timingIndex + 1).join(" "));
      if (!value) fail("coverageInvalidSubtitles");
      segments.push(value);
    }
  }
  if (!segments.length) fail("coverageEmpty");
  if (
    segments.length > MAX_COVERAGE_SEGMENTS ||
    segments.some((text) => text.length > MAX_SEGMENT_CHARS)
  )
    fail("coverageTooLarge");
  return segments;
}

function analyzeCoverage(segments, motions = []) {
  if (
    !Array.isArray(segments) ||
    !segments.length ||
    segments.length > MAX_COVERAGE_SEGMENTS ||
    segments.some(
      (text) => typeof text !== "string" || text.length > MAX_SEGMENT_CHARS,
    ) ||
    segments.join("").length > MAX_COVERAGE_CHARS
  )
    fail("coverageTooLarge");
  const matchers = compileTranslationMatchers(motions);
  const unknown = new Map();
  let matchedTokens = 0;
  let unknownTokens = 0;
  let skippedTokens = 0;
  const details = segments.map((text, index) => {
    const result = translateText(text, Number.MAX_SAFE_INTEGER, matchers);
    const runtime = translateText(text, 12, matchers);
    const matches = result?.matches || [];
    const unmatched = result?.unmatched || [];
    const skipped = result?.skipped || [];
    matchedTokens += matches.reduce(
      (count, match) =>
        count + JSON.parse(translationAliasKey(match.text)).length,
      0,
    );
    unknownTokens += unmatched.length;
    skippedTokens += skipped.length;
    for (const word of unmatched) {
      if (!unknown.has(word))
        unknown.set(word, { word, count: 0, segmentCount: 0, examples: [] });
      unknown.get(word).count += 1;
    }
    for (const word of new Set(unmatched)) {
      const item = unknown.get(word);
      item.segmentCount += 1;
      if (item.examples.length < 3) item.examples.push(index + 1);
    }
    return {
      segment: index + 1,
      text,
      matches,
      unmatched,
      skipped,
      truncated: runtime?.truncated || false,
      remainingText: runtime?.remainingText || "",
    };
  });
  const denominator = matchedTokens + unknownTokens;
  return {
    type: "signbridge-coverage",
    version: 1,
    metric: "matched-word-tokens-excluding-skipped",
    customMotionIds: motions.map((motion) => motion.id).sort(),
    summary: {
      segments: segments.length,
      matchedTokens,
      unknownTokens,
      skippedTokens,
      coverage: denominator ? matchedTokens / denominator : null,
      segmentsWithMatches: details.filter((detail) => detail.matches.length)
        .length,
      runtimeTruncatedSegments: details.filter((detail) => detail.truncated)
        .length,
    },
    unknown: [...unknown.values()].sort(
      (first, second) =>
        second.count - first.count ||
        first.word.localeCompare(second.word, "zh"),
    ),
    details,
  };
}

function coverageReportForExport(report, includeText = false) {
  return {
    ...report,
    includesSourceText: includeText,
    details: includeText ? report.details : undefined,
  };
}

export {
  MAX_COVERAGE_BYTES,
  MAX_COVERAGE_CHARS,
  parseCoverageInput,
  analyzeCoverage,
  coverageReportForExport,
};
