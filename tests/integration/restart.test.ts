import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile } from "node:fs/promises";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { RESTART_TYPE, restartMetadata, restartTaskId } from "../../src/task/restart-model.ts";
import { scopeOf, SCOPE_TYPE } from "../../src/pi/session-memory.ts";
import { windowMetadata } from "../../src/pi/window-service.ts";
import { stableId } from "../../src/storage/identity.ts";
import { workspaceKey } from "../../src/pi/session-memory.ts";
import { readOptional, withLock } from "../../src/storage/files.ts";
const input = { title: "restart task", goal: "new objective", project_name: "MemWeave", summary: "new task", keywords: ["restart"] };

test("restart command handles 26000 old events without inference, preserves old State and creates only one new Goal", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", { ...input, goal: "old objective" }, { id: "old" })]), fauxAssistantMessage("old done")]);
  await h.session.prompt("old work");
  const old = (await h.tasks.index.read())[0]!, before = await readFile(h.paths.state(old), "utf8");
  for (let i = 0; i < 26000; i++) h.manager.appendMessage({ role: "user", content: "native history " + i, timestamp: i });
  const originals = h.manager.getBranch().filter((entry) => entry.type === "message");
  const calls = h.faux.state.callCount;
  await h.session.prompt("/memweave-restart");
  assert.equal(h.faux.state.callCount, calls);
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  const receipt = restartMetadata(h.manager.getBranch())!;
  assert.equal(receipt.data.seed_event_ids.length, 200);
  assert.equal(windowMetadata(h.manager.getBranch()), null);
  await h.session.prompt("/memweave-restart");
  assert.equal(h.manager.getBranch().filter((entry) => entry.type === "custom" && entry.customType === RESTART_TYPE).length, 1);
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "new" })]), fauxAssistantMessage("new done")]);
  await h.session.prompt("start new objective");
  const id = scopeOf(h.manager.getBranch()).task_id!;
  assert.equal(id, restartTaskId(h.manager.getSessionId(), receipt.data.restart_id));
  assert.notEqual(id, old.task_id);
  assert.equal((await h.tasks.index.read()).length, 2);
  const state = await h.tasks.state.read(await h.tasks.index.get(id));
  assert.equal(state.version, 1); assert.equal(state.facts.length + state.decisions.length, 0);
  assert.equal(await readFile(h.paths.state(old), "utf8"), before);
  assert.ok(h.budgets.at(-1)!.M < 300);
  const entries = h.manager.getBranch().filter((entry) => entry.type === "message");
  assert.deepEqual(entries.slice(0, originals.length), originals);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
});

test("restart Goal committed before index/binding is repaired from its real native call after disk reopening", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("history")]); await h.session.prompt("earlier user");
  await h.session.prompt("/memweave-restart");
  const receipt = restartMetadata(h.manager.getBranch())!;
  h.manager.appendMessage({ role: "user", content: "new objective", timestamp: 20 });
  const assistant = h.manager.appendMessage(fauxAssistantMessage([fauxToolCall("task_create", input, { id: "create" })]));
  h.manager.appendMessage({ role: "toolResult", toolCallId: "create", toolName: "task_create", content: [{ type: "text", text: "PARTIAL_COMMIT: Goal committed; index failed" }], isError: true, timestamp: 21 });
  const task = { workspace: workspaceKey(h.cwd), task_id: restartTaskId(h.manager.getSessionId(), receipt.data.restart_id) };
  await withLock(h.paths.taskLock(task), () => h.tasks.state.initialize(task, input.goal, stableId(task.task_id, h.manager.getSessionId(), assistant, "create")));
  const before = await readFile(h.paths.state(task), "utf8");
  const restored = await taskSession(t, { paths: h.paths, manager: SessionManager.open(h.manager.getSessionFile()!) });
  restored.faux.setResponses([fauxAssistantMessage("recovered")]); await restored.session.prompt("continue");
  assert.equal(scopeOf(restored.manager.getBranch()).task_id, task.task_id);
  assert.equal((await restored.tasks.index.read()).length, 1);
  assert.equal(await readFile(h.paths.state(task), "utf8"), before);
  await restored.tasks.create(input, restored.session.extensionRunner!.createContext(), "create");
  assert.equal((await restored.tasks.index.read()).length, 1);
  const ctx = restored.session.extensionRunner!.createContext();
  const otherCwd = h.cwd + "-other";
  await restored.tasks.create(input, { ...ctx, cwd: otherCwd }, "create");
  assert.equal(await readOptional(h.paths.state({ task_id: task.task_id, workspace: workspaceKey(otherCwd) })), undefined);
  assert.deepEqual(restored.diagnostics, []);
});

test("empty restart waits for input; arguments are rejected without creating metadata or calling a model", async (t) => {
  const h = await taskSession(t);
  await h.session.prompt("/memweave-restart");
  assert.equal(restartMetadata(h.manager.getBranch()), null);
  await h.session.prompt("/memweave-restart invalid");
  assert.equal(restartMetadata(h.manager.getBranch()), null);
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(h.diagnostics.some((error) => /RESTART_ARGUMENTS/.test(error)));
});

test("restart pending survives reload and effective N/B change retains normal full-history reselection", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("past")]); await h.session.prompt("original");
  for (let i = 0; i < 15; i++) h.manager.appendMessage(fauxAssistantMessage("history " + i));
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 3, evict_turns: 1 }));
  await h.session.prompt("/memweave-restart");
  const receipt = restartMetadata(h.manager.getBranch())!;
  assert.equal(receipt.data.seed_event_ids[0], h.manager.getBranch().find((entry) => entry.type === "message" && entry.message.role === "user")!.id);
  await h.session.reload();
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "create" })]), fauxAssistantMessage("created")]);
  await h.session.prompt("new objective");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, restartTaskId(h.manager.getSessionId(), receipt.data.restart_id));
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 30, evict_turns: 2 }));
  h.faux.setResponses([fauxAssistantMessage("expanded")]); await h.session.prompt("expanded view");
  assert.match(JSON.stringify(h.frames.at(-1)), /history 0/);
  assert.deepEqual(h.diagnostics, []);
});

test("tree before a committed Goal reuses that intent's Task without losing its original creation source", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("past")]); await h.session.prompt("past");
  await h.session.prompt("/memweave-restart");
  const anchor = h.manager.getLeafId()!;
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "create" })]), fauxAssistantMessage("created")]);
  await h.session.prompt("new objective");
  const taskId = scopeOf(h.manager.getBranch()).task_id;
  await h.session.navigateTree(anchor, { summarize: false });
  h.faux.setResponses([fauxAssistantMessage("reused committed Goal")]);
  await h.session.prompt("continue the same restart");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, taskId);
  assert.equal((await h.tasks.index.read()).length, 1);
  assert.deepEqual(h.diagnostics, []);
});

test("restart scope partial write reopens as unbound and completes the same intent", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("old history")]); await h.session.prompt("old user");
  const append = h.tasks.memory.append.bind(h.tasks.memory);
  h.tasks.memory.append = async (ctx, kind, data) => {
    if (kind === SCOPE_TYPE) throw Error("injected scope failure");
    return append(ctx, kind, data);
  };
  await h.session.prompt("/memweave-restart");
  const receipt = restartMetadata(h.manager.getBranch())!;
  assert.ok(receipt); assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  const restored = await taskSession(t, { paths: h.paths, manager: SessionManager.open(h.manager.getSessionFile()!) });
  restored.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "create" })]), fauxAssistantMessage("done")]);
  await restored.session.prompt("new objective");
  assert.equal(scopeOf(restored.manager.getBranch()).task_id, restartTaskId(restored.manager.getSessionId(), receipt.data.restart_id));
  assert.equal((await restored.tasks.index.read()).length, 1);
  assert.deepEqual(restored.diagnostics, []);
});

test("restart ignores an oversized old State while retaining its file and other Session binding", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", { ...input, goal: "old" }, { id: "old" })]), fauxAssistantMessage("created")]);
  await h.session.prompt("old work");
  const old = (await h.tasks.index.read())[0]!;
  const forkFile = SessionManager.open(h.manager.getSessionFile()!).createBranchedSession(h.manager.getLeafId()!);
  assert.ok(forkFile);
  const other = SessionManager.open(forkFile);
  await withLock(h.paths.taskLock(old), () => h.tasks.state.append(old,
    Array.from({ length: 5000 }, () => ({ type: "fact", content: "中".repeat(100), evidence: { U1: "synthetic history" } })), "long-state", 100, new Set(["U1"])));
  const before = await readFile(h.paths.state(old), "utf8"), calls = h.faux.state.callCount;
  await h.session.prompt("old State cannot fit");
  assert.equal(h.faux.state.callCount, calls);
  assert.ok(h.diagnostics.some((error) => /CONTEXT_BUDGET_EXCEEDED/.test(error)));
  await h.session.prompt("/memweave-restart");
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "new" })]), fauxAssistantMessage("ready")]);
  await h.session.prompt("new objective");
  assert.notEqual(scopeOf(h.manager.getBranch()).task_id, old.task_id);
  assert.equal(scopeOf(other.getBranch()).task_id, old.task_id);
  assert.equal(await readFile(h.paths.state(old), "utf8"), before);
});

test("concurrent restart commands cannot clear the active command guard or infer", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("history")]); await h.session.prompt("user");
  const capture = h.tasks.resolveCommandBudget!;
  let release!: () => void, started!: () => void;
  const ready = new Promise<void>((resolve) => { started = resolve; });
  const wait = new Promise<void>((resolve) => { release = resolve; });
  h.tasks.resolveCommandBudget = async (ctx) => { started(); await wait; return capture(ctx); };
  const first = h.session.prompt("/memweave-restart"); await ready;
  await h.session.prompt("/memweave-restart"); await h.session.prompt("/memweave-restart");
  assert.equal(h.diagnostics.filter((error) => /RESTART_BUSY/.test(error)).length, 2);
  release(); await first;
  assert.equal(h.manager.getBranch().filter((entry) => entry.type === "custom" && entry.customType === RESTART_TYPE).length, 1);
  assert.equal(h.faux.state.callCount, 1);
});

test("forks of an unbound restart create independent candidates and retain each other's binding", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("history")]); await h.session.prompt("user");
  await h.session.prompt("/memweave-restart");
  const receipt = restartMetadata(h.manager.getBranch())!;
  const file = SessionManager.open(h.manager.getSessionFile()!).createBranchedSession(h.manager.getLeafId()!);
  assert.ok(file);
  const fork = await taskSession(t, { paths: h.paths, manager: SessionManager.open(file) });
  for (const branch of [h, fork]) {
    branch.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "create" })]), fauxAssistantMessage("done")]);
    await branch.session.prompt("new objective");
    assert.equal(scopeOf(branch.manager.getBranch()).task_id, restartTaskId(branch.manager.getSessionId(), receipt.data.restart_id));
    assert.deepEqual(branch.diagnostics, []);
  }
  assert.notEqual(scopeOf(h.manager.getBranch()).task_id, scopeOf(fork.manager.getBranch()).task_id);
  assert.equal((await h.tasks.index.read()).length, 2);
});

test("N/B changed before first cold request reselects full originals, and forged seed cancels before inference", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("first")]); await h.session.prompt("original");
  for (let i = 0; i < 15; i++) h.manager.appendMessage(fauxAssistantMessage("prior " + i));
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 3, evict_turns: 1 }));
  await h.session.prompt("/memweave-restart");
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 30, evict_turns: 2 }));
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("task_create", input, { id: "create" })]), fauxAssistantMessage("done")]);
  await h.session.prompt("new objective");
  assert.match(JSON.stringify(h.frames.at(-1)), /prior 0/);
  await h.session.prompt("/memweave-restart");
  const receipt = restartMetadata(h.manager.getBranch())!;
  h.manager.appendCustomEntry(RESTART_TYPE, { ...receipt.data, previous_task_id: null, seed_event_ids: ["missing-source"] });
  const calls = h.faux.state.callCount;
  await h.session.prompt("must not infer");
  assert.equal(h.faux.state.callCount, calls);
  assert.ok(h.diagnostics.some((error) => /CORRUPT_RESTART_SOURCE/.test(error)));
});
