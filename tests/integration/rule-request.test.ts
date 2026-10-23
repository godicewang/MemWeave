import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { Type } from "typebox";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { getSystemMessageText } from "@earendil-works/pi-ai/utils/text";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import type { RequestMessages } from "../../src/pi/request-lifecycle.ts";
import { ruleSession } from "../fixtures/rule-session.ts";

test("正式 Rule 接线：首次及工具续跑热读取，同一快照传递，原生提示和 Session 不变", async t => {
  let h: Awaited<ReturnType<typeof ruleSession>>;
  const requests: RequestMessages[] = [];
  let executions = 0;
  h = await ruleSession(t, pi => {
    pi.registerTool({
      name: "phase1_probe", label: "Phase 1 probe", description: "test only", parameters: Type.Object({}),
      async execute() {
        executions++;
        await writeFile(h.paths.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 8, evict_turns: 3 }));
        await writeFile(h.paths.rule, `${await readFile(h.paths.rule, "utf8")}\nHOT_RULE {{recent_turns}}/{{evict_turns}}`);
        return { content: [{ type: "text", text: "TOOL_ORIGINAL" }], details: {} };
      },
    });
  }, { afterRule: async prepared => {
    requests.push(structuredClone(prepared.messages));
    return [...prepared.messages, { role: "user", content: `TEST_STATE ${prepared.frame.config.recent_turns}`, timestamp: 1 }];
  } });
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("phase1_probe", {}, { id: "phase1-native-id" })]), fauxAssistantMessage("OK")]);
  const originalAppend = await readFile(join(h.agentDir, "APPEND_SYSTEM.md"));
  await h.session.prompt("USER {{recent_turns}} unchanged");
  assert.equal(executions, 1); assert.equal(h.frames.length, 2);
  assert.deepEqual(h.diagnostics, []);
  assert.equal(h.frames[0]?.frame.config.recent_turns, 200);
  assert.equal(h.frames[1]?.frame.config.recent_turns, 8);
  assert.equal(h.frames[0]?.frame.capacity.contextLimit, 629_145);
  for (const [index, messages] of requests.entries()) {
    const system = messages[0]; assert.ok(system?.role === "system");
    const text = getSystemMessageText(system);
    assert.match(text, /NATIVE_SYSTEM/); assert.match(text, /NATIVE_APPEND \{\{untouched\}\}/);
    assert.equal(text.split("<pi_long_task_rule>").length - 1, 1);
    assert.equal(system.toolsAdded?.filter(tool => tool.name === "phase1_probe").length, 1);
    assert.match(JSON.stringify(messages), /USER \{\{recent_turns\}\} unchanged/);
    assert.equal(text.includes("HOT_RULE 8/3"), index === 1);
  }
  const second = requests[1]!;
  const assistant = second.find(m => m.role === "assistant");
  const tool = second.find(m => m.role === "toolResult");
  assert.ok(assistant?.role === "assistant" && tool?.role === "toolResult");
  const call = assistant.content.find(part => part.type === "toolCall");
  assert.ok(call?.type === "toolCall"); assert.equal(call.id, tool.toolCallId);
  assert.deepEqual(call.arguments, {});
  assert.equal(originalAppend.equals(await readFile(join(h.agentDir, "APPEND_SYSTEM.md"))), true);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /pi_long_task_rule|HOT_RULE|TEST_STATE/);
});

test("非法配置/模板或缺失文件会主动取消，不沿用旧规则或自动补写", async t => {
  const h = await ruleSession(t);
  const goodRule = await readFile(h.paths.rule);
  const goodConfig = await readFile(h.paths.config);
  const cases: Array<["rule" | "config", string | Buffer | null, RegExp]> = [
    ["rule", "", /INVALID_RULE/], ["rule", "{{unknown}}", /INVALID_RULE/],
    ["rule", "{{recent_turns", /INVALID_RULE/], ["rule", Buffer.from([0xff]), /INVALID_RULE/],
    ["rule", "<pi_long_task_rule>bad</pi_long_task_rule>", /INVALID_RULE/],
    ["rule", null, /RULE_READ_FAILED/], ["config", "{", /INVALID_CONFIG/],
    ["config", JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 2 }), /INVALID_CONFIG/],
    ["config", null, /CONFIG_READ_FAILED/],
  ];
  for (const [target, bad, expected] of cases) {
    await writeFile(h.paths.rule, goodRule); await writeFile(h.paths.config, goodConfig);
    if (bad === null) await rm(h.paths[target]); else await writeFile(h.paths[target], bad);
    await h.session.prompt("must not send");
    assert.equal(h.faux.state.callCount, 0);
    assert.match(h.diagnostics.at(-1) ?? "", expected);
    if (bad === null) await assert.rejects(readFile(h.paths[target]), /ENOENT/);
  }
  await writeFile(h.paths.rule, goodRule); await writeFile(h.paths.config, goodConfig);
  await h.session.prompt("repaired request");
  assert.equal(h.faux.state.callCount, 1);
});

test("请求快照冻结，实例覆盖独立，显式配置与磁盘文件保持不变", async t => {
  let overrides = { recent_turns: 240 };
  let reads = 0;
  const h = await ruleSession(t, undefined, { readOverrides: () => { reads++; return overrides; } });
  const before = await readFile(h.paths.config);
  await h.session.prompt("first");
  overrides = { recent_turns: 300 };
  await h.session.prompt("second");
  assert.equal(reads, 2);
  assert.equal(h.frames[0]?.frame.config.recent_turns, 240);
  assert.equal(h.frames[1]?.frame.config.recent_turns, 300);
  assert.ok(h.frames.every(f => Object.isFrozen(f.frame) && Object.isFrozen(f.frame.config) && Object.isFrozen(f.frame.capacity)));
  const independent = await ruleSession(t, undefined, { paths: h.paths });
  await independent.session.prompt("independent instance");
  assert.equal(independent.frames[0]?.frame.config.recent_turns, 200);
  assert.ok(before.equals(await readFile(h.paths.config)));
});

test("正式 Rule 经 reload 保持单份处理器，原生项目 AGENTS 和提示信任继续生效", async t => {
  const h = await ruleSession(t);
  await mkdir(join(h.cwd, ".pi"));
  await writeFile(join(h.cwd, "AGENTS.md"), "PHASE1_PROJECT_AGENTS");
  await writeFile(join(h.cwd, ".pi", "SYSTEM.md"), "PHASE1_PROJECT_SYSTEM");
  await writeFile(join(h.cwd, ".pi", "APPEND_SYSTEM.md"), "PHASE1_PROJECT_APPEND {{untouched}}");
  for (let index = 0; index < 2; index++) {
    await h.session.reload();
    h.faux.appendResponses([fauxAssistantMessage("OK")]);
    await h.session.prompt("reload trusted project");
    assert.equal(h.frames.length, index + 1);
    const system = h.frames.at(-1)?.messages[0]; assert.ok(system?.role === "system");
    const text = getSystemMessageText(system);
    assert.match(text, /PHASE1_PROJECT_AGENTS/); assert.match(text, /PHASE1_PROJECT_SYSTEM/);
    assert.match(text, /PHASE1_PROJECT_APPEND \{\{untouched\}\}/);
    assert.equal(text.split("<pi_long_task_rule>").length - 1, 1);
  }
  h.settings.setProjectTrusted(false); await h.session.reload();
  h.faux.appendResponses([fauxAssistantMessage("OK")]);
  await h.session.prompt("untrusted project prompts");
  const system = h.frames.at(-1)?.messages[0]; assert.ok(system?.role === "system");
  const text = getSystemMessageText(system);
  assert.match(text, /NATIVE_SYSTEM/); assert.doesNotMatch(text, /PHASE1_PROJECT_SYSTEM|PHASE1_PROJECT_APPEND/);
  assert.equal(await readFile(join(h.cwd, ".pi", "APPEND_SYSTEM.md"), "utf8"), "PHASE1_PROJECT_APPEND {{untouched}}");
});

test("容量缺失不发请求，模型切换重新派生且不修改宿主目录", async t => {
  let capacity: unknown;
  const h = await ruleSession(t, undefined, { verifyCapacity: async () => capacity });
  await h.session.prompt("unverified");
  assert.equal(h.faux.state.callCount, 0);
  assert.match(h.diagnostics[0] ?? "", /MODEL_CAPACITY_UNVERIFIED/);
  capacity = 101;
  await h.session.prompt("verified odd capacity");
  assert.equal(h.frames.at(-1)?.frame.capacity.contextLimit, 60);
  const before = h.faux.getModel().contextWindow;
  capacity = 1_000_000;
  await h.session.setModel({ ...h.faux.getModel(), id: "second-model" });
  await h.session.prompt("model switch");
  assert.equal(h.frames.at(-1)?.frame.capacity.modelId, "second-model");
  assert.equal(h.frames.at(-1)?.frame.capacity.contextLimit, 600_000);
  assert.equal(h.faux.getModel().contextWindow, before);
});
