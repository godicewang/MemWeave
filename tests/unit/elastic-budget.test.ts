import assert from "node:assert/strict";
import test from "node:test";
import { allocate, ordinaryText, renderAllocated, renderMessage, type BudgetMessage } from "../../src/window/budget.ts";
import { mergeConfig } from "../../src/config/schema.ts";
import { settingsFor } from "../../src/config/defaults.ts";
import { boundMemoryRead, boundStateRead } from "../../src/window/read-budget.ts";
import { historyReadRanges, readHistoricalState } from "../../src/state/read.ts";
import { reduceState } from "../../src/state/model.ts";
import { eventGroups, indexEvents } from "../../src/window/select.ts";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { deepseekCounter } from "../../src/window/tokens.ts";

const counter = { count: (text: string) => [...text].length, estimator: "test" };
const item = (text: string, group: BudgetMessage["group"] = "older", event = "e"): BudgetMessage => ({
  message: { role: "user", content: text, timestamp: 1 }, head: "[U1]", exempt: false, group, event,
});
const base = { limit: 600000, capacity: 1000000, system: 15000, state: 25000, output: 60000,
  reminder: 35000, imageCost: () => 2048, counter };

test("40/40/20 pools count mandatory costs once, never lend read or safety, and do not fill short demand", () => {
  const inputs = [item("a".repeat(400000))];
  const budget = allocate({ ...base, messages: inputs });
  assert.equal(budget.peak, 800000);
  assert.equal(budget.K, 165036); // includes base safety, native user envelope
  assert.equal(budget.F, budget.peak - budget.K);
  assert.equal(budget.readLimit, Math.floor(budget.F * .4));
  assert.equal(budget.windowLimit, Math.floor(budget.F * .4));
  assert.equal(budget.poolSafety, budget.F - budget.readLimit - budget.windowLimit);
  assert.ok(budget.windowUsed <= budget.windowLimit);
  assert.equal(budget.X, 0);
  assert.ok(counter.count(ordinaryText(renderAllocated(inputs[0]!, budget.allocations[0]!, counter))) <= budget.windowLimit);
  const short = allocate({ ...base, messages: [item("short")] });
  assert.equal(short.windowUsed, 10);
  assert.ok(short.total < short.peak - short.poolSafety - short.readLimit);
});

test("mandatory costs can use extra 20% but cannot use outer or pool safety", () => {
  assert.ok(allocate({ ...base, system: 600000, messages: [] }).K > base.limit);
  assert.throws(() => allocate({ ...base, system: 800000, messages: [] }), /CONTEXT_BUDGET_EXCEEDED/);
});

test("event weights saturate short groups, redistribute only Window, and cap all expired reads", () => {
  const messages = [item("x".repeat(900000), "current", "c"), item("x".repeat(900000), "recent", "r"),
    item("x".repeat(900000), "older", "o"), item("x".repeat(900000), "expired", "z")];
  const b = allocate({ ...base, messages });
  assert.ok(b.expiredUsed <= Math.floor(b.windowLimit * .1));
  const q = b.allocations.map(a => a.tokens);
  assert.ok(q[0]! > q[1]! && q[1]! > q[2]!);
  messages[0] = item("s", "current", "c");
  const small = allocate({ ...base, messages });
  assert.equal(small.allocations[0]!.tokens, 6);
  assert.ok(small.allocations[1]!.tokens > q[1]!);
  assert.ok(small.expiredUsed <= Math.floor(small.windowLimit * .1));
});

test("active reads truncate to their own pool without aborting or changing originals; Unicode tag fits", () => {
  const read = { ...item("😀正文".repeat(200000)), read: true, exempt: true };
  const original = structuredClone(read);
  const b = allocate({ ...base, messages: [read, item("window".repeat(100000))] });
  const rendered = renderAllocated(read, b.allocations[0]!, counter);
  assert.match(ordinaryText(rendered), /\[TRUNCATED\]$/);
  assert.ok(counter.count(ordinaryText(rendered)) <= b.readLimit);
  assert.ok(b.X <= b.readLimit);
  assert.deepEqual(read, original);
  assert.ok(b.windowUsed <= b.windowLimit);
});

test("new policy deep overrides are validated while old config and six-field scopes remain compatible", () => {
  const config = mergeConfig({ recent_turns: 20, evict_turns: 4, elastic_budget: {
    extra_model_percent: 10, window_weights: { current: 40, recent: 45 },
  } });
  assert.equal(settingsFor(config).elastic_budget.pool_percent.read, 40);
  assert.equal(settingsFor(config).elastic_budget.window_weights.older, 15);
  for (const elastic_budget of [{ extra_model_percent: 21 }, { pool_percent: { read: 41 } },
    { window_weights: { older: 0 } }, { expired_read_percent: 100.001 }, { recent_events: 0 }])
    assert.throws(() => mergeConfig({ elastic_budget }, {}, 600000), /INVALID_CONFIG/);
  assert.throws(() => mergeConfig({}, { elastic_budget: { extra_model_percent: 10 } }, 600000), /INVALID_CONFIG/);
});

test("token-limited read returns keep valid metadata, code-point offsets and truthful ranges", () => {
  const output = { result: { total_chars: 1000, items: [{ ref: "U1", content: "😀".repeat(1000), offset: 17,
    total_chars: 1017, source_complete: true, range_complete: true, truncated: true, status: "ok" }] }, images: [] };
  const old = structuredClone(output);
  const bounded = boundMemoryRead(output, 400, counter, () => 2048);
  assert.ok(bounded.tokens <= 400);
  assert.equal(bounded.value.result.items[0]!.offset, 17);
  assert.equal(bounded.value.result.items[0]!.range_complete, false);
  assert.equal(bounded.value.result.total_chars, [...bounded.value.result.items[0]!.content].length);
  assert.equal(bounded.truncated, true);
  assert.deepEqual(output, old);
  assert.throws(() => boundMemoryRead(output, 1, counter, () => 2048), /READ_BUDGET_EXCEEDED/);
});

test("historical State token truncation preserves evidence keys and validated returned character counts", () => {
  const state = reduceState([{ op: "update_goal", op_id: "g", goal: "g", evidence: {}, time: "now" },
    { op: "append_fact", op_id: "f", id: "F1", fact: "事实", evidence: { U1: "依据😀".repeat(1000) }, time: "now" }]);
  const original = readHistoricalState("task_a", state, { event_ids: ["F1"] });
  const result = boundStateRead(original, 450, counter);
  assert.ok(result.tokens <= 450);
  assert.equal(result.truncated, true);
  assert.equal(historyReadRanges(result.value)[0]!.range_complete, false);
  assert.ok(Object.keys(result.value.items[0]!.evidence).every(key => key === "U1"));
  assert.equal(result.value.items[0]!.total_chars, original.items[0]!.total_chars);
});

test("images are indivisible, omitted images cannot claim a complete range, and returned image bytes are unchanged", () => {
  const image = { type: "image" as const, mimeType: "image/png", data: "native-bytes" };
  const output = { result: { total_chars: 0, items: [{ ref: "R1", content: "", offset: 0, total_chars: 0,
    source_complete: true, range_complete: true, truncated: false, status: "ok" }] }, images: [image], imageItems: [0] };
  const bounded = boundMemoryRead(output, 400, counter, () => 2048);
  assert.equal(bounded.value.images.length, 0);
  assert.equal(bounded.value.result.items[0]!.range_complete, false);
  assert.equal(bounded.truncated, true);
  assert.deepEqual(boundMemoryRead(output, 4000, counter, () => 2048).value.images, [image]);
  assert.deepEqual(output.images, [image]);
});

test("temporal groups use complete events and only a trailing tool round gets the current share", () => {
  const entries = Array.from({ length: 5 }, (_, i) => ({ type: "message" as const, id: `u${i}`, parentId: null,
    timestamp: "now", message: { role: "user" as const, content: "u", timestamp: i } }));
  const events = indexEvents(entries);
  assert.deepEqual([...eventGroups(events, 3).values()], ["older", "older", "recent", "recent", "recent"]);
  const round = { id: "a", messages: [{ entryId: "a", message: fauxAssistantMessage([fauxToolCall("read", { path: "x" })]) }] };
  assert.deepEqual([...eventGroups([...events, round], 3).values()], ["older", "older", "recent", "recent", "recent", "current"]);
});

test("exact capacity rounding and outer reserve remain safe for odd and maximum safe capacities", () => {
  for (const capacity of [1000001, Number.MAX_SAFE_INTEGER]) {
    const limit = Number(BigInt(capacity) * 3n / 5n), extra = Number(BigInt(capacity) / 5n);
    const b = allocate({ ...base, capacity, limit, messages: [] });
    assert.equal(b.peak, limit + extra);
    assert.equal(b.F, b.readLimit + b.windowLimit + b.poolSafety);
    assert.ok(capacity - b.peak >= extra);
  }
  assert.throws(() => allocate({ ...base, limit: 800000, messages: [] }), /CONTEXT_BUDGET_EXCEEDED/);
});

test("token-prefix hints preserve Unicode source prefixes and every final rendered quota is verified", async () => {
  const official = await deepseekCounter();
  assert.equal(typeof official.prefix, "function");
  const body = "原文😀é👩‍💻 \" [bos] punctuation...\n".repeat(20);
  for (let quota = official.count("[U1]\n\n[TRUNCATED]"); quota < 65; quota++) {
    const message = { ...item(body), head: "[U1]" };
    const b = allocate({ ...base, counter: official, messages: [message] });
    const shown = renderAllocated(message, { ...b.allocations[0]!, tokens: quota }, official);
    const text = ordinaryText(shown);
    assert.ok(official.count(text) <= quota);
    assert.ok(body.startsWith(text.slice("[U1]\n".length, -"\n[TRUNCATED]".length)));
  }
});

test("unusable or over-budget prefix hints fall back to verified Unicode truncation", () => {
  const message = item("abcdef😀".repeat(200)).message;
  for (const prefix of [() => undefined, () => "not the source", (text: string) => text]) {
    const value = renderMessage(message, "[U1]", 40, false, { ...counter, prefix });
    const text = ordinaryText(value);
    assert.ok(counter.count(text) <= 40);
    assert.match(text, /\[TRUNCATED\]$/);
  }
});
