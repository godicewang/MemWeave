import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
const create = () =>
  fauxAssistantMessage([
    fauxToolCall("task_create", {
      title: "Read lifetime",
      goal: "Verify source reads",
      project_name: "MemWeave",
      summary: "Lifetime test",
      keywords: ["lifetime"],
    }),
  ]);

test("native fork inherits read age; a smaller Window can evict a live result without pinning it", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([create(), fauxAssistantMessage("created")]);
  await h.session.prompt("Original source for a forked read");
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("memory_read", { items: [{ ref: "U1", limit: 20 }] }),
    ]),
    fauxAssistantMessage("read"),
  ]);
  await h.session.prompt("Read before fork");
  const file = h.manager.getSessionFile()!;
  const fork = SessionManager.forkFrom(file, h.cwd, h.manager.getSessionDir());
  const b = await taskSession(t, { paths: h.paths, manager: fork });
  b.faux.setResponses([fauxAssistantMessage("forked read still alive")]);
  await b.session.prompt("Continue fork");
  assert.ok(b.budgets.at(-1)!.X > 0);
  b.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("recent_window_set", { turns: 1, evict_turns: 1 }),
    ]),
    fauxAssistantMessage("small Window"),
  ]);
  await b.session.prompt("Only keep one recent event");
  assert.equal(b.budgets.at(-1)!.X, 0);
  assert.equal(
    b.frames
      .at(-1)!
      .some((m) => m.role === "toolResult" && m.toolName === "memory_read"),
    false,
  );
  assert.deepEqual(b.diagnostics, []);
  assert.deepEqual(b.errors, []);
});
test("native steering preserves a complete read; disk reopen keeps its age and tenth later message expires it", async (t) => {
  let h: Awaited<ReturnType<typeof taskSession>>;
  h = await taskSession(t, {
    verifyCapacity: async () => 100000,
    extra: (pi) => {
      pi.on("tool_result", async (event) => {
        if (event.toolName === "memory_read")
          await h.session.steer("Use the source you just read.");
      });
    },
  });
  h.faux.setResponses([create(), fauxAssistantMessage("created")]);
  await h.session.prompt("Original source " + "x".repeat(10000));
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("memory_read", {
        items: [{ ref: "U1", offset: 0, limit: 8000 }],
      }),
    ]),
    fauxAssistantMessage("read complete"),
  ]);
  await h.session.prompt("Read U1.");
  const result = h.manager
    .getBranch()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "memory_read",
    );
  assert.ok(result?.type === "message" && result.message.role === "toolResult");
  assert.equal(h.budgets.at(-1)!.X > 8000, true);
  let shown = h.frames
    .at(-1)!
    .find((m) => m.role === "toolResult" && m.toolName === "memory_read");
  assert.ok(shown?.role === "toolResult");
  assert.doesNotMatch(JSON.stringify(shown.content), /\[TRUNCATED\]/);
  assert.deepEqual(h.diagnostics, []);
  const task = (await h.tasks.index.read())[0]!,
    before = await readFile(h.paths.state(task));
  const restored = await taskSession(t, {
    paths: h.paths,
    manager: SessionManager.open(h.manager.getSessionFile()!),
    verifyCapacity: async () => 100000,
  });
  restored.faux.setResponses([
    fauxAssistantMessage("still complete after reopening"),
  ]);
  await restored.session.prompt(
    "Continue from disk while the read is still alive.",
  );
  assert.ok(restored.budgets.at(-1)!.X > 8000);
  // Reopening and rendering do not reset or spend age; only new messages do.
  const branch = restored.manager.getBranch(),
    position = branch.findIndex((e) => e.id === result.id);
  const following = branch
    .slice(position + 1)
    .filter(
      (e) =>
        e.type === "message" &&
        ["user", "assistant", "toolResult"].includes(e.message.role),
    ).length;
  for (let i = following; i < 9; i++)
    restored.manager.appendMessage({
      role: "user",
      content: `interruption ${i}`,
      timestamp: i,
    });
  // The next prompt is exactly the tenth raw message after the result.
  restored.faux.setResponses([fauxAssistantMessage("expired")]);
  await restored.session.prompt("Continue after ten messages.");
  assert.equal(restored.budgets.at(-1)!.X, 0);
  shown = restored.frames
    .at(-1)!
    .find((m) => m.role === "toolResult" && m.toolName === "memory_read");
  assert.ok(shown?.role === "toolResult");
  assert.match(JSON.stringify(shown.content), /\[TRUNCATED\]/);
  assert.deepEqual(restored.diagnostics, []);
  assert.deepEqual(restored.errors, []);
  assert.ok(before.equals(await readFile(h.paths.state(task))));
  const original = SessionManager.open(restored.manager.getSessionFile()!)
    .getBranch()
    .find((e) => e.id === result.id);
  assert.equal(JSON.stringify(original), JSON.stringify(result));
});
