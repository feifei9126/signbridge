import test from "node:test";
import assert from "node:assert/strict";
import { SIGNS } from "../src/avatar/sign-language-data.js";
import { planDemoText } from "../src/demo/demo-motion.js";
import {
  buildDemoPhraseCatalog,
  COMPOSED_PHRASES,
} from "../src/demo/phrase-catalog.js";

test("only completely matched dictionary compositions are advertised", () => {
  assert.ok(COMPOSED_PHRASES.length > 0 && COMPOSED_PHRASES.length < 53);
  assert.ok(!COMPOSED_PHRASES.some((p) => p.text === "我很好"));
  assert.equal(
    new Set(COMPOSED_PHRASES.map((phrase) => phrase.text)).size,
    COMPOSED_PHRASES.length,
  );
  assert.equal(
    new Set(COMPOSED_PHRASES.map((phrase) => phrase.id)).size,
    COMPOSED_PHRASES.length,
  );

  for (const phrase of COMPOSED_PHRASES) {
    const plan = planDemoText(phrase.text, "dictionary");
    assert.equal(plan.unmatched, "", `${phrase.id} leaves unsupported text`);
    assert.ok(
      plan.items.length >= 2,
      `${phrase.id} is not a phrase composition`,
    );
    assert.ok(plan.items.every((item) => item.source === "dictionary"));
    assert.equal(phrase.source, "composition");
    assert.equal(phrase.training_data_member, false);
    assert.equal(phrase.training_ready, false);
  }
  assert.ok(Object.keys(SIGNS).length >= 52);
});

test("catalog counts only supported combinations without implying training", () => {
  const references = Array.from({ length: 14 }, (_, index) => ({
    id: `reference-${index}`,
    text: `参考短句${index}`,
    runtime_candidate: false,
  }));
  const candidates = Array.from({ length: 3 }, (_, index) => ({
    id: `candidate-${index}`,
    text: `候选短句${index}`,
    runtime_candidate: true,
  }));

  const catalog = buildDemoPhraseCatalog([...references, ...candidates]);
  assert.equal(catalog.length, 17 + COMPOSED_PHRASES.length);
  assert.equal(
    new Set(catalog.map((entry) => entry.id)).size,
    17 + COMPOSED_PHRASES.length,
  );
  assert.equal(catalog.filter((entry) => entry.source === "t08").length, 14);
  assert.equal(
    catalog.filter((entry) => entry.source === "candidate").length,
    3,
  );
  assert.equal(
    catalog.filter((entry) => entry.source === "composition").length,
    COMPOSED_PHRASES.length,
  );
  assert.ok(
    catalog
      .filter((entry) => entry.source !== "t08")
      .every((entry) => entry.training_ready === false),
  );
});
