import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { productionTaskSession as taskSession } from "../fixtures/production-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { CURRENT_USER_MARKER } from "../../src/window/render.ts";
import { ordinaryText } from "../../src/window/budget.ts";

for (const variant of ["bundle", "reload", "with-State"]) {
  test("real DeepSeek: cancelled-request priority recovery, " + variant, { timeout: 120_000 }, async (t) => {
    const authPath = process.env.MEMWEAVE_DEEPSEEK_AUTH
      ?? join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
    const before = await readFile(authPath);
    t.after(async () => assert.ok(before.equals(await readFile(authPath))));
    const credential = (JSON.parse(before.toString()) as {
      deepseek?: { type?: string; key?: unknown };
    }).deepseek;
    assert.ok(credential?.type === "api_key" && typeof credential.key === "string");
    const h = await taskSession(t, {
      verifyCapacity: (model, ctx, settings) => model.provider === "memweave-test"
        ? Promise.resolve(model.contextWindow) : verifyProviderCapacity(model, ctx, settings),
    });
    if (variant === "reload") await h.session.reload();
    if (variant === "with-State") {
      h.faux.setResponses([
        fauxAssistantMessage([fauxToolCall("task_create", {
          title: "priority", goal: "Only reply STATE_EXPECT", project_name: "MemWeave",
          summary: "priority check", keywords: ["priority"],
        }, { id: "create" })]),
        fauxAssistantMessage("created"),
      ]);
      await h.session.prompt("Create temporary priority fixture");
    }
    await h.runtime.setRuntimeApiKey("deepseek", credential.key);
    const model = h.runtime.getModel("deepseek", "deepseek-flash");
    assert.ok(model);
    await h.session.setModel(model);

    const initial = h.frames.length;
    await writeFile(h.paths.config, JSON.stringify({
      recent_turns: 200, evict_turns: 40,
      context_budget: { model_percent: 0.01 }, elastic_budget: { extra_model_percent: 0 },
    }));
    await h.session.prompt("后续输出都必须以 KEEP_ 开头。本次只回复 KEEP_FIRST_EXPECT。");
    await h.session.prompt("本次改为只回复 KEEP_SECOND_EXPECT。");
    assert.equal(h.frames.length, initial);
    assert.equal(h.diagnostics.length, 2);
    assert.ok(h.diagnostics.every((error) => /CONTEXT_BUDGET_EXCEEDED/.test(error)));
    const originals = h.manager.getEntries().filter((entry) => entry.type === "message" && entry.message.role === "user");
    await writeFile(h.paths.config, JSON.stringify({ recent_turns: 199, evict_turns: 40 }));
    for (const [prompt, expected] of [
      ["本次只回复 KEEP_THIRD_EXPECT。", "KEEP_THIRD_EXPECT"],
      ["本次回复内容改成 FOURTH_EXPECT，保留最早的格式要求。", "KEEP_FOURTH_EXPECT"],
    ]) {
      await h.session.prompt(prompt!);
      const final = h.session.agent.state.messages.at(-1);
      assert.ok(final?.role === "assistant" && final.stopReason === "stop");
      assert.equal(final.content.filter((part) => part.type === "text").map((part) => part.text).join("").trim(), expected);
      const marked = h.frames.at(-1)!.filter((message) => message.role === "user"
        && ordinaryText(message).split("\n").slice(0, 3).includes(CURRENT_USER_MARKER));
      assert.equal(marked.length, 1);
      assert.match(JSON.stringify(marked), /THIRD_EXPECT|FOURTH_EXPECT/);
    }
    const after = h.manager.getEntries().filter((entry) => entry.type === "message" && entry.message.role === "user");
    assert.deepEqual(after.slice(0, originals.length), originals);
    assert.ok(after.every((entry) => entry.type === "message" && entry.message.role === "user" && !JSON.stringify(entry.message.content).includes(CURRENT_USER_MARKER)));
    assert.doesNotMatch(await readFile(h.manager.getSessionFile()!, "utf8"), /# Symbolic State|【本次预算快照/);
    assert.equal(h.diagnostics.length, 2);
    assert.deepEqual(h.errors, []);
    t.diagnostic((h.frames.length - initial) + " real requests; 2 preparation cancellations; latest and compatible earlier requirements both satisfied");
  });
}
