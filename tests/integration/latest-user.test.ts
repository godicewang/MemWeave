import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile } from "node:fs/promises";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { ordinaryText } from "../../src/window/budget.ts";
import { CURRENT_USER_MARKER } from "../../src/window/render.ts";
import type { RequestMessages } from "../../src/pi/request-lifecycle.ts";

const marked = (frame: RequestMessages) => frame.filter(
  (message) => message.role === "user" && ordinaryText(message).split("\n").slice(0, 3).includes(CURRENT_USER_MARKER),
);
test("two cancelled requests retain originals but mark only the latest real user after recovery, without Task", async (t) => {
  const h = await taskSession(t);
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 200, evict_turns: 40,
    context_budget: { model_percent: 0.01 }, elastic_budget: { extra_model_percent: 0 } }));
  await h.session.prompt("Only reply FIRST_EXPECT");
  await h.session.prompt("Only reply SECOND_EXPECT");
  assert.equal(h.faux.state.callCount, 0);
  assert.equal(h.diagnostics.length, 2);
  assert.ok(h.diagnostics.every((error) => /CONTEXT_BUDGET_EXCEEDED/.test(error)));
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 199, evict_turns: 40 }));
  h.faux.setResponses([fauxAssistantMessage("THIRD_EXPECT")]);
  await h.session.prompt("Only reply THIRD_EXPECT");
  const frame = h.frames.at(-1)!, users = frame.filter((message) => message.role === "user");
  assert.equal(users.length, 3);
  assert.deepEqual(users.map((message) => ordinaryText(message).match(/(?:FIRST|SECOND|THIRD)_EXPECT/)![0]),
    ["FIRST_EXPECT", "SECOND_EXPECT", "THIRD_EXPECT"]);
  assert.equal(marked(frame).length, 1);
  assert.match(JSON.stringify(marked(frame)), /THIRD_EXPECT/);
  const originals = h.manager.getEntries().filter((e) => e.type === "message" && e.message.role === "user");
  assert.equal(originals.length, 3);
  assert.doesNotMatch(JSON.stringify(originals), /CURRENT_USER_MESSAGE/);
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /最新真实用户要求|# Symbolic State/);
  assert.equal((await h.tasks.index.read()).length, 0);
});

test("tool continuations keep the same real user; State is unmarked and an evicted user is not pinned", async (t) => {
  const h = await taskSession(t);
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 2, evict_turns: 1 }));
  h.faux.setResponses([
    fauxAssistantMessage([fauxToolCall("task_create", {
      title: "latest user", goal: "check priority", project_name: "MemWeave", summary: "priority", keywords: ["priority"],
    }, { id: "create" })]),
    fauxAssistantMessage([fauxToolCall("state_append", { items: [
      { type: "fact", content: "first", evidence: { U1: "request" } },
    ] }, { id: "first" })]),
    fauxAssistantMessage([fauxToolCall("state_append", { items: [
      { type: "decision", content: "second", evidence: { U1: "request" } },
    ] }, { id: "second" })]),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("Real user request");
  for (const frame of h.frames.slice(0, 3)) {
    assert.equal(marked(frame).length, 1);
    assert.match(JSON.stringify(marked(frame)), /Real user request/);
  }
  assert.equal(marked(h.frames.at(-1)!).length, 0);
  assert.doesNotMatch(JSON.stringify(h.frames.at(-1)), /Real user request/);
  assert.equal(h.frames.at(-1)!.at(-1)!.role, "custom");
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});

test("tree navigation identifies the latest user on the active branch", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("one")]);
  await h.session.prompt("shared branch");
  const anchor = h.manager.getLeafId()!;
  h.faux.setResponses([fauxAssistantMessage("two")]);
  await h.session.prompt("abandoned branch");
  await h.session.navigateTree(anchor, { summarize: false });
  h.faux.setResponses([fauxAssistantMessage("three")]);
  await h.session.prompt("current branch");
  const frame = h.frames.at(-1)!;
  assert.equal(marked(frame).length, 1);
  assert.match(JSON.stringify(marked(frame)), /current branch/);
  assert.doesNotMatch(JSON.stringify(frame), /abandoned branch/);
  assert.deepEqual(h.diagnostics, []);
});
