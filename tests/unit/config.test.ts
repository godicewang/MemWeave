import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DEFAULT_CONFIG, mergeConfig, parseConfig } from "../../src/config/schema.ts";
import { readConfigSnapshot } from "../../src/config/read.ts";
import { memoryPaths } from "../../src/storage/paths.ts";

test("配置契约有六个明确默认值，返回不可变快照", () => {
  assert.deepEqual(DEFAULT_CONFIG, {
    recent_turns: 200, evict_turns: 40, state_max_events: 500,
    state_event_max_chars: 100, state_evict_batch: 100, state_keep_limit: 20,
  });
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
  const input = { ...DEFAULT_CONFIG };
  const parsed = parseConfig(input);
  input.recent_turns = 300;
  assert.equal(parsed.recent_turns, 200);
  assert.ok(Object.isFrozen(parsed));
});

test("拒绝多余字段、非对象与非法数字；缺省字段继承默认值，不能静默修复 N/B", () => {
  for (const bad of [null, [], "200", { ...DEFAULT_CONFIG, unknown: 1 },
    { ...DEFAULT_CONFIG, recent_turns: 10 }, { ...DEFAULT_CONFIG, evict_turns: 201 }]) {
    assert.throws(() => parseConfig(bad), /INVALID_CONFIG/);
  }
  for (const key of Object.keys(DEFAULT_CONFIG)) {
    for (const value of [0, -1, 1.5, "200", true, undefined, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      assert.throws(() => parseConfig({ ...DEFAULT_CONFIG, [key]: value }), /INVALID_CONFIG/);
    }
  }
});

test("覆盖只影响当前快照，未指定值保留，非法组合不静默调整", () => {
  const original = { ...DEFAULT_CONFIG };
  const first = mergeConfig(original, { recent_turns: 240, evict_turns: 30 });
  const second = mergeConfig(original, { recent_turns: 300 });
  assert.equal(first.recent_turns, 240); assert.equal(first.evict_turns, 30);
  assert.equal(second.recent_turns, 300); assert.equal(second.evict_turns, 40);
  assert.deepEqual(original, DEFAULT_CONFIG);
  assert.throws(() => mergeConfig(original, { recent_turns: 5 }), /INVALID_CONFIG/);
  assert.throws(() => mergeConfig(original, { extra: 1 }), /INVALID_CONFIG/);
});

test("配置读取一次；热改下轮生效，不回写文件或沿用错误前的配置", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-phase1-config-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  await writeFile(paths.config, JSON.stringify(DEFAULT_CONFIG));
  const first = await readConfigSnapshot(paths, { recent_turns: 240 });
  assert.deepEqual(JSON.parse(await readFile(paths.config, "utf8")), DEFAULT_CONFIG);
  await writeFile(paths.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 300 }));
  assert.equal((await readConfigSnapshot(paths)).recent_turns, 300);
  assert.equal(first.recent_turns, 240);
  await writeFile(paths.config, '{"do-not-log-this-value":');
  await assert.rejects(readConfigSnapshot(paths), error => {
    assert.ok(error instanceof Error);
    assert.match(error.message, /INVALID_CONFIG/);
    assert.doesNotMatch(error.message, /do-not-log-this-value/);
    return true;
  });
  await rm(paths.config);
  assert.equal((await readConfigSnapshot(paths, {}, undefined, 78643)).state_max_events, 500);
});
