import assert from "node:assert/strict";
import { readFile, writeFile, rm, mkdir } from "node:fs/promises";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { taskSession } from "../fixtures/task-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { prepareStateBatch } from "../../src/state/window.ts";
const create = {
  title: "Window test",
  goal: "Verify State window",
  project_name: "MemWeave",
  summary: "Window verification",
  keywords: ["window"],
};
const items = Array.from({ length: 10 }, (_, i) => ({
  type: "fact",
  content: `fact ${i + 1}`,
  evidence: { U1: "user request" },
}));
const call = (
  name: string,
  args: Parameters<typeof fauxToolCall>[1],
  id = "call",
) => fauxAssistantMessage([fauxToolCall(name, args, { id })]);
const config = {
  ...DEFAULT_CONFIG,
  state_max_events: 10,
  state_evict_batch: 2,
};
async function ready(t: Parameters<typeof taskSession>[0]) {
  const h = await taskSession(t);
  await writeFile(h.paths.config, JSON.stringify(config));
  return h;
}

for (const appendFirst of [false, true])
  test(`native State append/remain are independently committed (appendFirst=${appendFirst})`, async (t) => {
    const h = await ready(t);
    h.faux.setResponses([
      call("task_create", create),
      call("state_append", { items }, "initial"),
      fauxAssistantMessage(
        appendFirst
          ? [
              fauxToolCall(
                "state_append",
                {
                  items: [
                    {
                      type: "decision",
                      content: "new cognition while full",
                      evidence: { U1: "user" },
                    },
                  ],
                },
                { id: "new" },
              ),
              fauxToolCall(
                "state_remain",
                { event_ids: ["F1"] },
                { id: "remain" },
              ),
            ]
          : [
              fauxToolCall(
                "state_remain",
                { event_ids: ["F1"] },
                { id: "remain" },
              ),
              fauxToolCall(
                "state_append",
                {
                  items: [
                    {
                      type: "decision",
                      content: "new cognition while full",
                      evidence: { U1: "user" },
                    },
                  ],
                },
                { id: "new" },
              ),
            ],
      ),
      fauxAssistantMessage("done"),
    ]);
    await h.session.prompt("Create and maintain State");
    const task = (await h.tasks.index.read())[0]!,
      state = await h.tasks.state.read(task);
    assert.equal(state.facts.length, 9);
    assert.equal(state.decisions.length, 1);
    assert.equal(state.version, 13);
    assert.equal(state.events.filter((e) => e.op === "slide_window").length, 1);
    assert.match(JSON.stringify(h.frames[2]), /State 窗口管理/);
    assert.match(JSON.stringify(h.frames.at(-1)), /new cognition while full/);
    assert.equal(
      await h.tasks.remain(
        ["F1"],
        h.session.extensionRunner.createContext(),
        "remain",
      ),
      "State updated: v13",
    );
    assert.equal((await h.tasks.state.read(task)).version, 13);
    const bytes = await readFile(h.manager.getSessionFile()!, "utf8");
    assert.doesNotMatch(bytes, /State 窗口管理/);
    assert.match(bytes, /memweave.state.request.v1/);
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
  });

test("full window loads overflow immediately, keeps the pending ID stable, and removes only on committed remain", async (t) => {
  const h = await ready(t);
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }, "initial"),
    call(
      "state_append",
      {
        items: [
          {
            type: "fact",
            content: "overflow visible now",
            evidence: { U1: "user" },
          },
        ],
      },
      "overflow",
    ),
    fauxAssistantMessage("overflow observed"),
  ]);
  await h.session.prompt("Fill and overflow");
  const task = (await h.tasks.index.read())[0]!,
    state = await h.tasks.state.read(task);
  assert.equal(state.facts.length, 11);
  assert.equal(state.events.filter((e) => e.op === "slide_window").length, 0);
  assert.match(JSON.stringify(h.frames.at(-1)), /F11 overflow visible now/);
  const anchors = h.manager
    .getEntries()
    .filter(
      (e) =>
        e.type === "custom" && e.customType === "memweave.state.request.v1",
    );
  assert.ok(anchors.length >= 2);
  const batches = anchors.map((e) =>
    e.type === "custom" ? (e.data as { batch_id: string }).batch_id : "",
  );
  assert.equal(new Set(batches).size, 1);
  assert.doesNotMatch(
    await readFile(h.paths.view(task), "utf8"),
    /State 窗口管理/,
  );
});

test("actual modify_fact changes State atomically and rejects an outdated request batch", async (t) => {
  const h = await ready(t);
  h.session.agent.toolExecution = "sequential";
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }, "initial"),
    fauxAssistantMessage([
      fauxToolCall(
        "modify_fact",
        {
          archive: ["F1"],
          append_fact: { content: "corrected fact", evidence: { U1: "user" } },
        },
        { id: "modify" },
      ),
      fauxToolCall("state_remain", { event_ids: [] }, { id: "stale" }),
    ]),
    fauxAssistantMessage("after rejected old batch"),
  ]);
  await h.session.prompt("Correct a candidate and reject stale batch");
  const task = (await h.tasks.index.read())[0]!,
    state = await h.tasks.state.read(task);
  assert.equal(state.facts.length, 10);
  assert.equal(state.facts.at(-1)?.id, "F11");
  assert.equal(state.events.filter((e) => e.op === "slide_window").length, 0);
  assert.match(JSON.stringify(h.manager.getEntries()), /STALE_STATE_BATCH/);
  assert.deepEqual(h.diagnostics, []);
});

test("request batch survives disk reopen; same native invocation retry after derivative failure never slides twice", async (t) => {
  let h: Awaited<ReturnType<typeof ready>>,
    breakView = false;
  h = await taskSession(t, {
    extra: (pi) =>
      pi.on("tool_call", async (event) => {
        if (event.toolName === "state_remain" && breakView) {
          breakView = false;
          const task = (await h.tasks.index.read())[0]!;
          await rm(h.paths.view(task));
          await mkdir(h.paths.view(task));
        }
      }),
  });
  await writeFile(h.paths.config, JSON.stringify(config));
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }, "initial"),
    fauxAssistantMessage("full"),
  ]);
  await h.session.prompt("fill");
  const task = (await h.tasks.index.read())[0]!;
  breakView = true;
  h.faux.setResponses([
    call("state_remain", { event_ids: [] }, "remain"),
    fauxAssistantMessage("never sent"),
  ]);
  await h.session.prompt("slide with derivative failure");
  const committed = await h.tasks.state.read(task);
  assert.equal(committed.facts.length, 8);
  assert.equal(
    committed.events.filter((e) => e.op === "slide_window").length,
    1,
  );
  await rm(h.paths.view(task), { recursive: true });
  const reopened = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
  });
  assert.equal(
    await reopened.tasks.remain(
      [],
      reopened.session.extensionRunner.createContext(),
      "remain",
    ),
    `State updated: v${committed.version}`,
  );
  assert.equal(
    (await reopened.tasks.state.read(task)).version,
    committed.version,
  );
  assert.deepEqual(reopened.diagnostics, []);
});

test("two Pi instances act on the same batch once and reject conflicting retention choices", async (t) => {
  const a = await ready(t);
  a.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }, "initial"),
    fauxAssistantMessage("full"),
  ]);
  await a.session.prompt("fill");
  const task = (await a.tasks.index.read())[0]!;
  const b = await taskSession(t, { paths: a.paths });
  b.faux.setResponses([
    call("task_resume", { task_id: task.task_id }),
    fauxAssistantMessage("bound"),
  ]);
  await b.session.prompt("resume");
  let arrivals = 0,
    release!: () => void;
  const both = new Promise<void>((resolve) => {
    release = resolve;
  });
  const response = (ids: string[], id: string) => async () => {
    if (++arrivals === 2) release();
    await both;
    return call("state_remain", { event_ids: ids }, id);
  };
  a.faux.setResponses([
    response(["F1"], "remain-a"),
    fauxAssistantMessage("done"),
  ]);
  b.faux.setResponses([response([], "remain-b"), fauxAssistantMessage("done")]);
  await Promise.all([a.session.prompt("manage"), b.session.prompt("manage")]);
  const state = await a.tasks.state.read(task);
  assert.equal(state.events.filter((e) => e.op === "slide_window").length, 1);
  const results = [...a.manager.getEntries(), ...b.manager.getEntries()]
    .filter((e) => e.type === "message" && e.message.role === "toolResult")
    .map((e) =>
      e.type === "message" && e.message.role === "toolResult"
        ? JSON.stringify(e.message.content)
        : "",
    );
  assert.match(results.join("\n"), /STATE_BATCH_ALREADY_COMMITTED/);
  assert.deepEqual(a.diagnostics, []);
  assert.deepEqual(b.diagnostics, []);
});

test("a later request without reminder cannot reuse an old request anchor to initiate a fresh slide", async (t) => {
  const h = await ready(t);
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }, "initial"),
    fauxAssistantMessage("full"),
  ]);
  await h.session.prompt("fill");
  const task = (await h.tasks.index.read())[0]!,
    batch = prepareStateBatch(
      task.task_id,
      await h.tasks.state.read(task),
      config,
    )!;
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...config, state_max_events: 100 }),
  );
  h.faux.setResponses([
    call("state_remain", { event_ids: [] }, "unprepared"),
    fauxAssistantMessage("blocked"),
  ]);
  await h.session.prompt("new request with larger capacity");
  assert.equal(
    (await h.tasks.state.read(task)).events.filter(
      (e) => e.op === "slide_window",
    ).length,
    0,
  );
  assert.match(
    JSON.stringify(h.manager.getEntries()),
    /STATE_BATCH_NOT_PREPARED/,
  );
  assert.ok(batch.batch_id);
  assert.deepEqual(h.diagnostics, []);
});

test("batch anchor failure cancels before inference; request keep limit remains fixed after config changes", async (t) => {
  const h = await ready(t);
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...config, state_keep_limit: 1 }),
  );
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items: [...items, ...items] }, "initial"),
    fauxAssistantMessage("full"),
  ]);
  await h.session.prompt("fill twenty");
  const task = (await h.tasks.index.read())[0]!;
  h.faux.setResponses([
    async () => {
      await writeFile(
        h.paths.config,
        JSON.stringify({ ...config, state_keep_limit: 20 }),
      );
      return call("state_remain", { event_ids: ["F1", "F2"] }, "old-limit");
    },
    fauxAssistantMessage("old limit rejected"),
  ]);
  await h.session.prompt("old request permission");
  assert.match(
    JSON.stringify(
      h.manager
        .getEntries()
        .filter((e) => e.type === "message" && e.message.role === "toolResult"),
    ),
    /STATE_KEEP_LIMIT_EXCEEDED/,
  );
  assert.equal(
    (await h.tasks.state.read(task)).events.filter(
      (e) => e.op === "slide_window",
    ).length,
    0,
  );
  const append = h.tasks.memory.append.bind(h.tasks.memory);
  h.tasks.memory.append = async (ctx, kind, data) => {
    if (kind === "memweave.state.request.v1")
      throw Error("INJECTED_STATE_ANCHOR_FAILURE");
    await append(ctx, kind, data);
  };
  const before = h.faux.state.callCount;
  h.faux.setResponses([fauxAssistantMessage("never sent")]);
  await h.session.prompt("anchor must fail");
  assert.equal(h.faux.state.callCount, before);
  assert.ok(
    h.diagnostics.some((s) => s.includes("INJECTED_STATE_ANCHOR_FAILURE")),
  );
  assert.equal(
    (await h.tasks.state.read(task)).events.filter(
      (e) => e.op === "slide_window",
    ).length,
    0,
  );
});
