import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { windowMetadata } from "../../src/pi/window-service.ts";
test(
  "real DeepSeek changes the Window, reads an evicted original, saves cognition and observes transient reminders",
  { timeout: 90000 },
  async (t) => {
    const file =
      process.env.MEMWEAVE_DEEPSEEK_AUTH ??
      join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
    const original = await readFile(file);
    t.after(async () => assert.ok(original.equals(await readFile(file))));
    const credential = (
      JSON.parse(original.toString()) as {
        deepseek?: { type: string; key: unknown };
      }
    ).deepseek;
    assert.ok(
      credential?.type === "api_key" && typeof credential.key === "string",
    );
    const wireOutputs: number[] = [];
    const h = await taskSession(t, {
      extra: (pi) =>
        pi.on("before_provider_request", (event) => {
          const payload = event.payload as {
            model?: string;
            max_tokens?: unknown;
            max_completion_tokens?: unknown;
          };
          if (payload.model !== "deepseek-flash") return;
          const value = payload.max_tokens ?? payload.max_completion_tokens;
          assert.ok(
            typeof value === "number" &&
              Number.isSafeInteger(value) &&
              value > 0,
          );
          wireOutputs.push(value);
        }),
      verifyCapacity: (model, ctx) =>
        model.provider === "deepseek"
          ? verifyProviderCapacity(model, ctx)
          : Promise.resolve(model.contextWindow),
    });
    await writeFile(
      h.paths.config,
      JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 6, evict_turns: 2 }),
    );
    const nonce = randomBytes(8).toString("hex");
    h.faux.setResponses([
      fauxAssistantMessage([
        fauxToolCall("task_create", {
          title: "Window live",
          goal: "Verify original recovery",
          project_name: "MemWeave",
          summary: "Window recovery verification",
          keywords: ["window"],
        }),
      ]),
      fauxAssistantMessage("created"),
    ]);
    await h.session.prompt(
      `${nonce} Source user requests testing recovery from a bounded window.`,
    );
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);
    h.session.setActiveToolsByName([
      "recent_window_set",
      "memory_read",
      "state_append",
    ]);
    const start = h.frames.length;
    await h.session.prompt(
      'Integration test. First call recent_window_set exactly once with turns=4, evict_turns=2. After its success, call memory_read exactly once with items=[{"ref":"U1","offset":0,"limit":16}]. After reading the actual result, call state_append exactly once with one fact, under 60 characters, that the original user requested bounded-window recovery verification; evidence U1 must explain that user request. Use separate successive tool rounds. Do not guess additional IDs, repeat successful operations or change any other settings. Then finish with a brief acknowledgement.',
    );
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    const task = (await h.tasks.index.read())[0]!,
      state = await h.tasks.state.read(task);
    assert.equal(state.facts.length, 1);
    assert.ok(state.facts[0]!.evidence.U1);
    const read = h.manager
      .getBranch()
      .findLast(
        (e) =>
          e.type === "message" &&
          e.message.role === "toolResult" &&
          e.message.toolName === "memory_read",
      );
    assert.ok(
      read?.type === "message" &&
        read.message.role === "toolResult" &&
        !read.message.isError,
    );
    const part = read.message.content[0];
    assert.ok(part?.type === "text");
    assert.equal(JSON.parse(part.text).items[0].content, nonce);
    assert.equal(
      h.tasks.scope(h.session.extensionRunner!.createContext()).overrides
        .recent_turns,
      4,
    );
    assert.ok(
      h.frames
        .slice(start)
        .some((frame) =>
          JSON.stringify(frame).includes("Recent Window 移出提醒"),
        ),
    );
    assert.ok(h.budgets.slice(start).some((b) => b.X > 0));
    for (const b of h.budgets.slice(start)) {
      assert.equal(b.limit, 524288);
      assert.ok(b.total <= b.limit);
    }
    assert.ok(wireOutputs.length >= h.frames.length - start);
    assert.ok(wireOutputs.every((value) => value <= h.budgets[start]!.O));
    for (const entry of h.manager.getBranch())
      if (
        entry.type === "message" &&
        entry.message.role === "assistant" &&
        entry.message.provider === "deepseek"
      ) {
        const usage = entry.message.usage;
        assert.ok(usage.totalTokens > 0);
        assert.ok(
          usage.totalTokens - usage.output + h.budgets[start]!.O <= 524288,
        );
      }
    assert.ok(windowMetadata(h.manager.getBranch())!.boundary_entry_id);
    assert.doesNotMatch(
      await readFile(h.manager.getSessionFile()!, "utf8"),
      /Recent Window 移出提醒|# Symbolic State/,
    );
    t.diagnostic(
      `${h.frames.length - start} real DeepSeek inference requests; 2 Faux setup requests; half-context 524288, bounded read lifetime X, persisted State and Window boundaries verified`,
    );
  },
);
