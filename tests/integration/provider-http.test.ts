import assert from "node:assert/strict";
import { createServer } from "node:http";
import { rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test, { type TestContext } from "node:test";
import type { AddressInfo } from "node:net";
import { registerRequestLifecycle } from "../../src/pi/request-lifecycle.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { requestProbe } from "../fixtures/request-probe.ts";

async function httpHarness(t: TestContext, retry = false) {
  let probe: ReturnType<typeof requestProbe>;
  const h = await nativeSession(t, [(pi) => {
    registerRequestLifecycle(pi, {
      prepare: (messages, ctx) => probe.services.prepare(messages, ctx),
      report: (error, ctx) => probe.services.report(error, ctx),
    });
  }]);
  const rulePath = join(h.root, "rule.md");
  await writeFile(rulePath, "HTTP_RULE {{recent_turns}}");
  probe = requestProbe(rulePath);
  if (retry) h.settings.applyOverrides({ retry: { enabled: false, provider: { maxRetries: 1 } } });
  const bodies: Array<{ messages: unknown[] }> = [];
  const server = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += String(chunk);
    bodies.push(JSON.parse(body) as { messages: unknown[] });
    if (retry && bodies.length === 1) {
      probe.config.recent_turns = 240;
      await writeFile(rulePath, "HTTP_RULE {{recent_turns}} new text");
      response.writeHead(503, { "content-type": "application/json", "retry-after": "0" });
      response.end(JSON.stringify({ error: { message: "fixture retry", type: "server_error" } }));
      return;
    }
    response.writeHead(200, { "content-type": "text/event-stream" });
    response.write(`data: ${JSON.stringify({ id: "probe", choices: [{ index: 0, delta: { role: "assistant", content: "HTTP_OK" }, finish_reason: null }] })}\n\n`);
    response.write(`data: ${JSON.stringify({ id: "probe", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`);
    response.end("data: [DONE]\n\n");
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  });
  const port = (server.address() as AddressInfo).port;
  h.runtime.registerProvider("local-http", {
    baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "local-test-only", api: "openai-completions",
    models: [{ id: "probe", input: ["text"], reasoning: false, name: "probe",
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1_048_576, maxTokens: 32 }],
  });
  const model = h.runtime.getModel("local-http", "probe");
  assert.ok(model); await h.session.setModel(model);
  return { ...h, probe, bodies, rulePath };
}

test("原生 OpenAI 兼容供应商：正常请求到 HTTP，准备失败时 HTTP 新增数为零", async (t) => {
  const h = await httpHarness(t);
  await h.session.prompt("normal");
  assert.equal(h.bodies.length, 1);
  assert.match(JSON.stringify(h.bodies[0]), /HTTP_RULE 200/);
  for (const mode of ["template", "budget"]) {
    h.probe.fail(mode);
    await h.session.prompt(`must cancel ${mode}`);
    assert.equal(h.bodies.length, 1);
  }
  assert.deepEqual(h.probe.errors, ["INVALID_TEMPLATE", "CONTEXT_BUDGET_EXCEEDED"]);
  h.probe.fail(undefined);
  await writeFile(h.rulePath, "");
  await h.session.prompt("empty template must cancel");
  assert.equal(h.bodies.length, 1);
  await rm(h.rulePath);
  await h.session.prompt("unreadable template must cancel");
  assert.equal(h.bodies.length, 1);
  assert.match(h.probe.errors[2] ?? "", /INVALID_TEMPLATE/);
  assert.match(h.probe.errors[3] ?? "", /ENOENT/);
});

test("供应商内部 HTTP 重试复用同一快照，下一逻辑请求才读取新模板和配置", async (t) => {
  const h = await httpHarness(t, true);
  await h.session.prompt("retry once");
  assert.equal(h.bodies.length, 2);
  assert.deepEqual(h.bodies[0]?.messages, h.bodies[1]?.messages);
  assert.equal(h.probe.frames.length, 1);
  assert.match(JSON.stringify(h.bodies[1]), /HTTP_RULE 200/);
  await h.session.prompt("new request");
  assert.equal(h.bodies.length, 3);
  assert.equal(h.probe.frames.length, 2);
  assert.match(JSON.stringify(h.bodies[2]), /HTTP_RULE 240 new text/);
});
