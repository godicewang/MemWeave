import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { Type } from "typebox";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { productionTaskSession } from "../fixtures/production-session.ts";

test("真实 DeepSeek：完整生产 Rule 热加载、原生工具续跑与非法模板取消", { timeout: 60_000 }, async t => {
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const auth = await readFile(authPath);
  t.after(async () => assert.ok(auth.equals(await readFile(authPath))));
  const credential = (JSON.parse(auth.toString()) as {deepseek:{type:string;key:string}}).deepseek;
  assert.equal(credential.type, "api_key");
  const payloads: string[] = [];
  let executions = 0;
  const h = await productionTaskSession(t, { verifyCapacity: verifyProviderCapacity, extra(pi) {
    pi.on("before_provider_request", event => { payloads.push(JSON.stringify(event.payload)); });
    pi.registerTool({ name: "phase1_live_probe", label: "phase1_live_probe", description: "Call once with no arguments for a short integration check.", parameters: Type.Object({}),
      async execute() {
        executions++;
        await writeFile(h.paths.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 240 }));
        await writeFile(h.paths.rule, `${await readFile(h.paths.rule, "utf8")}\nPHASE1_HOT_RULE {{recent_turns}}/{{evict_turns}}`);
        return { content: [{ type: "text", text: "PROBE_OK. Reply MEMWEAVE_PHASE1_OK." }], details: {} };
      },
    });
  } });
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash")!;
  await h.session.setModel(model);
  await h.session.prompt("这是简短集成检查，不是持续任务。仅调用 phase1_live_probe 一次，成功后只回复 MEMWEAVE_PHASE1_OK，不需要其他操作。");
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  assert.equal(executions, 1); assert.equal(payloads.length, 2);
  assert.match(payloads[1]!, /PHASE1_HOT_RULE 240\/40/);
  for (const payload of payloads) {
    assert.match(payload, /You are an expert coding assistant/);
    assert.match(payload, /本次预算快照/);
    assert.equal(payload.split("<pi_long_task_rule>").length - 1, 1);
    assert.doesNotMatch(payload, /NATIVE_SYSTEM|PHASE1_TEST_STATE/);
  }
  await writeFile(h.paths.rule, "{{unknown}}");
  await h.session.prompt("This must be cancelled before inference");
  assert.equal(payloads.length, 2); assert.match(h.diagnostics.at(-1)!, /INVALID_RULE/);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /pi_long_task_rule|PHASE1_HOT_RULE|本次预算快照/);
  t.diagnostic("2 real inference requests; native System/default tools and full Rule retained while a test suffix/config hot-reloads");
});
