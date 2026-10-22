import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { taskSession } from "../fixtures/task-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { WINDOW_TYPE } from "../../src/window/model.ts";
import { windowMetadata, WindowService } from "../../src/pi/window-service.ts";
import { indexEvents } from "../../src/window/select.ts";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { visionImage } from "../fixtures/vision-image.ts";
const create = {
  title: "Window",
  goal: "Verify Recent Window",
  project_name: "MemWeave",
  summary: "Window integration",
  keywords: ["window"],
};
const call = (
  name: string,
  args: Parameters<typeof fauxToolCall>[1],
  id = name,
) => fauxAssistantMessage([fauxToolCall(name, args, { id })]);
test("native reminders keep complete events, coexist with State reminders, and commit despite failed State writes", async (t) => {
  const h = await taskSession(t);
  await writeFile(
    h.paths.config,
    JSON.stringify({
      ...DEFAULT_CONFIG,
      recent_turns: 3,
      evict_turns: 1,
      state_max_events: 10,
      state_evict_batch: 2,
    }),
  );
  const items = Array.from({ length: 10 }, (_, i) => ({
    type: "fact",
    content: `fact ${i}`,
    evidence: { U1: "user" },
  }));
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }, "fill"),
    call(
      "state_append",
      {
        items: [
          {
            type: "fact",
            content: "invalid evidence",
            evidence: { U999: "missing" },
          },
        ],
      },
      "fail",
    ),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("Create State and handle the window");
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  assert.ok(
    h.frames.some(
      (frame) =>
        JSON.stringify(frame).includes("Recent Window 移出提醒") &&
        JSON.stringify(frame).includes("State 窗口管理"),
    ),
  );
  const metadata = windowMetadata(h.manager.getBranch())!;
  assert.equal(metadata.stage, "commit");
  assert.equal(metadata.pending.length, 0);
  const task = (await h.tasks.index.read())[0]!;
  assert.equal((await h.tasks.state.read(task)).facts.length, 10);
  const raw = await readFile(h.manager.getSessionFile()!, "utf8");
  assert.match(raw, /INVALID_EVIDENCE/);
  assert.doesNotMatch(
    raw,
    /Recent Window 移出提醒|State 窗口管理|\[TRUNCATED\]/,
  );
  for (const frame of h.frames) {
    const state = frame.filter(
      (m) => m.role === "custom" && m.customType === "memweave.state",
    );
    assert.ok(state.length <= 1);
  }
});
test("settings apply to automatic continuation, reset range from originals and keep old-call retries from undoing newer settings", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("task_create", create),
    call("recent_window_set", { turns: 8, evict_turns: 2 }, "first"),
    call("recent_window_set", { turns: 2, evict_turns: 1 }, "second"),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("Change window settings");
  assert.deepEqual(h.diagnostics, []);
  const result = h.manager
    .getEntries()
    .filter(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "recent_window_set",
    );
  assert.equal(result.length, 2);
  assert.ok(JSON.stringify(h.frames[2]).includes("`8` 个交互事件"));
  assert.ok(JSON.stringify(h.frames[3]).includes("`2` 个交互事件"));
  assert.equal(
    h.frames[3]!.filter((m) => m.role !== "system" && m.role !== "custom")
      .length,
    4,
  );
  const window = new WindowService(h.tasks);
  assert.equal(
    await window.set(
      { turns: 8, evict_turns: 2 },
      h.session.extensionRunner!.createContext(),
      "first",
    ),
    "ok; turns=8; evict_turns=2; effective=next_request",
  );
  assert.equal(
    h.tasks.scope(h.session.extensionRunner!.createContext()).overrides
      .recent_turns,
    2,
  );
  assert.deepEqual(
    JSON.parse(await readFile(h.paths.config, "utf8")),
    DEFAULT_CONFIG,
  );
  h.faux.setResponses([
    call("recent_window_set", { turns: 1 }, "invalid"),
    fauxAssistantMessage("done"),
  ]);
  // Current B=1 is legal when omitted, and shrinking never silently changes it.
  await h.session.prompt("Shrink again");
  assert.equal(
    h.tasks.scope(h.session.extensionRunner!.createContext()).overrides
      .evict_turns,
    1,
  );
});
test("backlog shares one request; interrupted and partially committed batches reopen with stable remaining IDs", async (t) => {
  const h = await taskSession(t);
  for (let i = 0; i < 300; i++)
    h.manager.appendMessage({
      role: "user",
      content: `original ${i}`,
      timestamp: i,
    });
  const restored = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  let commits = 0;
  const append = restored.tasks.memory.pi.appendEntry;
  restored.tasks.memory.pi.appendEntry = (kind, data) => {
    if (
      kind === WINDOW_TYPE &&
      (data as { stage: string }).stage === "commit" &&
      ++commits === 2
    )
      throw Error("INJECTED_COMMIT_FAILURE");
    append(kind, data);
  };
  restored.faux.setResponses([
    fauxAssistantMessage("inspected all pending batches"),
  ]);
  await restored.session.prompt("inspect backlog");
  assert.equal(restored.faux.state.callCount, 1);
  assert.match(JSON.stringify(restored.frames[0]), /3 批/);
  const partial = windowMetadata(
    SessionManager.open(restored.manager.getSessionFile()!).getBranch(),
  )!;
  assert.equal(partial.stage, "commit");
  assert.equal(partial.pending.length, 2);
  assert.ok(
    restored.diagnostics.some((d) => d.includes("SESSION_WRITE_FAILED")),
  );
  const retry = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(restored.manager.getSessionFile()!),
  });
  retry.faux.setResponses([fauxAssistantMessage("retried remaining")]);
  await retry.session.prompt("retry remaining batches");
  assert.equal(retry.faux.state.callCount, 1);
  const records = retry.manager
    .getBranch()
    .filter((e) => e.type === "custom" && e.customType === WINDOW_TYPE);
  const prepared = records.findLast(
    (e) =>
      e.type === "custom" && (e.data as { stage: string }).stage === "prepare",
  );
  assert.ok(prepared?.type === "custom");
  assert.deepEqual((prepared.data as typeof partial).pending, partial.pending);
  const done = windowMetadata(retry.manager.getBranch())!;
  assert.equal(done.pending.length, 0);
  const events = indexEvents(retry.manager.getBranch());
  assert.ok(
    events.length -
      events.findIndex((e) => e.id === done.boundary_entry_id) -
      1 <=
      200,
  );
  assert.equal(
    records.filter(
      (e) =>
        e.type === "custom" && (e.data as { stage: string }).stage === "commit",
    ).length,
    3,
  );
});
test("cancelled model response retains batch; disk reopening retries the same candidates", async (t) => {
  const h = await taskSession(t);
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 2, evict_turns: 1 }),
  );
  h.faux.setResponses([fauxAssistantMessage("first")]);
  await h.session.prompt("first user");
  h.faux.setResponses([fauxAssistantMessage("", { stopReason: "aborted" })]);
  await h.session.prompt("second user");
  const pending = windowMetadata(h.manager.getBranch())!;
  assert.equal(pending.pending.length, 1);
  assert.equal(pending.boundary_entry_id, null);
  const b = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  b.faux.setResponses([fauxAssistantMessage("completed")]);
  await b.session.prompt("retry");
  const record = b.manager
    .getBranch()
    .findLast(
      (e) =>
        e.type === "custom" &&
        e.customType === WINDOW_TYPE &&
        (e.data as { stage: string }).stage === "prepare",
    );
  assert.ok(record?.type === "custom");
  assert.deepEqual(
    (record.data as typeof pending).pending[0],
    pending.pending[0],
  );
  assert.equal(windowMetadata(b.manager.getBranch())!.pending.length, 0);
  assert.deepEqual(b.diagnostics, []);
});
test("fixed costs exceeding half context abort before the provider even when full model capacity would fit", async (t) => {
  const h = await taskSession(t, { verifyCapacity: async () => 100_000 });
  await writeFile(h.paths.rule, "minimal rule {{recent_turns}}");
  h.faux.setResponses([fauxAssistantMessage("must not send")]);
  await h.session.prompt("x".repeat(60_000));
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(h.diagnostics.some((d) => d.startsWith("CONTEXT_BUDGET_EXCEEDED")));
  assert.equal(h.frames.length, 0);
  assert.match(
    await readFile(h.manager.getSessionFile()!, "utf8"),
    new RegExp("x{60000}"),
  );
});
test("memory_read full range survives tool continuation and expires after ten newer messages without changing Session", async (t) => {
  const h = await taskSession(t, { verifyCapacity: async () => 80_000 });
  await writeFile(h.paths.rule, "minimal rule {{recent_turns}}");
  h.faux.setResponses([
    call("task_create", create),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("e".repeat(10000));
  h.faux.setResponses([
    call("memory_read", { items: [{ ref: "U1", limit: 8000 }] }, "read"),
    call("task_status", { task_id: (await h.tasks.index.read())[0]!.task_id }),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("Read a bounded range then check status");
  assert.deepEqual(h.diagnostics, []);
  const withX = h.budgets.findIndex((b) => b.X > 0);
  assert.ok(withX >= 0);
  assert.ok(h.budgets[withX + 1]!.X > 0);
  const find = (index: number) =>
    h.frames[index]!.find(
      (m) => m.role === "toolResult" && m.toolName === "memory_read",
    );
  assert.match(JSON.stringify(find(withX)), /e{8000}/);
  assert.match(JSON.stringify(find(withX + 1)), /e{8000}/);
  const source = h.manager
    .getBranch()
    .find(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "memory_read",
    );
  assert.match(JSON.stringify(source), /e{8000}/);
  assert.doesNotMatch(JSON.stringify(source), /TRUNCATED/);
  const branch = h.manager.getBranch(),
    position = branch.findIndex((e) => e.id === source!.id);
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
  await h.session.prompt("The tenth newer message expires the read");
  assert.equal(h.budgets.at(-1)!.X, 0);
  assert.match(JSON.stringify(find(h.frames.length - 1)), /TRUNCATED/);
  assert.deepEqual(h.diagnostics, []);
});
test("Window fork and tree inherit only ancestor boundaries; expansion restores original omitted messages", async (t) => {
  const h = await taskSession(t);
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 3, evict_turns: 1 }),
  );
  for (const text of ["first original", "second original", "third original"]) {
    h.faux.setResponses([fauxAssistantMessage("reply")]);
    await h.session.prompt(text);
  }
  const file = h.manager.getSessionFile()!,
    anchor = h.manager.getLeafId()!,
    original = windowMetadata(h.manager.getBranch())!;
  const copy = SessionManager.open(file),
    forkFile = copy.createBranchedSession(anchor);
  assert.ok(forkFile);
  const fork = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(forkFile),
  });
  assert.deepEqual(windowMetadata(fork.manager.getBranch()), original);
  fork.faux.setResponses([fauxAssistantMessage("fork response")]);
  await fork.session.prompt("fork only user");
  assert.deepEqual(windowMetadata(h.manager.getBranch()), original);
  h.faux.setResponses([
    call("recent_window_set", { turns: 20, evict_turns: 2 }, "expand"),
    fauxAssistantMessage("expanded"),
  ]);
  await h.session.prompt("expand originals");
  assert.match(JSON.stringify(h.frames.at(-1)), /first original/);
  assert.equal(windowMetadata(h.manager.getBranch())!.boundary_entry_id, null);
  await h.session.navigateTree(anchor, { summarize: false });
  assert.deepEqual(windowMetadata(h.manager.getBranch()), original);
  assert.doesNotMatch(JSON.stringify(h.manager.getBranch()), /fork only user/);
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(fork.diagnostics, []);
});
test("conflicting settings and omitted invalid B are rejected; a preparation disk failure sends nothing", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    call("recent_window_set", { turns: 8 }, "invalid"),
    fauxAssistantMessage([
      fauxToolCall(
        "recent_window_set",
        { turns: 10, evict_turns: 2 },
        { id: "a" },
      ),
      fauxToolCall(
        "recent_window_set",
        { turns: 12, evict_turns: 2 },
        { id: "b" },
      ),
    ]),
    fauxAssistantMessage("done"),
  ]);
  await h.session.prompt("Reject invalid and conflicting settings");
  assert.deepEqual(
    h.tasks.scope(h.session.extensionRunner!.createContext()).overrides,
    {},
  );
  assert.match(
    JSON.stringify(h.manager.getBranch()),
    /INVALID_WINDOW_SETTINGS/,
  );
  assert.match(
    JSON.stringify(h.manager.getBranch()),
    /CONFLICTING_WINDOW_CALLS/,
  );
  const failing = await taskSession(t);
  failing.tasks.memory.pi.appendEntry = () => {
    throw Error("injected failure");
  };
  await failing.session.prompt("must abort before inference");
  assert.equal(failing.faux.state.callCount, 0);
  assert.match(failing.diagnostics.at(-1) ?? "", /SESSION_WRITE_FAILED/);
});
test("production Window HTTP retries preserve payload and batch; half-budget cancellation adds no HTTP request", async (t) => {
  const h = await taskSession(t);
  await writeFile(h.paths.rule, "stable {{recent_turns}}");
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 2, evict_turns: 1 }),
  );
  h.faux.setResponses([fauxAssistantMessage("setup")]);
  await h.session.prompt("first user");
  const bodies: unknown[] = [];
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const part of request) raw += String(part);
    bodies.push(JSON.parse(raw));
    if (bodies.length === 1) {
      await writeFile(h.paths.rule, "changed {{recent_turns}}");
      await writeFile(
        h.paths.config,
        JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 4, evict_turns: 2 }),
      );
      response.writeHead(503, {
        "content-type": "application/json",
        "retry-after": "0",
      });
      response.end('{"error":{"message":"retry fixture"}}');
      return;
    }
    response.writeHead(200, { "content-type": "text/event-stream" });
    response.write(
      `data: ${JSON.stringify({ id: "probe", choices: [{ index: 0, delta: { role: "assistant", content: "OK" }, finish_reason: null }] })}\n\n`,
    );
    response.write(
      `data: ${JSON.stringify({ id: "probe", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`,
    );
    response.end("data: [DONE]\n\n");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  });
  h.runtime.registerProvider("local-window", {
    baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`,
    apiKey: "local-test-only",
    api: "openai-completions",
    models: [
      {
        id: "probe",
        name: "probe",
        input: ["text"],
        reasoning: false,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 100000,
        maxTokens: 64,
      },
    ],
  });
  const model = h.runtime.getModel("local-window", "probe");
  assert.ok(model);
  await h.session.setModel(model);
  h.settings.applyOverrides({
    retry: { enabled: false, provider: { maxRetries: 1 } },
  });
  await h.session.prompt("retry Window request");
  assert.equal(bodies.length, 2);
  assert.deepEqual(bodies[0], bodies[1]);
  assert.equal(h.frames.length, 2);
  assert.match(JSON.stringify(bodies[0]), /stable 2/);
  assert.equal(windowMetadata(h.manager.getBranch())!.stage, "commit");
  await h.session.prompt("next logical request");
  assert.equal(bodies.length, 3);
  assert.match(JSON.stringify(bodies[2]), /changed 4/);
  await h.session.prompt("x".repeat(60000));
  assert.equal(bodies.length, 3);
  assert.match(h.diagnostics.at(-1) ?? "", /CONTEXT_BUDGET_EXCEEDED/);
});
test("old compaction restores raw ancestor messages; unknown custom context is diagnosed rather than dropped", async (t) => {
  const h = await taskSession(t);
  const original = h.manager.appendMessage({
    role: "user",
    content: "raw ancestor survives summary",
    timestamp: 1,
  });
  h.manager.appendMessage(fauxAssistantMessage("old response"));
  h.manager.appendCompaction(
    "summary must not be treated as original",
    original,
    1000,
  );
  const b = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  b.faux.setResponses([fauxAssistantMessage("restored")]);
  await b.session.prompt("use originals");
  assert.deepEqual(b.diagnostics, []);
  assert.match(JSON.stringify(b.frames[0]), /raw ancestor survives summary/);
  assert.doesNotMatch(
    JSON.stringify(b.frames[0]),
    /summary must not be treated as original/,
  );
  b.manager.appendCustomMessageEntry(
    "third-party",
    "must not silently disappear",
    false,
  );
  const c = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(b.manager.getSessionFile()!),
  });
  await c.session.prompt("diagnose unsupported context");
  assert.equal(c.faux.state.callCount, 0);
  assert.match(c.diagnostics.at(-1) ?? "", /UNSUPPORTED_WINDOW_CONTEXT/);
});
test("State is never trimmed to fit: a large full State cancels a small model budget with an empty tool set", async (t) => {
  let capacity = 1_048_576;
  const h = await taskSession(t, { verifyCapacity: async () => capacity });
  await writeFile(h.paths.rule, "minimal rule");
  const items = Array.from({ length: 60 }, (_, i) => ({
    type: "fact",
    content: `${i}:` + "f".repeat(90),
    evidence: { U1: "user" },
  }));
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }),
    fauxAssistantMessage("saved"),
  ]);
  await h.session.prompt("Create a complete State");
  assert.deepEqual(h.diagnostics, []);
  const task = (await h.tasks.index.read())[0]!,
    state = await readFile(h.paths.state(task));
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 1, evict_turns: 1 }),
  );
  capacity = 20_000;
  h.session.setActiveToolsByName([]);
  const count = h.faux.state.callCount;
  await h.session.prompt("retain the full State");
  assert.equal(h.faux.state.callCount, count);
  assert.match(h.diagnostics.at(-1) ?? "", /CONTEXT_BUDGET_EXCEEDED/);
  assert.ok(state.equals(await readFile(h.paths.state(task))));
});
test("an image before Task binding diagnoses the missing source without sending or losing the original", async (t) => {
  const h = await taskSession(t),
    image = visionImage().image;
  await h.session.prompt("unbound image", { images: [image] });
  assert.equal(h.faux.state.callCount, 0);
  assert.match(h.diagnostics.at(-1) ?? "", /ATTACHMENT_TASK_REQUIRED/);
  const user = h.manager
    .getBranch()
    .find((e) => e.type === "message" && e.message.role === "user");
  assert.ok(
    user?.type === "message" &&
      user.message.role === "user" &&
      Array.isArray(user.message.content),
  );
  assert.deepEqual(
    user.message.content.find((p) => p.type === "image"),
    image,
  );
});
