import test from "node:test";
import assert from "node:assert/strict";
import { createModelSession } from "../src/demo/model-demo-session.js";

test("late inference cannot replace newer input or a stopped session", async () => {
  const pending = [];
  const changes = [];
  const stops = [];
  const s = createModelSession({
    predict: (text, signal) =>
      new Promise((resolve) => pending.push({ text, signal, resolve })),
    onResult: (value) => changes.push(value),
    onStop: () => stops.push(1),
  });
  const first = s.analyze("我帮你");
  const second = s.analyze("你帮我");
  pending[0].resolve({ input: "我帮你" });
  await first;
  assert.equal(changes.length, 0);
  assert.equal(pending[0].signal.aborted, true);
  pending[1].resolve({ input: "你帮我" });
  await second;
  assert.deepEqual(changes, [{ input: "你帮我" }]);
  const third = s.analyze("我们");
  s.clear();
  pending[2].resolve({ input: "我们" });
  await third;
  assert.equal(changes.length, 1);
  assert.equal(stops.length, 4);
});

test("a current network failure clears old result and is surfaced, stale failures ignored", async () => {
  const errors = [];
  let fail;
  const s = createModelSession({
    predict: () =>
      new Promise((resolve, reject) => {
        fail = reject;
      }),
    onResult: () => {},
    onStop: () => {},
    onError: (e) => errors.push(e.message),
  });
  const p = s.analyze("我");
  fail(new Error("offline"));
  await p;
  assert.deepEqual(errors, ["offline"]);
});
