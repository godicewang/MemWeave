import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { randomInt } from "node:crypto";
import { Type } from "typebox";
import { fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { productionTaskSession as taskSession } from "../fixtures/production-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { loadReferences } from "../../src/memory/references.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";

async function enableFlash(t: TestContext, h: Awaited<ReturnType<typeof taskSession>>) {
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const auth = await readFile(authPath);
  t.after(async () => assert.ok(auth.equals(await readFile(authPath))));
  const credential = (JSON.parse(auth.toString()) as { deepseek?: { key?: unknown } }).deepseek;
  assert.ok(typeof credential?.key === "string");
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash");
  assert.ok(model); await h.session.setModel(model);
  return model;
}

async function fixture(t: TestContext, blocked = false) {
  let file = "";
  const delay = randomInt(80, 110), target = delay + 37;
  const result = (value: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(value) }], details: {} });
  const h = await taskSession(t, {
    verifyCapacity: (model, ctx, settings) => model.provider === "memweave-test"
      ? Promise.resolve(model.contextWindow) : verifyProviderCapacity(model, ctx, settings),
    extra(pi) {
      pi.registerTool({ name: "inspect_component", label: "inspect_component", description: "Inspect the component. target_timeout_ms is the exact required configuration, not a minimum; acceptance requires timeout_ms === target_timeout_ms.", parameters: Type.Object({}),
        async execute() { return result({ ...JSON.parse(await readFile(file, "utf8")), service_delay_ms: delay, target_timeout_ms: target }); } });
      pi.registerTool({ name: "set_component_timeout", label: "set_component_timeout", description: "Set the real local timeout to EXACTLY the inspected target_timeout_ms. Other values in the allowed input range do not meet acceptance. Inspect first.",
        parameters: Type.Object({ timeout_ms: Type.Integer({ minimum: 1, maximum: 10000 }) }, { additionalProperties: false }),
        async execute(_id, input) { await writeFile(file, JSON.stringify(input)); return result(input); } });
      pi.registerTool({ name: "verify_component", label: "verify_component", description: "Run the local component probe. Acceptance requires the configured timeout to equal target_timeout_ms exactly and the probe to succeed. Read passed and reason, not just tool execution status.", parameters: Type.Object({}),
        async execute() {
          const config = JSON.parse(await readFile(file, "utf8")) as { timeout_ms: number };
          if (blocked) return result({ passed: false, reason: "fixture transport blocked; verification cannot complete", timeout_ms: config.timeout_ms });
          let serviceTimer: ReturnType<typeof setTimeout> | undefined, timeoutTimer: ReturnType<typeof setTimeout> | undefined;
          try {
            const reached = await Promise.race([
              new Promise<boolean>((resolve) => { serviceTimer = setTimeout(() => resolve(true), delay); }),
              new Promise<boolean>((resolve) => { timeoutTimer = setTimeout(() => resolve(false), config.timeout_ms); }),
            ]);
            return result({ passed: reached && config.timeout_ms === target, timeout_ms: config.timeout_ms, target_timeout_ms: target, service_delay_ms: delay });
          } finally { clearTimeout(serviceTimer); clearTimeout(timeoutTimer); }
        } });
    },
  });
  file = join(h.cwd, "component.json");
  await writeFile(file, JSON.stringify({ timeout_ms: 31 }));
  const model = await enableFlash(t, h);
  return { ...h, file, target, model };
}

test("real Flash: substantial delivery binds a Task and preserves verified cognition without an explicit memory request", { timeout: 120000 }, async (t) => {
  const h = await fixture(t);
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 8, evict_turns: 2 }));
  await h.session.prompt("请修复这个组件的超时问题，按 inspect_component 提供的要求配置，并实际验证。完成后简要交付结果。");
  assert.equal(JSON.parse(await readFile(h.file, "utf8")).timeout_ms, h.target);
  const tasks = await h.tasks.index.read(); assert.equal(tasks.length, 1);
  const state = await h.tasks.state.read(tasks[0]!);
  const entries = [...state.facts, ...state.decisions];
  assert.ok(entries.length > 0, "important delivery cognition must be saved");
  assert.ok(entries.some((entry) => entry.content.includes(String(h.target))), "actual chosen value must survive in cognition");
  const refs = await loadReferences(tasks[0]!, h.tasks.memory);
  assert.ok(entries.some((entry) => Object.keys(entry.evidence).some((ref) => {
    const source = refs.get(ref);
    const record = source && h.manager.getEntries().find((row) => row.id === source.entry_id);
    return record?.type === "message" && record.message.role === "toolResult" && record.message.toolName === "verify_component";
  })), "verification cognition needs the actual probe result");
  const version = state.version;
  await h.session.prompt("继续采用刚才的结果，状态没有变化。仅用一句话确认，不重做操作。");
  assert.equal((await h.tasks.index.read()).length, 1);
  assert.equal((await h.tasks.state.read(tasks[0]!)).version, version);
  await h.session.setModel(h.faux.getModel());
  for (let i = 0; i < 6; i++) {
    h.faux.setResponses([fauxAssistantMessage("context continues")]);
    await h.session.prompt("无新任务信息的普通往返 " + i);
  }
  await h.session.reload(); await h.session.setModel(h.model);
  await h.session.prompt("此前修复的实际最终超时参数是多少？请根据已有认知回答，不重做工具操作。");
  const final = h.session.agent.state.messages.at(-1);
  assert.ok(final?.role === "assistant" && final.stopReason === "stop");
  assert.match(JSON.stringify(final.content), new RegExp(String(h.target)));
  assert.equal(scopeOf(h.manager.getBranch()).task_id, tasks[0]!.task_id);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  t.diagnostic("Real model decisions and real local-file/timer fixture; delivery, no-duplicate follow-up, Window eviction and reload verified");
});

test("real Flash: blocked delivery records failure boundaries rather than a passing result", { timeout: 120000 }, async (t) => {
  const h = await fixture(t, true);
  await h.session.prompt("请尝试修复这个组件的超时问题并实际验证。如果验证被阻塞，就说明阻塞原因及未完成部分，不要反复重试。");
  const tasks = await h.tasks.index.read(); assert.equal(tasks.length, 1);
  const state = await h.tasks.state.read(tasks[0]!);
  const entries = [...state.facts, ...state.decisions];
  assert.ok(entries.some((entry) => /阻塞|失败|未完成|未通过|blocked|fail/i.test(entry.content)));
  assert.ok(entries.every((entry) => !/(?:验证|测试|检查)(?:全部)?(?:已)?通过/.test(entry.content)));
  const final = h.session.agent.state.messages.at(-1);
  assert.ok(final?.role === "assistant" && final.stopReason === "stop");
  assert.match(JSON.stringify(final.content), /阻塞|未完成|未能|无法|blocked|fail/i);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
});

test("real Flash: short Q&A does not force a Task or State writes", { timeout: 60000 }, async (t) => {
  const h = await taskSession(t, { verifyCapacity: verifyProviderCapacity });
  await enableFlash(t, h);
  await h.session.prompt("12×7是多少？只回复数字。");
  assert.deepEqual(await h.tasks.index.read(), []);
  const final = h.session.agent.state.messages.at(-1);
  assert.ok(final?.role === "assistant" && final.stopReason === "stop");
  const text = final.content.filter((part) => part.type === "text").map((part) => part.text).join("").trim();
  if (text !== "84") t.diagnostic(JSON.stringify({ text, userInput: h.frames[0]?.filter(message => message.role === "user") }));
  assert.equal(text, "84");
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
});
