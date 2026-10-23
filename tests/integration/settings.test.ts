import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile, rm } from "node:fs/promises";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { STATE_REQUEST_TYPE, ScopeSchema } from "../../src/pi/session-memory.ts";
import { Check } from "typebox/value";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
const create = { title: "Settings", goal: "Verify configured policies", project_name: "MemWeave",
  summary: "Settings integration", keywords: ["settings"] };
const call = (name: string, args: Parameters<typeof fauxToolCall>[1]) => fauxAssistantMessage([fauxToolCall(name, args)]);

test("native request consumes partial policies, hot updates effective budgets, and preserves durable history", async t => {
  const observedTimeouts: number[] = [];
  const h = await taskSession(t, { verifyCapacity: async (_model, _ctx, settings) => {
    observedTimeouts.push(settings!.model_metadata_timeout_ms); return 1000000;
  } });
  const config = { context_budget: { model_percent: 50, parts_percent: { state: 15, window: 35 } },
    model_metadata_timeout_ms: 3210, source_cache: { max_entries: 0 },
    state_policy: { token_warning_percent: 0.01 }, read: { lifetime_messages: 3, default_total_chars: 20 } };
  await writeFile(h.paths.config, JSON.stringify(config));
  h.faux.setResponses([call("task_create", create), call("state_append", { items: [
    { type: "fact", content: "One durable cognition", evidence: { U1: "Original user source" } },
  ] }), fauxAssistantMessage("saved")]);
  await h.session.prompt("Source " + "认知😀".repeat(50));
  assert.deepEqual(h.diagnostics, []);
  assert.ok(observedTimeouts.every(value => value === 3210));
  assert.equal(h.budgets.at(-1)!.plan.state, 75000);
  assert.equal(h.budgets.at(-1)!.plan.system, 75000);
  const tail = JSON.stringify(h.frames.at(-1)!.at(-1));
  assert.match(tail, /总上限 500000 token/);
  assert.match(tail, /State 75000（15%）/);
  assert.match(tail, /0.01% 管理线 7/);
  assert.match(tail, /回读期限：3/);
  assert.ok(h.manager.getBranch().some(e => e.type === "custom" && e.customType === STATE_REQUEST_TYPE));
  const task = (await h.tasks.index.read())[0]!;
  const stateBefore = await readFile(h.paths.state(task));
  h.faux.setResponses([call("memory_read", { items: [{ ref: "U1" }] }),
    call("state_read", { task_id: task.task_id, event_ids: ["F1"] }), fauxAssistantMessage("read")]);
  await h.session.prompt("Read with configured defaults");
  const results = h.manager.getBranch().filter(e => e.type === "message" && e.message.role === "toolResult");
  for (const name of ["memory_read", "state_read"]) {
    const result = results.findLast(e => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === name);
    assert.ok(result?.type === "message" && result.message.role === "toolResult");
    const body = result.message.content[0]; assert.ok(body?.type === "text");
    assert.equal(JSON.parse(body.text).total_chars, 20);
  }
  await writeFile(h.paths.config, JSON.stringify({ recent_turns: 12, evict_turns: 2 }));
  h.faux.setResponses([fauxAssistantMessage("hot default restore")]);
  await h.session.prompt("Use defaults for omitted policies");
  assert.equal(observedTimeouts.at(-1), 15000);
  assert.match(JSON.stringify(h.frames.at(-1)!.at(-1)), /总上限 600000 token/);
  assert.match(JSON.stringify(h.frames.at(-1)!.at(-1)), /N\/B：12\/2/);
  assert.ok(stateBefore.equals(await readFile(h.paths.state(task))));
  assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /本次预算快照/);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
  assert.equal(Check(ScopeSchema, { task_id: null, overrides: { read: { lifetime_messages: 2 } } }), false);
});

test("configured three-message read lifetime expires on raw messages, without rewriting the result", async t => {
  const h = await taskSession(t);
  await writeFile(h.paths.config, JSON.stringify({ read: { lifetime_messages: 3 } }));
  h.faux.setResponses([call("task_create", create), fauxAssistantMessage("created")]);
  await h.session.prompt("known source");
  h.faux.setResponses([call("memory_read", { items: [{ ref: "U1", limit: 5 }] }), fauxAssistantMessage("read")]);
  await h.session.prompt("read source");
  assert.ok(h.budgets.at(-1)!.X > 0);
  const result = h.manager.getBranch().findLast(e => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "memory_read")!;
  h.faux.setResponses([fauxAssistantMessage("still within lifetime")]);
  await h.session.prompt("second newer message");
  assert.ok(h.budgets.at(-1)!.X > 0);
  h.faux.setResponses([fauxAssistantMessage("expired")]);
  await h.session.prompt("fourth newer message");
  assert.equal(h.budgets.at(-1)!.X, 0);
  assert.deepEqual(h.manager.getBranch().find(e => e.id === result.id), result);
  assert.deepEqual(h.diagnostics, []);
});

test("missing user file uses defaults; incompatible Rule or invalid policies cancel before inference", async t => {
  const h = await taskSession(t);
  await rm(h.paths.config);
  h.faux.setResponses([fauxAssistantMessage("defaults")]);
  await h.session.prompt("no user settings yet");
  assert.equal(h.faux.state.callCount, 1);
  await assert.rejects(readFile(h.paths.config), { code: "ENOENT" });
  const good = await readFile(h.paths.rule);
  await writeFile(h.paths.rule, "LEGACY {{recent_turns}}");
  await writeFile(h.paths.config, JSON.stringify({ read: { lifetime_messages: 3 } }));
  await h.session.prompt("must cancel mismatch");
  assert.equal(h.faux.state.callCount, 1);
  assert.match(h.diagnostics.at(-1)!, /RULE_CONFIG_MISMATCH/);
  await writeFile(h.paths.rule, good);
  await writeFile(h.paths.config, JSON.stringify({ context_budget: { model_percent: 61 } }));
  await h.session.prompt("must cancel invalid budget");
  assert.equal(h.faux.state.callCount, 1);
  assert.match(h.diagnostics.at(-1)!, /INVALID_CONFIG/);
});

test("configured metadata timeout reaches the real adapter and blocks inference before a slow models response", async t => {
  let inference = 0;
  const server = createServer((req, res) => {
    if (req.url === "/v1/models") return; // Kept open until timeout; closeAllConnections cleans up.
    inference++; res.writeHead(500); res.end();
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); });
  const h = await taskSession(t, { verifyCapacity: verifyProviderCapacity });
  await writeFile(h.paths.config, JSON.stringify({ model_metadata_timeout_ms: 20 }));
  h.runtime.registerProvider("settings-http", {
    baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`, apiKey: "fixture-only", api: "openai-completions",
    models: [{ id: "slow", name: "slow", input: ["text"], reasoning: false,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 1024 }],
  });
  await h.session.setModel(h.runtime.getModel("settings-http", "slow")!);
  await h.session.prompt("must stop on configured timeout");
  assert.equal(inference, 0);
  assert.match(h.diagnostics.at(-1)!, /MODEL_CAPACITY_UNVERIFIED/);
});

test("editing the file during capacity lookup cannot mix two settings snapshots", async t => {
  let edit = true;
  const h = await taskSession(t, { verifyCapacity: async () => {
    if (edit) {
      edit = false;
      await writeFile(h.paths.config, JSON.stringify({ context_budget: { model_percent: 40 } }));
    }
    return 1000000;
  } });
  await writeFile(h.paths.config, JSON.stringify({ context_budget: { model_percent: 50 } }));
  h.faux.setResponses([fauxAssistantMessage("first snapshot"), fauxAssistantMessage("next snapshot")]);
  await h.session.prompt("capture one immutable input file");
  assert.equal(h.budgets.at(-1)!.limit, 500000);
  await h.session.prompt("read changed file on next logical request");
  assert.equal(h.budgets.at(-1)!.limit, 400000);
  assert.deepEqual(h.diagnostics, []);
});
