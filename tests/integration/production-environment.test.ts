import assert from "node:assert/strict";
import test from "node:test";
import { readFile, access } from "node:fs/promises";
import { join } from "node:path";
import { getSystemMessageText } from "@earendil-works/pi-ai";
import { productionTaskSession, assertProductionPayload } from "../fixtures/production-session.ts";
import { renderRule } from "../../src/rule/render.ts";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";

test("production fixture retains native System, builtins, all memory tools and the complete Rule across reload", async (t) => {
  const h = await productionTaskSession(t);
  await assert.rejects(access(join(h.agentDir, "SYSTEM.md")), { code: "ENOENT" });
  await assert.rejects(access(join(h.agentDir, "APPEND_SYSTEM.md")), { code: "ENOENT" });
  const active = h.session.getActiveToolNames();
  for (const name of ["read", "bash", "edit", "write", "task_create", "task_resume", "task_find", "task_status", "state_read", "state_append", "modify_fact", "update_goal", "state_remain", "memory_read", "recent_window_set"])
    assert.ok(active.includes(name), `missing production tool ${name}`);
  await h.session.prompt("short fixture question");
  const system = h.frames.at(-1)![0];
  assert.ok(system?.role === "system");
  const text = getSystemMessageText(system);
  assert.match(text, /You are an expert coding assistant operating inside pi/);
  assert.doesNotMatch(text, /NATIVE_SYSTEM|NATIVE_APPEND/);
  assert.ok(text.includes(renderRule(await readFile(h.paths.rule, "utf8"), DEFAULT_CONFIG)));
  assert.match(JSON.stringify(h.frames.at(-1)!.at(-1)), /本次预算快照/);
  await h.session.reload();
  assert.deepEqual(h.session.getActiveToolNames().sort(), active.sort());
  await h.session.prompt("continue with the full production environment");
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
});

test("production acceptance rejects a stub System or a reduced tool set", async (t) => {
  const h = await productionTaskSession(t);
  await h.session.prompt("fixture request");
  const first = h.frames.at(-1)![0]!;
  assert.ok(first.role === "system");
  const wire = {
    messages: [{role:"system",content:getSystemMessageText(first)}, {role:"user",content:"本次预算快照"}],
    tools: h.session.getAllTools().map(tool => ({function:{name:tool.name}})),
  };
  assert.doesNotThrow(() => assertProductionPayload(wire, true));
  assert.throws(() => assertProductionPayload({...wire,messages:[{role:"system",content:"NATIVE_SYSTEM"}]}, true));
  assert.throws(() => assertProductionPayload({...wire,tools:wire.tools.filter(tool => tool.function.name !== "state_append")}, true), /state_append/);
  assert.throws(() => assertProductionPayload({...wire,messages:[{role:"system",content:"You are an expert coding assistant operating inside pi"},{role:"user",content:"本次预算快照"}]}, true));
});
