import test from "node:test";
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { Type } from "typebox";
import {
  fauxAssistantMessage as answer,
  fauxToolCall as call,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import {
  BINDING_TYPE,
  bindingReceipts,
  withoutBindingMessages,
} from "../../src/task/binding.ts";
import { scopeOf } from "../../src/pi/session-memory.ts";
import { indexEvents } from "../../src/window/select.ts";
const create = {
  title: "Orders",
  goal: "校验订单批次",
  project_name: "P",
  summary: "batch verification",
  keywords: ["orders"],
};
test("native boundary rejects unbound initialized delivery once, then continues through actual Task creation", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    answer([call("task_find", { query: "orders", initialize: true })]),
    answer("premature delivery"),
    answer([call("task_create", create)]),
    answer("bound delivery"),
  ]);
  await h.session.prompt("开始订单批次校验");
  assert.ok(scopeOf(h.manager.getBranch()).task_id);
  const receipts = bindingReceipts(h.manager.getBranch());
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0]!.details.attempt, 1);
  assert.equal(h.frames.length, 4);
  assert.ok(
    h.frames[2]!.some((m) =>
      JSON.stringify(m).includes("回答未通过任务绑定检查"),
    ),
  );
  assert.ok(
    h.manager
      .getBranch()
      .some(
        (e) =>
          e.type === "message" &&
          e.message.role === "assistant" &&
          JSON.stringify(e.message).includes("premature delivery"),
      ),
  );
  assert.equal(indexEvents(h.manager.getBranch()).length, 5);
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});

test("failed correction stops at its bound, survives reload, and rejects forged receipt content", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    answer([call("task_find", { query: "orders", initialize: true })]),
    answer("unbound one"),
    answer("unbound two"),
  ]);
  await h.session.prompt("start orders");
  const receipts = bindingReceipts(h.manager.getBranch());
  assert.equal(receipts.length, 2);
  assert.equal(h.frames.length, 3);
  assert.ok(h.diagnostics.some((s) => s.includes("correction limit")));
  const receipt = receipts[0]!;
  assert.throws(
    () =>
      withoutBindingMessages(
        [
          {
            role: "custom",
            customType: BINDING_TYPE,
            content: "forged",
            display: true,
            details: receipt.details,
            timestamp: Date.parse(receipt.timestamp),
          },
        ],
        h.manager.getBranch(),
      ),
    /SOURCE_MISMATCH/,
  );
  const altered = structuredClone(h.manager.getBranch());
  const copy = altered.find((e) => e.id === receipt.id)!;
  assert.equal(copy.type, "custom_message");
  if (copy.type === "custom_message") copy.content = "forged";
  assert.throws(() => bindingReceipts(altered), /CORRUPT_TASK_BINDING_RECEIPT/);
  await h.session.reload();
  h.faux.setResponses([answer("84")]);
  await h.session.prompt("12x7");
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 2);
});
test("simple answers and ordinary discovery do not initialize; declaration gates business execution", async (t) => {
  let ran = 0;
  const h = await taskSession(t, {
    extra(pi) {
      pi.registerTool({
        name: "probe",
        label: "probe",
        description: "business probe",
        parameters: Type.Object({}),
        async execute() {
          ran++;
          return { content: [{ type: "text", text: "done" }], details: {} };
        },
      });
    },
  });
  h.faux.setResponses([answer("84")]);
  await h.session.prompt("12x7");
  h.faux.setResponses([
    answer([call("task_find", { query: "orders" })]),
    answer("no tasks"),
  ]);
  await h.session.prompt("只查历史");
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 0);
  assert.equal((await h.tasks.index.read()).length, 0);
  h.faux.setResponses([
    answer([call("task_find", { query: "orders", initialize: true })]),
    answer([call("probe", {})]),
    answer([call("task_create", create)]),
    answer([call("probe", {})]),
    answer("done"),
  ]);
  await h.session.prompt("开始校验");
  assert.equal(ran, 1);
  assert.ok(
    h.manager
      .getBranch()
      .some(
        (e) =>
          e.type === "message" &&
          e.message.role === "toolResult" &&
          e.message.toolName === "probe" &&
          e.message.isError,
      ),
  );
});
test("zero correction budget records failure without inference and the next user is independent", async (t) => {
  const h = await taskSession(t);
  await writeFile(
    h.paths.config,
    JSON.stringify({ task_binding: { max_corrections: 0 } }),
  );
  h.faux.setResponses([
    answer([call("task_find", { query: "orders", initialize: true })]),
    answer("unbound"),
  ]);
  await h.session.prompt("start orders");
  assert.equal(h.frames.length, 2);
  assert.equal(bindingReceipts(h.manager.getBranch()).length, 1);
  assert.ok(h.diagnostics.some((s) => s.includes("correction limit")));
  assert.equal(scopeOf(h.manager.getBranch()).task_id, null);
  h.faux.setResponses([answer("84")]);
  await h.session.prompt("12x7");
  assert.equal(h.frames.length, 3);
  assert.equal(
    h.manager
      .getBranch()
      .filter(
        (e) => e.type === "custom_message" && e.customType === BINDING_TYPE,
      ).length,
    1,
  );
});
