import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { productionNativeSession as nativeSession, assertProductionPayload } from "./production-session.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import type { Task } from "../../src/task/model.ts";
import type { ReleaseCase, ReleaseResult } from "./release.ts";
test(
  "product Runtime in an independent Pi process",
  { timeout: 80_000 },
  async (t) => {
    const input = JSON.parse(
      process.env.MEMWEAVE_RELEASE_CASE ?? "null",
    ) as ReleaseCase;
    assert.ok(input && input.artifact && input.memory);
    const paths = memoryPaths(input.memory),
      entry = join(input.root, `entry-${input.label}.ts`);
    // Execute installed product code with isolated memoryRoot and Pi setup profile paths.
    // Capacity, request lifecycle, SDK loop and provider paths are production implementations.
    const startup = (await readFile(join(input.artifact, "src/extension/index.ts"), "utf8")).includes("registerLauncher")
      ? { module: "launcher.ts", factory: "registerLauncher" }
      : { module: "register.ts", factory: "registerMemweave" };
    await writeFile(
      entry,
      `import {${startup.factory}} from ${JSON.stringify(join(input.artifact, "src/extension", startup.module))};\nimport {memoryPaths} from ${JSON.stringify(join(input.artifact, "src/storage/paths.ts"))};\nexport default pi=>${startup.factory}(pi,{paths:memoryPaths(${JSON.stringify(input.memory)}),setupAgentDir:${JSON.stringify(join(input.root, "setup-agent"))}});\n`,
    );
    const manager = input.sessionFile
      ? SessionManager.open(input.sessionFile)
      : SessionManager.create(input.cwd, input.sessionDir);
    const h = await nativeSession(t, [pi => {
      if (input.action === "live") pi.on("before_provider_request", (event, ctx) => {
        try { assertProductionPayload(event.payload, true); }
        catch (error) { ctx.abort(); throw error; }
      });
    }], false, 512, [entry], manager);
    const call = (name: string, args: unknown) => ({ name, args });
    const fact = (content: string) => ({
      items: [
        { type: "fact", content, evidence: { U1: "source user request" } },
      ],
    });
    const steps =
      input.action === "create"
        ? [
            call("task_create", {
              title: "Release recovery",
              goal: "Verify persisted recovery",
              project_name: "MemWeave",
              summary: "Release upgrade test",
              keywords: ["release"],
            }),
            call(
              "state_append",
              fact("Source user requested release recovery verification"),
            ),
          ]
        : input.action === "concurrent"
          ? [
              call("task_resume", { task_id: input.taskId }),
              call("recent_window_set", { turns: input.turns, evict_turns: 2 }),
              call(
                "state_append",
                fact(`${input.label} concurrent observation`),
              ),
            ]
          : [
              call("recent_window_set", { turns: 4, evict_turns: 2 }),
              call("memory_read", {
                items: [{ ref: "U1", offset: 0, limit: 24 }],
              }),
              call(
                "state_append",
                fact(`${input.label} recovered the original user request`),
              ),
            ];
    const frames: unknown[] = [];
    let requests = 0;
    const server = createServer(async (request, response) => {
      if (request.method === "GET") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(
          JSON.stringify({
            data: [{ id: "release", context_window: 1_048_576 }],
          }),
        );
        return;
      }
      let bytes = "";
      for await (const chunk of request) bytes += String(chunk);
      frames.push(JSON.parse(bytes));
      const step = steps[requests++];
      const delta = step
        ? {
            role: "assistant",
            tool_calls: [
              {
                index: 0,
                id: `${input.label}-${requests}`,
                type: "function",
                function: {
                  name: step.name,
                  arguments: JSON.stringify(step.args),
                },
              },
            ],
          }
        : { role: "assistant", content: "Release verification complete" };
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.write(
        `data: ${JSON.stringify({ id: "release", choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`,
      );
      response.write(
        `data: ${JSON.stringify({ id: "release", choices: [{ index: 0, delta: {}, finish_reason: step ? "tool_calls" : "stop" }] })}\n\n`,
      );
      response.end("data: [DONE]\n\n");
    });
    await new Promise<void>((resolve) =>
      server.listen(0, "127.0.0.1", resolve),
    );
    t.after(async () => {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
    });
    h.runtime.registerProvider("release-http", {
      baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`,
      apiKey: "local-test-only",
      api: "openai-completions",
      models: [
        {
          id: "release",
          name: "release",
          input: ["text"],
          reasoning: false,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 1_000_000,
          maxTokens: 1024,
        },
      ],
    });
    const model = h.runtime.getModel("release-http", "release");
    assert.ok(model);
    await h.session.setModel(model);
    let before: Buffer | undefined;
    if (input.action === "live") {
      assert.ok(input.authPath);
      before = await readFile(input.authPath);
      t.after(async () =>
        assert.ok(before!.equals(await readFile(input.authPath!))),
      );
      const auth = (
        JSON.parse(before.toString()) as {
          deepseek?: { type: string; key: unknown };
        }
      ).deepseek;
      assert.ok(auth?.type === "api_key" && typeof auth.key === "string");
      await h.runtime.setRuntimeApiKey("deepseek", auth.key);
      const actual = h.runtime.getModel("deepseek", "deepseek-flash");
      assert.ok(actual);
      await h.session.setModel(actual);
      h.session.subscribe((event) => {
        if (
          event.type === "message_end" &&
          event.message.role === "assistant" &&
          event.message.provider === "deepseek"
        )
          requests++;
      });
    }
    const releaseGate = `GATE_${input.label}`;
    const prompt =
      input.action === "live"
        ? `New release requirement: approval requires ${releaseGate}. Read U1 using memory_read with offset=0, limit=24. After a successful read, append exactly one FACT under 60 characters recording this NEW requirement, include ${releaseGate}, and use the current user message as evidence. Existing F1 already records the original recovery request; do not duplicate it. Do not change the Task or settings or repeat successful calls. Then acknowledge briefly.`
        : input.action === "create"
          ? "Source user requested release recovery verification; retain this original."
          : `${input.label} continue persisted work`;
    const outcomes: string[] = [];
    h.session.subscribe((event) => {
      if (event.type === "message_end" && event.message.role === "assistant")
        outcomes.push(event.message.stopReason);
    });
    await h.session.prompt(prompt);
    assert.deepEqual(h.errors, []);
    const index = JSON.parse(await readFile(paths.index, "utf8")) as Task[];
    const task = index.find((t) => !input.taskId || t.task_id === input.taskId);
    assert.ok(task);
    const state = await readFile(paths.state(task), "utf8"),
      version = state.trimEnd().split("\n").length;
    if (input.action === "live") {
      const last = JSON.parse(state.trimEnd().split("\n").at(-1)!);
      assert.equal(last.op, "append_fact");
      assert.ok(last.fact.includes(releaseGate));
      const branch = manager.getBranch();
      const user = branch.findLast(e => e.type === "message" && e.message.role === "user");
      const ref = branch.flatMap(e => e.type === "custom" && e.customType === "memweave.references.v1"
        ? (e.data as {task_id:string;bindings:{ref:string;entry_id:string}[]}).task_id === task.task_id
          ? (e.data as {bindings:{ref:string;entry_id:string}[]}).bindings : [] : [])
        .find(b => b.entry_id === user?.id)?.ref;
      assert.ok(ref && Object.hasOwn(last.evidence, ref), "new requirement must cite the current user");
    }
    const results = manager
      .getBranch()
      .filter((e) => e.type === "message" && e.message.role === "toolResult");
    if (input.action !== "blocked") {
      assert.ok(requests > 0 && requests <= 6);
      // Historical failed requests must survive recovery; check only this run.
      assert.ok(!outcomes.includes("error"));
      assert.ok(!outcomes.includes("aborted"));
      assert.equal(outcomes.at(-1), "stop");
      assert.equal(h.session.messages.at(-1)?.role, "assistant");
      for (const entry of results)
        if (entry.type === "message" && entry.message.role === "toolResult")
          assert.equal(entry.message.isError, false);
      if (input.action === "recover" || input.action === "live") {
        const result = results.findLast(
          (e) =>
            e.type === "message" &&
            e.message.role === "toolResult" &&
            e.message.toolName === "memory_read",
        );
        assert.ok(
          result?.type === "message" && result.message.role === "toolResult",
        );
        const content = result.message.content[0];
        assert.ok(content?.type === "text");
        assert.equal(
          JSON.parse(content.text).items[0].content,
          "Source user requested re",
        );
      }
      assert.doesNotMatch(
        await readFile(manager.getSessionFile()!, "utf8"),
        /# Symbolic State|Recent Window 移出提醒/,
      );
      if (input.action !== "live")
        assert.ok(
          frames.some((frame) =>
            JSON.stringify(frame).includes("# Symbolic State"),
          ),
        );
    } else assert.equal(requests, 0);
    const branch = manager.getBranch();
    const scope = branch.findLast(
      (e) => e.type === "custom" && e.customType === "memweave.scope.v1",
    );
    const value: ReleaseResult = {
      taskId: task.task_id,
      version,
      sessionFile: manager.getSessionFile()!,
      requests,
      toolNames: results.flatMap((e) =>
        e.type === "message" && e.message.role === "toolResult"
          ? [e.message.toolName]
          : [],
      ),
      window: branch.some(
        (e) => e.type === "custom" && e.customType === "memweave.window.v1",
      ),
      settings:
        scope?.type === "custom"
          ? ((scope.data as { overrides: { recent_turns?: number } }).overrides
              .recent_turns ?? null)
          : null,
    };
    t.diagnostic(`MEMWEAVE_RESULT ${JSON.stringify(value)}`);
  },
);
