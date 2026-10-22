import assert from "node:assert/strict";
import test from "node:test";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { indexEvents } from "../../src/window/select.ts";
import { readGrants } from "../../src/window/read-grant.ts";
import {
  readHistoricalState,
  historyReadRanges,
} from "../../src/state/read.ts";
import { reduceState } from "../../src/state/model.ts";
const entry = (id: string, message: unknown) =>
  ({
    type: "message",
    id,
    parentId: null,
    timestamp: "now",
    message,
  }) as SessionEntry;
function memoryRead() {
  return [
    entry(
      "a",
      fauxAssistantMessage([
        fauxToolCall("memory_read", { items: [{ ref: "U1" }] }, { id: "r" }),
      ]),
    ),
    entry("r", {
      role: "toolResult",
      toolCallId: "r",
      toolName: "memory_read",
      isError: false,
      timestamp: 1,
      content: [
        {
          type: "text",
          text: JSON.stringify({
            items: [
              {
                ref: "U1",
                source_task_id: "task_a",
                offset: 0,
                content: "original",
                range_complete: true,
                source_complete: true,
                status: "ok",
              },
            ],
          }),
        },
      ],
      details: {
        memweave_read: {
          version: 1,
          ranges: [
            {
              ref: "U1",
              source_task_id: "task_a",
              offset: 0,
              returned_chars: 8,
              range_complete: true,
              source_complete: true,
              status: "ok",
            },
          ],
        },
      },
    }),
  ];
}
test("read lifecycle counts raw messages, survives steering and metadata, and expires exactly at ten", () => {
  const entries = memoryRead();
  for (let i = 0; i <= 10; i++) {
    const branch = [
      ...entries,
      ...Array.from({ length: i }, (_, n) =>
        entry(`u${n}`, { role: "user", content: "steering", timestamp: n }),
      ),
      {
        type: "custom",
        customType: "audit",
        data: {},
        id: "metadata",
        parentId: null,
        timestamp: "now",
      } as SessionEntry,
      entry("system", { role: "system", content: "native", timestamp: 0 }),
    ];
    assert.equal(readGrants(indexEvents(branch), branch).has("r"), i < 10);
    assert.equal(
      readGrants(
        indexEvents(structuredClone(branch)),
        structuredClone(branch),
      ).has("r"),
      i < 10,
    );
  }
});
test("each native tool result counts separately from its assistant event; failed assistant messages count too", () => {
  for (const count of [9, 10]) {
    const branch = memoryRead();
    branch.push(
      entry(
        "work",
        fauxAssistantMessage(
          Array.from({ length: count - 1 }, (_, i) =>
            fauxToolCall("probe", {}, { id: `p${i}` }),
          ),
        ),
      ),
    );
    for (let i = 0; i < count - 1; i++)
      branch.push(
        entry(`p${i}`, {
          role: "toolResult",
          toolCallId: `p${i}`,
          toolName: "probe",
          content: [{ type: "text", text: "OK" }],
          isError: false,
          timestamp: i,
        }),
      );
    assert.equal(readGrants(indexEvents(branch), branch).has("r"), count < 10);
  }
  const branch = [
    ...memoryRead(),
    ...Array.from({ length: 9 }, (_, i) =>
      entry(`u${i}`, { role: "user", content: "new", timestamp: i }),
    ),
  ];
  branch.push(
    entry("aborted", fauxAssistantMessage("", { stopReason: "aborted" })),
  );
  assert.equal(readGrants(indexEvents(branch), branch).has("r"), false);
  assert.equal(
    readGrants(indexEvents(branch.slice(0, -1)), branch.slice(0, -1)).has("r"),
    true,
  );
});
test("explicit historical State reads receive verified lifetime grants; legacy State reads and forged ranges do not", () => {
  const state = reduceState([
    { op_id: "g", op: "update_goal", time: "now", goal: "goal", evidence: {} },
    {
      op_id: "f",
      op: "append_fact",
      time: "now",
      id: "F1",
      fact: "saved",
      evidence: { U1: "source" },
    },
  ]);
  const input = { task_id: "task_a", event_ids: ["F1", "F999"] },
    body = readHistoricalState("task_a", state, input);
  const make = (
    args: { task_id: string; event_ids?: string[] },
    ranges: unknown,
  ) => [
    entry(
      "a",
      fauxAssistantMessage([fauxToolCall("state_read", args, { id: "s" })]),
    ),
    entry("s", {
      role: "toolResult",
      toolCallId: "s",
      toolName: "state_read",
      isError: false,
      timestamp: 1,
      content: [{ type: "text", text: JSON.stringify(body) }],
      details: { memweave_read: { version: 1, ranges } },
    }),
  ];
  let branch = make(input, historyReadRanges(body));
  assert.equal(readGrants(indexEvents(branch), branch).has("s"), true);
  branch = make({ task_id: "task_a" }, historyReadRanges(body));
  assert.equal(readGrants(indexEvents(branch), branch).has("s"), false);
  branch = make(input, []);
  assert.equal(readGrants(indexEvents(branch), branch).has("s"), false);
});

test("rereading the same source creates a fresh result lifetime without extending the old one", () => {
  const old = memoryRead(),
    newer = memoryRead();
  for (const entry of newer) {
    entry.id += "2";
    if (entry.type !== "message") continue;
    if (entry.message.role === "assistant")
      for (const part of entry.message.content)
        if (part.type === "toolCall") part.id = "r2";
    if (entry.message.role === "toolResult") entry.message.toolCallId = "r2";
  }
  const branch = [
    ...old,
    ...Array.from({ length: 8 }, (_, i) =>
      entry(`u${i}`, { role: "user", content: "new", timestamp: i }),
    ),
    ...newer,
  ];
  const grants = readGrants(indexEvents(branch), branch);
  assert.equal(grants.has("r"), false);
  assert.equal(grants.has("r2"), true);
});
