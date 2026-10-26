import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import type { ExtensionFactory } from "@earendil-works/pi-coding-agent";
import { nativeSession } from "./native-session.ts";
import { taskSession } from "./task-session.ts";
import { readConfigInput } from "../../src/config/read.ts";
import { mergeConfig } from "../../src/config/schema.ts";
import { renderRule } from "../../src/rule/render.ts";

const builtins = ["read", "bash", "edit", "write"];
const memoryTools = ["task_create", "task_find", "task_resume", "task_clarify", "task_status", "state_append", "state_read", "update_goal", "modify_fact", "state_remain", "memory_read", "recent_window_set"];

/** Fail before inference if a supplier test accidentally uses a reduced environment. */
export function assertProductionPayload(payload: unknown, memory: boolean): void {
  const wire = payload as { messages?: { role: string; content: unknown }[]; tools?: { function?: { name?: string } }[] };
  const system = wire.messages?.filter(message => message.role === "system").map(message =>
    typeof message.content === "string" ? message.content : JSON.stringify(message.content)).join("\n") ?? "";
  assert.match(system, /You are an expert coding assistant operating inside pi/);
  assert.doesNotMatch(system, /NATIVE_SYSTEM|NATIVE_APPEND|STATE_PROBE|PHASE1_TEST_STATE/);
  const names = new Set(wire.tools?.map(tool => tool.function?.name));
  for (const name of [...builtins, ...(memory ? memoryTools : [])])
    assert.ok(names.has(name), `incomplete production tool set: ${name}`);
  if (memory) {
    assert.equal(system.split("<pi_long_task_rule>").length - 1, 1);
    for (const section of ["上下文与权限", "任务选择与恢复", "短引用与证据", "State 维护", "Recent Window 与原文回读"])
      assert.ok(system.includes(section), `incomplete package Rule: ${section}`);
    assert.ok(wire.messages?.some(message => JSON.stringify(message.content).includes("本次预算快照")));
  }
}
function guard(memory: boolean): ExtensionFactory {
  return pi => {
    pi.on("before_provider_request", (event, ctx) => {
      if (ctx.model?.provider !== "deepseek") return;
      try { assertProductionPayload(event.payload, memory); }
      catch (error) { ctx.abort(); throw error; }
    });
  };
}
export async function productionNativeSession(...args: Parameters<typeof nativeSession>) {
  const [t, factories = [], enabled = false, reserveTokens = 512, paths = [], manager] = args;
  return nativeSession(t, [guard(false), ...factories], enabled, reserveTokens, paths, manager, true);
}
export async function productionTaskSession(t: Parameters<typeof taskSession>[0], options: Parameters<typeof taskSession>[1] = {}) {
  const bundledRule = await readFile(new URL("../../resources/rule.md", import.meta.url), "utf8");
  let h!: Awaited<ReturnType<typeof taskSession>>;
  let requests = 0;
  let responses = 0;
  const calls: string[] = [], errors: string[] = [];
  let reply = "";
  h = await taskSession(t, { ...options, fullEnvironment: true,
    extra(pi) {
      guard(true)(pi);
      pi.on("before_provider_request", async (event, ctx) => {
        if (ctx.model?.provider !== "deepseek") return;
        try {
          const template = await readFile(h.paths.rule, "utf8");
          assert.ok(template.startsWith(bundledRule.trimEnd()), "live acceptance must retain the complete bundled Rule");
          const config = mergeConfig(await readConfigInput(h.paths), h.tasks.scope(ctx).overrides, h.budgets.at(-1)!.limit);
          const wire = event.payload as {messages:{role:string;content:string}[]};
          const system = wire.messages.filter(message => message.role === "system").map(message => message.content).join("\n");
          assert.ok(system.includes(renderRule(template, config)), "outgoing Rule must equal the full rendered runtime template");
          requests++;
        } catch (error) { ctx.abort(); throw error; }
      });
      options.extra?.(pi);
    },
  });
  h.session.subscribe(event => {
    if (event.type !== "message_end") return;
    const message = event.message;
    if (message.role === "assistant" && message.provider === "deepseek") {
      responses++;
      for (const part of message.content) if (part.type === "toolCall") calls.push(part.name);
      reply = message.content.filter(part => part.type === "text").map(part => part.text).join("\n")
        .replace(/sk-[A-Za-z0-9_-]{20,}/g, "[redacted]").slice(0, 180);
    }
    if (message.role === "toolResult" && message.isError && h.session.model?.provider === "deepseek") errors.push(message.toolName);
  });
  t.after(() => t.diagnostic(JSON.stringify({ environment:"complete Pi + package Rule + all default tools", requestsPrepared:requests, responsesEnded:responses, calls, toolErrors:errors, reply })));
  return h;
}
