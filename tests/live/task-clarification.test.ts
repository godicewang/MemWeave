import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage as answer, fauxToolCall as call } from "@earendil-works/pi-ai/providers/faux";
import { productionTaskSession } from "../fixtures/production-session.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";
import { bindingReceipts } from "../../src/task/binding.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";

test("real Flash asks before ambiguous recovery, stops without guessing, then restores the user's chosen Task", { timeout: 180000 }, async (t) => {
  const source = await productionTaskSession(t);
  const goals = ["修复支付接口重复扣款并验证幂等键", "改进支付退款超时与失败补偿", "设计支付对账差异报表", "修复登录状态提前过期", "优化构建缓存"];
  for (const [i, goal] of goals.entries()) {
    source.faux.setResponses([answer([call("task_create", {
      title: goal, goal, project_name: "P", summary: goal,
      keywords: [i < 3 ? "payment" : "engineering"],
    })]), answer("created")]);
    await source.session.prompt(goal);
    source.faux.setResponses([answer("已确认，只保留讨论，不操作外部系统")]);
    await source.session.prompt(`该工作的环境别名为${i === 1 ? "REFUND_CHOSEN_72" : "OTHER_WORK_" + i}；暂不执行业务操作。`);
  }
  const tasks = await source.tasks.index.read(), target = tasks.find((task) => task.title === goals[1])!;
  const before = await Promise.all(tasks.map((task) => readFile(source.paths.state(task))));
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const auth = await readFile(authPath);
  t.after(async () => assert.ok(auth.equals(await readFile(authPath))));
  const key = (JSON.parse(auth.toString()) as {deepseek?:{key?:unknown}}).deepseek?.key;
  assert.equal(typeof key, "string");
  const h = await productionTaskSession(t, { paths: source.paths, verifyCapacity: verifyProviderCapacity });
  await h.runtime.setRuntimeApiKey("deepseek", key as string);
  const model = h.runtime.getModel("deepseek", "deepseek-flash");
  assert.ok(model); await h.session.setModel(model);
  await h.session.prompt("继续之前支付那个任务，先讨论下一步。");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null, "ambiguous input must not bind any candidate");
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 0);
  const ask = h.manager.getBranch().findLast((e) => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "task_clarify");
  assert.ok(ask?.type === "message" && ask.message.role === "toolResult" && !ask.message.isError, "the real Agent must use the clarification tool");
  assert.equal((ask.message.details as {status:string}).status, "waiting_for_user");
  for (const [i, task] of tasks.entries()) assert.ok(before[i]!.equals(await readFile(source.paths.state(task))));
  await h.session.prompt("退款超时与失败补偿那个。恢复后只告诉我之前讨论的环境别名，不执行任何外部业务操作。");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, target.task_id);
  assert.equal((await h.tasks.index.read()).length, goals.length);
  const last = h.session.agent.state.messages.at(-1);
  assert.ok(last?.role === "assistant" && last.stopReason === "stop");
  assert.match(JSON.stringify(last.content), /REFUND_CHOSEN_72/);
  const calls = h.manager.getBranch().flatMap((e) => e.type === "message" && e.message.role === "assistant"
    ? e.message.content.filter((p) => p.type === "toolCall") : []);
  assert.ok(calls.every((c) => c.name !== "task_find" || !("initialize" in c.arguments)));
  assert.ok(!calls.some((c) => ["bash", "read", "write", "edit"].includes(c.name)));
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
  t.diagnostic("full production Pi/Rule/default tools; ambiguous first input paused through task_clarify; actual follow-up selected refund Task and recovered raw old alias; scripted setup is separate from real Flash decisions");
});
