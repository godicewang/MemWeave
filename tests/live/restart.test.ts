import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";
import { restartMetadata, restartTaskId } from "../../src/task/restart-model.ts";

async function fixture(t: TestContext) {
  const h = await taskSession(t, { verifyCapacity: (model, ctx, settings) => model.provider === "memweave-test"
    ? Promise.resolve(model.contextWindow) : verifyProviderCapacity(model, ctx, settings) });
  h.faux.setResponses([
    fauxAssistantMessage([fauxToolCall("task_create", { title: "old task", goal: "旧目标支付模块优化", project_name: "MemWeave", summary: "old work", keywords: ["old"] }, { id: "old" })]),
    fauxAssistantMessage("old task created"),
  ]);
  await h.session.prompt("earlier work");
  const old = (await h.tasks.index.read())[0]!, bytes = await readFile(h.paths.state(old));
  const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const original = await readFile(authPath);
  t.after(async () => assert.ok(original.equals(await readFile(authPath))));
  const credential = (JSON.parse(original.toString()) as { deepseek?: { key?: unknown } }).deepseek;
  assert.ok(typeof credential?.key === "string");
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash"); assert.ok(model);
  await h.session.setModel(model); h.session.setActiveToolsByName(["task_create"]);
  return { ...h, old, bytes };
}

test("real Flash: 26000 native-format records restart without inference, survive reload, and establish a fresh Goal", { timeout: 120000 }, async (t) => {
  const h = await fixture(t);
  for (let i = 0; i < 26000; i++) h.manager.appendMessage({ role: "user", content: "旧原生交互 " + i, timestamp: i });
  const originals = h.manager.getBranch().filter((entry) => entry.type === "message"), frames = h.frames.length;
  await h.session.prompt("/memweave-restart");
  assert.equal(h.frames.length, frames);
  const receipt = restartMetadata(h.manager.getBranch())!;
  assert.ok(receipt); assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  await h.session.reload();
  h.session.setActiveToolsByName(["task_create"]);
  await h.session.prompt("接下来开展新的订单批次校验工作，请先确立新的工作目标即可，不执行外部操作。");
  const id = scopeOf(h.manager.getBranch()).task_id;
  assert.equal(id, restartTaskId(h.manager.getSessionId(), receipt.data.restart_id));
  assert.notEqual(id, h.old.task_id);
  const task = await h.tasks.index.get(id!); const state = await h.tasks.state.read(task);
  assert.equal(state.version, 1); assert.equal(state.facts.length + state.decisions.length, 0);
  assert.match(state.goal, /批次|batch/i);
  assert.ok(h.bytes.equals(await readFile(h.paths.state(h.old))));
  assert.ok(h.budgets.at(-1)!.M < 300);
  assert.deepEqual(h.manager.getBranch().filter((entry) => entry.type === "message").slice(0, originals.length), originals);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  const final = h.session.agent.state.messages.at(-1); assert.ok(final?.role === "assistant" && final.stopReason === "stop");
  t.diagnostic((h.frames.length - frames) + " real requests; no inference from command; 26000 records synthetic, fresh Goal real");
});

test("real Flash: ambiguous restart asks for the goal and keeps the intent until the user's clarification", { timeout: 120000 }, async (t) => {
  const h = await fixture(t);
  await h.session.prompt("/memweave-restart");
  const receipt = restartMetadata(h.manager.getBranch())!, frames = h.frames.length;
  await h.session.prompt("新的任务还没决定，与旧目标无关，请先问我一个问题确认目标。");
  const premature = (await h.tasks.index.read()).filter((task) => task.task_id !== h.old.task_id);
  if (premature.length) t.diagnostic(JSON.stringify({ prematureGoals: await Promise.all(premature.map(async task => (await h.tasks.state.read(task)).goal)) }));
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  assert.equal((await h.tasks.index.read()).length, 1);
  const question = h.session.agent.state.messages.at(-1);
  assert.ok(question?.role === "assistant" && question.stopReason === "stop");
  assert.match(JSON.stringify(question.content), /？|\?/);
  await h.session.prompt("新目标是实现订单批次校验，先建立这个工作目标，不执行外部操作。");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, restartTaskId(h.manager.getSessionId(), receipt.data.restart_id));
  assert.equal((await h.tasks.index.read()).length, 2);
  assert.ok(h.bytes.equals(await readFile(h.paths.state(h.old))));
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  t.diagnostic((h.frames.length - frames) + " real requests; ambiguous objective did not invent a Goal");
});
