import assert from "node:assert/strict";
import test from "node:test";
import { Check } from "typebox/value";
import { reduceState, type StateEvent } from "../../src/state/model.ts";
import {
  StateReadSchema,
  readHistoricalState,
  historyReadRanges,
} from "../../src/state/read.ts";
const events: StateEvent[] = [
  {
    op_id: "g",
    op: "update_goal",
    goal: "Audit history",
    evidence: {},
    time: "now",
  },
  {
    op_id: "f1",
    op: "append_fact",
    id: "F1",
    fact: "旧事实😀",
    evidence: { U1: "用户原要求" },
    time: "now",
  },
  {
    op_id: "d1",
    op: "append_decision",
    id: "D1",
    decision: "旧决定",
    evidence: { F1: "事实依据" },
    time: "now",
  },
  {
    op_id: "f2",
    op: "append_fact",
    id: "F2",
    fact: "当前事实",
    evidence: { F1: "历史依据", D1: "此前决定" },
    time: "now",
  },
  {
    op_id: "slide",
    op: "slide_window",
    batch_id: "batch",
    evicted_range: { from: 2, to: 2 },
    retained_ids: [],
    status: "committed",
    time: "now",
  },
  {
    op_id: "correct",
    op: "modify_fact",
    archive: ["D1"],
    append_fact: { content: "修正后事实", evidence: { D1: "保留原决定依据" } },
    time: "now",
  },
];
test("historical State input preserves legacy reads and bounds explicit F/D queries", () => {
  const wireSchema = JSON.parse(JSON.stringify(StateReadSchema));
  assert.equal(wireSchema.type, "object");
  assert.ok(wireSchema.properties);
  assert.equal(Check(StateReadSchema, { task_id: "task_a" }), true);
  assert.equal(
    Check(StateReadSchema, {
      task_id: "task_a",
      event_ids: ["F1", "D1"],
      max_total_chars: 50000,
    }),
    true,
  );
  for (const value of [
    { task_id: "task_a", max_total_chars: 20 },
    { task_id: "task_a", event_ids: [] },
    { task_id: "task_a", event_ids: ["U1"] },
    { task_id: "task_a", event_ids: ["F1"], max_total_chars: 50001 },
    { task_id: "task_a", event_ids: ["F1"], max_total_chars: 0 },
    { task_id: "task_a", event_ids: Array(51).fill("F1") },
    { task_id: "task_a", event_ids: ["F1"], unexpected: true },
  ])
    assert.equal(Check(StateReadSchema, value), false);
});
test("historical State returns evicted, archived and active original entries in input order without mutating replay", () => {
  const state = reduceState(events),
    before = structuredClone(state);
  const result = readHistoricalState("task_a", state, {
    event_ids: ["F1", "D1", "F999", "F2", "F1"],
  });
  assert.deepEqual(
    result.items.map((item) => item.id),
    ["F1", "D1", "F999", "F2", "F1"],
  );
  assert.equal(result.state_version, 6);
  assert.equal(result.items[0]!.content, "旧事实😀");
  assert.deepEqual(result.items[0]!.evidence, { U1: "用户原要求" });
  assert.equal(result.items[0]!.in_window, false);
  assert.equal(result.items[0]!.archived, false);
  assert.equal(result.items[1]!.archived, true);
  assert.equal(result.items[1]!.in_window, false);
  assert.equal(result.items[2]!.status, "not_found");
  assert.equal(result.items[2]!.total_chars, null);
  assert.equal(result.items[3]!.in_window, true);
  assert.deepEqual(state, before);
  const ranges = historyReadRanges(result);
  assert.equal(ranges[0]!.range_complete, true);
  assert.equal(ranges[2]!.range_complete, false);
  assert.equal(
    result.total_chars,
    result.items.reduce((sum, item) => sum + item.returned_chars, 0),
  );
});
test("historical State shared budget counts Unicode body and evidence; never cuts an evidence ID", () => {
  const state = reduceState(events);
  const tiny = readHistoricalState("task_a", state, {
    event_ids: ["F1", "D1", "F999"],
    max_total_chars: 4,
  });
  assert.equal(tiny.items[0]!.content, "旧事实😀");
  assert.deepEqual(tiny.items[0]!.evidence, {});
  assert.equal(tiny.items[0]!.truncated, true);
  assert.equal(tiny.items[1]!.status, "budget_exhausted");
  assert.equal(tiny.items[2]!.status, "not_found");
  assert.equal(tiny.total_chars, 4);
  const partial = readHistoricalState("task_a", state, {
    event_ids: ["F1"],
    max_total_chars: 7,
  });
  assert.deepEqual(partial.items[0]!.evidence, { U1: "用" });
  assert.equal(partial.total_chars, 7);
  assert.equal(historyReadRanges(partial)[0]!.range_complete, false);
});
test("historical State default 8000 budget includes long evidence and fixed 50000 maximum", () => {
  const state = reduceState([
    { op_id: "g", op: "update_goal", goal: "goal", evidence: {}, time: "now" },
    {
      op_id: "f",
      op: "append_fact",
      id: "F1",
      fact: "x",
      evidence: { U1: "😀".repeat(60000) },
      time: "now",
    },
  ]);
  assert.equal(
    readHistoricalState("task_a", state, { event_ids: ["F1"] }).total_chars,
    8000,
  );
  const full = readHistoricalState("task_a", state, {
    event_ids: ["F1"],
    max_total_chars: 50000,
  });
  assert.equal(full.total_chars, 50000);
  assert.equal(full.items[0]!.truncated, true);
  assert.throws(
    () => historyReadRanges({ ...full, total_chars: 1 }),
    /INVALID_STATE_READ_RESULT/,
  );
});
