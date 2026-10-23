import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import test from "node:test";
import { fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { SourceVerifier } from "../../src/pi/source-verification.ts";
import { registerRequestLifecycle } from "../../src/pi/request-lifecycle.ts";

test("production warm cache still rejects rewritten old input outside the selected Window before inference", async (t) => {
  let rewrite = false;
  const h = await taskSession(t, {
    extra: (pi) =>
      pi.on("context", (event) => {
        if (!rewrite) return;
        const message = event.messages.find((m) => m.role === "user");
        if (message?.role === "user") message.content = "UNTRUSTED_REWRITE";
      }),
  });
  h.faux.setResponses([fauxAssistantMessage("initial")]);
  await h.session.prompt("ORIGINAL_OLD_SOURCE");
  await writeFile(
    h.paths.config,
    JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 1, evict_turns: 1 }),
  );
  h.faux.setResponses([fauxAssistantMessage("warm")]);
  await h.session.prompt("new source outside old history");
  assert.deepEqual(h.diagnostics, []);
  assert.doesNotMatch(JSON.stringify(h.frames.at(-1)), /ORIGINAL_OLD_SOURCE/);
  const originals = structuredClone(
    h.manager.getBranch().filter((e) => e.type === "message"),
  );
  const calls = h.faux.state.callCount;
  rewrite = true;
  await h.session.prompt("must reject old rewrite");
  assert.equal(h.faux.state.callCount, calls);
  assert.match(h.diagnostics.at(-1) ?? "", /UNSUPPORTED_WINDOW_CONTEXT/);
  assert.deepEqual(
    h.manager
      .getBranch()
      .filter((e) => e.type === "message")
      .slice(0, originals.length),
    originals,
  );
  assert.doesNotMatch(
    await readFile(h.manager.getSessionFile()!, "utf8"),
    /UNTRUSTED_REWRITE/,
  );
});

test("native context_edit is verified through current Pi projection while original records remain untouched", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([fauxAssistantMessage("first")]);
  await h.session.prompt("ORIGINAL_CONTENT");
  const original = h.manager
    .getBranch()
    .find((e) => e.type === "message" && e.message.role === "user")!;
  const saved = structuredClone(original);
  h.manager.appendContextEdit(original.id, { content: "NATIVE_EDITED_VIEW" });
  h.session.refreshContext();
  h.faux.setResponses([fauxAssistantMessage("second")]);
  await h.session.prompt("continue after native edit");
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  assert.equal(h.faux.state.callCount, 2);
  assert.deepEqual(h.manager.getEntry(original.id), saved);
  assert.ok(
    h.manager
      .getBranch()
      .some((e) => e.type === "context_edit" && e.targetId === original.id),
  );
  assert.match(JSON.stringify(h.frames.at(-1)), /ORIGINAL_CONTENT/);
});

test("Pi reload invokes the existing session-start cache reset without duplicate handlers", async (t) => {
  const cache = new SourceVerifier();
  let resets = 0;
  const h = await nativeSession(t, [
    (pi) => {
      registerRequestLifecycle(pi, {
        reset: () => {
          resets++;
          cache.reset();
        },
        prepare: async (messages, ctx) => {
          const result = cache.match(
            messages,
            ctx.sessionManager.getBranch(),
            ctx.sessionManager.getSessionId(),
            () => ctx.sessionManager.buildSessionProjection(),
          );
          assert.ok(result.matched.every(Boolean));
          return messages;
        },
        report: (error) => {
          throw error;
        },
      });
    },
  ]);
  await h.session.prompt("cache native user");
  assert.ok(cache.stats.entries > 0);
  const before = resets;
  await h.session.reload();
  assert.ok(resets > before);
  assert.equal(cache.stats.entries, 0);
  h.faux.setResponses([fauxAssistantMessage("after reload")]);
  await h.session.prompt("rebuild source cache");
  assert.ok(cache.stats.entries > 0);
  for (const extension of h.loader.getExtensions().extensions)
    for (const handlers of extension.handlers.values())
      assert.equal(handlers.length, 1);
  assert.deepEqual(h.errors, []);
});
