import assert from "node:assert/strict";
import test from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { restartMetadata, RESTART_TYPE, restartTaskId } from "../../src/task/restart-model.ts";
import { restartSeed, restartEvents, validateRestart } from "../../src/window/restart.ts";
import { indexEvents } from "../../src/window/select.ts";
import { scopeOf, SCOPE_TYPE } from "../../src/pi/session-memory.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";

test("restart seed stays within N, inserts nearest real user and preserves whole tool events", () => {
  const manager = SessionManager.inMemory();
  const user = manager.appendMessage({ role: "user", content: "original user", timestamp: 1 });
  for (let i = 0; i < 5; i++) {
    manager.appendMessage(fauxAssistantMessage([fauxToolCall("read", {}, { id: String(i) })]));
    manager.appendMessage({ role: "toolResult", toolCallId: String(i), toolName: "read", content: [{ type: "text", text: "result" }], isError: false, timestamp: i + 1 });
  }
  const events = indexEvents(manager.getBranch());
  const seed = restartSeed(events, 3);
  assert.equal(seed.length, 3); assert.equal(seed[0]!.id, user);
  assert.ok(seed.slice(1).every((event) => event.messages.length === 2));
  assert.deepEqual(restartSeed(events, 1).map((event) => event.id), [user]);
  assert.equal(restartSeed(events.slice(1), 3).length, 3);
  assert.deepEqual(restartSeed([], 3), []);
});

test("restart receipt isolates old binding/window, verifies originals and is branch local", () => {
  const manager = SessionManager.inMemory();
  manager.appendCustomEntry(SCOPE_TYPE, { task_id: "task_old", overrides: { recent_turns: 3, evict_turns: 1 } });
  manager.appendMessage({ role: "user", content: "old user", timestamp: 1 });
  const oldLeaf = manager.getLeafId()!;
  for (let i = 0; i < 6; i++) manager.appendMessage(fauxAssistantMessage("old " + i));
  const original = manager.getBranch(), events = indexEvents(original);
  const seed = restartSeed(events, 3);
  manager.appendCustomEntry(RESTART_TYPE, { restart_id: "restart", previous_task_id: "task_old", anchor_entry_id: original.at(-1)!.id,
    seed_event_ids: seed.map((event) => event.id), recent_turns: 3, evict_turns: 1 });
  const receipt = restartMetadata(manager.getBranch())!;
  assert.deepEqual(scopeOf(manager.getBranch()), { task_id: null, overrides: { recent_turns: 3, evict_turns: 1 } });
  assert.deepEqual(validateRestart(manager.getBranch(), receipt).map((event) => event.id), seed.map((event) => event.id));
  const fresh = manager.appendMessage({ role: "user", content: "new user", timestamp: 10 });
  assert.deepEqual(restartEvents(manager.getBranch(), null, { ...DEFAULT_CONFIG, recent_turns: 3, evict_turns: 1 }).map((event) => event.id), [...seed.map((event) => event.id), fresh]);
  assert.equal(restartTaskId("session", "restart"), restartTaskId("session", "restart"));
  assert.notEqual(restartTaskId("session", "restart"), restartTaskId("fork", "restart"));
  const bad = { ...receipt, data: { ...receipt.data, seed_event_ids: events.slice(1, 4).map((event) => event.id) } };
  assert.throws(() => validateRestart(manager.getBranch(), bad), /RESTART/);
  manager.branch(oldLeaf);
  assert.equal(restartMetadata(manager.getBranch()), null);
  assert.equal(scopeOf(manager.getBranch()).task_id, "task_old");
});
