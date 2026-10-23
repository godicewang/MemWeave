import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { Type } from "typebox";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { getCurrentSystemPrompt } from "@earendil-works/pi-ai/utils/transcript";
import { registerRequestLifecycle } from "../../src/pi/request-lifecycle.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { requestProbe } from "../fixtures/request-probe.ts";

test("原生循环的首次与工具续跑使用新快照；提示和工具保留，临时上下文不持久化", async (t) => {
  let probe: ReturnType<typeof requestProbe>;
  let rulePath: string;
  const seen: string[] = [];
  const toolResults: unknown[] = [];
  const h = await nativeSession(t, [(pi) => {
    registerRequestLifecycle(pi, {
      prepare: (messages, ctx) => probe.services.prepare(messages, ctx),
      report: (error, ctx) => probe.services.report(error, ctx),
    });
    pi.registerTool({
      name: "stage0_probe", label: "Stage 0 probe", description: "Test-only configuration change", parameters: Type.Object({ value: Type.Number() }),
      async execute(_id, { value }) {
        probe.config.recent_turns = value;
        await writeFile(rulePath, "HOT_RULE {{recent_turns}} / {{evict_turns}} extra");
        return { content: [{ type: "text", text: "PROBE_TOOL_OK" }], details: {} };
      },
    });
  }]);
  rulePath = join(h.root, "rule.md");
  await writeFile(rulePath, "HOT_RULE {{recent_turns}} / {{evict_turns}}");
  probe = requestProbe(rulePath);
  h.session.setActiveToolsByName(["stage0_probe"]);
  h.faux.setResponses([
    (context) => {
      seen.push(getCurrentSystemPrompt(context.messages));
      return fauxAssistantMessage([fauxToolCall("stage0_probe", { value: 240 }, { id: "native-tool-001" })]);
    },
    (context) => {
      seen.push(getCurrentSystemPrompt(context.messages));
      toolResults.push(...context.messages.filter(message => message.role === "toolResult"));
      assert.ok(context.messages.some(message => message.role === "toolResult" && message.toolCallId === "native-tool-001"));
      assert.ok(context.messages[0]?.role === "system" && context.messages[0].toolsAdded?.some(tool => tool.name === "stage0_probe"));
      return fauxAssistantMessage("DONE");
    },
  ]);
  await h.session.prompt("Run the probe");
  assert.equal(h.faux.state.callCount, 2);
  assert.match(JSON.stringify(toolResults), /PROBE_TOOL_OK/);
  assert.match(seen[0] ?? "", /HOT_RULE 200/);
  assert.match(seen[1] ?? "", /HOT_RULE 240.*extra/);
  for (const prompt of seen) {
    assert.match(prompt, /NATIVE_SYSTEM/); assert.match(prompt, /NATIVE_APPEND \{\{untouched\}\}/);
    assert.equal(prompt.split("<pi_long_task_rule>").length - 1, 1);
  }
  assert.equal(probe.frames.length, 2);
  assert.ok(probe.frames[1]!.systemCost > probe.frames[0]!.systemCost);
  assert.equal(probe.frames[0]!.limit, 629_145);
  const sessionText = await readFile(h.manager.getSessionFile()!, "utf8");
  assert.doesNotMatch(sessionText, /HOT_RULE|STATE_PROBE|REMINDER_PROBE/);
  assert.match(sessionText, /PROBE_TOOL_OK/);
  assert.equal(await readFile(join(h.agentDir, "APPEND_SYSTEM.md"), "utf8"), "NATIVE_APPEND {{untouched}}");
  assert.deepEqual(probe.errors, []);
});

test("项目 SYSTEM/APPEND/AGENTS 沿用原生信任与优先级，不加载包内开发文档", async (t) => {
  let prompt = "";
  const h = await nativeSession(t, [(pi) => { registerRequestLifecycle(pi); }]);
  await mkdir(join(h.cwd, ".pi"));
  const files = {
    "SYSTEM.md": "PROJECT_SYSTEM",
    "APPEND_SYSTEM.md": "PROJECT_APPEND {{untouched}}",
  };
  for (const [name, content] of Object.entries(files)) await writeFile(join(h.cwd, ".pi", name), content);
  await writeFile(join(h.cwd, "AGENTS.md"), "PROJECT_AGENTS_SENTINEL");
  await h.session.reload();
  h.faux.setResponses([(context) => { prompt = getCurrentSystemPrompt(context.messages); return fauxAssistantMessage("OK"); }]);
  await h.session.prompt("check project prompts");
  assert.match(prompt, /PROJECT_SYSTEM/); assert.match(prompt, /PROJECT_APPEND \{\{untouched\}\}/);
  assert.match(prompt, /PROJECT_AGENTS_SENTINEL/);
  assert.doesNotMatch(prompt, /NATIVE_SYSTEM|NATIVE_APPEND|AGENTS.md — Pi Long Task Agent|MODEL_CAPACITY_UNVERIFIED/);
  for (const [name, content] of Object.entries(files)) assert.equal(await readFile(join(h.cwd, ".pi", name), "utf8"), content);
  h.settings.setProjectTrusted(false);
  await h.session.reload();
  h.faux.setResponses([(context) => { prompt = getCurrentSystemPrompt(context.messages); return fauxAssistantMessage("OK"); }]);
  await h.session.prompt("check untrusted project");
  assert.match(prompt, /NATIVE_SYSTEM/); assert.doesNotMatch(prompt, /PROJECT_SYSTEM|PROJECT_APPEND/);
});

test("只 throw 会继续调用模型；主动取消在报告失败前阻止发送", async (t) => {
  const bad = await nativeSession(t, [(pi) => {
    pi.on("context_with_system", () => { throw new Error("throw-only counterexample"); });
  }]);
  await bad.session.prompt("counterexample");
  assert.equal(bad.faux.state.callCount, 1);
  assert.ok(bad.errors.some(error => error.includes("throw-only")));
  for (const reason of ["INVALID_TEMPLATE", "CONTEXT_BUDGET_EXCEEDED", "INVALID_CONFIG"]) {
    const h = await nativeSession(t, [(pi) => { registerRequestLifecycle(pi, {
      async prepare() { throw new Error(reason); },
      report(_error, ctx) { assert.ok(ctx.signal?.aborted); throw new Error("report also fails"); },
    }); }]);
    await h.session.prompt(reason);
    assert.equal(h.faux.state.callCount, 0, reason);
  }
});

test("每次请求检查有效压缩设置，reload 与新 Session 不叠加处理器", async (t) => {
  let calls = 0;
  const errors: string[] = [];
  const h = await nativeSession(t, [(pi) => { registerRequestLifecycle(pi, {
    async prepare(messages) { calls++; return messages; },
    report(error) { errors.push(String(error)); },
  }); }]);
  for (let index = 0; index < 3; index++) {
    await h.session.reload();
    h.faux.appendResponses([fauxAssistantMessage("OK")]);
    await h.session.prompt(`request ${index}`);
  }
  assert.equal(calls, 3);
  h.settings.setCompactionEnabled(true);
  await h.session.prompt("must not send");
  assert.equal(calls, 3);
  assert.ok(errors.some(error => error.includes("COMPACTION_ENABLED")));
  h.settings.setCompactionEnabled(false);
  h.manager.newSession();
  await h.session.reload();
  h.faux.appendResponses([fauxAssistantMessage("NEW")]);
  await h.session.prompt("new session");
  assert.equal(calls, 4);
});

test("两个 Pi 实例可共享模板，各自的配置快照独立", async (t) => {
  let first: ReturnType<typeof requestProbe>;
  let second: ReturnType<typeof requestProbe>;
  const a = await nativeSession(t, [(pi) => { registerRequestLifecycle(pi, {
    prepare: (messages, ctx) => first.services.prepare(messages, ctx),
    report: (error, ctx) => first.services.report(error, ctx),
  }); }]);
  const b = await nativeSession(t, [(pi) => { registerRequestLifecycle(pi, {
    prepare: (messages, ctx) => second.services.prepare(messages, ctx),
    report: (error, ctx) => second.services.report(error, ctx),
  }); }]);
  const path = join(a.root, "shared-rule.md");
  await writeFile(path, "SHARED_RULE {{recent_turns}}");
  first = requestProbe(path); second = requestProbe(path);
  second.config.recent_turns = 400;
  await Promise.all([a.session.prompt("A"), b.session.prompt("B")]);
  assert.deepEqual(first.frames.map(frame => frame.turns), [200]);
  assert.deepEqual(second.frames.map(frame => frame.turns), [400]);
  assert.notEqual(a.manager.getSessionFile(), b.manager.getSessionFile());
});
