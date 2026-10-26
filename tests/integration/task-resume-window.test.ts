import test from "node:test";
import assert from "node:assert/strict";
import {
  fauxAssistantMessage as answer,
  fauxToolCall as call,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { resumeMetadata } from "../../src/task/resume-window.ts";
import { readFile, rm, mkdir } from "node:fs/promises";
import { scopeOf } from "../../src/pi/session-memory.ts";
test("cross Session resume restores the old Task's bounded events without copying messages and survives reload", async (t) => {
  const source = await taskSession(t);
  source.faux.setResponses([
    answer([
      call("task_create", {
        title: "A",
        goal: "订单校验",
        project_name: "P",
        summary: "orders",
        keywords: ["orders"],
      }),
    ]),
    answer("OLD_TASK_CONTEXT_123"),
  ]);
  await source.session.prompt("OLD_TASK_REQUEST_123");
  const task = (await source.tasks.index.read())[0]!;
  const target = await taskSession(t, { paths: source.paths });
  target.faux.setResponses([
    answer([call("task_resume", { task_id: task.task_id })]),
    answer("resumed"),
  ]);
  await target.session.prompt("继续订单校验");
  assert.ok(resumeMetadata(target.manager.getBranch()));
  assert.match(JSON.stringify(target.frames.at(-1)), /OLD_TASK_CONTEXT_123/);
  assert.match(JSON.stringify(target.frames.at(-1)), /继续订单校验/);
  assert.ok(
    !target.manager
      .getBranch()
      .some(
        (e) =>
          e.type === "message" &&
          JSON.stringify(e.message).includes("OLD_TASK_CONTEXT_123"),
      ),
  );
  const before = source.manager.getBranch();
  await target.session.reload();
  target.faux.setResponses([answer("continued")]);
  await target.session.prompt("继续");
  assert.match(JSON.stringify(target.frames.at(-1)), /OLD_TASK_CONTEXT_123/);
  assert.deepEqual(source.manager.getBranch(), before);
  assert.deepEqual(target.diagnostics, []);
  assert.deepEqual(target.errors, []);
});

test("source is frozen, another Task is excluded, N/B reset expands only the chosen branch", async (t) => {
  const source = await taskSession(t);
  const create = {
    title: "A",
    goal: "订单",
    project_name: "P",
    summary: "orders",
    keywords: ["orders"],
  };
  source.faux.setResponses([
    answer([call("task_create", create)]),
    answer("A_FIRST"),
  ]);
  await source.session.prompt("A_USER");
  const task = (await source.tasks.index.read())[0]!;
  source.faux.setResponses([
    answer([call("task_create", { ...create, title: "B", goal: "颜色" })]),
    answer("B_EXCLUDED"),
  ]);
  await source.session.prompt("B_USER");
  const target = await taskSession(t, { paths: source.paths });
  target.faux.setResponses([
    answer([call("task_resume", { task_id: task.task_id })]),
    answer("resumed"),
  ]);
  await target.session.prompt("恢复A");
  assert.doesNotMatch(JSON.stringify(target.frames.at(-1)), /B_EXCLUDED/);
  assert.match(JSON.stringify(target.frames.at(-1)), /A_FIRST/);
  source.faux.setResponses([answer("SOURCE_LATER_ADDITION")]);
  await source.session.prompt("B later");
  target.faux.setResponses([
    answer([call("recent_window_set", { turns: 20, evict_turns: 4 })]),
    answer("expanded"),
  ]);
  await target.session.prompt("扩大窗口");
  assert.doesNotMatch(
    JSON.stringify(target.frames.at(-1)),
    /SOURCE_LATER_ADDITION|B_EXCLUDED/,
  );
  assert.match(JSON.stringify(target.frames.at(-1)), /A_FIRST/);
  assert.deepEqual(target.diagnostics, []);
});

test("a persisted restore repairs a partial binding on disk reopening without selecting new seeds", async (t) => {
  const source = await taskSession(t);
  source.faux.setResponses([
    answer([
      call("task_create", {
        title: "A",
        goal: "订单",
        project_name: "P",
        summary: "orders",
        keywords: ["orders"],
      }),
    ]),
    answer("ORIGINAL_SEED"),
  ]);
  await source.session.prompt("orders");
  const task = (await source.tasks.index.read())[0]!,
    target = await taskSession(t, { paths: source.paths });
  const before = await readFile(source.paths.state(task));
  await rm(source.paths.view(task));
  await mkdir(source.paths.view(task));
  target.faux.setResponses([
    answer([call("task_resume", { task_id: task.task_id })]),
    answer("partial"),
  ]);
  await target.session.prompt("restore");
  const receipt = resumeMetadata(target.manager.getBranch());
  assert.ok(receipt);
  assert.equal(scopeOf(target.manager.getBranch()).task_id, null);
  await rm(source.paths.view(task), { recursive: true });
  await target.session.reload();
  target.faux.setResponses([answer("repaired")]);
  await target.session.prompt("continue after repair");
  assert.equal(scopeOf(target.manager.getBranch()).task_id, task.task_id);
  assert.deepEqual(
    resumeMetadata(target.manager.getBranch())!.data,
    receipt.data,
  );
  assert.ok(before.equals(await readFile(source.paths.state(task))));
});

test("a missing registered source fails explicitly before inference and never substitutes a different Session", async (t) => {
  const source = await taskSession(t);
  source.faux.setResponses([
    answer([
      call("task_create", {
        title: "A",
        goal: "订单",
        project_name: "P",
        summary: "orders",
        keywords: ["orders"],
      }),
    ]),
    answer("seed"),
  ]);
  await source.session.prompt("orders");
  const task = (await source.tasks.index.read())[0]!,
    target = await taskSession(t, { paths: source.paths });
  target.faux.setResponses([
    answer([call("task_resume", { task_id: task.task_id })]),
    answer("restored"),
  ]);
  await target.session.prompt("restore");
  const frames = target.frames.length;
  await rm(source.manager.getSessionFile()!);
  target.faux.setResponses([answer("must not send")]);
  await target.session.prompt("continue");
  assert.equal(target.frames.length, frames);
  assert.ok(target.diagnostics.length > 0);
  assert.equal(scopeOf(target.manager.getBranch()).task_id, task.task_id);
});
