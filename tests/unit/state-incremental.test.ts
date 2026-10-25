import assert from "node:assert/strict";
import test from "node:test";
import { reduceState, extendState, cloneState, type StateEvent } from "../../src/state/model.ts";

const events: StateEvent[] = [
  { op: "update_goal", op_id: "init", time: "t", goal: "goal", evidence: {} },
  { op: "append_fact", op_id: "f1", time: "t", id: "F1", fact: "one", evidence: { U1: "user" } },
  { op: "append_decision", op_id: "d1", time: "t", id: "D1", decision: "two", evidence: { F1: "fact" } },
  { op: "modify_fact", op_id: "replace", time: "t", archive: ["F1"], append_fact: { content: "corrected", evidence: { U1: "user" } } },
  { op: "slide_window", op_id: "slide", time: "t", batch_id: "b", evicted_range: { from: 3, to: 4 }, retained_ids: ["F2"], status: "committed" },
  { op: "update_goal", op_id: "goal2", time: "t", goal: "new goal", evidence: { F2: "fact" } },
];
test("incremental State matches full replay, without mutating previous states or new inputs", () => {
  let state = reduceState(events.slice(0, 1));
  for (let i = 1; i < events.length; i++) {
    const previous = structuredClone(state), input = structuredClone(events[i]!);
    const next = extendState(state, [input]);
    assert.deepEqual(next, reduceState(events.slice(0, i + 1)));
    assert.deepEqual(state, previous);
    input.op_id = "caller changed";
    assert.equal(next.events.at(-1)?.op_id, events[i]!.op_id);
    state = next;
  }
  const copy = cloneState(state);
  copy.entries.get("F2")!.evidence.U1 = "changed";
  copy.events[0]!.op_id = "changed";
  copy.entries.clear();
  copy.facts.length = 0;
  assert.deepEqual(state, reduceState(events));
});
test("invalid incremental operations reject with no partial changes to previous State", () => {
  const state = reduceState(events.slice(0, 4)), before = structuredClone(state);
  for (const invalid of [
    events[1]!,
    { ...events[4]!, retained_ids: ["F999"] },
    { ...events[3]!, op_id: "bad", archive: ["F2", "F999"] },
    { ...events[1]!, op_id: "bad", id: "F999" },
  ]) {
    assert.throws(() => extendState(state, [invalid]), /CORRUPT_STATE/);
    assert.deepEqual(state, before);
  }
});
