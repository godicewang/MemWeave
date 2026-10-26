import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { memoryPaths } from "../../src/storage/paths.ts";
import { StateStore } from "../../src/state/store.ts";
import { TaskSearch, type SearchProgress } from "../../src/task/search.ts";
import { rankTasks } from "../../src/task/search-rank.ts";
import type { Task } from "../../src/task/model.ts";
import type { Embedder } from "../../src/task/embedding.ts";
import { DEFAULT_SETTINGS } from "../../src/config/defaults.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { taskSession } from "../fixtures/task-session.ts";
import { fauxAssistantMessage as answer, fauxToolCall as call } from "@earendil-works/pi-ai/providers/faux";

const vector = (text: string) => {
  const hash = createHash("sha256").update(text).digest();
  return Array.from({ length: 384 }, (_, i) => hash[i % hash.length]! + 1);
};
const document = (task: Task, goal: string) =>
  `Goal: ${goal}\nTitle: ${task.title}\nKeywords: ${task.keywords.join(", ")}\nProject: ${task.project_name}\nSummary: ${task.summary}`;

async function fixture(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), "memweave-search-batch-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root), state = new StateStore(paths), tasks: Task[] = [];
  for (let i = 0; i < 33; i++) {
    const task: Task = {
      task_id: `task_${i}`, workspace: "test", title: `Work ${i}`,
      summary: i % 2 ? "refund timeout" : "payment duplicate charge",
      keywords: [i % 2 ? "refund" : "payment"], project_name: "P",
      state_version: 1, status: "active", updated_at: "2026-10-26T00:00:00.000Z", sessions: [],
    };
    await state.initialize(task, i === 0 ? `排查支付\nTitle: 这是Goal正文` : `排查${task.summary} ${i}`, `seed_${i}`);
    tasks.push(task);
  }
  return { paths, state, tasks };
}

test("bounded index batches preserve exact rankings, publish completed progress and never re-embed unchanged Tasks", async (t) => {
  const h = await fixture(t), batches: string[][] = [], progress: SearchProgress[] = [];
  const embed: Embedder = async (texts, kind) => {
    if (kind === "passage") batches.push([...texts]);
    return { vectors: texts.map(vector), truncated: texts.map(() => false) };
  };
  const search = new TaskSearch(h.paths, h.state, embed);
  t.after(() => search.close());
  const input = { query: "payment duplicate", keywords: ["payment"], limit: 10 };
  const actual = await search.find(h.tasks, input, DEFAULT_SETTINGS.task_search, undefined, (p) => progress.push(p));
  assert.deepEqual(batches.map((b) => b.length), [16, 16, 1]);
  const docs = await Promise.all(h.tasks.map(async (task) => {
    const goal = (await h.state.read(task)).goal;
    return { ...task, goal, vector: vector(document(task, goal)) };
  }));
  const expected = rankTasks(docs, input.query, input.keywords, vector(input.query), DEFAULT_SETTINGS.task_search)
    .slice(0, input.limit).map((d) => ({ task_id: d.task_id, title: d.title, summary: d.summary,
      keywords: d.keywords, goal: d.goal, workspace: d.workspace, score: d.score, ranks: d.ranks, index_truncated: false }));
  assert.deepEqual(actual, expected);
  assert.deepEqual(progress.at(-1), { completed: 33, total: 33, indexed: 33 });
  assert.equal(progress[0]!.completed, 0);
  assert.ok(progress.every((p, i) => !i || p.completed >= progress[i - 1]!.completed));
  assert.ok(progress.length <= 5);
  await search.find(h.tasks, input, DEFAULT_SETTINGS.task_search);
  assert.equal(batches.length, 3);
  h.tasks[5] = { ...h.tasks[5]!, summary: "updated task discovery metadata" };
  await search.find(h.tasks, input, DEFAULT_SETTINGS.task_search);
  assert.deepEqual(batches.map((b) => b.length), [16, 16, 1, 1]);
});

test("cancelled embedding and malformed batches never publish completion or derived successes", async (t) => {
  const h = await fixture(t), controller = new AbortController(), progress: SearchProgress[] = [];
  const embed: Embedder = async (texts, kind) => {
    if (kind === "passage") controller.abort();
    return { vectors: texts.map(vector), truncated: texts.map(() => false) };
  };
  const search = new TaskSearch(h.paths, h.state, embed);
  t.after(() => search.close());
  await assert.rejects(search.find(h.tasks, { query: "payment" }, DEFAULT_SETTINGS.task_search,
    controller.signal, (p) => progress.push(p)), /abort/i);
  assert.ok(progress.every((p) => p.completed < p.total));
  await assert.rejects(readFile(h.paths.search(h.tasks[0]!.task_id).data), /ENOENT/);
  const broken = new TaskSearch(h.paths, h.state, async (texts, kind) => ({
    vectors: kind === "query" ? texts.map(vector) : [vector("only one")],
    truncated: texts.map(() => false),
  }));
  t.after(() => broken.close());
  await assert.rejects(broken.find(h.tasks, { query: "payment" }, DEFAULT_SETTINGS.task_search), /INVALID_TASK_EMBEDDING/);
  await assert.rejects(readFile(h.paths.search(h.tasks[0]!.task_id).data), /ENOENT/);
});

test("a failed derived write is reported, all started writes settle, and a later search can rebuild", async (t) => {
  const h = await fixture(t);
  const { mkdir } = await import("node:fs/promises");
  // A directory at one cache-file location fails atomically without changing authority.
  await mkdir(h.paths.search(h.tasks[1]!.task_id).data, { recursive: true });
  const embed: Embedder = async (texts) => ({ vectors: texts.map(vector), truncated: texts.map(() => false) });
  const search = new TaskSearch(h.paths, h.state, embed);
  t.after(() => search.close());
  const before = await readFile(h.paths.state(h.tasks[1]!), "utf8");
  await assert.rejects(search.find(h.tasks, { query: "payment" }, DEFAULT_SETTINGS.task_search), /EISDIR|ENOTDIR/);
  assert.equal(await readFile(h.paths.state(h.tasks[1]!), "utf8"), before);
  await rm(h.paths.search(h.tasks[1]!.task_id).data, { recursive: true });
  assert.ok((await search.find(h.tasks, { query: "payment" }, DEFAULT_SETTINGS.task_search)).length > 0);
  await writeFile(h.paths.state(h.tasks[1]!), "corrupt authority\n");
  await assert.rejects(search.find(h.tasks, { query: "payment" }, DEFAULT_SETTINGS.task_search), /CORRUPT_STATE/);
});

test("native task_find streams UI progress without persisting it or injecting it into model context", async (t) => {
  const data = await fixture(t);
  await writeFile(data.paths.config, JSON.stringify(DEFAULT_CONFIG));
  await writeFile(data.paths.rule, await readFile(new URL("../../resources/rule.md", import.meta.url)));
  const h = await taskSession(t, { paths: data.paths, embedder: async (texts) => ({
    vectors: texts.map(vector), truncated: texts.map(() => false),
  }) });
  for (const task of data.tasks) await h.tasks.index.put(task);
  const updates: string[] = [];
  h.session.subscribe((event) => {
    if (event.type === "tool_execution_update") updates.push(JSON.stringify(event));
  });
  h.faux.setResponses([answer([call("task_find", { query: "payment" })]), answer("found candidates")]);
  await h.session.prompt("只找历史任务，不切换");
  assert.ok(updates.some((value) => value.includes("索引 0/33")));
  assert.ok(updates.some((value) => value.includes("索引 33/33")));
  assert.ok(h.frames.every((frame) => !JSON.stringify(frame).includes("本地 Task 检索")));
  assert.ok(!JSON.stringify(h.manager.getBranch()).includes("本地 Task 检索"));
  assert.deepEqual(h.manager.getBranch().filter((entry) => entry.type === "message" &&
    entry.message.role !== "system").map((entry) => entry.type === "message" && entry.message.role),
    ["user", "assistant", "toolResult", "assistant"]);
  assert.deepEqual(h.errors, []);
});
