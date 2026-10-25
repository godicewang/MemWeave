import assert from "node:assert/strict";
import test from "node:test";
import { createRequestCounter } from "../../src/window/request-counter.ts";
import { conservativeCounter, deepseekCounter } from "../../src/window/tokens.ts";
import { allocate, type BudgetMessage } from "../../src/window/budget.ts";

test("request counter reuses equal strings, delegates prefix, and releases on dispose", () => {
  const calls: string[] = [];
  const base = { estimator: "test", count(text: string) { calls.push(text); return [...text].length; },
    prefix(text: string, tokens: number) { return [...text].slice(0, tokens).join(""); } };
  const scope = createRequestCounter(base, 4, 4096);
  assert.equal(scope.counter.estimator, base.estimator);
  assert.equal(scope.counter.count("😀中文"), 3);
  assert.equal(scope.counter.count(["😀", "中", "文"].join("")), 3);
  assert.deepEqual(calls, ["😀中文"]);
  assert.equal(scope.counter.prefix?.("😀中文", 2), "😀中");
  assert.equal(scope.size, 1);
  scope.dispose();
  assert.equal(scope.size, 0); assert.equal(scope.bytes, 0);
  scope.counter.count("😀中文"); scope.counter.count("😀中文");
  assert.equal(calls.length, 3);
  assert.equal(scope.size, 0);
  const other = createRequestCounter({ ...base, count: () => 99 });
  assert.equal(other.counter.count("😀中文"), 99);
  other.dispose();
});

test("request counter enforces LRU/byte limits, skips large/failed entries and supports disabled cache", () => {
  const calls: string[] = [];
  const base = { estimator: "test", count(text: string) {
    calls.push(text); if (text === "bad") throw Error("expected"); return text.length;
  } };
  const scope = createRequestCounter(base, 2, 256);
  for (const text of ["a", "b", "a", "c", "b"]) scope.counter.count(text);
  assert.deepEqual(calls, ["a", "b", "c", "b"]);
  assert.equal(scope.size, 2); assert.ok(scope.bytes <= 256);
  for (let i = 0; i < 2; i++) {
    scope.counter.count("x".repeat(1000));
    assert.throws(() => scope.counter.count("bad"), /expected/);
  }
  assert.equal(calls.filter((text) => text === "bad").length, 2);
  assert.equal(scope.size, 2);
  scope.dispose();
  const disabled = createRequestCounter(base, 0, 0);
  disabled.counter.count("a"); disabled.counter.count("a");
  assert.equal(disabled.size, 0);
  disabled.dispose();
  const bytesOnly = createRequestCounter(base, 20, 110);
  bytesOnly.counter.count("a"); bytesOnly.counter.count("b");
  assert.equal(bytesOnly.size, 1);
  bytesOnly.dispose();
  const cheap = createRequestCounter(conservativeCounter);
  assert.equal(cheap.counter.count("中文😀"), conservativeCounter.count("中文😀"));
  cheap.counter.count("中文😀");
  assert.equal(cheap.size, 0);
  cheap.dispose();
});

test("request memoization preserves official/conservative allocations, Unicode, protocol and pool limits exactly", async () => {
  for (const base of [conservativeCounter, await deepseekCounter()]) {
    const messages: BudgetMessage[] = Array.from({ length: 10 }, (_, i) => ({
      message: { role: "user", content: ("中文😀日志" + i).repeat(1500), timestamp: i },
      head: "[U" + (i + 1) + "]", exempt: false, event: String(i),
      group: i > 7 ? "recent" : "older",
    }));
    messages.push({ message: { role: "user", content: "最新要求", timestamp: 11 },
      head: "[CURRENT_USER_MESSAGE]", exempt: true, event: "latest", group: "recent" });
    messages[0] = { ...messages[0]!, read: true, exempt: true };
    messages[1] = { ...messages[1]!, group: "expired" };
    const input = { limit: 30000, capacity: 50000, system: 100, state: 200, output: 1000,
      reminder: 100, messages, imageCost: () => 2048 };
    const original = structuredClone(messages), expected = allocate({ ...input, counter: base });
    const scope = createRequestCounter(base);
    try {
      assert.deepEqual(allocate({ ...input, counter: scope.counter }), expected);
      assert.deepEqual(messages, original);
    } finally { scope.dispose(); }
    assert.equal(scope.size, 0);
  }
});
