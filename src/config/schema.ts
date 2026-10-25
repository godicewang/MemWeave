import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
import { DEFAULT_SETTINGS, DEFAULT_STATE, POLICY_SCHEMA, POLICY_KEYS, freezeConfig,
  validateSettings, percentUnits, percentOf, type PolicySettings } from "./defaults.ts";
const positiveInteger = () => Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER });
/** This six-field schema is also the existing scope persistence contract. Do not expand it. */
export const CONFIG_SCHEMA = Type.Object({
  recent_turns: positiveInteger(), evict_turns: positiveInteger(), state_max_events: positiveInteger(),
  state_event_max_chars: positiveInteger(), state_evict_batch: positiveInteger(), state_keep_limit: positiveInteger(),
}, { additionalProperties: false });
type CoreConfig = Static<typeof CONFIG_SCHEMA>;
export type MemoryConfig = Readonly<CoreConfig & Partial<PolicySettings>>;
export type ResolvedConfig = Readonly<CoreConfig & PolicySettings>;
/** Legacy explicit 1M example, not the automatic on-disk defaults. */
export const DEFAULT_CONFIG: MemoryConfig = Object.freeze({
  recent_turns: DEFAULT_SETTINGS.window_auto.max_events,
  evict_turns: Math.max(1, Math.ceil(DEFAULT_SETTINGS.window_auto.max_events * DEFAULT_SETTINGS.window_auto.evict_percent / 100)),
  ...DEFAULT_STATE,
});
export const CONFIG_KEYS = Object.freeze(Object.keys(CONFIG_SCHEMA.properties) as (keyof CoreConfig)[]);
const overridesSchema = Type.Partial(CONFIG_SCHEMA, { additionalProperties: false });
const fileSchema = Type.Partial(Type.Object({ ...CONFIG_SCHEMA.properties,
  ...POLICY_SCHEMA.properties,
  context_budget: Type.Partial(Type.Object({
    model_percent: POLICY_SCHEMA.properties.context_budget.properties.model_percent,
    parts_percent: Type.Partial(POLICY_SCHEMA.properties.context_budget.properties.parts_percent, { additionalProperties: false }),
  }, { additionalProperties: false }), { additionalProperties: false }),
  elastic_budget: Type.Partial(Type.Object({
    ...POLICY_SCHEMA.properties.elastic_budget.properties,
    pool_percent: Type.Partial(POLICY_SCHEMA.properties.elastic_budget.properties.pool_percent, { additionalProperties: false }),
    window_weights: Type.Partial(POLICY_SCHEMA.properties.elastic_budget.properties.window_weights, { additionalProperties: false }),
  }, { additionalProperties: false }), { additionalProperties: false }),
  window_auto: Type.Partial(POLICY_SCHEMA.properties.window_auto, { additionalProperties: false }),
  state_policy: Type.Partial(POLICY_SCHEMA.properties.state_policy, { additionalProperties: false }),
  read: Type.Partial(POLICY_SCHEMA.properties.read, { additionalProperties: false }),
  source_cache: Type.Partial(POLICY_SCHEMA.properties.source_cache, { additionalProperties: false }),
}, { additionalProperties: false }), { additionalProperties: false });
function rejectUndefined(value: unknown): void {
  if (typeof value !== "object" || value === null) return;
  for (const child of Object.values(value)) {
    if (child === undefined) throw Error("INVALID_CONFIG: undefined field");
    rejectUndefined(child);
  }
}
function mergeObject(base: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const result = { ...base };
  for (const [key, value] of Object.entries(patch)) result[key] = value && typeof value === "object" && !Array.isArray(value)
    ? mergeObject(base[key] as Record<string, unknown>, value as Record<string, unknown>) : value;
  return result;
}
/** Validate the partial file before provider lookup; resolve N/B only after verified capacity. */
export function configInput(value: unknown): typeof DEFAULT_STATE & Partial<Pick<CoreConfig, "recent_turns" | "evict_turns">> & PolicySettings {
  if (!Check(fileSchema, value)) throw Error("INVALID_CONFIG: unsupported fields or invalid configuration");
  rejectUndefined(value);
  const policies = mergeObject(DEFAULT_SETTINGS as unknown as Record<string, unknown>,
    Object.fromEntries(POLICY_KEYS.filter(key => Object.hasOwn(value, key)).map(key => [key, value[key]])));
  validateSettings(policies);
  return freezeConfig({ ...DEFAULT_STATE, ...value, ...policies });
}
export function parseConfig(value: unknown, contextLimit?: number): ResolvedConfig {
  return mergeConfig(value, {}, contextLimit);
}
export function mergeConfig(global: unknown, overrides: unknown = {}, contextLimit?: number): ResolvedConfig {
  const input = configInput(global);
  if (!Check(overridesSchema, overrides)) throw Error("INVALID_CONFIG: invalid branch overrides");
  rejectUndefined(overrides);
  const values = { ...input, ...overrides };
  let N = values.recent_turns;
  const auto = values.window_auto;
  if (N === undefined) {
    if (contextLimit === undefined) throw Error("MODEL_CAPACITY_UNVERIFIED: automatic Window requires verified capacity");
    if (!Number.isSafeInteger(contextLimit) || contextLimit < 1) throw Error("MODEL_CAPACITY_UNVERIFIED");
    const available = percentOf(contextLimit, values.context_budget.parts_percent.window);
    const step = BigInt(auto.event_step);
    const count = Number(BigInt(available) / (BigInt(auto.messages_per_event) * BigInt(auto.tokens_per_message) * step) * step);
    N = Math.max(auto.min_events, Math.min(auto.max_events, count));
  }
  const B = values.evict_turns ?? Math.max(1, Number((BigInt(N) * BigInt(percentUnits(auto.evict_percent)) + 9999n) / 10000n));
  const result = { ...values, recent_turns: N, evict_turns: B };
  if (!Check(CONFIG_SCHEMA, Object.fromEntries(CONFIG_KEYS.map(key => [key, result[key]]))) || B > N)
    throw Error("INVALID_CONFIG: invalid effective values or evict_turns exceeds recent_turns");
  return freezeConfig(result);
}
