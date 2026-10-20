import assert from "node:assert/strict";
import test from "node:test";
import { deriveContextLimit } from "../../src/pi/context-limit.ts";
import { assertSupportedHost } from "../../src/pi/request-lifecycle.ts";

test("Agent 上限使用经核验的精确 token 容量并向下取整", () => {
  assert.equal(deriveContextLimit(1_048_576), 524_288);
  assert.equal(deriveContextLimit(1_000_000), 500_000);
  assert.equal(deriveContextLimit(131_073), 65_536);
});

test("未验收的 Pi 版本有明确诊断，peer 通配符不是兼容声明", () => {
  assert.doesNotThrow(() => assertSupportedHost("1.3.0"));
  for (const version of ["1.1.0", "1.3.1", "2.0.0", "unknown"]) {
    assert.throws(() => assertSupportedHost(version), /UNVERIFIED_PI_VERSION/);
  }
});

test("未知或非法模型容量不能退回完整上下文", () => {
  for (const value of [undefined, "1M", 0, -1, 2.5, Infinity, NaN]) {
    assert.throws(() => deriveContextLimit(value), /MODEL_CAPACITY_UNVERIFIED/);
  }
});
