import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";
const create = {
  title: "Goal test",
  goal: "initial goal",
  project_name: "initial project",
  summary: "initial summary",
  keywords: ["initial"],
};
const call = (
  name: string,
  args: Parameters<typeof fauxToolCall>[1],
  id = "call",
) => fauxAssistantMessage([fauxToolCall(name, args, { id })]);

test("native Goal update refreshes next-request State and discovery metadata; state_read does not switch Task", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create first task");
  const first = (await h.tasks.index.read())[0]!;
  h.faux.setResponses([
    call(
      "update_goal",
      {
        goal: "new goal",
        summary: "new summary",
        keywords: ["new"],
        project_name: "new project",
        evidence: { U2: "user changed objective" },
      },
      "goal",
    ),
    fauxAssistantMessage("updated"),
  ]);
  await h.session.prompt("change objective");
  const updated = await h.tasks.index.get(first.task_id);
  assert.equal(updated.state_version, 2);
  assert.equal(updated.summary, "new summary");
  assert.deepEqual(updated.keywords, ["new"]);
  assert.equal(updated.project_name, "new project");
  assert.match(JSON.stringify(h.frames.at(-1)), /new goal/);
  h.faux.setResponses([
    call("task_create", { ...create, title: "Second" }),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("independent second task");
  const second = scopeOf(h.manager.getBranch()).task_id;
  const before = await readFile(h.paths.state(first), "utf8");
  h.faux.setResponses([
    call("state_read", { task_id: first.task_id }),
    fauxAssistantMessage("read"),
  ]);
  await h.session.prompt("read first cognition");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, second);
  assert.equal(await readFile(h.paths.state(first), "utf8"), before);
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});

test("index failure after Goal commit is repaired from native source arguments; stale call retry cannot roll metadata back", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create");
  const task = (await h.tasks.index.read())[0]!;
  const put = h.tasks.index.put.bind(h.tasks.index);
  let fail = true;
  h.tasks.index.put = async (value) => {
    if (value.state_version === 2 && fail) {
      fail = false;
      throw Error("injected index failure");
    }
    return put(value);
  };
  const first = {
    goal: "goal v2",
    summary: "summary v2",
    keywords: ["v2"],
    project_name: "project v2",
    evidence: { U2: "user request" },
  };
  h.faux.setResponses([
    call("update_goal", first, "old-goal"),
    fauxAssistantMessage("continuation repairs metadata"),
  ]);
  await h.session.prompt("change goal once");
  assert.equal((await h.tasks.state.read(task)).version, 2);
  assert.equal((await h.tasks.index.get(task.task_id)).summary, "summary v2");
  const latest = await h.tasks.index.get(task.task_id);
  await h.tasks.index.put({
    ...latest,
    state_version: 1,
    summary: create.summary,
    keywords: create.keywords,
    project_name: create.project_name,
  });
  await h.session.reload();
  h.faux.setResponses([fauxAssistantMessage("repaired after reload")]);
  await h.session.prompt("recover discovery metadata after reload");
  assert.equal((await h.tasks.index.get(task.task_id)).summary, "summary v2");
  assert.equal(
    (await h.tasks.index.get(task.task_id)).project_name,
    "project v2",
  );
  const second = {
    goal: "goal v3",
    summary: "summary v3",
    keywords: ["v3"],
    evidence: { U4: "newer request" },
  };
  h.faux.setResponses([
    call("update_goal", second, "new-goal"),
    fauxAssistantMessage("updated"),
  ]);
  await h.session.prompt("change goal again");
  assert.equal(
    await h.tasks.updateGoal(
      first,
      h.session.extensionRunner.createContext(),
      "old-goal",
    ),
    "State updated: v3",
  );
  const current = await h.tasks.index.get(task.task_id);
  assert.equal(current.summary, "summary v3");
  assert.equal(current.project_name, "project v2");
  assert.deepEqual(h.diagnostics, []);
});

test("retrying native task_create after a Goal change preserves the newer discovery metadata and cognition", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create, "create-original"),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create");
  const task = (await h.tasks.index.read())[0]!;
  h.faux.setResponses([
    call(
      "update_goal",
      {
        goal: "later objective",
        summary: "later summary",
        keywords: ["later"],
        evidence: { U2: "new goal" },
      },
      "goal",
    ),
    fauxAssistantMessage("updated"),
  ]);
  await h.session.prompt("change");
  const result = await h.tasks.create(
    create,
    h.session.extensionRunner.createContext(),
    "create-original",
  );
  assert.equal(result.state_version, 2);
  assert.equal(
    (await h.tasks.index.get(task.task_id)).summary,
    "later summary",
  );
  assert.equal((await h.tasks.state.read(task)).goal, "later objective");
  assert.equal((await h.tasks.index.read()).length, 1);
});
