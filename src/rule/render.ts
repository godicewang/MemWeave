import { CONFIG_KEYS, parseConfig } from "../config/schema.ts";

export const RULE_OPEN = "<pi_long_task_rule>";
export const RULE_CLOSE = "</pi_long_task_rule>";
export const RESERVED_RULE_TAG = /<\/?pi_long_task_rule\b/;

export function renderRule(template: unknown, values: unknown): string {
  const config = parseConfig(values);
  if (typeof template !== "string" || !template.trim() || RESERVED_RULE_TAG.test(template)) {
    throw new Error("INVALID_RULE: template is empty or contains a reserved boundary");
  }
  const tokens = /\{\{[\s\S]*?\}\}/g;
  // Validate the original template completely before substituting any values.
  const remainder = template.replace(tokens, token => {
    const match = /^\{\{\s*([a-z][a-z0-9_]*)\s*\}\}$/.exec(token);
    if (!match || !CONFIG_KEYS.includes(match[1] as typeof CONFIG_KEYS[number])) {
      throw new Error("INVALID_RULE: unsupported placeholder or template expression");
    }
    return "";
  });
  if (remainder.includes("{{") || remainder.includes("}}")) throw new Error("INVALID_RULE: unmatched placeholder delimiter");
  return template.replace(tokens, token => {
    const key = /^\{\{\s*([a-z][a-z0-9_]*)\s*\}\}$/.exec(token)![1] as typeof CONFIG_KEYS[number];
    return String(config[key]);
  });
}
