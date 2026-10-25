import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { Type } from "typebox";
import { productionTaskSession } from "../fixtures/production-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";

test("真实 DeepSeek：完整入口、原生提示/工具、精确容量、续跑与失败取消", { timeout: 60_000 }, async (t) => {
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const original = await readFile(authPath);
  t.after(async () => assert.ok(original.equals(await readFile(authPath))));
  const key = (JSON.parse(original.toString()) as {deepseek:{type:string;key:string}}).deepseek;
  assert.equal(key.type, "api_key");
  const payloads: string[] = [];
  let executions = 0;
  const h = await productionTaskSession(t, { verifyCapacity: verifyProviderCapacity, extra(pi) {
    pi.on("before_provider_request", event => { payloads.push(JSON.stringify(event.payload)); });
    pi.registerTool({ name: "stage0_probe", label: "stage0_probe", description: "Short integration check: call once with no arguments.", parameters: Type.Object({}),
      async execute() {
        executions++;
        await writeFile(h.paths.config, JSON.stringify({ recent_turns: 240, evict_turns: 40 }));
        return { content: [{ type: "text", text: "PROBE_OK. Reply MEMWEAVE_STAGE0_OK." }], details: {} };
      },
    });
  } });
  await h.runtime.setRuntimeApiKey("deepseek", key.key);
  await h.session.setModel(h.runtime.getModel("deepseek", "deepseek-flash")!);
  await h.session.prompt("这是一次简短集成检查，不是持续任务。仅调用 stage0_probe 一次，成功后只回复 MEMWEAVE_STAGE0_OK，不执行其他操作。");
  assert.equal(executions, 1); assert.equal(payloads.length, 2);
  assert.match(payloads[0]!, /当前窗口容量为.*200/);
  assert.match(payloads[1]!, /当前窗口容量为.*240/);
  assert.ok(payloads.every(payload => payload.includes("本次预算快照") && payload.includes("You are an expert coding assistant")));
  assert.equal(h.budgets[0]!.limit, 629145);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  await writeFile(h.paths.config, JSON.stringify({ context_budget: { model_percent: 0.01 }, elastic_budget: { extra_model_percent: 0 } }));
  await h.session.prompt("This request must be cancelled locally");
  assert.equal(payloads.length, 2);
  assert.match(h.diagnostics.at(-1)!, /CONTEXT_BUDGET_EXCEEDED/);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /本次预算快照|pi_long_task_rule/);
  t.diagnostic("2 real requests through complete production launcher/Rule and default tools; next request cancelled before inference");
});
