import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { verifyProviderCapacity } from "../../src/pi/model-capacity.ts";

test("real DeepSeek reads a bounded range with the fixed truncation protocol and shared pool", { timeout: 90000 }, async t => {
  const auth = join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json"), originalAuth = await readFile(auth);
  t.after(async () => assert.ok(originalAuth.equals(await readFile(auth))));
  const credential = JSON.parse(originalAuth.toString()).deepseek as { type: string; key: unknown };
  assert.ok(credential.type === "api_key" && typeof credential.key === "string");
  const wires: { output: number; fixedRule: boolean; tag: boolean }[] = [];
  const h = await taskSession(t, {
    verifyCapacity: (m, c, s) => m.provider === "deepseek" ? verifyProviderCapacity(m, c, s) : Promise.resolve(m.contextWindow),
    extra: pi => { pi.on("before_provider_request", e => {
      const body = e.payload as Record<string, unknown>;
      if (body.model !== "deepseek-flash") return;
      const view = JSON.stringify(body.messages);
      wires.push({ output: (body.max_tokens ?? body.max_completion_tokens) as number,
        fixedRule: view.includes("回读也可能因字符或 token 限额"), tag: view.includes("[TRUNCATED]") });
    }); },
  });
  // A small configurable pool exercises truncation without sending a huge live prompt.
  await writeFile(h.paths.config, JSON.stringify({ elastic_budget: { pool_percent: { read: .5, window: 79.5, safety: 20 } } }));
  h.faux.setResponses([
    fauxAssistantMessage([fauxToolCall("task_create", { title: "Elastic live", goal: "Verify bounded original reading",
      project_name: "MemWeave", summary: "Elastic live test", keywords: ["elastic"] })]), fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("ABCDE0123456789".repeat(3500));
  h.faux.setResponses([fauxAssistantMessage([fauxToolCall("memory_read", { items: [{ ref: "U1" }], max_total_chars: 50000 })]), fauxAssistantMessage("seeded partial read")]);
  await h.session.prompt("read the original source");
  assert.deepEqual(h.diagnostics, []);
  const seeded = h.manager.getBranch().findLast(e => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "memory_read");
  assert.ok(seeded?.type === "message" && seeded.message.role === "toolResult" && !seeded.message.isError);
  assert.match(JSON.stringify(seeded.message.content), /TRUNCATED/);
  await h.runtime.setRuntimeApiKey("deepseek", credential.key);
  await h.session.setModel(h.runtime.getModel("deepseek", "deepseek-flash")!);
  h.session.setActiveToolsByName(["memory_read"]);
  await h.session.prompt('这是功能验证。请调用一次 memory_read，参数 {"items":[{"ref":"U1","offset":900,"limit":100}],"max_total_chars":100}，核对实际返回后只回复 ELASTIC_OK。不要调用其他工具。');
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
  const last = h.manager.getBranch().findLast(e => e.type === "message" && e.message.role === "toolResult" && e.message.toolName === "memory_read");
  assert.ok(last?.type === "message" && last.message.role === "toolResult" && last.id !== seeded.id && !last.message.isError);
  const body = last.message.content[0];
  assert.ok(body?.type === "text");
  assert.equal(JSON.parse(body.text).items[0].offset, 900);
  assert.equal(JSON.parse(body.text).total_chars, 100);
  assert.ok(wires.length >= 2 && wires.every(w => w.output === 62914 && w.fixedRule && w.tag));
  assert.ok(h.budgets.every(b => b.X <= b.readLimit && b.windowUsed <= b.windowLimit));
  t.diagnostic(`${wires.length} real DeepSeek requests; 4 Faux setup requests; configured read pool 0.5%; JSON/range/tag and fixed Rule reached provider; official capacity 1048576`);
});
