import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { Type } from "typebox";
import { deriveContextLimit } from "../../src/pi/context-limit.ts";
import { registerRequestLifecycle } from "../../src/pi/request-lifecycle.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { requestProbe } from "../fixtures/request-probe.ts";

test("真实 DeepSeek：精确容量、原生工具续跑、请求级注入和失败取消", { timeout: 60_000 }, async (t) => {
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const originalAuth = await readFile(authPath);
  const credential = (JSON.parse(originalAuth.toString()) as { deepseek?: { type?: string; key?: unknown } }).deepseek;
  assert.ok(credential?.type === "api_key" && typeof credential.key === "string", "Private DeepSeek API configuration is required");
  const response = await fetch("https://api.deepseek.com/models", {
    headers: { Authorization: `Bearer ${credential.key}` }, signal: AbortSignal.timeout(15_000),
  });
  assert.ok(response.ok, `DeepSeek metadata HTTP ${response.status}`);
  const metadata = await response.json() as { data?: Array<{ id?: string; context_window?: unknown }> };
  assert.ok(Array.isArray(metadata.data));
  const capacity = metadata.data.find(model => model.id === "deepseek-flash")?.context_window;
  const limit = deriveContextLimit(capacity);
  let probe: ReturnType<typeof requestProbe>;
  let rulePath: string;
  let executions = 0;
  const payloads: string[] = [];
  const h = await nativeSession(t, [(pi) => {
    registerRequestLifecycle(pi, {
      prepare: (messages, ctx) => probe.services.prepare(messages, ctx),
      report: (error, ctx) => probe.services.report(error, ctx),
    });
    pi.on("before_provider_request", event => { payloads.push(JSON.stringify(event.payload)); });
    pi.registerTool({
      name: "stage0_probe", label: "Stage 0 probe", description: "Required test-only probe; call once with no arguments", parameters: Type.Object({}),
      async execute() {
        executions++; probe.config.recent_turns = 240;
        await writeFile(rulePath, "LIVE_RULE {{recent_turns}} / {{evict_turns}} updated");
        return { content: [{ type: "text", text: "PROBE_OK. Now reply MEMWEAVE_STAGE0_OK." }], details: {} };
      },
    });
  }]);
  rulePath = join(h.root, "rule.md");
  await writeFile(rulePath, "LIVE_RULE {{recent_turns}} / {{evict_turns}}");
  probe = requestProbe(rulePath, capacity as number);
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash");
  assert.ok(model);
  await h.session.setModel(model);
  h.session.setActiveToolsByName(["stage0_probe"]);
  await h.session.prompt("This is a test. Call stage0_probe exactly once with empty arguments. After its successful result, reply exactly MEMWEAVE_STAGE0_OK. Do not use any other tool.");
  assert.equal(executions, 1);
  assert.equal(payloads.length, 2);
  assert.match(payloads[0] ?? "", /LIVE_RULE 200/);
  assert.match(payloads[1] ?? "", /LIVE_RULE 240.*updated/);
  assert.ok(payloads.every(payload => payload.includes("STATE_PROBE") && payload.includes("NATIVE_APPEND")));
  const last = h.session.agent.state.messages.at(-1);
  assert.ok(last?.role === "assistant" && last.stopReason === "stop");
  assert.match(JSON.stringify(last.content), /MEMWEAVE_STAGE0_OK/);
  probe.fail("budget");
  await h.session.prompt("This request must be cancelled locally");
  assert.equal(payloads.length, 2);
  assert.deepEqual(probe.errors, ["CONTEXT_BUDGET_EXCEEDED"]);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /LIVE_RULE|STATE_PROBE|REMINDER_PROBE/);
  assert.ok(originalAuth.equals(await readFile(authPath)), "Private configuration must remain unchanged");
  t.diagnostic(`DeepSeek verified capacity=${String(capacity)}, Agent limit=${limit}, Pi static capacity=${model.contextWindow}; 2 real requests`);
});
