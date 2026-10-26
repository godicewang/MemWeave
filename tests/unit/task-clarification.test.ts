import test from "node:test";
import assert from "node:assert/strict";
import { Check } from "typebox/value";
import type { ExtensionAPI, ExtensionToolContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { registerTaskClarification } from "../../src/extension/clarify.ts";
import { ClarifySchema } from "../../src/task/model.ts";

function fixture(input: () => Promise<string | undefined>, signal?: AbortSignal) {
  let definition!: ToolDefinition<typeof ClarifySchema>;
  const queued: { content: unknown; options: unknown }[] = [];
  const pi = {
    registerTool(tool: ToolDefinition<typeof ClarifySchema>) { definition = tool; },
    sendUserMessage(content: unknown, options: unknown) { queued.push({ content, options }); },
  } as unknown as ExtensionAPI;
  registerTaskClarification(pi);
  const ctx = { hasUI: true, ui: { input }, signal } as unknown as ExtensionToolContext;
  return { definition, queued, ctx };
}

test("clarification queues only actual UI text as a new native user input and terminates the old request", async () => {
  const h = fixture(async () => " 退款超时那个 ");
  const result = await h.definition.execute("ask", { question: "恢复哪一个支付任务？" }, undefined, undefined, h.ctx);
  assert.equal(result.terminate, true);
  assert.deepEqual(h.queued, [{ content: " 退款超时那个 ", options: { deliverAs: "followUp", expandPromptTemplates: false } }]);
  assert.deepEqual(result.details, { status: "input_queued", question: "恢复哪一个支付任务？" });
});

test("cancelling or blank clarification never invents an answer; headless mode does not open a dialog", async () => {
  for (const text of [undefined, "", "   "]) {
    const h = fixture(async () => text);
    const result = await h.definition.execute("ask", { question: "哪一个？" }, undefined, undefined, h.ctx);
    assert.equal(result.terminate, true);
    assert.equal(h.queued.length, 0);
    assert.deepEqual(result.details, { status: "waiting_for_user", question: "哪一个？" });
  }
  const h = fixture(async () => { throw Error("headless must not call input"); });
  h.ctx.hasUI = false;
  assert.equal((await h.definition.execute("ask", { question: "哪一个？" }, undefined, undefined, h.ctx)).terminate, true);
  assert.equal(h.queued.length, 0);
});

test("an aborted UI response is never sent to a replacement turn", async () => {
  const controller = new AbortController();
  const h = fixture(async () => { controller.abort(); return "ignore this late response"; }, controller.signal);
  await assert.rejects(h.definition.execute("ask", { question: "哪一个？" }, controller.signal, undefined, h.ctx), /abort/i);
  assert.equal(h.queued.length, 0);
});

test("clarification schema requires only a meaningful question and rejects hidden initialization fields", () => {
  assert.ok(Check(ClarifySchema, { question: "请选择任务" }));
  for (const value of [{}, { question: "  " }, { question: "请选择", initialize: true }]) assert.equal(Check(ClarifySchema, value), false);
});
