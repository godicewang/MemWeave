import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import test from "node:test";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
for (const appendFirst of [false, true])
  test(`native parallel State remain/append and Window settings commit independently (appendFirst=${appendFirst})`, async (t) => {
    const h = await taskSession(t);
    await writeFile(
      h.paths.config,
      JSON.stringify({
        ...DEFAULT_CONFIG,
        recent_turns: 2,
        evict_turns: 1,
        state_max_events: 10,
        state_evict_batch: 2,
      }),
    );
    const change = fauxToolCall(
      "recent_window_set",
      { turns: 4, evict_turns: 2 },
      { id: "window" },
    );
    const remain = fauxToolCall(
      "state_remain",
      { event_ids: [] },
      { id: "remain" },
    );
    const append = fauxToolCall(
      "state_append",
      {
        items: [
          { type: "fact", content: "new cognition", evidence: { U1: "user" } },
        ],
      },
      { id: "append" },
    );
    h.faux.setResponses([
      fauxAssistantMessage([
        fauxToolCall("task_create", {
          title: "Combined windows",
          goal: "Verify independent windows",
          project_name: "MemWeave",
          summary: "Combined verification",
          keywords: ["windows"],
        }),
      ]),
      fauxAssistantMessage([
        fauxToolCall(
          "state_append",
          {
            items: Array.from({ length: 10 }, (_, i) => ({
              type: "fact",
              content: `fact ${i}`,
              evidence: { U1: "user" },
            })),
          },
          { id: "fill" },
        ),
      ]),
      fauxAssistantMessage(
        appendFirst ? [change, append, remain] : [remain, change, append],
      ),
      fauxAssistantMessage("done"),
    ]);
    await h.session.prompt("Handle independent window commits");
    assert.deepEqual(h.diagnostics, []);
    assert.deepEqual(h.errors, []);
    assert.ok(
      h.frames.some(
        (frame) =>
          JSON.stringify(frame).includes("State 窗口管理") &&
          JSON.stringify(frame).includes("Recent Window 移出提醒"),
      ),
    );
    const task = (await h.tasks.index.read())[0]!,
      state = await h.tasks.state.read(task);
    assert.equal(state.facts.length, 9);
    assert.equal(state.events.filter((e) => e.op === "slide_window").length, 1);
    assert.equal(state.facts.at(-1)?.content, "new cognition");
    const commits = h.manager
      .getBranch()
      .filter(
        (e) =>
          e.type === "custom" &&
          e.customType === "memweave.window.v1" &&
          (e.data as { stage: string }).stage === "commit",
      );
    assert.equal(commits.length, 1);
    assert.equal(
      h.tasks.scope(h.session.extensionRunner!.createContext()).overrides
        .recent_turns,
      4,
    );
    assert.doesNotMatch(
      await readFile(h.manager.getSessionFile()!, "utf8"),
      /State 窗口管理|Recent Window 移出提醒/,
    );
  });
