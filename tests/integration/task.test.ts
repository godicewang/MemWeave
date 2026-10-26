import assert from "node:assert/strict";
import { readFile, rm, mkdir } from "node:fs/promises";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { taskSession } from "../fixtures/task-session.ts";
import {
  scopeOf,
  REF_TYPE,
  SessionMemory,
} from "../../src/pi/session-memory.ts";
import { loadReferences } from "../../src/memory/references.ts";
const create = {
  title: "Test task",
  goal: "Verify memory",
  project_name: "MemWeave",
  summary: "Memory verification",
  keywords: ["memory"],
};
const call = (
  name: string,
  args: Parameters<typeof fauxToolCall>[1],
  id = "call",
) => fauxAssistantMessage([fauxToolCall(name, args, { id })]);

test("native loop: create → evidence → atomic State → next request → disk recovery; no persisted temporary State", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    call(
      "state_append",
      {
        items: [
          {
            type: "fact",
            content: "User requested a memory test",
            evidence: { U1: "user request" },
          },
        ],
      },
      "append",
    ),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("Please verify memory.");
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
  assert.equal(h.faux.state.callCount, 3);
  const scope = scopeOf(h.manager.getBranch());
  assert.ok(scope.task_id);
  const task = await h.tasks.index.get(scope.task_id),
    state = await h.tasks.state.read(task);
  assert.equal(state.version, 2);
  assert.equal(state.facts[0]?.id, "F1");
  assert.equal(state.facts[0]?.content, "User requested a memory test");
  assert.equal(
    h.frames[0]?.filter(
      (m) =>
        (m.role === "user" || m.role === "custom") &&
        JSON.stringify(m.content).includes("# Symbolic State"),
    ).length,
    0,
  );
  for (const frame of h.frames.slice(1)) {
    assert.equal(
      frame.filter(
        (m) =>
          m.role === "custom" &&
          JSON.stringify(m.content).includes("# Symbolic State"),
      ).length,
      1,
    );
    assert.equal(frame.at(-1)?.role, "custom");
  }
  assert.match(JSON.stringify(h.frames.at(-1)), /F1 User requested/);
  assert.match(JSON.stringify(h.frames[1]), /U1/);
  const source = await readFile(h.manager.getSessionFile()!, "utf8");
  assert.doesNotMatch(source, /# Symbolic State|pi_long_task_rule/);
  const reopened = SessionManager.open(h.manager.getSessionFile()!);
  assert.equal(scopeOf(reopened.getBranch()).task_id, task.task_id);
  const refs = await loadReferences(task, h.tasks.memory);
  assert.ok(refs.has("U1"));
  assert.ok(refs.has("T1"));
  assert.ok(refs.has("A3"));
  const originals = h.manager.getEntries().filter((e) => e.type === "message");
  assert.deepEqual(
    reopened.getEntries().filter((e) => e.type === "message"),
    JSON.parse(JSON.stringify(originals)),
  );
  await h.session.reload();
  h.faux.setResponses([fauxAssistantMessage("after reload")]);
  await h.session.prompt("next user after reload");
  assert.match(JSON.stringify(h.frames.at(-1)), /F1 User requested/);
  assert.equal(
    h.frames
      .at(-1)
      ?.filter(
        (m) =>
          m.role === "custom" &&
          JSON.stringify(m.content).includes("# Symbolic State"),
      ).length,
    1,
  );
  assert.ok(
    (
      await loadReferences(
        await h.tasks.index.get(task.task_id),
        h.tasks.memory,
      )
    ).has("U2"),
  );
});

test("Task discovery/status/resume and conflict rejection use native tool calls", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("Create test task");
  const first = (await h.tasks.index.read())[0]!;
  h.faux.setResponses([
    call("task_create", { ...create, title: "Second", goal: "Other goal" }),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("Create another task");
  const second = (await h.tasks.index.read()).find(
    (task) => task.task_id !== first.task_id,
  )!;
  h.faux.setResponses([
    call("task_find", { query: "Memory" }),
    call("task_status", { task_id: first.task_id }),
    call("task_resume", { task_id: first.task_id }),
    fauxAssistantMessage("resumed"),
  ]);
  await h.session.prompt("Find and resume first task");
  assert.equal(scopeOf(h.manager.getBranch()).task_id, first.task_id, JSON.stringify(h.manager.getBranch().filter(e=>e.type==="message"&&e.message.role==="toolResult"&&e.message.isError)));
  assert.equal((await h.tasks.index.get(second.task_id)).status, "active");
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  const count = (await h.tasks.index.read()).length;
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("task_create", create, { id: "switch" }),
      fauxToolCall(
        "state_append",
        {
          items: [{ type: "fact", content: "wrong", evidence: { U1: "user" } }],
        },
        { id: "write" },
      ),
    ]),
    fauxAssistantMessage("blocked"),
  ]);
  await h.session.prompt("Conflicting batch test");
  assert.equal((await h.tasks.index.read()).length, count);
  assert.equal((await h.tasks.state.read(first)).version, 1);
  assert.match(
    JSON.stringify(h.manager.getEntries()),
    /CONFLICTING_TASK_CALLS/,
  );
});

test("invalid evidence and derivative write failure are explicit; committed State survives retry", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("Create task");
  const task = (await h.tasks.index.read())[0]!;
  h.faux.setResponses([
    call(
      "state_append",
      {
        items: [
          { type: "fact", content: "invalid", evidence: { T999: "missing" } },
        ],
      },
      "bad",
    ),
    fauxAssistantMessage("bad evidence rejected"),
  ]);
  await h.session.prompt("Test missing evidence");
  assert.equal((await h.tasks.state.read(task)).version, 1);
  await rm(h.paths.view(task));
  await mkdir(h.paths.view(task));
  h.faux.setResponses([
    call(
      "state_append",
      {
        items: [
          { type: "fact", content: "committed", evidence: { U1: "user" } },
        ],
      },
      "partial",
    ),
    fauxAssistantMessage("must not infer"),
  ]);
  // Preparation fails before inference while the derivative is unwritable.
  const before = h.faux.state.callCount;
  await h.session.prompt("unwritable State view");
  assert.equal(h.faux.state.callCount, before);
  assert.match(h.diagnostics.at(-1) ?? "", /state.md failed/);
  await rm(h.paths.view(task), { recursive: true });
  assert.equal((await h.tasks.state.read(task)).version, 1);
  const refs = h.manager
    .getEntries()
    .filter((e) => e.type === "custom" && e.customType === REF_TYPE);
  assert.ok(refs.length);
});

test("new Session is unbound; explicit resume, fork and simultaneous instances continue Task-scoped numbering", async (t) => {
  const original = await taskSession(t);
  original.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await original.session.prompt("original user");
  const task = (await original.tasks.index.read())[0]!;
  const originalFile = original.manager.getSessionFile()!;
  const a = await taskSession(t, {
    paths: original.paths,
    manager: SessionManager.create(
      original.cwd,
      original.manager.getSessionDir(),
    ),
  });
  assert.equal(
    a.tasks.scope(a.session.extensionRunner.createContext()).task_id,
    null,
  );
  a.faux.setResponses([
    call("task_resume", { task_id: task.task_id }),
    fauxAssistantMessage("resumed"),
  ]);
  await a.session.prompt("resume");
  const b = await taskSession(t, { paths: a.paths });
  b.faux.setResponses([
    call("task_resume", { task_id: task.task_id }),
    fauxAssistantMessage("resumed"),
  ]);
  await b.session.prompt("resume from another workspace");
  a.faux.setResponses([
    call(
      "state_append",
      {
        items: [
          {
            type: "fact",
            content: "first writer",
            evidence: { U1: "original user" },
          },
        ],
      },
      "same-call-id",
    ),
    fauxAssistantMessage("done"),
  ]);
  b.faux.setResponses([
    call(
      "state_append",
      {
        items: [
          {
            type: "decision",
            content: "second writer",
            evidence: { U1: "original user" },
          },
        ],
      },
      "same-call-id",
    ),
    fauxAssistantMessage("done"),
  ]);
  await Promise.all([
    a.session.prompt("new user A"),
    b.session.prompt("new user B"),
  ]);
  assert.deepEqual(a.diagnostics, []);
  assert.deepEqual(b.diagnostics, []);
  let current = await a.tasks.index.get(task.task_id);
  assert.equal(
    (await a.tasks.state.read(current)).version,
    3,
    JSON.stringify([
      a.manager
        .getEntries()
        .filter((e) => e.type === "message" && e.message.role === "toolResult"),
      b.manager
        .getEntries()
        .filter((e) => e.type === "message" && e.message.role === "toolResult"),
    ]),
  );
  assert.equal(current.sessions.length, 3);
  let refs = await loadReferences(current, a.tasks.memory);
  assert.deepEqual([...refs.keys()].filter((r) => r.startsWith("U")).sort(), [
    "U1",
    "U2",
    "U3",
  ]);
  assert.ok(
    refs.get("U1")?.source_session_id ===
      SessionManager.open(originalFile).getSessionId(),
  );
  const oldCount = refs.size;
  const leaf = a.manager.getLeafId();
  assert.ok(leaf);
  const forkFile = a.manager.createBranchedSession(leaf);
  assert.ok(forkFile);
  const fork = await taskSession(t, {
    paths: a.paths,
    manager: SessionManager.open(forkFile),
  });
  fork.faux.setResponses([fauxAssistantMessage("fork done")]);
  await fork.session.prompt("new fork user");
  current = await fork.tasks.index.get(task.task_id);
  refs = await loadReferences(current, fork.tasks.memory);
  assert.ok(refs.has("U4"));
  assert.equal(refs.size, oldCount + 2);
  assert.equal((await fork.tasks.state.read(current)).version, 3);
  assert.deepEqual(fork.diagnostics, []);
  assert.deepEqual(a.diagnostics, []);
  assert.deepEqual(b.diagnostics, []);
});

test("tree rollback restores binding and branch overrides durably; Task State is shared across branches", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("first task");
  const first = (await h.tasks.index.read())[0]!;
  h.manager.appendCustomEntry("memweave.scope.v1", {
    task_id: first.task_id,
    overrides: { recent_turns: 240 },
  });
  const anchor = h.manager.getLeafId()!;
  h.faux.setResponses([
    call("state_append", {
      items: [
        { type: "fact", content: "shared cognition", evidence: { U1: "user" } },
      ],
    }),
    fauxAssistantMessage("saved"),
  ]);
  await h.session.prompt("record cognition after branch point");
  h.faux.setResponses([
    call("task_create", { ...create, title: "Second" }),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("second task");
  assert.notEqual(scopeOf(h.manager.getBranch()).task_id, first.task_id);
  assert.equal(
    (await h.session.navigateTree(anchor, { summarize: false })).cancelled,
    false,
  );
  assert.deepEqual(scopeOf(h.manager.getBranch()), {
    task_id: first.task_id,
    overrides: { recent_turns: 240 },
  });
  const reopened = SessionManager.open(h.manager.getSessionFile()!);
  assert.equal(scopeOf(reopened.getBranch()).task_id, first.task_id);
  h.faux.setResponses([fauxAssistantMessage("shared State received")]);
  await h.session.prompt("after rollback");
  assert.match(JSON.stringify(h.frames.at(-1)), /shared cognition/);
  assert.equal((await h.tasks.state.read(first)).version, 2);
  assert.deepEqual(h.diagnostics, []);
});

test("committed append is recoverable after actual derivative failure and same-call retry", async (t) => {
  let h: Awaited<ReturnType<typeof taskSession>>;
  let breakView = false;
  h = await taskSession(t, {
    extra: (pi) => {
      pi.on("tool_call", async (event) => {
        if (event.toolName === "state_append" && breakView) {
          breakView = false;
          const task = (await h.tasks.index.read())[0]!;
          await rm(h.paths.view(task));
          await mkdir(h.paths.view(task));
        }
      });
    },
  });
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create");
  const task = (await h.tasks.index.read())[0]!;
  const items = [
    {
      type: "fact" as const,
      content: "committed before derivative failure",
      evidence: { U1: "user" },
    },
  ];
  breakView = true;
  h.faux.setResponses([
    call("state_append", { items }, "retryable"),
    fauxAssistantMessage("never sent"),
  ]);
  await h.session.prompt("append");
  assert.equal((await h.tasks.state.read(task)).version, 2);
  assert.match(JSON.stringify(h.manager.getEntries()), /PARTIAL_COMMIT/);
  await rm(h.paths.view(task), { recursive: true });
  const ctx = h.session.extensionRunner.createContext();
  assert.equal(
    await h.tasks.append(items, ctx, "retryable"),
    "State updated: v2",
  );
  assert.equal((await h.tasks.state.read(task)).version, 2);
  assert.equal((await h.tasks.index.get(task.task_id)).state_version, 2);
});

test("missing registered source aborts before inference and never resets reference numbering", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create");
  const task = (await h.tasks.index.read())[0]!;
  // A missing historical Session must not be treated as a fresh empty counter.
  await h.tasks.index.put({
    ...task,
    sessions: [
      ...task.sessions,
      { session_id: "missing-session", file: h.paths.root + "/missing.jsonl" },
    ],
  });
  const before = h.faux.state.callCount;
  h.faux.setResponses([fauxAssistantMessage("never sent")]);
  await h.session.prompt("must abort");
  assert.equal(h.faux.state.callCount, before);
  assert.ok(h.diagnostics.some((s) => s.includes("REFERENCE_SOURCE_MISSING")));
  assert.equal((await h.tasks.state.read(task)).version, 1);
});

test("same native call retry is idempotent; a reused tool ID in a new assistant entry is a new operation", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create");
  const task = (await h.tasks.index.read())[0]!;
  const items = [
    {
      type: "fact" as const,
      content: "same content",
      evidence: { U1: "original user" },
    },
  ];
  for (let i = 0; i < 2; i++) {
    h.faux.setResponses([
      call("state_append", { items }, "reused"),
      fauxAssistantMessage("saved"),
    ]);
    await h.session.prompt(`round ${i}`);
    assert.equal(
      await h.tasks.append(
        items,
        h.session.extensionRunner.createContext(),
        "reused",
      ),
      `State updated: v${i + 2}`,
    );
  }
  assert.equal((await h.tasks.state.read(task)).version, 3);
  assert.deepEqual(h.diagnostics, []);
});

test("only the triggering unbound user/creation turn is adopted; latest_paused uses workspace and updated time", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("old unbound reply")]);
  await h.session.prompt("old unbound user");
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("new triggering user");
  const task = (await h.tasks.index.read())[0]!;
  const refs = await loadReferences(task, h.tasks.memory);
  assert.equal([...refs.keys()].filter((r) => r.startsWith("U")).length, 1);
  const user = h.manager.getEntry(refs.get("U1")!.entry_id);
  assert.ok(user?.type === "message" && user.message.role === "user");
  assert.match(JSON.stringify(user.message.content), /new triggering user/);
  await h.tasks.index.put({ ...task, status: "paused" });
  h.faux.setResponses([
    call("task_resume", { mode: "latest_paused" }),
    fauxAssistantMessage("resumed"),
  ]);
  await h.session.prompt("resume latest paused");
  assert.equal((await h.tasks.index.get(task.task_id)).status, "active",JSON.stringify(h.manager.getBranch().filter(e=>e.type==="message"&&e.message.role==="toolResult"&&e.message.isError)));
  assert.deepEqual(h.diagnostics, []);
});

test("actual Session disk failure taints metadata; extension reload cannot legitimize the dirty memory view", async (t) => {
  const { rename } = await import("node:fs/promises");
  const { renameSync, mkdirSync } = await import("node:fs");
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create");
  const file = h.manager.getSessionFile()!,
    backup = file + ".backup",
    ctx = h.session.extensionRunner.createContext(),
    before = h.manager.getEntries().length;
  const failing = new SessionMemory({
    appendEntry(kind, data) {
      renameSync(file, backup);
      mkdirSync(file);
      h.manager.appendCustomEntry(kind, data);
    },
  });
  await assert.rejects(
    failing.append(ctx, "memweave.scope.v1", { task_id: null, overrides: {} }),
    /SESSION_WRITE_FAILED/,
  );
  assert.equal(h.manager.getEntries().length, before + 1);
  await rm(file, { recursive: true });
  await rename(backup, file);
  assert.equal(SessionManager.open(file).getEntries().length, before);
  await h.session.reload();
  h.faux.setResponses([fauxAssistantMessage("must not send")]);
  const calls = h.faux.state.callCount;
  await h.session.prompt("dirty memory cannot be reused");
  assert.equal(h.faux.state.callCount, calls);
  assert.ok(
    h.diagnostics.some((s) =>
      /SESSION_STATE_DIVERGED|CORRUPT_REFERENCE_SOURCE/.test(s),
    ),
  );
});
