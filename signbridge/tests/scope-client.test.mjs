import test from "node:test";
import assert from "node:assert/strict";
import { understand } from "../src/private/private-api.js";
const base = {
  status: "parsed",
  roles: { actor: "我", negation: "不", modal: "想", predicate: "去" },
  csl_translation_trained: false,
};
const eventGraph = {
  type: "operator",
  operator: "negation:不",
  argument: {
    type: "operator",
    operator: "modal:想",
    argument: { type: "event", roles: { actor: "我", predicate: "去" } },
  },
};
const evidence = {
  id: "handref-1",
  human_approved: false,
  word_boundaries_verified: false,
  training_ready: false,
};
const plan = {
  can_play: false,
  motion_items: [],
  components: [
    { role: "actor", text: "我", evidence: [] },
    { role: "negation", text: "不", evidence: [] },
    { role: "modal", text: "想", evidence: [] },
    { role: "predicate", text: "去", evidence: [evidence] },
  ],
  uncovered: ["我", "不", "想"],
};
const request = (body) =>
  understand({
    endpoint: "http://127.0.0.1:8770",
    token: "a".repeat(43),
    text: "我不想去",
    fetchImpl: async () => ({ ok: true, json: async () => body }),
  });

test("scope graph and plan validate as one text-only, non-playable contract", async () => {
  const result = await request({
    ...base,
    event_graph: eventGraph,
    expression_plan: plan,
  });
  assert.deepEqual(result.event_graph, eventGraph);
  assert.equal(result.expression_plan.can_play, false);
  assert.deepEqual(result.expression_plan.motion_items, []);
});

test("malformed or mismatched event graphs and evidence are rejected", async () => {
  for (const event_graph of [
    { type: "operator", operator: "bad", argument: {} },
    { type: "event", roles: [] },
    { type: "event", roles: { actor: 4 } },
    { type: "event", roles: { actor: "他", predicate: "去" } },
  ])
    await assert.rejects(request({ ...base, event_graph }));
  await assert.rejects(
    request({
      ...base,
      event_graph: eventGraph,
      expression_plan: { ...plan, can_play: true, motion_items: [{}] },
    }),
  );
  const forged = { ...evidence, human_approved: true };
  await assert.rejects(
    request({
      ...base,
      event_graph: eventGraph,
      expression_plan: {
        ...plan,
        components: plan.components.map((c) =>
          c.role === "predicate" ? { ...c, evidence: [forged] } : c,
        ),
      },
    }),
  );
  await assert.rejects(
    request({
      ...base,
      event_graph: eventGraph,
      expression_plan: {
        ...plan,
        components: plan.components.map((c) =>
          c.role === "predicate"
            ? { ...c, evidence: [{ ...evidence, id: "x".repeat(129) }] }
            : c,
        ),
      },
    }),
  );
});
