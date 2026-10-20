import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { renderRule } from "../../src/rule/render.ts";
import { applyRule } from "../../src/rule/apply.ts";
import { prepareRule } from "../../src/rule/prepare.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import type { RequestMessages } from "../../src/pi/request-lifecycle.ts";
import { fauxAssistantMessage, fauxThinking, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";

const messages: RequestMessages = [
  { role: "system", content: "NATIVE {{untouched}}", timestamp: 1,
    sections: { addendum: "APPEND {{untouched}}", other: "UNCHANGED" } },
  { role: "user", content: "USER {{untouched}}", timestamp: 2 },
];

test("Rule 只做六变量的单次替换，保留模板其他字节", () => {
  assert.equal(renderRule("N={{ recent_turns }}; B={{evict_turns}}\n", DEFAULT_CONFIG), "N=200; B=40\n");
  const template = Object.keys(DEFAULT_CONFIG).map(key => `{{${key}}}`).join("/");
  assert.equal(renderRule(template, DEFAULT_CONFIG), "200/40/2000/100/200/20");
  assert.equal(renderRule("JSON {\"a\":1} / literal $1", DEFAULT_CONFIG), 'JSON {"a":1} / literal $1');
});

test("拒绝空模板、表达式、未知/未闭合/嵌套占位符和保留标记", () => {
  for (const template of ["", " \n", "{{unknown}}", "{{recent_turns + 1}}", "{{recent_turns", "recent_turns}}",
    "{{{{recent_turns}}}}", "{{constructor}}", "{{__proto__}}", "{{recent_turns}} {{",
    "<pi_long_task_rule>", "</pi_long_task_rule>", "<pi_long_task_rule invalid>"]) {
    assert.throws(() => renderRule(template, DEFAULT_CONFIG), /INVALID_RULE/);
  }
  assert.throws(() => renderRule("{{recent_turns}}", {}), /INVALID_CONFIG/);
});

test("请求级插入/替换仅更新自有 addendum 范围，原始消息不变", () => {
  const original = structuredClone(messages);
  const first = applyRule(messages, "RULE_ONE");
  assert.equal(first[0]?.role, "system");
  assert.match(JSON.stringify(first[0]), /RULE_ONE/);
  assert.deepEqual(messages, original);
  assert.deepEqual(first.slice(1), original.slice(1));
  assert.match(JSON.stringify(first[0]), /NATIVE \{\{untouched\}\}/);
  assert.match(JSON.stringify(first[0]), /APPEND \{\{untouched\}\}/);
  const second = applyRule(first, "RULE_TWO");
  assert.doesNotMatch(JSON.stringify(second), /RULE_ONE/);
  assert.equal(JSON.stringify(second).split("<pi_long_task_rule>").length - 1, 1);
  assert.deepEqual(first.slice(1), second.slice(1));
});

test("替换保留范围前后正文；损坏或越界标记报错，不覆盖用户内容", () => {
  const make = (addendum: string): RequestMessages => [{ role: "system", content: "NATIVE", sections: { addendum }, timestamp: 0 }];
  const valid = applyRule(make("BEFORE<pi_long_task_rule>OLD</pi_long_task_rule>AFTER"), "NEW");
  assert.equal(valid[0]?.role === "system" && valid[0].sections?.addendum, "BEFORE<pi_long_task_rule>\nNEW\n</pi_long_task_rule>AFTER");
  for (const invalid of ["<pi_long_task_rule>", "</pi_long_task_rule>",
    "</pi_long_task_rule><pi_long_task_rule>", "<pi_long_task_rule><pi_long_task_rule></pi_long_task_rule></pi_long_task_rule>",
    "<pi_long_task_rule></pi_long_task_rule><pi_long_task_rule></pi_long_task_rule>", "<pi_long_task_rule bad>"]) {
    assert.throws(() => applyRule(make(invalid), "NEW"), /RULE_BOUNDARY_CONFLICT/);
  }
  assert.throws(() => applyRule([{ role: "system", content: "<pi_long_task_rule>old</pi_long_task_rule>", timestamp: 0 }], "NEW"), /RULE_BOUNDARY_CONFLICT/);
  assert.throws(() => applyRule(messages.slice(1), "NEW"), /MISSING_SYSTEM/);
});

test("原生增量 system 的工具投影被保留，推理签名/工具配对/图片原样通过", () => {
  const tool = { name: "still-active", description: "native schema", parameters: { type: "object", properties: {} } };
  const assistant = fauxAssistantMessage([
    { ...fauxThinking("original reasoning"), thinkingSignature: "opaque-native-signature" },
    fauxToolCall("still-active", { value: "untouched" }, { id: "opaque-native-id" }),
  ]);
  const original: RequestMessages = [
    { role: "system", content: "BASE", toolsAdded: [tool, { ...tool, name: "removed" }], timestamp: 1 },
    { role: "system", content: "UPDATE", sections: { addendum: "ORIGINAL_APPEND" }, toolsRemoved: [{ name: "removed" }], timestamp: 2 },
    { role: "user", content: [{ type: "image", mimeType: "image/png", data: "opaque-image" }], timestamp: 3 },
    assistant,
    { role: "toolResult", toolCallId: "opaque-native-id", toolName: "still-active", content: [{ type: "text", text: "ORIGINAL_RESULT" }], isError: false, timestamp: 4 },
  ];
  const before = structuredClone(original);
  const prepared = applyRule(original, "RENDERED_RULE");
  assert.equal(prepared.filter(message => message.role === "system").length, 1);
  const system = prepared[0]; assert.ok(system?.role === "system");
  assert.deepEqual(system.toolsAdded, [tool]);
  assert.match(JSON.stringify(system.content), /BASE/); assert.match(JSON.stringify(system.content), /UPDATE/);
  assert.deepEqual(prepared.slice(1), original.slice(2));
  assert.deepEqual(original, before);
});

test("Rule 读取与模型快照固定；缺失/无效 UTF-8/取消不使用旧模板", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-phase1-rule-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root);
  const frame = { config: DEFAULT_CONFIG,
    capacity: { provider: "fixture", modelId: "unit", contextWindow: 1_048_576, contextLimit: 524_288 } };
  await writeFile(paths.rule, "FIRST {{recent_turns}}");
  const first = await prepareRule(messages, frame, paths);
  await writeFile(paths.rule, "SECOND {{recent_turns}}");
  const second = await prepareRule(messages, frame, paths);
  assert.equal(first.renderedRule, "FIRST 200"); assert.equal(second.renderedRule, "SECOND 200");
  assert.notEqual(first.templateHash, second.templateHash);
  assert.equal(await readFile(paths.rule, "utf8"), "SECOND {{recent_turns}}");
  const abort = new AbortController(); abort.abort();
  await assert.rejects(prepareRule(messages, frame, paths, abort.signal), { name: "AbortError" });
  await writeFile(paths.rule, Buffer.from([0xff]));
  await assert.rejects(prepareRule(messages, frame, paths), /INVALID_RULE/);
  await rm(paths.rule);
  await assert.rejects(prepareRule(messages, frame, paths), /RULE_READ_FAILED/);
});
