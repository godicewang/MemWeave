import test from "node:test";
import assert from "node:assert/strict";
import { Type } from "typebox";
import { Check } from "typebox/value";
import { fauxAssistantMessage as answer, fauxToolCall as call } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";
import { bindingRequired, bindingReceipts } from "../../src/task/binding.ts";
import { FindSchema } from "../../src/task/model.ts";
import { readFile, symlink } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { SessionManager, type ExtensionUIContext } from "@earendil-works/pi-coding-agent";
import { releaseFixture, repository, sourceArtifact } from "../fixtures/release.ts";

const create = (goal: string) => ({ title: goal, goal, project_name: "P", summary: goal, keywords: ["payment"] });

test("ambiguous search pauses with a native clarification; reload and the real user selection resume only the chosen Task", async (t) => {
  const source = await taskSession(t);
  for (const goal of ["支付重复扣款", "支付退款超时"]) {
    source.faux.setResponses([answer([call("task_create", create(goal))]), answer("created")]);
    await source.session.prompt(goal);
  }
  const tasks = await source.tasks.index.read(), target = tasks.find((task) => task.title === "支付退款超时")!;
  const h = await taskSession(t, { paths: source.paths });
  h.faux.setResponses([
    answer([call("task_find", { query: "支付" })]),
    answer([call("task_clarify", { question: "要继续支付重复扣款，还是支付退款超时？" })]),
    answer([call("task_resume", { task_id: tasks[0]!.task_id })]),
  ]);
  await h.session.prompt("继续之前支付那个任务，先讨论下一步。");
  assert.equal(h.frames.length, 2, "no guessing inference after clarification");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 0);
  assert.ok(h.manager.getBranch().some((e) => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "task_clarify" && !e.message.isError));
  const states = await Promise.all(tasks.map((task) => h.tasks.state.read(task)));
  assert.ok(states.every((state) => state.version === 1));
  await h.session.reload();
  assert.equal(h.frames.length, 2, "reload does not infer without user input");
  h.faux.setResponses([answer([call("task_resume", { task_id: target.task_id })]), answer("已恢复退款任务，等待讨论")]);
  await h.session.prompt("退款超时那个");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, target.task_id);
  assert.equal((await h.tasks.index.read()).length, 2);
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
});

test("clarification stops even after failed binding and suppresses final-answer corrections", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    answer([call("task_resume", { task_id: "task_missing" })]),
    answer([call("task_clarify", { question: "这个Task不存在，请说明要恢复哪项工作？" })]),
    answer("this must not be generated"),
  ]);
  await h.session.prompt("继续原任务");
  assert.equal(h.frames.length, 2);
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 0);
  assert.equal((await h.tasks.index.read()).length, 0);
});

test("a clarification mixed with business tools blocks the entire batch before side effects", async (t) => {
  let ran = 0;
  const h = await taskSession(t, { extra(pi) {
    pi.registerTool({ name: "business_probe", label: "probe", description: "business operation",
      parameters: Type.Object({}), async execute() {
        ran++; return { content: [{ type: "text", text: "ran" }], details: {} };
      } });
  } });
  h.faux.setResponses([
    answer([call("business_probe", {}), call("task_clarify", { question: "选择哪一项？" })]),
    answer([call("task_clarify", { question: "选择哪一项？" })]),
    answer("must not continue"),
  ]);
  await h.session.prompt("先确认范围");
  assert.equal(ran, 0);
  assert.equal(h.frames.length, 2);
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
});

test("new calls reject initialize while old binding receipt provenance remains readable and inactive", async (t) => {
  assert.equal(Check(FindSchema, { query: "payment", initialize: true }), false);
  const h = await taskSession(t);
  h.faux.setResponses([
    answer([call("task_resume", { task_id: "task_missing" })]),
    answer("not bound"),
    answer("still not bound"),
  ]);
  await h.session.prompt("start payment work");
  const legacy = structuredClone(h.manager.getBranch());
  for (const e of legacy) {
    if (e.type === "message" && e.message.role === "assistant") {
      for (const p of e.message.content) if (p.type === "toolCall" && p.name === "task_resume") {
        p.name = "task_find"; p.arguments = { query: "payment", initialize: true };
      }
    }
    if (e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "task_resume") e.message.toolName = "task_find";
  }
  assert.equal(bindingReceipts(legacy).length, 2, "legacy v1 receipt validation still recognizes old source calls");
  assert.equal(bindingRequired(legacy), false, "legacy initialization never starts a new gate");
});

test("actual pre-removal Session receipts reopen unchanged with the new runtime", async (t) => {
  const f = await releaseFixture(t), oldRoot = await sourceArtifact(f.root, "0a43fa6");
  await symlink(join(repository, "node_modules"), join(oldRoot, "node_modules"), "dir");
  const old = await import(pathToFileURL(join(oldRoot, "tests/fixtures/task-session.ts")).href) as { taskSession: typeof taskSession };
  const previous = await old.taskSession(t);
  previous.faux.setResponses([
    answer([call("task_find", { query: "payment", initialize: true })]),
    answer("请选择一个支付任务"), answer("目标仍待澄清"),
  ]);
  await previous.session.prompt("继续支付工作");
  const file = previous.manager.getSessionFile()!;
  const original = await readFile(file);
  assert.equal(bindingReceipts(previous.manager.getBranch()).length, 2);
  await previous.session.abort(); previous.session.dispose();
  const h = await taskSession(t, { paths: previous.paths, manager: SessionManager.open(file) });
  h.faux.setResponses([answer("84")]);
  await h.session.prompt("12×7是多少？");
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 2);
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  assert.equal(h.frames.length, 1);
  assert.ok((await readFile(file)).subarray(0, original.length).equals(original));
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
});

test("native dialog reply becomes exactly one real user follow-up before Task creation", async (t) => {
  const h = await taskSession(t);
  let dialogs = 0;
  const ui = {
    input: async () => { dialogs++; return "新建订单核对任务"; },
    notify: () => {}, setFooter: () => {},
  } as unknown as ExtensionUIContext;
  await h.session.bindExtensions({ mode: "rpc", uiContext: ui, onError: (error) => h.errors.push(error.error) });
  h.faux.setResponses([
    answer([call("task_resume", { task_id: "task_missing" })]),
    answer([call("task_clarify", { question: "旧任务不存在，要新建什么目标？" })]),
    answer([call("task_create", create("订单核对"))]), answer("已按新输入创建"),
  ]);
  await h.session.prompt("继续订单任务");
  await h.session.waitForIdle();
  const users = h.manager.getBranch().flatMap((e) => e.type === "message" && e.message.role === "user"
    ? [typeof e.message.content === "string" ? e.message.content : e.message.content.filter((p) => p.type === "text").map((p) => p.text).join("")] : []);
  assert.equal(dialogs, 1);
  assert.deepEqual(users, ["继续订单任务", "新建订单核对任务"]);
  assert.ok(scopeOf(h.manager.getBranch()).task_id);
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 0);
  assert.equal(h.frames.length, 4);
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
});
