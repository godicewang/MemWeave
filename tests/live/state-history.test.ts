import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
test(
  "real DeepSeek traces evicted and archived F/D using bounded state_read without changing cognition",
  { timeout: 90000 },
  async (t) => {
    const file =
      process.env.MEMWEAVE_DEEPSEEK_AUTH ??
      join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
    const credentialBefore = await readFile(file);
    t.after(async () =>
      assert.ok(credentialBefore.equals(await readFile(file))),
    );
    const credential = (
      JSON.parse(credentialBefore.toString()) as {
        deepseek?: { type: string; key: unknown };
      }
    ).deepseek;
    assert.ok(
      credential?.type === "api_key" && typeof credential.key === "string",
    );
    const h = await taskSession(t, {
      verifyCapacity: (model, ctx) =>
        model.provider === "deepseek"
          ? verifyProviderCapacity(model, ctx)
          : Promise.resolve(model.contextWindow),
    });
    await writeFile(
      h.paths.config,
      JSON.stringify({
        ...DEFAULT_CONFIG,
        state_max_events: 2,
        state_evict_batch: 1,
      }),
    );
    h.faux.setResponses([
      fauxAssistantMessage([
        fauxToolCall("task_create", {
          title: "History live",
          goal: "Verify historical cognition reads",
          project_name: "MemWeave",
          summary: "History read validation",
          keywords: ["history"],
        }),
      ]),
      fauxAssistantMessage([
        fauxToolCall("state_append", {
          items: [
            {
              type: "fact",
              content: "The source user requested recovery verification",
              evidence: { U1: "actual source request" },
            },
            {
              type: "decision",
              content: "Inspect the persisted source before continuing",
              evidence: { U1: "actual source request" },
            },
          ],
        }),
      ]),
      fauxAssistantMessage([fauxToolCall("state_remain", { event_ids: [] })]),
      fauxAssistantMessage([
        fauxToolCall("modify_fact", {
          archive: ["D1"],
          append_fact: {
            content: "Historical evidence is available for explicit checking",
            evidence: { D1: "previous decision remains traceable" },
          },
        }),
      ]),
      fauxAssistantMessage("Historical fixtures prepared"),
    ]);
    await h.session.prompt(
      "The source user requests verifying that persisted cognition can be recovered and traced.",
    );
    const task = (await h.tasks.index.read())[0]!,
      stateBefore = await readFile(h.paths.state(task));
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);
    assert.equal(h.session.getActiveToolNames().length, 11);
    const start = h.frames.length;
    await h.session.prompt(
      `Call state_read exactly once with task_id="${task.task_id}", event_ids=["F1","D1","F999"], max_total_chars=8000. Inspect the actual returned content, evidence and states, then briefly acknowledge which finding left the window and which decision was archived. Do not repeat a successful call or modify anything.`,
    );
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    const failed = h.session.messages.flatMap((message) =>
      message.role === "assistant" &&
      message.provider === "deepseek" &&
      message.stopReason === "error"
        ? [message.errorMessage?.replace(/sk-[A-Za-z0-9]+/g, "[redacted]")]
        : [],
    );
    assert.deepEqual(failed, []);
    const result = h.manager
      .getBranch()
      .findLast(
        (e) =>
          e.type === "message" &&
          e.message.role === "toolResult" &&
          e.message.toolName === "state_read",
      );
    assert.ok(
      result?.type === "message" &&
        result.message.role === "toolResult" &&
        !result.message.isError,
    );
    const content = result.message.content[0];
    assert.ok(content?.type === "text");
    const body = JSON.parse(content.text);
    assert.equal(body.items[0].in_window, false);
    assert.equal(body.items[0].archived, false);
    assert.equal(
      body.items[0].content,
      "The source user requested recovery verification",
    );
    assert.deepEqual(body.items[0].evidence, { U1: "actual source request" });
    assert.equal(body.items[1].archived, true);
    assert.equal(body.items[2].status, "not_found");
    assert.ok(h.budgets.at(-1)!.X > 0);
    assert.ok(stateBefore.equals(await readFile(h.paths.state(task))));
    assert.equal(
      h.tasks.scope(h.session.extensionRunner!.createContext()).task_id,
      task.task_id,
    );
    const messages = h.session.messages.filter(
      (m) => m.role === "assistant" && m.provider === "deepseek",
    );
    for (const message of messages)
      if (message.role === "assistant") {
        assert.notEqual(message.stopReason, "error");
        assert.notEqual(message.stopReason, "aborted");
      }
    const requests = h.frames.length - start;
    assert.ok(requests >= 2 && requests <= 4);
    t.diagnostic(
      `${requests} real DeepSeek requests; 5 Faux setup requests; historical body/evidence, status, X and unchanged State verified`,
    );
  },
);
