import type { RequestMessages } from "../pi/request-lifecycle.ts";
import { replaySystem } from "../pi/system.ts";
import { RESERVED_RULE_TAG, RULE_CLOSE, RULE_OPEN } from "./render.ts";

export function applyRule(messages: RequestMessages, renderedRule: string): RequestMessages {
  if (!renderedRule.trim() || RESERVED_RULE_TAG.test(renderedRule)) throw new Error("INVALID_RULE: invalid rendered body");
  const system = replaySystem(messages);
  const baseContent = typeof system.content === "string" ? system.content : system.content.map(block => block.text).join("\n");
  const outside = [baseContent, ...Object.entries(system.sections ?? {})
    .filter(([name]) => name !== "addendum").map(([, value]) => value ?? "")];
  if (outside.some(text => RESERVED_RULE_TAG.test(text))) throw new Error("RULE_BOUNDARY_CONFLICT: reserved boundary outside addendum");
  const addendum = system.sections?.addendum ?? "";
  const matches = [...addendum.matchAll(/<\/?pi_long_task_rule\b[^>]*>?/g)];
  const scope = `${RULE_OPEN}\n${renderedRule}\n${RULE_CLOSE}`;
  let updated: string;
  if (!matches.length) {
    updated = addendum ? `${addendum}\n\n${scope}` : scope;
  } else {
    const [open, close] = matches;
    if (matches.length !== 2 || open?.[0] !== RULE_OPEN || close?.[0] !== RULE_CLOSE) {
      throw new Error("RULE_BOUNDARY_CONFLICT: incomplete, duplicate or nested rule boundaries");
    }
    updated = addendum.slice(0, open.index) + scope + addendum.slice(close.index + close[0].length);
  }
  system.sections = { ...system.sections, addendum: updated };
  return [system, ...messages.filter(message => message.role !== "system")];
}
