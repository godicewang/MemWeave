import assert from "node:assert/strict";
import test from "node:test";
import { writeFile, readFile } from "node:fs/promises";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";

test("native tools advertise required type/example and report actual/configured Goal limits without committing", async (t) => {
  const h = await taskSession(t);
  await writeFile(h.paths.config, JSON.stringify({ state_event_max_chars: 7 }));
  const tools = h.session.getAllTools();
  assert.match(tools.find((tool) => tool.name === "state_append")!.description, /type.*fact.*decision/);
  assert.match(tools.find((tool) => tool.name === "state_append")!.description, /"items".*"type"/);
  assert.match(tools.find((tool) => tool.name === "task_create")!.description, /state_event_max_chars/);
  const create = { title: "limits", goal: "😀".repeat(8), project_name: "test", summary: "test", keywords: ["test"] };
  h.faux.setResponses([
    fauxAssistantMessage([fauxToolCall("task_create", create, { id: "bad-goal" })]),
    fauxAssistantMessage("rejected"),
  ]);
  await h.session.prompt("create with oversized goal");
  assert.equal((await h.tasks.index.read()).length, 0);
  const result = h.manager.getEntries().find((entry) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolCallId === "bad-goal");
  assert.ok(result?.type === "message" && result.message.role === "toolResult" && result.message.isError);
  assert.match(JSON.stringify(result.message.content), /field=task_create.goal.*actual=8.*max=7/);
  h.faux.setResponses([
    fauxAssistantMessage([fauxToolCall("task_create", { ...create, goal: "😀".repeat(7) }, { id: "create" })]),
    fauxAssistantMessage([fauxToolCall("state_append", { items: [{ content: "short", evidence: { U1: "user" } }] }, { id: "missing-type" })]),
    fauxAssistantMessage([fauxToolCall("state_append", { items: [{ type: "fact", content: "short", evidence: { U1: "user" } }] }, { id: "valid" })]),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("create valid goal and verify State type rejection");
  const task = (await h.tasks.index.read())[0]!;
  assert.equal((await h.tasks.state.read(task)).version, 2);
  const bad = h.manager.getEntries().find((entry) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolCallId === "missing-type");
  assert.ok(bad?.type === "message" && bad.message.role === "toolResult" && bad.message.isError);
  assert.match(JSON.stringify(bad.message.content), /type/);
  const before = await readFile(h.paths.state(task), "utf8");
  await assert.rejects(h.tasks.state.append(task, [{ type: "fact", content: "😀".repeat(8), evidence: { U1: "user" } }], "oversize", 7, new Set(["U1"])), /field=items\[0\].content; actual=8; max=7/);
  await assert.rejects(h.tasks.state.updateGoal(task, { goal: "😀".repeat(8), summary: "s", keywords: ["s"], evidence: { U1: "user" } }, "goal-oversize", 7, new Set(["U1"])), /field=update_goal.goal; actual=8; max=7/);
  await assert.rejects(h.tasks.state.modifyFact(task, { archive: ["F1"], append_fact: { content: "😀".repeat(8), evidence: { U1: "user" } } }, "modify-oversize", 7, new Set(["U1"])), /field=modify_fact.append_fact.content; actual=8; max=7/);
  assert.equal(await readFile(h.paths.state(task), "utf8"), before);
});
