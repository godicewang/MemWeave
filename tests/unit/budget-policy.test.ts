import assert from "node:assert/strict";
import test from "node:test";
import { deriveContextLimit } from "../../src/pi/context-limit.ts";
import { budgetPlan } from "../../src/window/policy.ts";
import { DEFAULT_CONFIG, mergeConfig } from "../../src/config/schema.ts";
import { counterForModel, deepseekCounter } from "../../src/window/tokens.ts";
import {
  renderMessage,
  ordinaryText,
  allocate,
} from "../../src/window/budget.ts";
import { outputReserve, alignOutput } from "../../src/pi/window-budget.ts";
import { fauxProvider } from "@earendil-works/pi-ai/providers/faux";

test("60% safe-integer capacity and integer allocations sum exactly; N/B adapt only when absent", () => {
  const { recent_turns: _n, evict_turns: _b, ...file } = DEFAULT_CONFIG;
  for (const [model, N, B] of [
    [131072, 50, 10],
    [262144, 110, 22],
    [1048576, 200, 40],
  ]) {
    const C = deriveContextLimit(model!);
    const plan = budgetPlan(C);
    assert.equal(
      Object.values(plan).reduce((a, b) => a + b, 0),
      C,
    );
    assert.equal(plan.state, Math.floor(C / 8));
    assert.equal(plan.system, Math.floor((C * 15) / 100));
    assert.equal(mergeConfig(file, {}, C).recent_turns, N);
    assert.equal(mergeConfig(file, {}, C).evict_turns, B);
    assert.equal(mergeConfig(DEFAULT_CONFIG, {}, C).recent_turns, 200);
  }
  assert.equal(mergeConfig(file, {}, 54612).recent_turns, 30);
  assert.equal(
    deriveContextLimit(Number.MAX_SAFE_INTEGER),
    Number((BigInt(Number.MAX_SAFE_INTEGER) * 3n) / 5n),
  );
  assert.equal(mergeConfig(file, { recent_turns: 35 }, 78643).evict_turns, 7);
  assert.throws(() => mergeConfig(file, {}), /MODEL_CAPACITY_UNVERIFIED/);
  assert.throws(
    () => mergeConfig({ ...file, evict_turns: 40 }, { recent_turns: 8 }, 78643),
    /INVALID_CONFIG/,
  );
});

test("official tokenizer treats control spellings as literal text; Unicode Q preserves full protocol and source", async () => {
  const counter = await deepseekCounter();
  assert.ok(
    counter.count("工程认知与工具记录。") <
      Buffer.byteLength("工程认知与工具记录。"),
  );
  assert.ok(counter.count("[bos]") > 1);
  const message = {
    role: "assistant" as const,
    content: [
      { type: "text" as const, text: "中文😀".repeat(100) },
      {
        type: "toolCall" as const,
        id: "native",
        name: "read",
        arguments: { path: "unchanged" },
      },
    ],
    api: "openai-completions" as const,
    provider: "deepseek",
    model: "deepseek-flash",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "toolUse" as const,
    timestamp: 1,
  };
  const original = structuredClone(message);
  const rendered = renderMessage(message, "[A1]", 40, false, counter);
  assert.ok(counter.count(ordinaryText(rendered)) <= 40);
  assert.match(ordinaryText(rendered), /TRUNCATED/);
  assert.deepEqual(
    rendered.content.find((p) => p.type === "toolCall"),
    original.content[1],
  );
  assert.deepEqual(message, original);
  const input = {
    limit: 10000,
    system: 100,
    state: 200,
    output: 1000,
    reminder: 0,
    messages: [{ message, head: "", exempt: false }],
    imageCost: () => 0,
    counter,
  };
  const a = allocate(input),
    b = allocate({
      ...input,
      messages: [
        {
          message: {
            ...message,
            timestamp: 999,
            usage: { ...message.usage, input: 999999 },
          },
          head: "",
          exempt: false,
        },
      ],
    });
  assert.equal(a.P, b.P);
  assert.equal(a.A, 500);
  assert.ok(a.total <= 10000);
});

test("default output follows 10% plan, explicit caps are reserved, actual payload is aligned without editing history", () => {
  const model = {
    ...fauxProvider().getModel(),
    api: "openai-completions" as const,
    maxTokens: 384000,
  };
  assert.equal(outputReserve(model, "off", 629145), 62914);
  assert.equal(
    outputReserve(
      { ...model, samplingParams: { max_tokens: 12345 } },
      "off",
      629145,
    ),
    12345,
  );
  assert.equal(
    outputReserve({ ...model, maxTokens: 1024 }, "off", 629145),
    1024,
  );
  const payload = {
    model: model.id,
    max_tokens: 384000,
    messages: [{ role: "user", content: "unaltered" }],
  };
  const result = alignOutput(payload, model, 62914);
  assert.equal(result.max_tokens, 62914);
  assert.deepEqual(result.messages, payload.messages);
  assert.equal(payload.max_tokens, 384000);
  assert.throws(
    () => alignOutput({ ...payload, model: "other" }, model, 62914),
    /OUTPUT_BUDGET_UNVERIFIED/,
  );
  assert.throws(
    () => alignOutput({ ...payload, max_completion_tokens: 1 }, model, 62914),
    /OUTPUT_BUDGET_UNVERIFIED/,
  );
});


test("tokenizer selection is explicit about unknown providers and future revisions", async () => {
  const model = {...fauxProvider().getModel(), provider:"deepseek", id:"deepseek-flash", api:"openai-completions" as const, baseUrl:"https://api.deepseek.com"};
  assert.equal((await counterForModel(model,"DeepSeek-V4.1-Flash")).estimator,"deepseek-v41-text-with-protocol-margin");
  for (const name of [undefined,"DeepSeek-V4-Flash","DeepSeek-V4.10-Flash","DeepSeek-V5-Flash"]) assert.equal((await counterForModel(model,name)).estimator,"utf8-bytes-with-protocol-margin");
  assert.equal((await counterForModel({...model,baseUrl:"https://example.invalid"},"DeepSeek-V4.1-Flash")).estimator,"utf8-bytes-with-protocol-margin");
});
