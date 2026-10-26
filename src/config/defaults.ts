import { readFileSync } from "node:fs";
import { Type, type Static, type TSchema } from "typebox";
import { Check } from "typebox/value";

/** Protocol/resource ceilings, not user preferences. */
export const CONFIG_LIMITS = Object.freeze({
  model_percent: 60, cache_entries: 8192, cache_bytes: 16 * 1024 * 1024,
  read_chars: 50000, state_read_items: 50, image_bytes: 10 * 1024 * 1024,
});
const integer = (minimum = 1, maximum = Number.MAX_SAFE_INTEGER) => Type.Integer({ minimum, maximum });
const percent = (maximum = 100) => Type.Number({ minimum: 0.01, maximum });
const object = <T extends Record<string, TSchema>>(properties: T) => Type.Object(properties, { additionalProperties: false });
export const POLICY_SCHEMA = object({
  context_budget: object({ model_percent: percent(CONFIG_LIMITS.model_percent), parts_percent: object({
    state: percent(), window: percent(), output: percent(), system: percent(),
    user: percent(), read: percent(), protocol: percent(), safety: percent(),
  }) }),
  elastic_budget: object({ extra_model_percent: Type.Number({ minimum: 0, maximum: 20 }),
    pool_percent: object({ read: percent(), window: percent(), safety: percent() }),
    window_weights: object({ current: percent(), recent: percent(), older: percent() }),
    recent_events: integer(), expired_read_percent: percent() }),
  window_auto: object({ min_events: integer(), max_events: integer(), event_step: integer(),
    messages_per_event: integer(), tokens_per_message: integer(), evict_percent: percent() }),
  state_policy: object({ token_warning_percent: percent() }),
  read: object({ lifetime_messages: integer(), default_total_chars: integer(1, CONFIG_LIMITS.read_chars) }),
  source_cache: object({ max_entries: integer(0, CONFIG_LIMITS.cache_entries), max_bytes: integer(0, CONFIG_LIMITS.cache_bytes) }),
  model_metadata_timeout_ms: integer(1, 2147483647),
  task_binding: object({ max_corrections: integer(0, 3) }),
  task_search: object({ default_limit: integer(), candidates_per_channel: integer(), rrf_constant: integer(),
    channel_weights: object({ lexical: Type.Number({exclusiveMinimum:0}), semantic: Type.Number({exclusiveMinimum:0}), keywords: Type.Number({exclusiveMinimum:0}) }),
    field_weights: object({goal:percent(1000),title:percent(1000),keywords:percent(1000),summary:percent(1000),project_name:percent(1000)}),
    embedding: object({model:Type.Literal("Xenova/multilingual-e5-small"),revision:Type.Literal("761b726dd34fb83930e26aab4e9ac3899aa1fa78"),dtype:Type.Literal("q8")}),
    cache_max_bytes:integer(0,33554432),model_idle_ms:integer(1,2147483647),model_timeout_ms:integer(1,2147483647),
  }),
});
export type PolicySettings = Readonly<Static<typeof POLICY_SCHEMA>>;
export const POLICY_KEYS = Object.freeze(Object.keys(POLICY_SCHEMA.properties) as (keyof PolicySettings)[]);
function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
export const percentUnits = (percent: number) => Math.round(percent * 100);
export const percentOf = (total: number, percent: number) => Number(BigInt(total) * BigInt(percentUnits(percent)) / 10000n);
export function validateSettings(value: unknown): asserts value is PolicySettings {
  if (!Check(POLICY_SCHEMA, value)) throw Error("INVALID_CONFIG: invalid policy settings");
  if (Math.abs(Object.values(value.task_search.channel_weights).reduce((a,b)=>a+b,0)-1)>1e-8)
    throw Error("INVALID_CONFIG: Task search weights must sum to 1");
  const p = value.context_budget.parts_percent;
  const elastic = value.elastic_budget;
  const percentages = [value.context_budget.model_percent, ...Object.values(p),
    elastic.extra_model_percent, ...Object.values(elastic.pool_percent),
    ...Object.values(elastic.window_weights), elastic.expired_read_percent,
    value.window_auto.evict_percent, value.state_policy.token_warning_percent];
  if (percentages.some(n => Math.abs(n * 100 - percentUnits(n)) > 1e-8) ||
      Object.values(p).reduce((sum, n) => sum + percentUnits(n), 0) !== 10000 ||
      [elastic.pool_percent, elastic.window_weights].some(group =>
        Object.values(group).reduce((sum, n) => sum + percentUnits(n), 0) !== 10000) ||
      value.window_auto.min_events > value.window_auto.max_events)
    throw Error("INVALID_CONFIG: policy percentages or window bounds");
}
const STATE_SCHEMA = object({ state_max_events: integer(), state_event_max_chars: integer(),
  state_evict_batch: integer(), state_keep_limit: integer() });
const document: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(
  readFileSync(new URL("./defaults.json", import.meta.url))));
if (!Check(object({ ...STATE_SCHEMA.properties, ...POLICY_SCHEMA.properties }), document))
  throw Error("INVALID_CONFIG: bundled defaults.json");
const policy = Object.fromEntries(POLICY_KEYS.map(key => [key, document[key]]));
validateSettings(policy);
export const DEFAULT_SETTINGS: PolicySettings = freeze(policy);
export const DEFAULT_STATE = freeze({ state_max_events: document.state_max_events,
  state_event_max_chars: document.state_event_max_chars, state_evict_batch: document.state_evict_batch,
  state_keep_limit: document.state_keep_limit });

/** A resolved request carries full groups; legacy six-field internal callers inherit bundle defaults. */
export function settingsFor(config?: Partial<PolicySettings>): PolicySettings {
  return Object.freeze({
    context_budget: config?.context_budget ?? DEFAULT_SETTINGS.context_budget,
    elastic_budget: config?.elastic_budget ?? DEFAULT_SETTINGS.elastic_budget,
    window_auto: config?.window_auto ?? DEFAULT_SETTINGS.window_auto,
    state_policy: config?.state_policy ?? DEFAULT_SETTINGS.state_policy,
    read: config?.read ?? DEFAULT_SETTINGS.read,
    source_cache: config?.source_cache ?? DEFAULT_SETTINGS.source_cache,
    model_metadata_timeout_ms: config?.model_metadata_timeout_ms ?? DEFAULT_SETTINGS.model_metadata_timeout_ms,
    task_binding:config?.task_binding??DEFAULT_SETTINGS.task_binding,
    task_search:config?.task_search??DEFAULT_SETTINGS.task_search,
  });
}
export { freeze as freezeConfig };
