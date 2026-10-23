import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import type { AddressInfo } from "node:net";
import test, { type TestContext } from "node:test";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";
import { ruleSession } from "../fixtures/rule-session.ts";

async function httpRuleSession(t: TestContext, retry = false) {
  const h = await ruleSession(t, undefined, { verifyCapacity: verifyProviderCapacity });
  let metadata: unknown = { data: [{ id: "probe", context_window: 1_048_576 }] };
  let metadataStatus = 200;
  let metadataCalls = 0;
  const bodies: Array<{ messages: unknown[] }> = [];
  const server = createServer(async (request, response) => {
    if (request.method === "GET" && request.url === "/v1/models") {
      metadataCalls++;
      assert.equal(request.headers.authorization, "Bearer local-test-only");
      response.writeHead(metadataStatus, { "content-type": "application/json" });
      response.end(JSON.stringify(metadata)); return;
    }
    assert.equal(request.method, "POST"); assert.equal(request.url, "/v1/chat/completions");
    let raw = ""; for await (const chunk of request) raw += String(chunk);
    bodies.push(JSON.parse(raw) as { messages: unknown[] });
    if (retry && bodies.length === 1) {
      await writeFile(h.paths.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 240 }));
      await writeFile(h.paths.rule, "HTTP_HOT_RULE {{recent_turns}}");
      metadata = { data: [{ id: "probe", context_window: 1_000_001 }] };
      response.writeHead(503, { "content-type": "application/json", "retry-after": "0" });
      response.end(JSON.stringify({ error: { message: "test retry" } })); return;
    }
    response.writeHead(200, { "content-type": "text/event-stream" });
    response.write(`data: ${JSON.stringify({ id: "probe", choices: [{ index: 0, delta: { role: "assistant", content: "OK" }, finish_reason: null }] })}\n\n`);
    response.write(`data: ${JSON.stringify({ id: "probe", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`);
    response.end("data: [DONE]\n\n");
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  });
  h.runtime.registerProvider("local-http", {
    baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`, apiKey: "local-test-only", api: "openai-completions",
    models: [{ id: "probe", name: "probe", input: ["text"], reasoning: false,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1_000_000, maxTokens: 32 }],
  });
  const model = h.runtime.getModel("local-http", "probe"); assert.ok(model);
  await h.session.setModel(model);
  if (retry) h.settings.applyOverrides({ retry: { enabled: false, provider: { maxRetries: 1 } } });
  return { ...h, model, bodies, metadataCalls: () => metadataCalls,
    setMetadata: (value: unknown, status = 200) => { metadata = value; metadataStatus = status; } };
}

test("生产容量适配核验精确元数据；配置/模板错误时实际推理 HTTP 为零", async t => {
  const h = await httpRuleSession(t);
  const rule = await readFile(h.paths.rule);
  await h.session.prompt("normal");
  assert.equal(h.bodies.length, 1); assert.equal(h.metadataCalls(), 1);
  assert.equal(h.frames[0]?.frame.capacity.contextWindow, 1_048_576);
  assert.equal(h.frames[0]?.frame.capacity.contextLimit, 629_145);
  assert.equal(h.model.contextWindow, 1_000_000, "host catalog must remain untouched");
  for (const template of ["", "{{unknown}}", "{{recent_turns + 1}}", "{{recent_turns"]) {
    await writeFile(h.paths.rule, template);
    await h.session.prompt("cancel invalid rule");
    assert.equal(h.bodies.length, 1);
    assert.match(h.diagnostics.at(-1) ?? "", /INVALID_RULE/);
  }
  await writeFile(h.paths.rule, rule);
  await writeFile(h.paths.config, JSON.stringify({ ...DEFAULT_CONFIG, evict_turns: 201 }));
  const metadataCalls = h.metadataCalls();
  await h.session.prompt("cancel invalid config");
  assert.equal(h.bodies.length, 1); assert.equal(h.metadataCalls(), metadataCalls + 1);
});

test("供应商容量缺失/冲突/HTTP 错误不回退目录，诊断不包含响应秘密", async t => {
  const h = await httpRuleSession(t);
  for (const [metadata, status] of [
    [{ data: [{ id: "probe" }] }, 200],
    [{ data: [{ id: "probe", context_window: 10 }, { id: "probe", context_window: 20 }] }, 200],
    [{ secret: "private-response-fixture" }, 401],
  ] as const) {
    h.setMetadata(metadata, status);
    await h.session.prompt("capacity must fail");
    assert.equal(h.bodies.length, 0);
    assert.match(h.diagnostics.at(-1) ?? "", /MODEL_CAPACITY_UNVERIFIED/);
    assert.doesNotMatch(h.diagnostics.at(-1) ?? "", /private-response-fixture|local-test-only/);
  }
});

test("原生供应商网络重试不重读配置/Rule/容量，下一逻辑请求重新读取", async t => {
  const h = await httpRuleSession(t, true);
  await h.session.prompt("retry one HTTP 503");
  assert.equal(h.bodies.length, 2); assert.equal(h.metadataCalls(), 1); assert.equal(h.frames.length, 1);
  assert.deepEqual(h.bodies[0]?.messages, h.bodies[1]?.messages);
  assert.equal(h.frames[0]?.frame.config.recent_turns, 200);
  assert.equal(h.frames[0]?.frame.capacity.contextLimit, 629_145);
  await h.session.prompt("next logical request");
  assert.equal(h.bodies.length, 3); assert.equal(h.metadataCalls(), 2); assert.equal(h.frames.length, 2);
  assert.equal(h.frames[1]?.frame.config.recent_turns, 240);
  assert.equal(h.frames[1]?.frame.capacity.contextLimit, 600_000);
  assert.match(JSON.stringify(h.bodies[2]), /HTTP_HOT_RULE 240/);
});
