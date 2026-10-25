import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { getSystemMessageText } from "@earendil-works/pi-ai";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";

test("stage guidance reaches the effective system/tools but ordinary turn completion creates no automatic cognition", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", {
    title: "stage", goal: "verify delivery", project_name: "MemWeave", summary: "phase", keywords: ["phase"],
  }, { id: "create" })]), fauxAssistantMessage("Please clarify the remaining requirement.")]);
  await h.session.prompt("start ongoing work");
  const system = h.frames.at(-1)![0]!;
  assert.ok(system.role === "system");
  assert.match(getSystemMessageText(system), /先验业务、再验记忆/);
  assert.match(getSystemMessageText(system), /turn_end.*不等于阶段完成/);
  const tools = h.session.getAllTools();
  assert.match(tools.find((tool) => tool.name === "state_append")!.description, /stage.*result/);
  assert.match(tools.find((tool) => tool.name === "task_create")!.description, /Short.*Q&A/);
  const task = (await h.tasks.index.read())[0]!, state = await h.tasks.state.read(task);
  assert.equal(state.version, 1); assert.equal(state.facts.length + state.decisions.length, 0);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /先验业务、再验记忆|pi_long_task_rule/);
});
