import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { Type } from "typebox";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { ruleSession } from "../fixtures/rule-session.ts";

test("真实 DeepSeek：生产配置/Rule/容量适配与工具续跑，非法模板取消", { timeout: 60_000 }, async t => {
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const originalAuth = await readFile(authPath);
  t.after(async () => { assert.ok(originalAuth.equals(await readFile(authPath)), "private credentials must remain unchanged"); });
  const credential = (JSON.parse(originalAuth.toString()) as { deepseek?: { type?: string; key?: unknown } }).deepseek;
  assert.ok(credential?.type === "api_key" && typeof credential.key === "string", "Private DeepSeek API configuration is required");
  let h: Awaited<ReturnType<typeof ruleSession>>;
  const payloads: string[] = [];
  let executions = 0;
  h = await ruleSession(t, pi => {
    pi.on("before_provider_request", event => { payloads.push(JSON.stringify(event.payload)); });
    pi.registerTool({
      name: "phase1_live_probe", label: "Phase 1 live probe", description: "Required test-only probe: call once with empty arguments", parameters: Type.Object({}),
      async execute() {
        executions++;
        await writeFile(h.paths.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 240 }));
        await writeFile(h.paths.rule, `${await readFile(h.paths.rule, "utf8")}\nPHASE1_HOT_RULE {{recent_turns}}/{{evict_turns}}`);
        return { content: [{ type: "text", text: "PROBE_OK. Reply MEMWEAVE_PHASE1_OK now." }], details: {} };
      },
    });
  }, { verifyCapacity: verifyProviderCapacity, afterRule: async prepared => [
    ...prepared.messages, { role: "user", content: `PHASE1_TEST_STATE ${prepared.frame.config.recent_turns}`, timestamp: 1 },
  ] });
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash"); assert.ok(model);
  const catalogCapacity = model.contextWindow;
  await h.session.setModel(model); h.session.setActiveToolsByName(["phase1_live_probe"]);
  await h.session.prompt("Integration test: call phase1_live_probe exactly once with empty arguments. After success, reply exactly MEMWEAVE_PHASE1_OK. No other tools or memory operations are needed.");
  assert.deepEqual(h.diagnostics, []);
  assert.equal(executions, 1); assert.equal(payloads.length, 2); assert.equal(h.frames.length, 2);
  assert.equal(h.frames[0]?.frame.config.recent_turns, 200);
  assert.equal(h.frames[1]?.frame.config.recent_turns, 240);
  assert.match(payloads[1] ?? "", /PHASE1_HOT_RULE 240\/40/);
  for (const [index, payload] of payloads.entries()) {
    assert.match(payload, /NATIVE_SYSTEM/); assert.match(payload, /NATIVE_APPEND \{\{untouched\}\}/);
    assert.match(payload, new RegExp(`PHASE1_TEST_STATE ${index === 0 ? 200 : 240}`));
    assert.equal(payload.split("<pi_long_task_rule>").length - 1, 1);
    assert.equal(h.frames[index]?.frame.capacity.contextLimit, Math.floor(h.frames[index]!.frame.capacity.contextWindow * 3 / 5));
  }
  const last = h.session.agent.state.messages.at(-1);
  assert.ok(last?.role === "assistant" && last.stopReason === "stop");
  assert.match(JSON.stringify(last.content), /MEMWEAVE_PHASE1_OK/);
  await writeFile(h.paths.rule, "{{unknown}}");
  await h.session.prompt("This must be cancelled before inference");
  assert.equal(payloads.length, 2); assert.match(h.diagnostics.at(-1) ?? "", /INVALID_RULE/);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /pi_long_task_rule|PHASE1_HOT_RULE|PHASE1_TEST_STATE/);
  assert.equal(model.contextWindow, catalogCapacity);
  t.diagnostic(`Production adapter: capacity=${h.frames[0]!.frame.capacity.contextWindow}, C=${h.frames[0]!.frame.capacity.contextLimit}, catalog=${catalogCapacity}; 2 real inference requests, 1 tool continuation`);
});
