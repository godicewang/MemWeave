import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile } from "node:fs/promises";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { taskSession } from "../fixtures/task-session.ts";
import { ordinaryText } from "../../src/window/budget.ts";
const create = { title: "Elastic", goal: "Verify bounded reads", project_name: "MemWeave", summary: "Elastic budget", keywords: ["elastic"] };
const call = (name: string, args: Parameters<typeof fauxToolCall>[1], id = name) => fauxAssistantMessage([fauxToolCall(name, args, { id })]);
const results = (h: Awaited<ReturnType<typeof taskSession>>) => h.manager.getBranch().flatMap(e =>
  e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "memory_read" ? [{ ...e, message: e.message }] : []);

test("parallel native reads share one pool, keep valid truncated JSON and ranges, and idempotent retries do not charge twice", async t => {
  const h = await taskSession(t, { verifyCapacity: async () => 120000 });
  h.faux.setResponses([call("task_create", create), fauxAssistantMessage("created")]);
  await h.session.prompt("S".repeat(50000));
  assert.deepEqual(h.diagnostics, []);
  const args = { items: [{ ref: "U1" }], max_total_chars: 50000 };
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("memory_read", args, { id: "r1" }),
    fauxToolCall("memory_read", args, { id: "r2" })]), fauxAssistantMessage("done")]);
  await h.session.prompt("read two ranges concurrently");
  const rows = results(h);
  assert.equal(rows.length, 2);
  const success = rows.filter(e => !e.message.isError);
  assert.equal(success.length, 2);
  const body = success[0]!.message.content[0];
  assert.ok(body?.type === "text");
  const payload = JSON.parse(body.text);
  assert.equal(payload.items[0].source_complete, true);
  assert.equal(payload.items[0].range_complete, false);
  assert.equal(payload.total_chars, payload.items[0].content.length);
  assert.ok(payload.total_chars > 0 && payload.total_chars < 50000);
  assert.match(ordinaryText(success[0]!.message), /\[TRUNCATED\]$/);
  const tool = h.session.agent.state.tools.find(tool => tool.name === "memory_read")!;
  const retried = await tool.execute(success[0]!.message.toolCallId, args, undefined);
  assert.deepEqual(await tool.execute(success[0]!.message.toolCallId, args, undefined), retried);
  h.faux.setResponses([call("memory_read", { items: [{ ref: "U1", offset: 10000, limit: 30000 }], max_total_chars: 30000 }, "offset-read"), fauxAssistantMessage("continued")]);
  await h.session.prompt("Continue using offset while older reads are still alive");
  const continued = results(h).at(-1)!;
  assert.equal(continued.message.isError, false);
  const continuedBody = continued.message.content[0];
  assert.ok(continuedBody?.type === "text");
  assert.equal(JSON.parse(continuedBody.text).items[0].offset, 10000);
  assert.ok(JSON.parse(continuedBody.text).total_chars > 0);
  assert.ok(h.budgets.every(b => b.X <= b.readLimit && b.windowUsed <= b.windowLimit && b.total <= b.peak - b.poolSafety));
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});

test("a shrinking pool truncates live reads, then the expired aggregate cap applies across native disk recovery", async t => {
  let capacity = 1000000;
  const h = await taskSession(t, { verifyCapacity: async () => capacity });
  const rule = await readFile(h.paths.rule);
  h.faux.setResponses([call("task_create", create), fauxAssistantMessage("created")]);
  await h.session.prompt("original:" + "ABCD".repeat(12500));
  h.faux.setResponses([call("memory_read", { items: [{ ref: "U1", limit: 50000 }], max_total_chars: 50000 }), fauxAssistantMessage("read")]);
  await h.session.prompt("read the known range");
  const stored = structuredClone(results(h)[0]!);
  assert.doesNotMatch(ordinaryText(stored.message), /\[TRUNCATED\]/);
  assert.equal(JSON.parse(ordinaryText(stored.message)).items[0].range_complete, true);
  capacity = 120000;
  h.faux.setResponses([fauxAssistantMessage("smaller model")]);
  await h.session.prompt("continue with smaller capacity");
  assert.ok(h.budgets.at(-1)!.X > 0);
  const shown = h.frames.at(-1)!.find(m => m.role === "toolResult" && m.toolCallId === stored.message.toolCallId);
  assert.ok(shown?.role === "toolResult");
  assert.match(ordinaryText(shown), /\[TRUNCATED\]$/);
  assert.deepEqual(h.manager.getBranch().find(e => e.id === stored.id), stored);
  const reopened = await taskSession(t, { paths: h.paths, manager: SessionManager.open(h.manager.getSessionFile()!), verifyCapacity: async () => capacity });
  for (let i = 0; i < 5; i++) {
    reopened.faux.setResponses([fauxAssistantMessage("continue")]);
    await reopened.session.prompt("next");
  }
  const b = reopened.budgets.at(-1)!;
  assert.equal(b.X, 0);
  assert.ok(b.expiredUsed > 0 && b.expiredUsed <= Math.floor(b.windowLimit * .1));
  assert.equal(JSON.stringify(reopened.manager.getBranch().find(e => e.id === stored.id)), JSON.stringify(stored));
  assert.deepEqual(await readFile(h.paths.rule), rule);
  assert.deepEqual(reopened.diagnostics, []);
});

test("native historical State token limits preserve valid evidence/ranges and do not modify cognition", async t => {
  const h = await taskSession(t, { verifyCapacity: async () => 120000 });
  h.faux.setResponses([call("task_create", create), call("state_append", { items: [
    { type: "fact", content: "A source-backed fact", evidence: { U1: "evidence".repeat(5000) } },
  ] }), fauxAssistantMessage("saved")]);
  await h.session.prompt("known evidence source");
  const task = (await h.tasks.index.read())[0]!, state = await readFile(h.paths.state(task));
  h.faux.setResponses([call("state_read", { task_id: task.task_id, event_ids: ["F1"], max_total_chars: 50000 }), fauxAssistantMessage("read")]);
  await h.session.prompt("read the historical fact and its evidence");
  const row = h.manager.getBranch().findLast(e => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "state_read");
  assert.ok(row?.type === "message" && row.message.role === "toolResult" && !row.message.isError);
  const text = row.message.content[0];
  assert.ok(text?.type === "text");
  const result = JSON.parse(text.text);
  assert.equal(result.items[0].truncated, true);
  assert.deepEqual(Object.keys(result.items[0].evidence), ["U1"]);
  assert.ok(result.total_chars > 0 && result.total_chars < result.items[0].total_chars);
  assert.match(ordinaryText(row.message), /\[TRUNCATED\]$/);
  assert.deepEqual(await readFile(h.paths.state(task)), state);
  assert.deepEqual(h.diagnostics, []);
});

test("a pool too small for result metadata produces a native tool error and lets the agent continue", async t => {
  const h = await taskSession(t);
  await writeFile(h.paths.config, JSON.stringify({ elastic_budget: { pool_percent: { read: .01, window: 79.99, safety: 20 } } }));
  h.faux.setResponses([call("task_create", create), call("memory_read", { items: [{ ref: "U1" }] }), fauxAssistantMessage("handled tool error")]);
  await h.session.prompt("known source");
  const row = results(h)[0]!;
  assert.equal(row.message.isError, true);
  assert.match(ordinaryText(row.message), /READ_BUDGET_EXCEEDED.*available/);
  assert.equal(h.faux.state.callCount, 3);
  assert.equal(h.budgets.at(-1)!.X, 0);
  assert.deepEqual(h.diagnostics, []);
});
