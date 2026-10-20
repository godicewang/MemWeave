import assert from "node:assert/strict";
import test from "node:test";
import { parseModelCapacity } from "../../src/pi/model-capacity.ts";

test("容量只采纳实际模型的精确 context_window，不猜测 1M 或采用其他模型", () => {
  assert.equal(parseModelCapacity({ data: [{ id: "other", context_window: 8 }, { id: "probe", context_window: 1_048_576 }] }, "probe"), 1_048_576);
  assert.equal(parseModelCapacity({ data: [{ id: "probe", context_window: 101 }] }, "probe"), 101);
  for (const value of [undefined, null, "1M", "1048576", 1, 2.5, -1, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => parseModelCapacity({ data: [{ id: "probe", context_window: value }] }, "probe"), /MODEL_CAPACITY_UNVERIFIED/);
  }
});

test("缺失、重复或冲突的容量信息拒绝发送，不泄露响应正文", () => {
  for (const value of [null, {}, { data: [] }, { data: {} }, { data: [null] },
    { data: [{ id: "other", context_window: 100 }] },
    { data: [{ id: "probe", context_window: 100 }, { id: "probe", context_window: 200 }] },
    { data: [{ id: "probe", contextWindow: 100, secret: "private-fixture" }] }]) {
    assert.throws(() => parseModelCapacity(value, "probe"), error => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /MODEL_CAPACITY_UNVERIFIED/);
      assert.doesNotMatch(error.message, /private-fixture/);
      return true;
    });
  }
});
