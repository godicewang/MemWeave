import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DEFAULT_SETTINGS, settingsFor } from "../../src/config/defaults.ts";
import { mergeConfig } from "../../src/config/schema.ts";
import { readConfigSnapshot } from "../../src/config/read.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { budgetPlan } from "../../src/window/policy.ts";
import { deriveContextLimit } from "../../src/pi/context-limit.ts";
import { renderRule } from "../../src/rule/render.ts";
import { SourceVerifier } from "../../src/pi/source-verification.ts";

test("partial overrides inherit immutable JSON defaults; branch six fields win without mutation", () => {
  const input = { state_max_events: 400, source_cache: { max_entries: 4096 } };
  const config = mergeConfig(input, { recent_turns: 80, evict_turns: 16 }, 629145);
  assert.equal(config.state_max_events, 400);
  assert.equal(config.state_event_max_chars, 100);
  assert.equal(config.recent_turns, 80);
  assert.equal(settingsFor(config).source_cache.max_entries, 4096);
  assert.equal(settingsFor(config).source_cache.max_bytes, 16777216);
  assert.ok(Object.isFrozen(config));
  assert.ok(Object.isFrozen(settingsFor(config).source_cache));
  assert.equal(DEFAULT_SETTINGS.source_cache.max_entries, 8192);
  assert.deepEqual(input, { state_max_events: 400, source_cache: { max_entries: 4096 } });
  assert.throws(() => mergeConfig({}, { source_cache: { max_entries: 1 } }, 629145), /INVALID_CONFIG/);
});

test("missing file and empty file inherit defaults; corrupt or unknown fields never silently fall back", async t => {
  const root = await mkdtemp(join(tmpdir(), "memweave-settings-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  const first = await readConfigSnapshot(paths, {}, undefined, 78643);
  assert.equal(first.recent_turns, 50);
  await assert.rejects(readFile(paths.config), { code: "ENOENT" });
  await writeFile(paths.config, JSON.stringify({ read: { default_total_chars: 500 } }));
  const second = await readConfigSnapshot(paths, {}, undefined, 78643);
  assert.equal(settingsFor(first).read.default_total_chars, 8000);
  assert.equal(settingsFor(second).read.default_total_chars, 500);
  await writeFile(paths.config, '{"private-input":');
  await assert.rejects(readConfigSnapshot(paths), error => {
    assert.match(String(error), /INVALID_CONFIG/);
    assert.doesNotMatch(String(error), /private-input/);
    return true;
  });
});

test("budget policies and automatic window derive from the same settings using integer rounding", () => {
  const config = mergeConfig({
    context_budget: { model_percent: 50, parts_percent: { state: 15, window: 35 } },
    window_auto: { max_events: 80, min_events: 10, event_step: 5, evict_percent: 25 },
  }, {}, 500000);
  const settings = settingsFor(config);
  assert.equal(deriveContextLimit(1000001, settings), 500000);
  const plan = budgetPlan(500003, settings);
  assert.equal(plan.state, 75000);
  assert.equal(Object.values(plan).reduce((a,b) => a+b, 0), 500003);
  assert.equal(config.recent_turns, 80);
  assert.equal(config.evict_turns, 20);
  assert.equal(mergeConfig({ recent_turns: 9 }, {}, 500000).evict_turns, 2);
});

test("reject invalid nested fields, unsafe percentages, limits and crossed automatic window bounds", () => {
  for (const value of [
    { context_budget: { model_percent: 61 } },
    { context_budget: { parts_percent: { state: 10 } } },
    { context_budget: { parts_percent: { safety: 0 } } },
    { read: { default_total_chars: 50001 } }, { read: { lifetime_messages: 0 } },
    { source_cache: { max_entries: 8193 } }, { source_cache: { max_bytes: 16777217 } },
    { source_cache: { unknown: 1 } }, { window_auto: { min_events: 300 } },
    { window_auto: { evict_percent: 101 } }, { model_metadata_timeout_ms: 0 },
    { state_policy: { token_warning_percent: 100.001 } },
    { read: null }, { read: { lifetime_messages: undefined } },
  ]) assert.throws(() => mergeConfig(value, {}, 629145), /INVALID_CONFIG/);
  assert.equal(settingsFor(mergeConfig({ source_cache: { max_entries: 0 } }, {}, 629145)).source_cache.max_entries, 0);
});

test("nondefault protocol settings require matching whitelist placeholders; defaults accept old templates", async () => {
  const config = mergeConfig({ recent_turns: 20, evict_turns: 4,
    context_budget: { model_percent: 50 }, state_policy: { token_warning_percent: 75 },
    read: { lifetime_messages: 3, default_total_chars: 2000 } });
  assert.throws(() => renderRule("old template", config), /RULE_CONFIG_MISMATCH/);
  const template = "{{agent_context_percent}}/{{state_token_warning_percent}}/{{read_lifetime_messages}}/{{read_default_total_chars}}";
  assert.equal(renderRule(template, config), "50/75/3/2000");
  assert.throws(() => renderRule("{{read.lifetime_messages}}", config), /INVALID_RULE/);
  const bundled = await readFile(new URL("../../resources/rule.md", import.meta.url), "utf8");
  assert.ok(renderRule(bundled, config).includes("50%"));
});

test("cache reconfiguration clears hints and actually obeys smaller/disabled limits", () => {
  const verifier = new SourceVerifier();
  const entries = Array.from({ length: 4 }, (_, i) => ({ type: "message" as const,
    id: `e${i}`, parentId: null, timestamp: "2026", message: { role: "user" as const, content: "x", timestamp: i } }));
  const messages = entries.map(e => e.message);
  verifier.match(messages, entries, "s", () => { throw Error("no projection"); });
  assert.equal(verifier.stats.entries, 4);
  verifier.configure({ max_entries: 2, max_bytes: 16777216 });
  assert.equal(verifier.stats.entries, 0);
  verifier.match(messages, entries, "s", () => { throw Error("no projection"); });
  assert.equal(verifier.stats.entries, 2);
  verifier.configure({ max_entries: 0, max_bytes: 0 });
  verifier.match(messages, entries, "s", () => { throw Error("no projection"); });
  assert.equal(verifier.stats.entries, 0);
});

test("Task search policies merge nested overrides and reject unsupported model or invalid weights", () => {
  const config=mergeConfig({task_binding:{max_corrections:0},task_search:{field_weights:{goal:4},cache_max_bytes:0}},{},629145);
  assert.equal(config.task_binding.max_corrections,0);
  assert.equal(config.task_search.field_weights.goal,4);
  assert.equal(config.task_search.field_weights.title,2);
  assert.equal(config.task_search.embedding.dtype,"q8");
  for(const value of [
    {task_binding:{max_corrections:4}},
    {task_search:{channel_weights:{semantic:0.9}}},
    {task_search:{embedding:{model:"arbitrary-remote-code"}}},
    {task_search:{embedding:{revision:"main"}}},
    {task_search:{model_idle_ms:0}},
    {task_search:{field_weights:{goal:0}}},
  ])assert.throws(()=>mergeConfig(value,{},629145),/INVALID_CONFIG/);
});
