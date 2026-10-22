import assert from "node:assert/strict";
import { readFile, mkdtemp, rm, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { crc32, deflateSync } from "node:zlib";
import test from "node:test";
import {
  SessionManager,
  createBashToolDefinition,
} from "@earendil-works/pi-coding-agent";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { loadAliases, loadOriginals } from "../../src/memory/metadata.ts";
import { SessionMemory } from "../../src/pi/session-memory.ts";
import { MemoryService } from "../../src/memory/service.ts";
import { loadReferences } from "../../src/memory/references.ts";
import { Type } from "typebox";

const create = {
  title: "Read test",
  goal: "Verify original reads",
  project_name: "MemWeave",
  summary: "Original verification",
  keywords: ["read"],
};
const call = (
  name: string,
  args: Parameters<typeof fauxToolCall>[1],
  id = "call",
) => fauxAssistantMessage([fauxToolCall(name, args, { id })]);
async function initialized(
  t: Parameters<typeof taskSession>[0],
  options: Parameters<typeof taskSession>[1] = {},
) {
  const h = await taskSession(t, options);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("source 😀 line\r\nsecond");
  return { h, task: (await h.tasks.index.read())[0]! };
}
function readResult(h: Awaited<ReturnType<typeof taskSession>>) {
  const entry = h.manager
    .getEntries()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "memory_read",
    );
  assert.ok(entry?.type === "message" && entry.message.role === "toolResult");
  const part = entry.message.content[0];
  assert.ok(part?.type === "text");
  return JSON.parse(part.text);
}

test("native memory_read reads originals despite context edits, isolates errors, and obeys ordered total budget", async (t) => {
  const { h, task } = await initialized(t);
  const first = h.manager
    .getEntries()
    .find((e) => e.type === "message" && e.message.role === "user")!;
  h.manager.appendContextEdit(first.id, { content: "edited projection" });
  const before = JSON.stringify(
    h.manager.getEntries().filter((e) => e.type === "message"),
  );
  h.faux.setResponses([
    call("memory_read", {
      items: [
        { ref: "U999" },
        { ref: "U1", offset: 7, limit: 4 },
        { ref: "U1" },
      ],
      max_total_chars: 6,
    }),
    fauxAssistantMessage("read"),
  ]);
  await h.session.prompt("read known originals");
  const result = readResult(h);
  assert.equal(result.items[0].status, "not_found");
  assert.equal(result.items[1].content, "😀 li");
  assert.equal(result.items[1].range_complete, true);
  assert.equal(result.items[2].content, "so");
  assert.equal(result.items[2].range_complete, false);
  assert.equal(result.total_chars, 6);
  assert.equal(result.items[1].source_task_id, task.task_id);
  assert.equal(result.items[1].source_complete, true);
  assert.equal(
    JSON.stringify(
      h.manager
        .getEntries()
        .filter((e) => e.type === "message")
        .slice(0, JSON.parse(before).length),
    ),
    before,
  );
  assert.equal((await h.tasks.state.read(task)).version, 1);
  assert.deepEqual(h.errors, []);
});

test("real native Bash output is saved before continuation; temp deletion, reopening and corruption are explicit", async (t) => {
  const cwd = await mkdtemp(join(tmpdir(), "memweave-bash-original-"));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const { h, task } = await initialized(t, {
    extra: (pi) => pi.registerTool(createBashToolDefinition(cwd)),
  });
  h.faux.setResponses([
    call("bash", {
      command:
        "awk 'BEGIN { for (i=1; i<=2500; i++) print \"original-line-\" i }'",
    }),
    fauxAssistantMessage("output received"),
  ]);
  await h.session.prompt("produce real native Bash output");
  const entries = h.manager.getEntries(),
    output = entries.findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "bash",
    );
  assert.ok(output?.type === "message" && output.message.role === "toolResult");
  const path = (output.message.details as { fullOutputPath: string })
    .fullOutputPath;
  t.after(() => rm(path, { force: true }));
  const refs = await loadReferences(
    await h.tasks.index.get(task.task_id),
    h.tasks.memory,
  );
  const ref = [...refs].find(([, value]) => value.entry_id === output.id)![0];
  const originals = await loadOriginals(
    await h.tasks.index.get(task.task_id),
    h.tasks.memory,
  );
  const original = originals.get(ref);
  assert.ok(original);
  await rm(path);
  const reopened = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  reopened.faux.setResponses([
    call("memory_read", { items: [{ ref, limit: 32 }] }),
    fauxAssistantMessage("read"),
  ]);
  await reopened.session.prompt("read preserved output beginning");
  let result = readResult(reopened);
  assert.ok(result.items[0].content.startsWith("original-line-1\n"));
  assert.equal(result.items[0].source_complete, true);
  assert.equal(result.items[0].range_complete, true);
  assert.equal(result.items[0].tool_call_id, output.message.toolCallId);
  await writeFile(h.paths.blob(original.blob_hash), "corrupt");
  reopened.faux.setResponses([
    call("memory_read", { items: [{ ref }, { ref: "U1" }] }),
    fauxAssistantMessage("reported"),
  ]);
  await reopened.session.prompt(
    "report corrupt output and still read valid user",
  );
  result = readResult(reopened);
  assert.equal(result.items[0].status, "read_error");
  assert.match(result.items[0].error, /CORRUPT_ORIGINAL_BLOB/);
  assert.match(result.items[1].content, /source 😀/);
  assert.deepEqual(reopened.diagnostics, []);
});

test("image attachments get stable R; only explicit supported-model reads return unchanged native bytes", async (t) => {
  const { h } = await initialized(t);
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type), data]),
      result = Buffer.alloc(data.length + 12);
    result.writeUInt32BE(data.length);
    body.copy(result, 4);
    result.writeUInt32BE(crc32(body), result.length - 4);
    return result;
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(1);
  header.writeUInt32BE(1, 4);
  header[8] = 8;
  header[9] = 6;
  const png = Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.from([0, 255, 0, 0, 255]))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  const image = {
    type: "image" as const,
    mimeType: "image/png",
    data: png.toString("base64"),
  };
  h.faux.setResponses([
    call("memory_read", { items: [{ ref: "U2" }] }),
    fauxAssistantMessage("listed"),
  ]);
  await h.session.prompt("image source", { images: [image] });
  assert.ok(
    h.frames
      .at(-2)!
      .every(
        (m) =>
          !(
            "content" in m &&
            Array.isArray(m.content) &&
            m.content.some((p) => p.type === "image")
          ),
      ),
  );
  assert.match(JSON.stringify(h.frames.at(-2)), /attachment R1/);
  assert.ok(readResult(h).items[0].attachments, JSON.stringify(readResult(h)));
  assert.equal(readResult(h).items[0].attachments[0].ref, "R1");
  await h.session.setModel({ ...h.faux.getModel(), input: ["text"] });
  h.faux.setResponses([
    call("memory_read", { items: [{ ref: "R1" }] }),
    fauxAssistantMessage("unsupported"),
  ]);
  await h.session.prompt("explicit image read using text-only model");
  assert.equal(readResult(h).items[0].status, "model_unsupported");
  await h.session.setModel({ ...h.faux.getModel(), input: ["text", "image"] });
  h.faux.setResponses([
    call("memory_read", { items: [{ ref: "R1", offset: 0 }, { ref: "R1" }] }),
    fauxAssistantMessage("read image"),
  ]);
  await h.session.prompt("explicit image read using capable model");
  const result = readResult(h);
  assert.equal(result.items[0].status, "read_error");
  assert.equal(result.items[1].status, "ok");
  const last = h.manager
    .getEntries()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "memory_read",
    );
  assert.ok(last?.type === "message" && last.message.role === "toolResult");
  assert.deepEqual(last.message.content[1], image);
  assert.ok(h.budgets.at(-1)!.X >= 2048);
  h.faux.setResponses([fauxAssistantMessage("later request")]);
  await h.session.prompt("The earlier image exemption is still alive");
  assert.ok(h.budgets.at(-1)!.X >= 2048);
  assert.ok(
    h.frames
      .at(-1)!
      .some(
        (m) =>
          "content" in m &&
          Array.isArray(m.content) &&
          m.content.some((p) => p.type === "image"),
      ),
  );
  const branch = h.manager.getBranch(),
    position = branch.findIndex((e) => e.id === last.id);
  const following = branch
    .slice(position + 1)
    .filter(
      (e) =>
        e.type === "message" &&
        ["user", "assistant", "toolResult"].includes(e.message.role),
    ).length;
  for (let i = following; i < 9; i++)
    h.manager.appendMessage({
      role: "user",
      content: `new message ${i}`,
      timestamp: i,
    });
  h.faux.setResponses([fauxAssistantMessage("expired")]);
  await h.session.prompt("The tenth newer message expires the image exemption");
  assert.equal(h.budgets.at(-1)!.X, 0);
  assert.ok(
    h.frames
      .at(-1)!
      .every(
        (m) =>
          !(
            "content" in m &&
            Array.isArray(m.content) &&
            m.content.some((p) => p.type === "image")
          ),
      ),
  );
  assert.deepEqual(h.diagnostics, []);
});

test("a recorded truncated fragment never claims a complete original or complete unbounded range", async (t) => {
  const { h, task } = await initialized(t, {
    extra: (pi) =>
      pi.registerTool({
        name: "fragment",
        label: "fragment",
        description: "Test recorded fragment",
        parameters: Type.Object({}),
        async execute() {
          return {
            content: [{ type: "text", text: "only recorded tail" }],
            details: { truncation: { truncated: true } },
          };
        },
      }),
  });
  h.faux.setResponses([
    call("fragment", {}),
    fauxAssistantMessage("fragment recorded"),
  ]);
  await h.session.prompt("record fragment without original");
  const refs = await loadReferences(
    await h.tasks.index.get(task.task_id),
    h.tasks.memory,
  );
  const entry = h.manager
    .getEntries()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "fragment",
    )!;
  const ref = [...refs].find(([, value]) => value.entry_id === entry.id)![0];
  h.faux.setResponses([
    call("memory_read", { items: [{ ref }] }),
    fauxAssistantMessage("incomplete"),
  ]);
  await h.session.prompt("read fragment honestly");
  const item = readResult(h).items[0];
  assert.equal(item.content, "only recorded tail");
  assert.equal(item.source_complete, false);
  assert.equal(item.range_complete, false);
  assert.equal(item.total_chars, null);
  assert.equal(item.status, "incomplete");
});

test("Task switching and memory_read in one native assistant response are both blocked", async (t) => {
  const { h, task } = await initialized(t);
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall(
        "task_create",
        { ...create, title: "Not created" },
        { id: "switch" },
      ),
      fauxToolCall("memory_read", { items: [{ ref: "U1" }] }, { id: "read" }),
    ]),
    fauxAssistantMessage("blocked"),
  ]);
  await h.session.prompt("test ambiguous scope rejection");
  assert.equal((await h.tasks.index.read()).length, 1);
  assert.equal(
    h.tasks.scope(h.session.extensionRunner!.createContext()).task_id,
    task.task_id,
  );
  assert.match(
    JSON.stringify(h.manager.getEntries()),
    /CONFLICTING_TASK_CALLS/,
  );
});

test("cross-Task aliases deduplicate, survive disk reopening, validate evidence and never switch Task", async (t) => {
  const { h, task: source } = await initialized(t);
  h.faux.setResponses([
    call("task_create", { ...create, title: "Consumer" }),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("new independent Task");
  const current = (await h.tasks.index.read()).find(
    (e) => e.task_id !== source.task_id,
  )!;
  h.faux.setResponses([
    call("memory_read", {
      items: [
        { ref: "U1", task_id: source.task_id },
        { ref: "U1", task_id: source.task_id },
      ],
    }),
    fauxAssistantMessage("read"),
  ]);
  await h.session.prompt("read source user");
  const result = readResult(h);
  assert.equal(result.items[0].resolved_ref, "R1");
  assert.equal(result.items[1].resolved_ref, "R1");
  assert.equal(result.items[0].source_task_id, source.task_id);
  assert.match(result.items[0].content, /source 😀 line/);
  assert.equal(
    h.tasks.scope(h.session.extensionRunner!.createContext()).task_id,
    current.task_id,
  );
  assert.equal(
    (
      await loadAliases(
        await h.tasks.index.get(current.task_id),
        h.tasks.memory,
      )
    ).size,
    1,
  );
  const reopened = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  reopened.faux.setResponses([
    call("memory_read", { items: [{ ref: "R1" }] }),
    call("state_append", {
      items: [
        {
          type: "fact",
          content: "Source user requested verification",
          evidence: { R1: "original user request" },
        },
      ],
    }),
    fauxAssistantMessage("done"),
  ]);
  await reopened.session.prompt("use persisted alias");
  assert.match(readResult(reopened).items[0].content, /source 😀 line/);
  assert.equal((await reopened.tasks.state.read(current)).version, 2);
  assert.deepEqual(reopened.diagnostics, []);
  const raw = await readFile(reopened.manager.getSessionFile()!, "utf8");
  assert.doesNotMatch(raw, /# Symbolic State/);
});

test("two Pi instances share one alias sequence across concurrency and native fork", async (t) => {
  const { h, task: source } = await initialized(t);
  h.faux.setResponses([
    call("task_create", { ...create, title: "Consumer" }),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("consumer");
  const task = (await h.tasks.index.read()).find(
    (e) => e.task_id !== source.task_id,
  )!;
  const forkFile = h.manager.createBranchedSession(h.manager.getLeafId()!);
  assert.ok(forkFile);
  const b = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(forkFile),
  });
  const args = { items: [{ ref: "U1", task_id: source.task_id }] };
  h.faux.setResponses([call("memory_read", args), fauxAssistantMessage("a")]);
  b.faux.setResponses([call("memory_read", args), fauxAssistantMessage("b")]);
  await Promise.all([
    h.session.prompt("parallel A"),
    b.session.prompt("parallel B"),
  ]);
  assert.equal(readResult(h).items[0].resolved_ref, "R1");
  assert.equal(readResult(b).items[0].resolved_ref, "R1");
  const updated = await b.tasks.index.get(task.task_id);
  assert.equal((await loadAliases(updated, b.tasks.memory)).size, 1);
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(b.diagnostics, []);
});

test("missing external sources are per-item and stale R cannot become new State evidence", async (t) => {
  const { h: origin, task: source } = await initialized(t);
  const consumer = await taskSession(t, { paths: origin.paths });
  consumer.faux.setResponses([
    call("task_create", { ...create, title: "Consumer" }),
    fauxAssistantMessage("created"),
  ]);
  await consumer.session.prompt("consumer source");
  const task = (await consumer.tasks.index.read()).find(
    (e) => e.task_id !== source.task_id,
  )!;
  consumer.faux.setResponses([
    call("memory_read", { items: [{ ref: "U1", task_id: source.task_id }] }),
    fauxAssistantMessage("aliased"),
  ]);
  await consumer.session.prompt("allocate alias");
  assert.equal(readResult(consumer).items[0].resolved_ref, "R1");
  const committed = [
    {
      type: "fact" as const,
      content: "Committed source evidence",
      evidence: { R1: "source available at commit" },
    },
  ];
  consumer.faux.setResponses([
    call("state_append", { items: committed }, "committed-R"),
    fauxAssistantMessage("saved"),
  ]);
  await consumer.session.prompt("commit valid R evidence");
  assert.equal((await consumer.tasks.state.read(task)).version, 2);
  await rm(origin.manager.getSessionFile()!);
  assert.equal(
    await consumer.tasks.append(
      committed,
      consumer.session.extensionRunner!.createContext(),
      "committed-R",
    ),
    "State updated: v2",
  );
  consumer.faux.setResponses([
    call("memory_read", {
      items: [
        { ref: "R1" },
        { ref: "U1" },
        { ref: "U1", task_id: "task_missing" },
      ],
    }),
    call("state_append", {
      items: [
        {
          type: "fact",
          content: "Must not be saved",
          evidence: { R1: "missing source" },
        },
      ],
    }),
    fauxAssistantMessage("reported"),
  ]);
  await consumer.session.prompt("check missing sources");
  const result = readResult(consumer);
  assert.equal(result.items[0].status, "source_missing");
  assert.equal(result.items[1].content, "consumer source");
  assert.equal(result.items[2].status, "not_found");
  assert.equal((await consumer.tasks.state.read(task)).version, 2);
  assert.match(
    JSON.stringify(consumer.manager.getEntries()),
    /INVALID_EVIDENCE/,
  );
});

test("failed alias metadata persistence publishes no alias and recovery can retry the same source", async (t) => {
  const { h, task: source } = await initialized(t);
  h.faux.setResponses([
    call("task_create", { ...create, title: "Consumer" }),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("consumer");
  const task = (await h.tasks.index.read()).find(
    (e) => e.task_id !== source.task_id,
  )!;
  const memory = new SessionMemory({
    appendEntry() {
      throw Error("injected append failure");
    },
  });
  const reader = new MemoryService(h.paths, h.tasks.index, memory),
    ctx = h.session.extensionRunner!.createContext();
  await assert.rejects(
    reader.read(task, { items: [{ ref: "U1", task_id: source.task_id }] }, ctx),
    /SESSION_WRITE_FAILED/,
  );
  assert.equal(memory.failed, true);
  assert.equal((await loadAliases(task, h.tasks.memory)).size, 0);
  const reopened = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  reopened.faux.setResponses([
    call("memory_read", { items: [{ ref: "U1", task_id: source.task_id }] }),
    fauxAssistantMessage("retried"),
  ]);
  await reopened.session.prompt("retry after disk reopening");
  assert.equal(readResult(reopened).items[0].resolved_ref, "R1");
});

test("actual blob storage failure aborts before continuation and retries capture after repair", async (t) => {
  const cwd = await mkdtemp(join(tmpdir(), "memweave-bash-original-"));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const { h, task } = await initialized(t, {
    extra: (pi) => pi.registerTool(createBashToolDefinition(cwd)),
  });
  const blocked = join(h.paths.root, "blobs");
  await writeFile(blocked, "not a directory");
  const before = h.faux.state.callCount;
  h.faux.setResponses([
    call("bash", {
      command: "awk 'BEGIN { for (i=1; i<=2500; i++) print i }'",
    }),
    fauxAssistantMessage("must not run"),
  ]);
  await h.session.prompt("output preservation failure");
  const output = h.manager
    .getEntries()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "bash",
    );
  assert.ok(output?.type === "message" && output.message.role === "toolResult");
  const path = (output.message.details as { fullOutputPath: string })
    .fullOutputPath;
  t.after(() => rm(path, { force: true }));
  assert.equal(h.faux.state.callCount - before, 1);
  assert.ok(
    h.diagnostics.some((message) => /ORIGINAL_SAVE_FAILED/.test(message)),
  );
  assert.equal((await loadOriginals(task, h.tasks.memory)).size, 0);
  await rm(blocked);
  await mkdir(blocked);
  h.faux.setResponses([fauxAssistantMessage("recovered")]);
  await h.session.prompt("repair and capture original");
  assert.equal(
    (await loadOriginals(await h.tasks.index.get(task.task_id), h.tasks.memory))
      .size,
    1,
  );
});

test("default 8000 and explicit 50000 budgets count emoji code points; later items are budget-exhausted", async (t) => {
  const { h } = await initialized(t);
  h.faux.setResponses([
    call("memory_read", { items: [{ ref: "U2" }] }),
    fauxAssistantMessage("default read"),
  ]);
  await h.session.prompt("😀".repeat(50001));
  assert.equal([...readResult(h).items[0].content].length, 8000);
  assert.equal(readResult(h).items[0].total_chars, 50001);
  assert.equal(readResult(h).items[0].range_complete, false);
  h.faux.setResponses([
    call("memory_read", {
      items: [{ ref: "U2" }, { ref: "U1" }],
      max_total_chars: 50000,
    }),
    fauxAssistantMessage("bounded read"),
  ]);
  await h.session.prompt("read at hard ceiling");
  const result = readResult(h);
  assert.equal(result.total_chars, 50000);
  assert.equal([...result.items[0].content].length, 50000);
  assert.equal(result.items[1].content, "");
  assert.equal(result.items[1].status, "budget_exhausted");
});

test("memory_read requires a bound Task and cannot create one implicitly", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("memory_read", { items: [{ ref: "U1" }] }),
    fauxAssistantMessage("unbound"),
  ]);
  await h.session.prompt("unbound read");
  const entry = h.manager
    .getEntries()
    .find((e) => e.type === "message" && e.message.role === "toolResult");
  assert.ok(
    entry?.type === "message" &&
      entry.message.role === "toolResult" &&
      entry.message.isError,
  );
  assert.match(JSON.stringify(entry.message.content), /NO_CURRENT_TASK/);
  assert.equal((await h.tasks.index.read()).length, 0);
});
