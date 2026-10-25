import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { productionTaskSession as taskSession } from "../fixtures/production-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";

test(
  "real DeepSeek reads exact Unicode ranges across Tasks and persists R-backed cognition",
  { timeout: 60_000 },
  async (t) => {
    const authPath =
      process.env.MEMWEAVE_DEEPSEEK_AUTH ??
      join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
    const original = await readFile(authPath);
    t.after(async () => assert.ok(original.equals(await readFile(authPath))));
    const credential = (
      JSON.parse(original.toString()) as {
        deepseek?: { type?: string; key?: unknown };
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
    const create = {
      title: "Source",
      goal: "Verify read ranges",
      project_name: "MemWeave",
      summary: "Read verification",
      keywords: ["read"],
    };
    for (const title of ["Source", "Consumer"]) {
      h.faux.setResponses([
        fauxAssistantMessage([
          fauxToolCall("task_create", { ...create, title }),
        ]),
        fauxAssistantMessage("created"),
      ]);
      await h.session.prompt(
        title === "Source" ? "source 😀 original" : "new consumer",
      );
    }
    const tasks = await h.tasks.index.read(),
      source = tasks.find((task) => task.title === "Source")!,
      consumer = tasks.find((task) => task.title === "Consumer")!;
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);
    const framesBefore = h.frames.length;

    await h.session.prompt(
      `Integration test: call memory_read exactly once with items=[{"ref":"U1","task_id":"${source.task_id}","offset":7,"limit":1},{"ref":"U999"},{"ref":"U1","task_id":"${source.task_id}","offset":0,"limit":6}], max_total_chars=7. Then use its returned R alias as evidence in one state_append fact stating that the source user requested original text verification. Do not guess new IDs, do not repeat successful calls. Finish with a brief acknowledgement after both tools succeed.`,
    );
    const read = h.manager
      .getEntries()
      .findLast(
        (entry) =>
          entry.type === "message" &&
          entry.message.role === "toolResult" &&
          entry.message.toolName === "memory_read",
      );
    assert.ok(
      read?.type === "message" &&
        read.message.role === "toolResult" &&
        !read.message.isError,
    );
    const body = read.message.content[0];
    assert.ok(body?.type === "text");
    const result = JSON.parse(body.text);
    assert.equal(result.items[0].content, "😀");
    assert.equal(result.items[0].resolved_ref, "R1");
    assert.equal(result.items[1].status, "not_found");
    assert.equal(result.items[2].content, "source");
    assert.equal(result.total_chars, 7);
    const state = await h.tasks.state.read(consumer);
    assert.equal(state.version, 2);
    assert.ok(state.facts[0]?.evidence.R1);
    assert.equal(
      h.tasks.scope(h.session.extensionRunner!.createContext()).task_id,
      consumer.task_id,
    );
    assert.deepEqual(h.errors, []);
    assert.deepEqual(h.diagnostics, []);
    assert.equal(h.session.agent.state.messages.at(-1)?.role, "assistant");
    t.diagnostic(
      `${h.frames.length - framesBefore} real DeepSeek inference requests; 4 Faux setup requests, no real visual-model verification`,
    );
  },
);
