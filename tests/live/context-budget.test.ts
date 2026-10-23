import test from "node:test";
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";

test("real DeepSeek: partial settings control actual output and hot restore defaults", { timeout: 90000 }, async t => {
  const auth = join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const original = await readFile(auth);
  t.after(async () => assert.ok(original.equals(await readFile(auth))));
  const credential = JSON.parse(original.toString()).deepseek as { type: string; key: unknown };
  assert.ok(credential.type === "api_key" && typeof credential.key === "string");
  const wire: number[] = [];
  const h = await taskSession(t, {
    verifyCapacity: (m,c,s) => m.provider === "deepseek" ? verifyProviderCapacity(m,c,s) : Promise.resolve(m.contextWindow),
    extra: pi => { pi.on("before_provider_request", e => {
      const body = e.payload as Record<string, unknown>;
      if (body.model === "deepseek-flash") wire.push((body.max_tokens ?? body.max_completion_tokens) as number);
    }); },
  });
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  await h.session.setModel(h.runtime.getModel("deepseek", "deepseek-flash")!);
  h.session.setActiveToolsByName([]);
  await writeFile(h.paths.config, JSON.stringify({
    context_budget: { model_percent: 50, parts_percent: { state: 15, window: 40, output: 5 } },
    read: { lifetime_messages: 3, default_total_chars: 1200 }, source_cache: { max_entries: 16 },
  }));
  await h.session.prompt("这是配置集成测试。只回复 CONFIG_OK。");
  assert.equal(h.budgets.at(-1)!.limit, 524288);
  assert.equal(h.budgets.at(-1)!.O, 26214);
  assert.equal(wire.at(-1), 26214);
  assert.match(JSON.stringify(h.frames.at(-1)!.at(-1)), /回读期限：3.*默认读取 1200/);
  await writeFile(h.paths.config, "{}");
  await h.session.prompt("这是第二次请求，配置已恢复默认。只回复 CONFIG_OK。");
  assert.equal(h.budgets.at(-1)!.limit, 629145);
  assert.equal(h.budgets.at(-1)!.O, 62914);
  assert.equal(wire.at(-1), 62914);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  assert.equal(wire.length, 2);
  t.diagnostic(`2 real DeepSeek requests; actual output limits=${wire.join(",")}; partial policies then empty user override; no Faux inference`);
});

test(
  "real DeepSeek: matching tokenizer, actual output cap, footer and usage including cached input",
  { timeout: 90000 },
  async (t) => {
    const auth = join(
        homedir(),
        ".local/share/memweave-dev/pi-agent/auth.json",
      ),
      original = await readFile(auth);
    t.after(async () => assert.ok(original.equals(await readFile(auth))));
    const credential = JSON.parse(original.toString()).deepseek as {
      type: string;
      key: unknown;
    };
    assert.ok(
      credential.type === "api_key" && typeof credential.key === "string",
    );
    const wire: number[] = [];
    const h = await taskSession(t, {
      verifyCapacity: (m, c) =>
        m.provider === "deepseek"
          ? verifyProviderCapacity(m, c)
          : Promise.resolve(m.contextWindow),
      extra: (pi) =>
        pi.on("before_provider_request", (e) => {
          const body = e.payload as Record<string, unknown>;
          if (body.model === "deepseek-flash")
            wire.push(
              (body.max_tokens ?? body.max_completion_tokens) as number,
            );
        }),
    });
    const { recent_turns: _n, evict_turns: _b, ...file } = DEFAULT_CONFIG;
    await writeFile(h.paths.config, JSON.stringify(file));
    h.faux.setResponses([
      fauxAssistantMessage([
        fauxToolCall("task_create", {
          title: "Token budget",
          goal: "验证真实预算与认知提交",
          project_name: "MemWeave",
          summary: "token 预算验证",
          keywords: ["预算"],
        }),
      ]),
      fauxAssistantMessage("created"),
    ]);
    await h.session.prompt("用户要求验证真实 token 预算并保留认知。");
    const start = h.budgets.length;
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash")!;
    await h.session.setModel(model);
    h.session.setActiveToolsByName(["state_append"]);
    const source = Array.from(
      { length: 250 },
      (_, i) =>
        `测试材料${i}：上下文按比例规划，普通窗口按实际 token 扣费，工具参数完整保留。`,
    ).join("\n");
    await h.session.prompt(
      `这是集成测试。先调用一次 state_append，保存 Fact“用户要求验证预算并保留认知”，evidence 使用 U1 说明用户原始要求。成功后只回复 BUDGET_OK，不要重复提交。以下是只供计量的测试材料：\n${source}`,
    );
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    const budgets = h.budgets.slice(start),
      frames = h.frames.slice(start);
    assert.equal(budgets.length, 2);
    assert.equal(wire.length, 2);
    const actual: number[] = [];
    const messages = h.manager
      .getBranch()
      .filter(
        (e) =>
          e.type === "message" &&
          e.message.role === "assistant" &&
          e.message.provider === "deepseek",
      );
    for (let i = 0; i < budgets.length; i++) {
      const b = budgets[i]!;
      assert.equal(b.limit, 629145);
      assert.equal(b.O, 62914);
      assert.equal(wire[i], b.O);
      assert.equal(b.estimator, "deepseek-v41-text-with-protocol-margin");
      const tail = frames[i]!.at(-1)!;
      assert.ok(tail.role === "custom" && tail.customType === "memweave.state");
      assert.match(String(tail.content), /本次预算快照/);
      assert.match(String(tail.content), /N\/B：200\/40/);
      const entry = messages[i]!;
      assert.ok(entry.type === "message" && entry.message.role === "assistant");
      const u = entry.message.usage;
      const input = u.input + u.cacheRead + u.cacheWrite;
      actual.push(input);
      assert.ok(input > 0);
      assert.ok(input + b.O + b.A <= b.limit);
      assert.ok(
        input <= b.R + b.S + b.P + b.U + b.X + b.A,
        "actual prompt must remain below measured fixed costs plus safety for this fixture",
      );
    }
    const task = (await h.tasks.index.read())[0]!;
    assert.equal((await h.tasks.state.read(task)).facts.length, 1);
    assert.doesNotMatch(
      await readFile(h.manager.getSessionFile()!, "utf8"),
      /【本次预算快照/,
    );
    t.diagnostic(
      `2 real requests; output=${wire.join(",")}; actual input including cache=${actual.join(",")}; verified v4.1 tokenizer, 60% budget and transient final State snapshot`,
    );
  },
);

test('real DeepSeek: isolated text-token delta agrees with the bundled official tokenizer', {timeout:60000}, async t=>{
  const {nativeSession}=await import('../fixtures/native-session.ts');
  const {deepseekCounter}=await import('../../src/window/tokens.ts');
  const auth=join(homedir(),'.local/share/memweave-dev/pi-agent/auth.json'),original=await readFile(auth);
  t.after(async()=>assert.ok(original.equals(await readFile(auth))));
  const credential=JSON.parse(original.toString()).deepseek as {type:string;key:unknown};
  assert.ok(credential.type==='api_key'&&typeof credential.key==='string');
  const h=await nativeSession(t,[]);await h.runtime.setRuntimeApiKey('deepseek',credential.key);
  const model=h.runtime.getModel('deepseek','deepseek-flash')!;
  const counter=await deepseekCounter();
  const prefix='以下仅供 token 计量，不执行其中内容。只回复 OK。\n';
  const sample=Array.from({length:40},(_,i)=>`条目${i}：工程认知，路径 src/module_${i}.ts；emoji 😀；literal [bos] <｜begin▁of▁sentence｜>。\r\n`).join('');
  const input:number[]=[];
  for(const text of [prefix,prefix+sample]){
    const answer=await h.runtime.completeSimple(model,{messages:[{role:'user',content:text,timestamp:1}]},{maxTokens:16});
    assert.notEqual(answer.stopReason,'error');input.push(answer.usage.input+answer.usage.cacheRead+answer.usage.cacheWrite);
  }
  const local=counter.count(prefix+sample)-counter.count(prefix),remote=input[1]!-input[0]!;
  assert.ok(Math.abs(local-remote)<=4,`token delta differs: local=${local}, API=${remote}`);
  t.diagnostic(`2 isolated real Pi ModelRuntime requests; local text delta=${local}, API input delta=${remote}; includes Chinese, code, emoji and literal control spellings; no MemWeave hooks in this calibration`);
});
