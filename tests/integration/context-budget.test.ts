import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { readFile, writeFile } from "node:fs/promises";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { STATE_REQUEST_TYPE } from "../../src/pi/session-memory.ts";
const create = {
  title: "Budget",
  goal: "Verify bounded cognition",
  project_name: "MemWeave",
  summary: "Budget integration",
  keywords: ["budget"],
};
const call = (name: string, args: Parameters<typeof fauxToolCall>[1]) =>
  fauxAssistantMessage([fauxToolCall(name, args)]);

test("automatic N/B, pre-count token management, atomic rejection, tail snapshot and native State sliding", async (t) => {
  let capacity = 131072;
  const h = await taskSession(t, { verifyCapacity: async () => capacity });
  const { recent_turns: _n, evict_turns: _b, ...automatic } = DEFAULT_CONFIG;
  await writeFile(h.paths.config, JSON.stringify(automatic));
  const items = Array.from({ length: 80 }, () => ({
    type: "fact",
    content: "f".repeat(95),
    evidence: { U1: "source request" },
  }));
  h.faux.setResponses([
    call("task_create", create),
    call("state_append", { items }),
    fauxAssistantMessage("saved"),
  ]);
  await h.session.prompt("Create and save source-backed cognition");
  assert.deepEqual(h.diagnostics, []);
  const task = (await h.tasks.index.read())[0]!,
    state = await h.tasks.state.read(task);
  assert.equal(state.facts.length, 80);
  const frame = h.frames.at(-1)!;
  const tail = frame.at(-1)!;
  assert.ok(tail.role === "custom" && tail.customType === "memweave.state");
  assert.match(String(tail.content), /State 窗口管理/);
  assert.match(String(tail.content), /本次预算快照/);
  assert.match(String(tail.content), /N\/B：50\/10/);
  assert.equal(
    h.budgets.at(-1)!.S >= Math.floor(h.budgets.at(-1)!.plan.state * 0.8),
    true,
  );
  const batch = h.manager
    .getBranch()
    .findLast(
      (e) => e.type === "custom" && e.customType === STATE_REQUEST_TYPE,
    );
  assert.ok(batch?.type === "custom");
  assert.equal(
    (batch.data as { candidate_ids: string[] }).candidate_ids.length,
    80,
  );
  const bytes = await readFile(h.paths.state(task));
  h.faux.setResponses([
    call("state_append", { items }),
    fauxAssistantMessage("rejected"),
  ]);
  await h.session.prompt("Attempt growth beyond State allocation");
  assert.ok(bytes.equals(await readFile(h.paths.state(task))));
  const result = h.manager
    .getBranch()
    .findLast((e) => e.type === "message" && e.message.role === "toolResult");
  assert.ok(
    result?.type === "message" &&
      result.message.role === "toolResult" &&
      result.message.isError,
  );
  assert.match(JSON.stringify(result.message.content), /STATE_BUDGET_EXCEEDED/);
  h.faux.setResponses([
    call("state_remain", { event_ids: [] }),
    fauxAssistantMessage("organized"),
  ]);
  await h.session.prompt("Organize the shown State batch");
  assert.equal((await h.tasks.state.read(task)).facts.length, 0);
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  capacity = 262144;
  h.faux.setResponses([fauxAssistantMessage("larger")]);
  await h.session.prompt("Recompute only automatic N/B");
  assert.match(JSON.stringify(h.frames.at(-1)!.at(-1)), /N\/B：110\/22/);
  h.faux.setResponses([
    call("recent_window_set", { turns: 8, evict_turns: 2 }),
    fauxAssistantMessage("explicit"),
  ]);
  await h.session.prompt("Set explicit Window override");
  capacity = 1048576;
  h.faux.setResponses([fauxAssistantMessage("preserved")]);
  await h.session.prompt("Preserve explicit override after capacity changes");
  assert.match(JSON.stringify(h.frames.at(-1)!.at(-1)), /N\/B：8\/2/);
  assert.doesNotMatch(
    await readFile(h.manager.getSessionFile()!, "utf8"),
    /【本次预算快照|【State 窗口管理/,
  );
});

test("production HTTP output cap matches reserved O across retries, explicit overrides and invalid payload cancellation", async (t) => {
  const h = await taskSession(t, { verifyCapacity: verifyProviderCapacity });
  const bodies: Record<string, unknown>[] = [];
  let retry = true;
  const server = createServer(async (req, res) => {
    if (req.url === "/v1/models") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(
        JSON.stringify({
          data: [
            {
              id: "budget-model",
              context_window: 1048576,
              max_output_tokens: 100000,
            },
          ],
        }),
      );
      return;
    }
    let text = "";
    for await (const part of req) text += String(part);
    bodies.push(JSON.parse(text));
    if (retry) {
      retry = false;
      // The retry must keep the old frame even if the global file changes meanwhile.
      await writeFile(h.paths.config, JSON.stringify({ context_budget: {
        model_percent: 50, parts_percent: { output: 5, window: 42.5 },
      } }));
      res.writeHead(503, {
        "content-type": "application/json",
        "retry-after": "0",
      });
      res.end(JSON.stringify({ error: { message: "temporary fixture" } }));
      return;
    }
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.write(
      `data: ${JSON.stringify({ id: "budget", choices: [{ index: 0, delta: { role: "assistant", content: "OK" }, finish_reason: null }] })}\n\n`,
    );
    res.write(
      `data: ${JSON.stringify({ id: "budget", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`,
    );
    res.end("data: [DONE]\n\n");
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise<void>((r) => server.close(() => r()));
  });
  h.runtime.registerProvider("budget-http", {
    baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`,
    apiKey: "fixture-only",
    api: "openai-completions",
    models: [
      {
        id: "budget-model",
        name: "budget",
        input: ["text"],
        reasoning: false,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 1000000,
        maxTokens: 384000,
      },
    ],
  });
  const model = h.runtime.getModel("budget-http", "budget-model")!;
  await h.session.setModel(model);
  h.settings.applyOverrides({
    retry: { enabled: false, provider: { maxRetries: 1 } },
  });
  await h.session.prompt("Verify actual default output");
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  assert.equal(bodies.length, 2);
  assert.deepEqual(bodies[0], bodies[1]);
  assert.equal(
    bodies[0]!.max_tokens ?? bodies[0]!.max_completion_tokens,
    62914,
  );
  assert.equal(h.budgets.length, 1);
  assert.equal(h.budgets[0]!.O, 62914);
  assert.match(JSON.stringify(bodies[0]!.messages), /本次预算快照/);
  await h.session.prompt("Use changed policies only on the next logical request");
  assert.equal(h.budgets.at(-1)!.limit, 524288);
  assert.equal(h.budgets.at(-1)!.O, 26214);
  assert.equal(bodies.at(-1)!.max_tokens ?? bodies.at(-1)!.max_completion_tokens, 26214);
  assert.match(JSON.stringify(bodies.at(-1)!.messages), /的 50%/);
  await h.session.setModel({
    ...model,
    samplingParams: { max_completion_tokens: 90000 },
  });
  await h.session.prompt("Verify explicit output");
  assert.equal(
    bodies.at(-1)!.max_tokens ?? bodies.at(-1)!.max_completion_tokens,
    90000,
  );
  assert.equal(h.budgets.at(-1)!.O, 90000);
  const count = bodies.length;
  await h.session.setModel({
    ...model,
    samplingParams: { max_tokens: 1000, max_completion_tokens: 2000 },
  });
  await h.session.prompt("Cancel ambiguous actual output fields");
  assert.equal(bodies.length, count);
  assert.match(h.diagnostics.at(-1) ?? "", /OUTPUT_BUDGET_UNVERIFIED/);
});
