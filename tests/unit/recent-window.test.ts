import assert from "node:assert/strict";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
  fauxProvider,
} from "@earendil-works/pi-ai/providers/faux";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { indexEvents, selectWindow } from "../../src/window/select.ts";
import { allocate, renderMessage, textCost } from "../../src/window/budget.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { outputReserve, imageReserve } from "../../src/pi/window-budget.ts";
import { readGrants } from "../../src/window/read-grant.ts";
const user = (i: number) =>
  ({
    type: "message",
    id: `u${i}`,
    parentId: null,
    timestamp: "2026-10-22T00:00:00Z",
    message: { role: "user", content: `body ${i}`, timestamp: i },
  }) as SessionEntry;
test("200 events plus one prepares 40, remains visible until commit, and then selects 161", () => {
  const events = indexEvents(
    Array.from({ length: 201 }, (_, i) => user(i + 1)),
  );
  const first = selectWindow(events, DEFAULT_CONFIG, null, "session", "u201");
  assert.equal(first.events.length, 201);
  assert.equal(first.metadata.pending.length, 1);
  assert.equal(first.metadata.pending[0]!.candidate_event_ids.length, 40);
  const committed = {
    ...first.metadata,
    stage: "commit" as const,
    boundary_entry_id: "u40",
    pending: [],
    completed_by: "a201",
  };
  const next = selectWindow(
    events,
    DEFAULT_CONFIG,
    committed,
    "session",
    "u201",
  );
  assert.equal(next.events.length, 161);
  assert.equal(next.metadata.pending.length, 0);
});
test("300 events prepare three stable batches together; reset recovers the last N originals", () => {
  const events = indexEvents(
    Array.from({ length: 300 }, (_, i) => user(i + 1)),
  );
  const first = selectWindow(events, DEFAULT_CONFIG, null, "s", "u300");
  assert.equal(first.metadata.pending.length, 3);
  const retry = selectWindow(
    events,
    DEFAULT_CONFIG,
    first.metadata,
    "s",
    "u300",
  );
  assert.deepEqual(retry.metadata.pending, first.metadata.pending);
  const reset = selectWindow(
    events,
    { ...DEFAULT_CONFIG, recent_turns: 8, evict_turns: 2 },
    first.metadata,
    "s",
    "u300",
  );
  assert.deepEqual(
    reset.events.map((e) => e.id),
    Array.from({ length: 8 }, (_, i) => `u${293 + i}`),
  );
  assert.equal(reset.metadata.pending.length, 0);
  assert.equal(reset.metadata.stage, "reset");
});
test("one assistant and every native tool result form one event; incomplete/unpaired results fail", () => {
  const assistant = {
    type: "message",
    id: "a",
    parentId: "u1",
    timestamp: "now",
    message: fauxAssistantMessage([
      fauxToolCall("read", {}, { id: "x" }),
      fauxToolCall("read", {}, { id: "y" }),
    ]),
  } as SessionEntry;
  const result = (id: string) =>
    ({
      type: "message",
      id: `t${id}`,
      parentId: "a",
      timestamp: "now",
      message: {
        role: "toolResult",
        toolCallId: id,
        toolName: "read",
        content: [{ type: "text", text: id }],
        isError: false,
        timestamp: 1,
      },
    }) as SessionEntry;
  const events = indexEvents([user(1), assistant, result("y"), result("x")]);
  assert.equal(events.length, 2);
  assert.equal(events[1]!.messages.length, 3);
  assert.throws(
    () => indexEvents([assistant, result("x")]),
    /INCOMPLETE_TOOL_EVENT/,
  );
  assert.throws(() => indexEvents([result("x")]), /UNPAIRED_TOOL_RESULT/);
});
test("one Q shared across Unicode text blocks preserves arguments and signatures and originals", () => {
  const message = fauxAssistantMessage([
    { type: "text", text: "😀".repeat(20) },
    { type: "thinking", thinking: "protected", thinkingSignature: "signature" },
    fauxToolCall("x", { huge: "untouched" }, { id: "native" }),
    { type: "text", text: "tail" },
  ]);
  const original = structuredClone(message);
  const view = renderMessage(message, "[A1]", 40, false);
  assert.deepEqual(message, original);
  assert.deepEqual(
    view.content.filter((p) => p.type !== "text"),
    original.content.filter((p) => p.type !== "text"),
  );
  const text = view.content
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("");
  assert.ok(textCost(text) <= 40);
  assert.match(text, /\[TRUNCATED\]/);
  assert.doesNotMatch(text, /tai/);
  assert.throws(
    () => renderMessage(message, "[A1]", 4, false),
    /CONTEXT_BUDGET_EXCEEDED/,
  );
});
test("60%-context budget includes output, State, latest user, read exemptions and every message in M", () => {
  const messages = [
    {
      message: { role: "user" as const, content: "latest", timestamp: 1 },
      head: "[U1]",
      exempt: true,
    },
  ];
  const value = allocate({
    limit: 10000,
    system: 100,
    state: 200,
    output: 1000,
    reminder: 0,
    messages,
    imageCost: () => {
      throw Error("unexpected");
    },
  });
  assert.equal(value.M, 1);
  assert.equal(value.U, 11 + 32 + textCost("user"));
  assert.equal(value.X, 0);
  assert.ok(value.Q > 0);
  assert.ok(value.total <= 10000);
  assert.throws(
    () =>
      allocate({
        limit: 500,
        system: 100,
        state: 200,
        output: 1000,
        reminder: 0,
        messages,
        imageCost: () => 0,
      }),
    /CONTEXT_BUDGET_EXCEEDED/,
  );
});
test("output overrides and protected text signatures remain fixed costs; empty M does not divide by zero", () => {
  const model = fauxProvider().getModel();
  assert.equal(
    outputReserve({
      ...model,
      maxTokens: 100,
      samplingParams: { max_tokens: 1000 },
    }),
    1000,
  );
  assert.equal(
    outputReserve({
      ...model,
      maxTokens: 100,
      samplingParams: { max_tokens: 16 },
    }),
    16,
  );
  assert.throws(
    () => outputReserve({ ...model, maxTokens: NaN }),
    /OUTPUT_BUDGET_UNVERIFIED/,
  );
  assert.throws(
    () =>
      imageReserve(model, {
        type: "image",
        mimeType: "image/png",
        data: "invalid",
      }),
    /INVALID_IMAGE/,
  );
  const message = fauxAssistantMessage([
    { type: "text", text: "signed text", textSignature: "opaque" },
    { type: "text", text: "x".repeat(100) },
  ]);
  const view = renderMessage(message, "[A1]", 30, false);
  assert.deepEqual(
    view.content.find((p) => p.type === "text" && p.textSignature),
    message.content[0],
  );
  const budget = allocate({
    limit: 10000,
    system: 0,
    state: 0,
    output: 1,
    reminder: 0,
    messages: [],
    imageCost: () => 0,
  });
  assert.equal(budget.M, 0);
  assert.equal(budget.Q, 0);
});
test("user text and forged read metadata never acquire a full-read grant", () => {
  assert.equal(readGrants(indexEvents([user(1)]), [user(1)]).size, 0);
  const a = {
    type: "message",
    id: "a",
    parentId: "u1",
    timestamp: "now",
    message: fauxAssistantMessage([
      fauxToolCall("memory_read", { items: [{ ref: "U1" }] }, { id: "r" }),
    ]),
  } as SessionEntry;
  const result = {
    type: "message",
    id: "t",
    parentId: "a",
    timestamp: "now",
    message: {
      role: "toolResult",
      toolCallId: "r",
      toolName: "memory_read",
      content: [
        {
          type: "text",
          text: JSON.stringify({
            items: [
              {
                ref: "U1",
                content: "original",
                range_complete: true,
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
              returned_chars: 1,
              range_complete: true,
              status: "ok",
            },
          ],
        },
      },
      isError: false,
      timestamp: 1,
    },
  } as SessionEntry;
  assert.equal(readGrants(indexEvents([a, result]), [a, result]).size, 0);
});
