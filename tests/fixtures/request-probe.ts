// Stage 0 test-only composition. Real config/Rule/Task/Window implementations are later milestones.
import { readFile } from "node:fs/promises";
import { getCurrentSystemMessage } from "@earendil-works/pi-ai/utils/transcript";
import { deriveContextLimit } from "../../src/pi/context-limit.ts";
import type { RequestMessages, RequestServices } from "../../src/pi/request-lifecycle.ts";

export function requestProbe(rulePath: string, verifiedCapacity?: number) {
  const config = { recent_turns: 200, evict_turns: 40 };
  const frames: Array<{ turns: number; rule: string; systemCost: number; limit: number }> = [];
  const errors: string[] = [];
  let failure: string | undefined;
  const services: RequestServices = {
    report(error) { errors.push(error instanceof Error ? error.message : "UNKNOWN_FAILURE"); },
    async prepare(messages, ctx) {
      const snapshot = structuredClone(config);
      const capacity = deriveContextLimit(verifiedCapacity ?? ctx.model?.contextWindow);
      const template = await readFile(rulePath, "utf8");
      if (!template.trim() || failure === "template") throw new Error("INVALID_TEMPLATE");
      const rule = template.replace(/\{\{(recent_turns|evict_turns)\}\}/g,
        (_match, key: keyof typeof config) => String(snapshot[key]));
      if (rule.includes("{{")) throw new Error("INVALID_TEMPLATE");
      const system = structuredClone(getCurrentSystemMessage(messages));
      if (!system) throw new Error("MISSING_SYSTEM");
      system.sections = { ...system.sections,
        addendum: `${system.sections?.addendum ?? ""}\n<pi_long_task_rule>\n${rule}\n</pi_long_task_rule>` };
      const state = { role: "user" as const, content: "STATE_PROBE: Goal=stage0", timestamp: 0 };
      const reminder = { role: "user" as const, content: "REMINDER_PROBE", timestamp: 0 };
      const result: RequestMessages = [system, ...messages.filter(message => message.role !== "system"), state, reminder];
      const systemCost = Buffer.byteLength(JSON.stringify(system));
      if (failure === "budget" || Buffer.byteLength(JSON.stringify(result)) + (ctx.model?.maxTokens ?? 0) > capacity) {
        throw new Error("CONTEXT_BUDGET_EXCEEDED");
      }
      frames.push({ turns: snapshot.recent_turns, rule, systemCost, limit: capacity });
      return result;
    },
  };
  return { config, frames, errors, services, fail(mode: string | undefined) { failure = mode; } };
}
