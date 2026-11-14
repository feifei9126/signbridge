import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { LOCALES } from "../src/i18n/locales.js";
import { bundleRuntime, runRuntime } from "./helpers/runtime-harness.mjs";

const sourceUrl = new URL(
  "../src/tools/word-motion-review.js",
  import.meta.url,
);
const htmlUrl = new URL(
  "../src/tools/word-motion-review.html",
  import.meta.url,
);
let runtimeCode;

// This DOM double rejects HTML sinks and records real runtime-created elements.
class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toLowerCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.open = false;
    this.pauses = 0;
    this.loads = 0;
    this._text = "";
  }

  set innerHTML(_value) {
    assert.fail("Untrusted data must never reach an HTML sink");
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get textContent() {
    return (
      this._text + this.children.map((child) => child.textContent).join("")
    );
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this._text = "";
    this.children = [...children];
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") delete this.src;
  }

  addEventListener(type, handler) {
    (this.listeners[type] ??= []).push(handler);
  }

  dispatch(type) {
    if (this.disabled) return;
    for (const handler of this.listeners[type] || []) handler({ target: this });
  }

  querySelectorAll(selector) {
    return this.children.flatMap((child) => [
      ...(child.tagName === selector ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }

  pause() {
    this.pauses++;
  }

  load() {
    this.loads++;
  }
}

function candidate(index, overrides = {}) {
  return {
    id: `candidate-${index}`,
    proposed_text: ["我", "你", "他", "我们"][index % 4],
    source_batch: index % 2 ? "batch-b" : "batch-a",
    source_id: `source-${index}`,
    source_sha256: "a".repeat(64),
    source_absolute_path: `/local/original-${index}.mp4`,
    source_window_seconds: [index, index + 0.8],
    evidence_kind: "source_window",
    language_scope_status: "CSL_source_scope_unconfirmed",
    label_status: "candidate_only",
    text_verified: "",
    word_boundaries_verified: false,
    human_approved: false,
    training_ready: false,
    model_training_ready: false,
    reference_clip: `clips/${index}.mp4`,
    keyframes: `sheets/${index}.jpg`,
    native_3d_available: index % 3 === 0,
    native_asset: index % 3 === 0 ? `motions/${index}.json` : null,
    review_flags: ["needs_word_alignment"],
    notes: "Candidate source window only",
    ...overrides,
  };
}

function artifact(count = 55) {
  return {
    summary: {
      videos: 90,
      unique_sources: 80,
      candidates: 1200,
      materialized: 55,
      unique_labels: 4,
      native_3d: 19,
    },
    candidates: Array.from({ length: count }, (_, index) => candidate(index)),
    coverage: Array.from({ length: count }, (_, index) => ({
      source_id: `source-${index}`,
      path: `/local/original-${index}.mp4`,
      batch: index % 2 ? "batch-b" : "batch-a",
      status: "candidate_windows_only",
      candidate_count: 1,
    })),
  };
}

async function runReview(data = artifact(), language = "en") {
  assert.ok(existsSync(sourceUrl), "The offline review entry must exist");
  runtimeCode ??= await bundleRuntime("../../src/tools/word-motion-review.js");
  const html = readFileSync(htmlUrl, "utf8");
  const elements = new Map();
  for (const [, tag, id] of html.matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"/g))
    elements.set(id, new Element(tag));
  const localized = [...html.matchAll(/data-i18n="([^"]+)"/g)].map((match) => {
    const element = new Element();
    element.dataset.i18n = match[1];
    return element;
  });
  const window = new Element();
  const document = Object.assign(new Element("document"), {
    visibilityState: "visible",
    documentElement: new Element("html"),
    createElement: (tag) => new Element(tag),
    querySelector: (selector) => {
      assert.ok(
        elements.has(selector.slice(1)),
        `Unknown selector ${selector}`,
      );
      return elements.get(selector.slice(1));
    },
    querySelectorAll: (selector) => {
      assert.equal(selector, "[data-i18n]");
      return localized;
    },
  });
  const context = runRuntime(runtimeCode, {
    document,
    window,
    URL,
    location: { href: `file:///local/review/index.html?lang=${language}` },
    navigator: { language },
    SIGNBRIDGE_WORD_MOTIONS: data,
    fetch: () => assert.fail("Offline review must not fetch JSON or services"),
  });
  const get = (id) => elements.get(`word-motion-${id}`);
  return { get, window, context, localized, document };
}

function freeze(value) {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

test("offline HTML uses only adjacent external data, bundle and stylesheet", () => {
  assert.ok(existsSync(htmlUrl), "The offline review HTML must exist");
  const html = readFileSync(htmlUrl, "utf8");
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 2);
  assert.match(scripts[0][1], /src="review-data\.js"/);
  assert.match(scripts[1][1], /src="review\.js"/);
  for (const [, attributes, body] of scripts) {
    assert.doesNotMatch(attributes, /\b(?:type="module"|async)\b/);
    assert.equal(body.trim(), "");
  }
  assert.match(html, /href="review\.css"/);
  assert.doesNotMatch(html, /<(?:base|iframe)\b|https?:\/\//i);
  assert.ok(
    existsSync(new URL("../src/tools/word-motion-review.css", import.meta.url)),
  );
});

test("relative media paths reject schemes, traversal, executable files and encoded tricks", async () => {
  assert.ok(existsSync(sourceUrl), "The offline review entry must exist");
  const { safeRelativePath } = await import(sourceUrl);
  for (const path of [
    null,
    "",
    "/tmp/private.mp4",
    "//host/clip.mp4",
    "../clip.mp4",
    "clips/../clip.mp4",
    "clips/%2e%2e/clip.mp4",
    "clips/%252e%252e/clip.mp4",
    "clips/%2e%2e%2fclip.mp4",
    "clips/%5c..%5cclip.mp4",
    "clips\\clip.mp4",
    "javascript:alert(1)",
    "data:video/mp4,xxx",
    "https://host/clip.mp4",
    "file:///tmp/clip.mp4",
    "C:/clip.mp4",
    "clips/a.mp4?remote=1",
    "clips/a.mp4#fragment",
    "clips/%00.mp4",
    "clips/%0a.mp4",
    "clips/%zz.mp4",
    " clips/a.mp4",
    "clips//a.mp4",
    "clips/a.html",
  ])
    assert.equal(safeRelativePath(path, "clip"), null, String(path));
  assert.equal(
    safeRelativePath("clips/我 你.mp4", "clip"),
    "clips/%E6%88%91%20%E4%BD%A0.mp4",
  );
  assert.equal(
    safeRelativePath("./clips/a%20b.mp4", "clip"),
    "clips/a%20b.mp4",
  );
  assert.equal(safeRelativePath("sheets/a.png", "sheet"), "sheets/a.png");
  assert.equal(safeRelativePath("sheets/a.svg", "sheet"), null);
  assert.equal(
    safeRelativePath("motions/a.motion.json", "asset"),
    "motions/a.motion.json",
  );
  assert.equal(safeRelativePath("motions/a.html", "asset"), null);
});

test("candidate and coverage pagination cap DOM and media at 24 per page", async () => {
  const { get } = await runReview();
  assert.equal(get("candidates").children.length, 24);
  assert.equal(get("candidates").querySelectorAll("video").length, 24);
  assert.equal(get("coverage-body").children.length, 24);
  assert.match(get("count").textContent, /55.*1\/3/);
  assert.equal(get("previous").disabled, true);
  get("next").dispatch("click");
  assert.match(get("candidates").children[0].textContent, /candidate-24/);
  get("next").dispatch("click");
  assert.equal(get("candidates").children.length, 7);
  assert.equal(get("next").disabled, true);
  get("previous").dispatch("click");
  assert.equal(get("candidates").children.length, 24);
  get("coverage-next").dispatch("click");
  assert.match(get("coverage-body").children[0].textContent, /source-24/);
});

test("malformed Unicode media paths are rejected without aborting the review", async () => {
  const { safeRelativePath } = await import(sourceUrl);
  for (const [kind, extension] of [
    ["clip", "mp4"],
    ["sheet", "jpg"],
    ["asset", "json"],
  ]) {
    for (const surrogate of ["\ud800", "\udfff"])
      assert.equal(
        safeRelativePath(`media/${surrogate}.${extension}`, kind),
        null,
      );
  }
  const data = artifact(1);
  Object.assign(data.candidates[0], {
    reference_clip: "clips/\ud800.mp4",
    keyframes: "sheets/\udfff.jpg",
    native_asset: "motions/\ud800.json",
  });
  const { get } = await runReview(data);
  assert.equal(get("candidates").children.length, 1);
  assert.equal(get("coverage-body").children.length, 1);
  assert.equal(get("candidates").querySelectorAll("video").length, 0);
  assert.match(get("candidates").textContent, /no safe local clip/i);
});

test("search, batch, native and exact focus-word filters combine and reset pages", async () => {
  const { get } = await runReview();
  get("next").dispatch("click");
  get("kind").value = "native";
  get("kind").dispatch("change");
  assert.equal(get("candidates").children.length, 19);
  assert.equal(get("previous").disabled, true);
  get("batch").value = "batch-a";
  get("batch").dispatch("change");
  assert.equal(get("candidates").children.length, 10);
  get("search").value = "SOURCE-12";
  get("search").dispatch("input");
  assert.equal(get("candidates").children.length, 1);
  get("search").value = "";
  get("search").dispatch("input");
  get("kind").value = "all";
  get("kind").dispatch("change");
  get("batch").value = "";
  get("batch").dispatch("change");
  const focus = get("focus").children;
  assert.equal(focus.length, 5);
  focus[1].dispatch("click");
  assert.equal(get("candidates").children.length, 14);
  assert.equal(focus[1].attributes["aria-pressed"], "true");
  focus[4].dispatch("click");
  assert.equal(get("candidates").children.length, 13);
  focus[0].dispatch("click");
  get("kind").value = "2d";
  get("kind").dispatch("change");
  assert.match(get("count").textContent, /36/);
});

test("hostile labels and provenance remain literal text and unsafe media never get URLs", async () => {
  const hostile =
    '<img src=x onerror="globalThis.pwned=true"><script>pwned=true</script>';
  const data = artifact(1);
  data.candidates[0] = candidate(0, {
    proposed_text: hostile,
    source_batch: hostile,
    source_id: hostile,
    source_sha256: hostile,
    source_absolute_path: hostile,
    evidence_kind: hostile,
    notes: hostile,
    review_flags: [hostile],
    reference_clip: "javascript:alert(1)",
    keyframes: "../outside.png",
    native_asset: "https://outside/motion.json",
  });
  data.coverage[0] = {
    source_id: hostile,
    path: hostile,
    batch: hostile,
    status: hostile,
    candidate_count: 1,
  };
  const { get, context } = await runReview(freeze(data));
  assert.ok(get("candidates").textContent.includes(hostile));
  assert.ok(get("coverage-body").textContent.includes(hostile));
  assert.equal(get("candidates").querySelectorAll("script").length, 0);
  assert.equal(get("candidates").querySelectorAll("video").length, 0);
  assert.equal(get("candidates").querySelectorAll("img").length, 0);
  assert.equal(get("candidates").querySelectorAll("a").length, 0);
  assert.equal(context.pwned, undefined);
});

test("safe local clips load on demand and contact sheets load only when expanded", async () => {
  const { get, window } = await runReview(artifact(25));
  const first = get("candidates").children[0];
  const video = first.querySelectorAll("video")[0];
  assert.equal(video.preload, "none");
  assert.equal(video.controls, true);
  assert.equal(video.autoplay, undefined);
  assert.equal(video.src, "clips/0.mp4");
  const image = first.querySelectorAll("img")[0];
  assert.equal(image.loading, "lazy");
  assert.equal(image.src, undefined);
  const details = first
    .querySelectorAll("details")
    .find((entry) => entry.querySelectorAll("img").length);
  details.open = true;
  details.dispatch("toggle");
  assert.equal(image.src, "sheets/0.jpg");
  assert.match(first.querySelectorAll("a")[0].href, /^motions\/0\.json$/);
  window.dispatch("pagehide");
  assert.ok(video.pauses > 0);
  get("next").dispatch("click");
  assert.equal(video.src, undefined);
  assert.ok(video.loads > 0);
  assert.equal(get("candidates").querySelectorAll("video").length, 1);
});

test("backgrounding the review pauses playback without removing reusable media", async () => {
  const { get, document } = await runReview(artifact(1));
  const video = get("candidates").querySelectorAll("video")[0];
  document.dispatch("visibilitychange");
  assert.equal(video.pauses, 0, "A visible review must not interrupt playback");
  document.visibilityState = "hidden";
  document.dispatch("visibilitychange");
  assert.ok(video.pauses > 0, "Hidden review clips must stop playing");
  assert.equal(video.src, "clips/0.mp4");
  assert.equal(video.loads, 0);
});

test("native asset links preserve the offline review when file downloads are unsupported", async () => {
  const { get } = await runReview(artifact(1));
  const link = get("candidates").querySelectorAll("a")[0];
  assert.equal(link.href, "motions/0.json");
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener noreferrer");
});

test("missing, empty and malformed data remain usable and do not invent zero totals", async () => {
  const missing = await runReview(null);
  assert.match(missing.get("data-status").textContent, /review-data\.js/);
  assert.equal(missing.get("candidates").children.length, 0);
  assert.match(missing.get("summary").textContent, /Unknown/);
  const empty = await runReview({
    summary: { videos: 0 },
    candidates: [],
    coverage: [],
  });
  assert.equal(empty.get("data-status").textContent, "");
  assert.match(empty.get("summary").textContent, /0/);
  assert.equal(empty.get("empty").hidden, false);
  const malformed = await runReview({
    summary: { videos: -1, candidates: "many" },
    candidates: [null, 1, []],
    coverage: [null],
  });
  assert.equal(malformed.get("candidates").children.length, 0);
  assert.doesNotMatch(malformed.get("summary").textContent, /many|-1/);
});

test("summary preserves reported totals while labels and boundaries stay explicitly unverified", async () => {
  const data = artifact(1);
  data.candidates[0].human_approved = true;
  data.candidates[0].training_ready = true;
  data.candidates[0].model_training_ready = true;
  data.candidates[0].word_boundaries_verified = true;
  const before = JSON.stringify(data);
  const { get, context } = await runReview(freeze(data));
  assert.match(get("summary").textContent, /1200/);
  assert.match(get("summary-note").textContent, /1 candidate records/);
  assert.match(
    get("candidates").textContent,
    /sign meaning and word boundaries are unverified/i,
  );
  assert.equal(get("candidates").querySelectorAll("button").length, 0);
  assert.equal(JSON.stringify(data), before);
  assert.equal(context.approve, undefined);
  const source = readFileSync(sourceUrl, "utf8");
  assert.doesNotMatch(
    source,
    /innerHTML|insertAdjacentHTML|localStorage|fetch\s*\(/,
  );
});

test("media errors and unsafe or absent references show an explicit localized fallback", async () => {
  const data = artifact(2);
  data.candidates[1].reference_clip = null;
  data.candidates[1].keyframes = null;
  const { get } = await runReview(data);
  const first = get("candidates").children[0];
  first.querySelectorAll("video")[0].dispatch("error");
  assert.match(first.textContent, /could not be read/i);
  const sheet = first.querySelectorAll("img")[0];
  sheet.dispatch("error");
  assert.equal(sheet.hidden, true);
  assert.match(
    get("candidates").children[1].textContent,
    /no safe local clip/i,
  );
});

test("all wordMotion translations and placeholder sets match in Chinese, English and Japanese", () => {
  const keys = Object.keys(LOCALES.en).filter((key) =>
    key.startsWith("wordMotion"),
  );
  assert.ok(keys.length > 20, "Register the complete review UI vocabulary");
  const references = [
    readFileSync(htmlUrl, "utf8"),
    readFileSync(sourceUrl, "utf8"),
  ].flatMap((source) =>
    [...source.matchAll(/wordMotion[A-Z]\w*/g)].map((match) => match[0]),
  );
  assert.deepEqual(
    [...new Set(references)].filter((key) => !keys.includes(key)),
    [],
    "Every review UI translation reference must be registered",
  );
  for (const locale of ["zh-CN", "en", "ja"]) {
    assert.deepEqual(
      Object.keys(LOCALES[locale])
        .filter((key) => key.startsWith("wordMotion"))
        .sort(),
      [...keys].sort(),
    );
    for (const key of keys) {
      assert.equal(typeof LOCALES[locale][key], "string", `${locale}: ${key}`);
      assert.ok(LOCALES[locale][key].length > 0);
      const placeholders = (text) =>
        [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
      assert.deepEqual(
        placeholders(LOCALES[locale][key]),
        placeholders(LOCALES.en[key]),
        `${locale}: ${key}`,
      );
    }
  }
});

test("language switches translate dynamic UI while preserving active filters", async () => {
  const { get, document } = await runReview(artifact(), "ja");
  assert.equal(document.documentElement.lang, "ja");
  assert.match(get("count").textContent, /候補/);
  get("search").value = "source-12";
  get("search").dispatch("input");
  get("language").value = "en";
  get("language").dispatch("change");
  assert.equal(document.documentElement.lang, "en");
  assert.equal(get("candidates").children.length, 1);
  assert.match(get("count").textContent, /candidates/);
  assert.doesNotMatch(get("candidates").textContent, /wordMotion[A-Z]|\{\w+\}/);
});

test("every card and its provenance localize scope without validating standard CSL", async () => {
  const scopes = [
    ["CSL_source_scope_unconfirmed", "wordMotionScopeCslUnconfirmed"],
    ["regional_variant_candidate_separate", "wordMotionScopeRegional"],
    ["fingerspelling_candidate_separate", "wordMotionScopeFingerspelling"],
    [undefined, "wordMotionScopeUnknown"],
    ["<script>unknownScope</script>", "wordMotionScopeUnknown"],
  ];
  const data = artifact(scopes.length);
  data.candidates.forEach((row, index) => {
    row.language_scope_status = scopes[index][0];
  });
  const before = JSON.stringify(data);
  for (const locale of ["zh-CN", "en", "ja"]) {
    const { get } = await runReview(freeze(data), locale);
    for (const [index, card] of get("candidates").children.entries()) {
      const badge = card.children.find(
        (node) => node.className === "scope-badge",
      );
      assert.ok(badge, "Every card needs a visible language-scope warning");
      assert.equal(badge.textContent, LOCALES[locale][scopes[index][1]]);
      const provenance = card.querySelectorAll("dl")[0];
      assert.ok(provenance.textContent.includes(badge.textContent));
      if (scopes[index][0])
        assert.ok(provenance.textContent.includes(scopes[index][0]));
      assert.equal(card.querySelectorAll("script").length, 0);
    }
  }
  assert.equal(JSON.stringify(data), before);
});

test("scope filters separate regional and fingerspelling candidates and compose with other filters", async () => {
  const scopes = [
    "CSL_source_scope_unconfirmed",
    "regional_variant_candidate_separate",
    "fingerspelling_candidate_separate",
  ];
  const data = artifact(61);
  data.candidates.forEach((row, index) => {
    row.language_scope_status = scopes[index % scopes.length];
    row.native_3d_available = true;
  });
  data.candidates[60].language_scope_status = "unrecognized_scope";
  const { get } = await runReview(data);
  assert.ok(get("scope"), "The review needs a labeled scope filter");
  get("next").dispatch("click");
  const priorVideo = get("candidates").querySelectorAll("video")[0];
  for (const [filter, scope] of [
    ["csl", scopes[0]],
    ["regional", scopes[1]],
    ["fingerspelling", scopes[2]],
  ]) {
    get("scope").value = filter;
    get("scope").dispatch("change");
    assert.equal(get("candidates").children.length, 20);
    assert.equal(get("previous").disabled, true);
    for (const card of get("candidates").children)
      assert.ok(card.querySelectorAll("dl")[0].textContent.includes(scope));
  }
  assert.equal(priorVideo.src, undefined);
  assert.ok(priorVideo.pauses > 0 && priorVideo.loads > 0);
  get("scope").value = "regional";
  get("scope").dispatch("change");
  get("batch").value = "batch-b";
  get("batch").dispatch("change");
  get("kind").value = "native";
  get("kind").dispatch("change");
  get("focus").children[2].dispatch("click");
  assert.equal(get("candidates").children.length, 5);
  get("search").value = "source-13";
  get("search").dispatch("input");
  assert.equal(get("candidates").children.length, 1);
  get("language").value = "ja";
  get("language").dispatch("change");
  assert.equal(get("scope").value, "regional");
  assert.equal(get("candidates").children.length, 1);
  get("kind").value = "2d";
  get("kind").dispatch("change");
  assert.equal(get("candidates").children.length, 0);
  assert.equal(get("empty").hidden, false);
});

test("offline HTML offers exactly all, CSL-unconfirmed, regional and fingerspelling scope options", () => {
  const html = readFileSync(htmlUrl, "utf8");
  assert.match(html, /for="word-motion-scope"/);
  const scopeSelect = html.match(
    /<select id="word-motion-scope">([\s\S]*?)<\/select>/,
  );
  assert.ok(scopeSelect, "Scope filter must exist in the offline page");
  assert.deepEqual(
    [...scopeSelect[1].matchAll(/value="([^"]+)"/g)].map((match) => match[1]),
    ["all", "csl", "regional", "fingerspelling"],
  );
});

test("projection labels do not imply full motion, verified action or pronoun-native data", async () => {
  const expected = {
    "zh-CN": {
      wordMotionNativeCount: "已有 3D 展示投影",
      wordMotionNativeFilter: "含已有展示投影",
      wordMotionNativeReported:
        "数据标记：已有展示投影；非完整动作、已核验手语动作或代词原生动作",
      wordMotionNativeAsset: "打开本地 3D 展示投影文件",
    },
    en: {
      wordMotionNativeCount: "Existing 3D display projections",
      wordMotionNativeFilter: "With existing projection",
      wordMotionNativeReported:
        "Existing display projection; not full motion, verified action, or pronoun-native motion",
      wordMotionNativeAsset: "Open local 3D display projection",
    },
    ja: {
      wordMotionNativeCount: "既存の3D表示投影",
      wordMotionNativeFilter: "既存の表示投影あり",
      wordMotionNativeReported:
        "既存の表示投影です。全身動作、検証済みの手話動作、代名詞のネイティブ動作ではありません",
      wordMotionNativeAsset: "ローカルの3D表示投影を開く",
    },
  };
  for (const [locale, labels] of Object.entries(expected)) {
    for (const [key, value] of Object.entries(labels))
      assert.equal(LOCALES[locale][key], value, `${locale}: ${key}`);
    assert.match(LOCALES[locale].wordMotionLimits, /pronoun|代名詞|代词/);
    assert.match(LOCALES[locale].wordMotionLimits, /projection|投影/);
  }
  const data = artifact(1);
  for (const locale of Object.keys(expected)) {
    const { get } = await runReview(data, locale);
    const card = get("candidates").children[0];
    assert.match(
      get("summary").textContent,
      new RegExp(LOCALES[locale].wordMotionNativeCount),
    );
    assert.equal(
      card.children.find((node) => node.className === "evidence-badge")
        .textContent,
      LOCALES[locale].wordMotionNativeReported,
    );
    assert.equal(
      card.querySelectorAll("a")[0].textContent,
      LOCALES[locale].wordMotionNativeAsset,
    );
  }
});
