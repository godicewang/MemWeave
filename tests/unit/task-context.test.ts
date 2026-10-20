import assert from "node:assert/strict";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxThinking,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { taskContext } from "../../src/pi/task-context.ts";
import type { TaskSnapshot } from "../../src/task/service.ts";
import type { RequestMessages } from "../../src/pi/request-lifecycle.ts";

test("reference heads preserve opaque tool IDs/arguments, reasoning signatures and image blocks without mutating native messages", () => {
  const user = {
    role: "user" as const,
    content: [
      { type: "image" as const, mimeType: "image/png", data: "opaque-image" },
    ],
    timestamp: 1,
  };
  const assistant = fauxAssistantMessage([
    { ...fauxThinking("reasoning"), thinkingSignature: "opaque-signature" },
    fauxToolCall("probe", { arg: "opaque" }, { id: "native-id" }),
  ]);
  const result = {
    role: "toolResult" as const,
    toolCallId: "native-id",
    toolName: "probe",
    content: [{ type: "text" as const, text: "original result" }],
    isError: false,
    timestamp: 3,
  };
  const messages: RequestMessages = [
    { role: "system", content: "native", timestamp: 0 },
    user,
    assistant,
    result,
  ];
  const before = structuredClone(messages);
  const entries: SessionEntry[] = [user, assistant, result].map(
    (message, i) => ({
      type: "message",
      message,
      id: `entry${i}`,
      parentId: null,
      timestamp: "2026-10-21T00:00:00Z",
    }),
  );
  const bindings = [
    { ref: "U1", entry_id: "entry0" },
    { ref: "A1", entry_id: "entry1" },
    { ref: "T1", entry_id: "entry2", tool_call_id: "native-id" },
  ];
  entries.push({
    type: "custom",
    id: "refs",
    parentId: null,
    timestamp: "2026-10-21T00:00:00Z",
    customType: "memweave.references.v1",
    data: { task_id: "task_unit", source_session_id: "source", bindings },
  });
  const snapshot: TaskSnapshot = {
    task: {
      task_id: "task_unit",
      workspace: "--test--",
      title: "test",
      project_name: "test",
      summary: "test",
      keywords: ["test"],
      status: "active",
      state_version: 1,
      updated_at: "2026-10-21T00:00:00Z",
      sessions: [],
    },
    state: "# Symbolic State",
    entries,
    references: new Map(
      bindings.map((b) => [b.ref, { ...b, source_session_id: "source" }]),
    ),
  };
  const view = taskContext(messages, snapshot);
  assert.deepEqual(messages, before);
  assert.equal(view.length, 5);
  for (let i = 1; i <= 3; i++) {
    const original = before[i],
      labeled = view[i];
    assert.ok(original && labeled && "content" in labeled);
    assert.deepEqual(
      {
        ...labeled,
        content: Array.isArray(labeled.content)
          ? labeled.content.slice(1)
          : labeled.content,
      },
      original,
    );
  }
  const last = view.at(-1);
  assert.ok(last?.role === "user");
  assert.equal(last.content, "# Symbolic State");
});
