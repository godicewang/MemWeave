import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { writeFile } from "node:fs/promises";
const creation = (title: string) =>
  fauxAssistantMessage([
    fauxToolCall("task_create", {
      title,
      goal: "Audit State history",
      project_name: "MemWeave",
      summary: title,
      keywords: ["history"],
    }),
  ]);
test("native tools trace evicted/archived F/D, preserve disk State and legacy reads, and never switch the requested Task", async (t) => {
  const h = await taskSession(t);
  await writeFile(
    h.paths.config,
    JSON.stringify({
      ...DEFAULT_CONFIG,
      state_max_events: 3,
      state_evict_batch: 1,
    }),
  );
  h.faux.setResponses([creation("Source"), fauxAssistantMessage("created")]);
  await h.session.prompt("Original evidence for historical conclusions.");
  const source = (await h.tasks.index.read())[0]!;
  let before!: Buffer;
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("state_append", {
        items: [
          {
            type: "fact",
            content: "Original finding",
            evidence: { U1: "source request" },
          },
          {
            type: "fact",
            content: "Conclusion based on the original",
            evidence: { U1: "source request" },
          },
          {
            type: "decision",
            content: "Previous decision",
            evidence: { U1: "source request" },
          },
        ],
      }),
    ]),
    fauxAssistantMessage([fauxToolCall("state_remain", { event_ids: [] })]),
    fauxAssistantMessage([
      fauxToolCall("modify_fact", {
        archive: ["D1"],
        append_fact: {
          content: "Corrected finding",
          evidence: { D1: "previous decision explained" },
        },
      }),
    ]),
    () => {
      before = readFileSync(h.paths.state(source));
      return fauxAssistantMessage([
        fauxToolCall("state_read", {
          task_id: source.task_id,
          event_ids: ["F1", "D1", "F2", "F3", "F999"],
        }),
      ]);
    },
    fauxAssistantMessage("history read"),
  ]);
  await h.session.prompt(
    "Create history, evict the old finding, archive the old decision, and read them back.",
  );
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  const result = h.manager
    .getBranch()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "state_read",
    );
  assert.ok(result?.type === "message" && result.message.role === "toolResult");
  assert.equal(result.message.isError, false);
  const part = result.message.content[0];
  assert.ok(part?.type === "text");
  const body = JSON.parse(part.text);
  assert.equal(body.items[0].content, "Original finding");
  assert.equal(body.items[0].in_window, false);
  assert.equal(body.items[0].archived, false);
  assert.equal(body.items[1].archived, true);
  assert.deepEqual(body.items[1].evidence, { U1: "source request" });
  assert.equal(body.items[2].in_window, true);
  assert.equal(body.items[4].status, "not_found");
  assert.ok(h.budgets.at(-1)!.X > 0);
  assert.ok(before.equals(await readFile(h.paths.state(source))));
  h.faux.setResponses([
    creation("Other"),
    fauxAssistantMessage("other created"),
  ]);
  await h.session.prompt("Create an unrelated Task.");
  const other = (await h.tasks.index.read()).find(
    (task) => task.task_id !== source.task_id,
  )!;
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("state_read", {
        task_id: source.task_id,
        event_ids: ["F1"],
      }),
      fauxToolCall("state_read", { task_id: other.task_id }),
    ]),
    fauxAssistantMessage("queries complete"),
  ]);
  await h.session.prompt(
    "Read the source finding and current State without changing Tasks.",
  );
  assert.equal(
    h.tasks.scope(h.session.extensionRunner!.createContext()).task_id,
    other.task_id,
  );
  assert.ok(before.equals(await readFile(h.paths.state(source))));
  const legacy = h.manager
    .getBranch()
    .findLast(
      (e) =>
        e.type === "message" &&
        e.message.role === "toolResult" &&
        e.message.toolName === "state_read",
    );
  assert.ok(legacy?.type === "message" && legacy.message.role === "toolResult");
  const text = legacy.message.content[0];
  assert.ok(text?.type === "text");
  assert.match(text.text, /^# Symbolic State/);
  assert.deepEqual(legacy.message.details, {});
  assert.equal(
    h.manager
      .getBranch()
      .some(
        (e) => e.type === "custom" && e.customType === "memweave.aliases.v1",
      ),
    false,
  );
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});
