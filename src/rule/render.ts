import { settingsFor } from "../config/defaults.ts";
import { CONFIG_KEYS, parseConfig } from "../config/schema.ts";

export const RULE_OPEN = "<pi_long_task_rule>";
export const RULE_CLOSE = "</pi_long_task_rule>";
export const RESERVED_RULE_TAG = /<\/?pi_long_task_rule\b/;

export function renderRule(template: unknown, values: unknown): string {
  const config = parseConfig(values);
  const settings = settingsFor(config);
  const protocol = {
    agent_context_percent: settings.context_budget.model_percent,
    state_token_warning_percent: settings.state_policy.token_warning_percent,
    read_lifetime_messages: settings.read.lifetime_messages,
    read_default_total_chars: settings.read.default_total_chars,
  };
  // Values literally embedded in the legacy six-variable protocol, not mutable defaults.
  const baseline = {
    agent_context_percent: 60,
    state_token_warning_percent: 80,
    read_lifetime_messages: 10,
    read_default_total_chars: 8000,
  };
  const replacements = { ...Object.fromEntries(CONFIG_KEYS.map(key => [key, config[key]])), ...protocol };
  const present = new Set<string>();
  if (typeof template !== "string" || !template.trim() || RESERVED_RULE_TAG.test(template)) {
    throw new Error("INVALID_RULE: template is empty or contains a reserved boundary");
  }
  const tokens = /\{\{[\s\S]*?\}\}/g;
  // Validate the original template completely before substituting any values.
  const remainder = template.replace(tokens, token => {
    const match = /^\{\{\s*([a-z][a-z0-9_]*)\s*\}\}$/.exec(token);
    if (!match || !Object.hasOwn(replacements, match[1]!)) {
      throw new Error("INVALID_RULE: unsupported placeholder or template expression");
    }
    present.add(match[1]!);
    return "";
  });
  if (remainder.includes("{{") || remainder.includes("}}")) throw new Error("INVALID_RULE: unmatched placeholder delimiter");
  for (const key of Object.keys(protocol) as (keyof typeof protocol)[])
    if (protocol[key] !== baseline[key] && !present.has(key))
      throw Error(`RULE_CONFIG_MISMATCH: update rule.md to include {{${key}}} before using this policy`);
  return template.replace(tokens, token => {
    const key = /^\{\{\s*([a-z][a-z0-9_]*)\s*\}\}$/.exec(token)![1] as keyof typeof replacements;
    return String(replacements[key]);
  });
}
