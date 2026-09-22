import assert from "node:assert/strict";
import test from "node:test";
import {
  parseCoverageInput,
  analyzeCoverage,
  coverageReportForExport,
  MAX_COVERAGE_CHARS,
} from "../src/avatar/coverage-analysis.js";
import {
  compileTranslationMatchers,
  translateText,
} from "../src/avatar/sign-language-data.js";
import { LOCALES } from "../src/i18n/locales.js";

test("plain text preserves separate repeated segments and removes only empty lines", () => {
  assert.deepEqual(parseCoverageInput("\uFEFF你好\r\n\r\n你好\r谢谢"), [
    "你好",
    "你好",
    "谢谢",
  ]);
});

test("SRT ignores indices, timestamps and markup, preserving cue boundaries", () => {
  const input =
    "1\r\n00:00:00,000 --> 00:00:02,000\r\n<b>你好</b>\r\nquasar &amp; &#x4f60;\r\n\r\n2\r\n00:00:02,500 --> 00:00:03,000\r\n谢谢";
  assert.deepEqual(parseCoverageInput(input, "srt"), [
    "你好 quasar & 你",
    "谢谢",
  ]);
});

test("WebVTT excludes metadata blocks, speaker markup and embedded timestamps", () => {
  const input =
    "WEBVTT\nKind: captions\nLanguage: zh\n\nNOTE not a subtitle\nignore me\n\nSTYLE\n::cue { color: red; }\n\nREGION\nid:example\n\ncue-id\n00:00.000 --> 00:02.000 position:50%\n<v 王老师><c.green>你好</c> <00:01.000>谢谢\n\n00:00:03.000 --> 00:00:04.000\n你好 &lt;span&gt;";
  assert.deepEqual(parseCoverageInput(input, "vtt"), [
    "你好 谢谢",
    "你好 <span>",
  ]);
});

test("malformed subtitles fail closed rather than counting timeline or silently omitting bad cues", () => {
  const cases = [
    [
      "1\n00:00:00,000 --> 00:00:01,000\n你好\n2\n00:00:02,000 --> 00:00:03,000\n谢谢",
      "srt",
    ],
    ["hello", "srt"],
    ["00:00.000 --> 00:01.000\n你好", "vtt"],
    ["WEBVTT\n00:00.000 --> 00:01.000\n你好", "vtt"],
    ["1\n00:99:00,000 --> 01:00:00,000\n你好", "srt"],
    ["1\n00:00:05,000 --> 00:00:04,000\n你好", "srt"],
    ["1\n00:00:00,000 --> 00:00:01,000", "srt"],
    ["1\n00:00:00,000 --> 00:00:01,000\n你好\n\nmissing timeline", "srt"],
  ];
  for (const [text, format] of cases)
    assert.throws(
      () => parseCoverageInput(text, format),
      /coverageInvalidSubtitles/,
    );
});

test("input and segment limits reject unsafe amounts of synchronous work", () => {
  assert.throws(() => parseCoverageInput(""), /coverageEmpty/);
  assert.throws(() => parseCoverageInput("a", "html"), /coverageInvalidFormat/);
  assert.throws(
    () => parseCoverageInput("a".repeat(MAX_COVERAGE_CHARS + 1)),
    /coverageTooLarge/,
  );
  assert.throws(
    () => parseCoverageInput("a\n".repeat(1001)),
    /coverageTooLarge/,
  );
  assert.throws(() => parseCoverageInput("a".repeat(2001)), /coverageTooLarge/);
  assert.throws(() => analyzeCoverage(["a".repeat(2001)]), /coverageTooLarge/);
});

test("coverage counts tokens, ranks unknowns, and does not mistake substring aliases for signs", () => {
  const result = analyzeCoverage([
    "你好 quasar quasar",
    "谢谢 quasar",
    "however",
  ]);
  assert.equal(result.summary.matchedTokens, 2);
  assert.equal(result.summary.unknownTokens, 4);
  assert.equal(result.summary.coverage, 1 / 3);
  assert.deepEqual(result.unknown[0], {
    word: "quasar",
    count: 3,
    segmentCount: 2,
    examples: [1, 2],
  });
  assert.equal(result.details[2].matches.length, 0);
});

test("skipped tokens and punctuation are not reported as missing or fake 100 percent coverage", () => {
  const result = analyzeCoverage(["的 了 着", "？！"]);
  assert.equal(result.summary.coverage, null);
  assert.equal(result.summary.unknownTokens, 0);
  assert.equal(result.summary.skippedTokens, 3);
  assert.deepEqual(result.unknown, []);
});

test("multi-word custom alias coverage matches the runtime tokenizer and segment order", () => {
  const motions = [
    {
      id: "custom_alpha",
      gloss: "样本",
      texts: ["quasar nebula"],
      frames: [{ value: {}, duration: 0.5 }],
    },
  ];
  const lines = ["quasar nebula 你好", "谢谢 nebula quasar"];
  const result = analyzeCoverage(lines, motions);
  assert.equal(result.summary.matchedTokens, 4);
  assert.equal(result.summary.unknownTokens, 2);
  for (const [index, line] of lines.entries()) {
    const actual = translateText(
      line,
      Number.MAX_SAFE_INTEGER,
      compileTranslationMatchers(motions),
    );
    assert.deepEqual(result.details[index].matches, actual.matches);
    assert.deepEqual(result.details[index].unmatched, actual.unmatched);
  }
});

test("full dictionary coverage does not hide the 12-motion runtime cutoff", () => {
  const line = "你好 ".repeat(13) + "quasar";
  const result = analyzeCoverage([line]);
  assert.equal(result.summary.matchedTokens, 13);
  assert.equal(result.summary.unknownTokens, 1);
  assert.equal(result.summary.runtimeTruncatedSegments, 1);
  assert.equal(
    result.details[0].remainingText,
    translateText(line).remainingText,
  );
});

test("report excludes source and all segment details unless explicitly included", () => {
  const result = analyzeCoverage(["你好 quasar"]);
  const safe = JSON.parse(JSON.stringify(coverageReportForExport(result)));
  assert.equal(safe.includesSourceText, false);
  assert.equal("details" in safe, false);
  assert.equal(safe.unknown[0].word, "quasar");
  assert.deepEqual(
    coverageReportForExport(result, true).details,
    result.details,
  );
  assert.equal(result.details[0].text, "你好 quasar");
});

test("all coverage messages exist with identical placeholders in every supported locale", () => {
  for (const key of Object.keys(LOCALES["zh-CN"]).filter((key) =>
    key.startsWith("coverage"),
  )) {
    for (const locale of Object.values(LOCALES)) {
      assert.equal(typeof locale[key], "string", key);
      assert.deepEqual(
        (locale[key].match(/\{\w+\}/g) || []).sort(),
        (LOCALES["zh-CN"][key].match(/\{\w+\}/g) || []).sort(),
        key,
      );
    }
  }
});
