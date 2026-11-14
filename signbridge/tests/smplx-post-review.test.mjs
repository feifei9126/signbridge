import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import vm from "node:vm";
import { LOCALES } from "../src/i18n/locales.js";

const source = new URL("../src/tools/smplx-post-review.js", import.meta.url);
const html = new URL("../src/tools/smplx-post-review.html", import.meta.url);

class Element {
  constructor(tagName = "div") {
    Object.assign(this, {
      tagName,
      children: [],
      attributes: {},
      dataset: {},
      listeners: {},
      value: "",
      disabled: false,
      hidden: false,
      open: false,
      pauses: 0,
      loads: 0,
      _text: "",
    });
  }
  set innerHTML(_) {
    assert.fail("Untrusted metadata reached HTML");
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
  setAttribute(key, value) {
    this.attributes[key] = String(value);
  }
  removeAttribute(key) {
    delete this.attributes[key];
    if (key === "src") delete this.src;
  }
  addEventListener(type, handler) {
    (this.listeners[type] ??= []).push(handler);
  }
  dispatch(type) {
    if (!this.disabled)
      for (const fn of this.listeners[type] || []) fn({ target: this });
  }
  querySelectorAll(tag) {
    return this.children.flatMap((child) => [
      ...(child.tagName === tag ? [child] : []),
      ...child.querySelectorAll(tag),
    ]);
  }
  pause() {
    this.pauses++;
  }
  load() {
    this.loads++;
  }
}

function record(index, overrides = {}) {
  const folder = `media/row-${String(index).padStart(6, "0")}-candidate`;
  return {
    uid: `candidate-${index}`,
    label_candidate: index % 2 ? "hello" : "候选",
    annotation_id: `fit-${index}`,
    source_id: `source-${index}`,
    chunk: "chunk-1",
    source_sha256: "a".repeat(64),
    quality_tier:
      index % 2
        ? "quarantine_missing_detections"
        : "no_automatic_motion_red_flag",
    review_status: index % 2 ? "quarantined_candidate" : "candidate_only",
    missing_detection_frames: index % 2 ? [2] : [],
    raw_rotation_metrics: null,
    review_frames: [4, 2],
    frames_expected: 4,
    fps: 5,
    processed_frames: 4,
    media: {
      contact: { path: `${folder}/contact.jpg` },
      original: { path: `${folder}/original.mp4` },
      comparison: { path: `${folder}/comparison.mp4` },
    },
    failures: [],
    human_approved: false,
    semantic_approved: false,
    training_ready: false,
    model_training_ready: false,
    ...overrides,
  };
}

function freeze(obj) {
  if (obj && typeof obj === "object") {
    Object.values(obj).forEach(freeze);
    Object.freeze(obj);
  }
  return obj;
}

function run(
  records = Array.from({ length: 55 }, (_, i) => record(i)),
  locale = "en",
) {
  assert.ok(existsSync(source), "Offline post-fit viewer is missing");
  const elements = new Map(
    [
      ...readFileSync(html, "utf8").matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"/g),
    ].map(([, tag, id]) => [id, new Element(tag)]),
  );
  const localized = [
    ...readFileSync(html, "utf8").matchAll(/data-i18n="([^"]+)"/g),
  ].map(([, key]) => {
    const el = new Element();
    el.dataset.i18n = key;
    return el;
  });
  const document = Object.assign(new Element(), {
    documentElement: new Element("html"),
    createElement: (tag) => new Element(tag),
    querySelector: (selector) => {
      assert.ok(elements.has(selector.slice(1)), selector);
      return elements.get(selector.slice(1));
    },
    querySelectorAll: (selector) => {
      assert.equal(selector, "[data-i18n]");
      return localized;
    },
  });
  const window = new Element();
  const data = freeze({
    records,
    summary: {
      total_records: records.length,
      successful_media: 3 * records.length,
      processed_frames: records.length * 4,
      failed_candidates: 0,
      failure_count: 0,
    },
  });
  const context = vm.createContext({
    document,
    window,
    URL,
    location: { href: `file:///review/index.html?lang=${locale}` },
    SIGNBRIDGE_POST_FIT_REVIEW: data,
    SIGNBRIDGE_POST_FIT_LOCALES: Object.fromEntries(
      Object.entries(LOCALES).map(([key, dict]) => [
        key,
        Object.fromEntries(
          Object.entries(dict).filter(([name]) => name.startsWith("postFit")),
        ),
      ]),
    ),
    fetch: () => assert.fail("file:// review must never fetch"),
  });
  vm.runInContext(readFileSync(source, "utf8"), context);
  return {
    get: (id) => elements.get(`post-fit-${id}`),
    document,
    window,
    context,
    localized,
  };
}

test("offline HTML has adjacent classic scripts, CSP, no network or modules", () => {
  assert.ok(existsSync(html), "Offline post-fit HTML is missing");
  const value = readFileSync(html, "utf8");
  assert.match(value, /src="review-data\.js"/);
  assert.match(value, /src="review\.js"/);
  assert.match(value, /href="review\.css"/);
  assert.match(value, /connect-src 'none'/);
  assert.doesNotMatch(value, /https?:|type="module"|autoplay|onclick=/i);
});

test("2112 records create only 24 cards, no videos until explicit demand, release on page change", () => {
  const { get } = run(Array.from({ length: 2112 }, (_, i) => record(i)));
  assert.equal(get("records").children.length, 24);
  assert.equal(get("records").querySelectorAll("video").length, 0);
  const first = get("records").children[0];
  const button = first
    .querySelectorAll("button")
    .find((el) => el.dataset.media === "comparison");
  assert.ok(button);
  button.dispatch("click");
  const video = first.querySelectorAll("video")[0];
  assert.equal(video.preload, "none");
  assert.equal(video.autoplay, undefined);
  assert.equal(video.controls, true);
  assert.match(video.src, /comparison\.mp4$/);
  get("next").dispatch("click");
  assert.ok(video.pauses > 0);
  assert.equal(video.src, undefined);
  assert.equal(get("records").children.length, 24);
  assert.match(get("records").children[0].textContent, /candidate-24/);
  assert.match(get("count").textContent, /25.*48.*2112/);
});

test("search and quality filter reset and bound pagination, no all-record DOM", () => {
  const { get } = run();
  get("next").dispatch("click");
  get("search").value = "hello";
  get("search").dispatch("input");
  assert.equal(get("records").children.length, 24);
  assert.match(get("count").textContent, /1.*24.*27/);
  get("quality").value = "no_automatic_motion_red_flag";
  get("quality").dispatch("change");
  assert.equal(get("records").children.length, 0);
  assert.equal(get("empty").hidden, false);
  get("search").value = "";
  get("search").dispatch("input");
  assert.equal(get("records").children.length, 24);
  get("next").dispatch("click");
  assert.equal(get("records").children.length, 4);
  assert.equal(get("next").disabled, true);
});

test("unknown metrics stay unknown; malicious metadata stays text and unsafe media never loads", () => {
  const attack = '</script><img src=x onerror="alert(1)">';
  for (const path of [
    "javascript:alert(1)",
    "https://evil.test/a.mp4",
    "../original.mp4",
    "/tmp/a.mp4",
    "media/ok/../original.mp4",
    "media/%2e%2e/original.mp4",
    "media/ok/original.mp4?x=1",
    "media/ok\\original.mp4",
  ]) {
    const { get } = run([
      record(0, {
        label_candidate: attack,
        source_id: attack,
        raw_rotation_metrics: null,
        media: { contact: { path }, original: { path }, comparison: { path } },
      }),
    ]);
    const card = get("records").children[0];
    assert.ok(card.textContent.includes(attack));
    assert.ok(card.textContent.includes(LOCALES.en.postFitUnknown));
    assert.equal(card.querySelectorAll("img").length, 0);
    assert.equal(card.querySelectorAll("video").length, 0);
    assert.equal(card.querySelectorAll("button").length, 0);
  }
});

test("every row keeps the nonapproval warning even when untrusted data claims approval", () => {
  const { get } = run([
    record(0, {
      human_approved: true,
      semantic_approved: true,
      training_ready: true,
    }),
    null,
  ]);
  assert.equal(get("records").children.length, 2);
  for (const card of get("records").children)
    assert.ok(card.textContent.includes(LOCALES.en.postFitCandidateOnly));
  assert.ok(
    get("summary-note").textContent.includes(LOCALES.en.postFitCandidateOnly),
  );
  for (const card of get("records").children)
    assert.ok(card.textContent.includes(LOCALES.en.postFitUnassessedQuality));
  assert.ok(
    get("summary-note").textContent.includes(
      LOCALES.en.postFitUnassessedQuality,
    ),
  );
});

test("all postFit strings are registered in Chinese English Japanese with matching placeholders", () => {
  assert.ok(existsSync(source), "Offline post-fit viewer is missing");
  const sourceText = readFileSync(source, "utf8") + readFileSync(html, "utf8");
  const keys = new Set(
    [...sourceText.matchAll(/\b(postFit[A-Z]\w*)\b/g)].map((match) => match[1]),
  );
  assert.ok(keys.size > 25);
  for (const locale of ["zh-CN", "en", "ja"]) {
    for (const key of keys) {
      assert.equal(typeof LOCALES[locale][key], "string", `${locale}: ${key}`);
      const placeholders = (value) =>
        [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
      assert.deepEqual(
        placeholders(LOCALES[locale][key]),
        placeholders(LOCALES.en[key]),
      );
    }
    const { get, localized } = run([record(0)], locale);
    assert.ok(
      get("summary-note").textContent.includes(
        LOCALES[locale].postFitCandidateOnly,
      ),
    );
    for (const element of localized)
      assert.equal(element.textContent, LOCALES[locale][element.dataset.i18n]);
  }
});
