import { Type, type Static } from "typebox";
import { Check } from "typebox/value";

const positiveInteger = () => Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER });
export const CONFIG_SCHEMA = Type.Object({
  recent_turns: positiveInteger(), evict_turns: positiveInteger(),
  state_max_events: positiveInteger(), state_event_max_chars: positiveInteger(),
  state_evict_batch: positiveInteger(), state_keep_limit: positiveInteger(),
}, { additionalProperties: false });
const OVERRIDES_SCHEMA = Type.Partial(CONFIG_SCHEMA);
export type MemoryConfig = Readonly<Static<typeof CONFIG_SCHEMA>>;
export const DEFAULT_CONFIG: MemoryConfig = Object.freeze({
  recent_turns: 200, evict_turns: 40, state_max_events: 2000,
  state_event_max_chars: 100, state_evict_batch: 200, state_keep_limit: 20,
});
export const CONFIG_KEYS = Object.freeze(Object.keys(DEFAULT_CONFIG) as Array<keyof MemoryConfig>);

function invalidFields(value: unknown, partial = false): never {
  const object = typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
  const invalid = CONFIG_KEYS.filter(key => (!partial || Object.hasOwn(object, key)) &&
    (typeof object[key] !== "number" || !Number.isSafeInteger(object[key]) || (object[key] as number) < 1));
  // Never include untrusted keys, values or JSON parser snippets in diagnostics.
  throw new Error(`INVALID_CONFIG: ${invalid.length ? `invalid or missing ${invalid.join(", ")}` : "unsupported configuration fields or object"}`);
}

export function parseConfig(value: unknown): MemoryConfig {
  if (!Check(CONFIG_SCHEMA, value)) invalidFields(value);
  if (value.evict_turns > value.recent_turns) {
    throw new Error("INVALID_CONFIG: evict_turns must not exceed recent_turns");
  }
  return Object.freeze({ ...value });
}

export function mergeConfig(global: unknown, overrides: unknown = {}): MemoryConfig {
  const defaults = parseConfig(global);
  if (!Check(OVERRIDES_SCHEMA, overrides)) invalidFields(overrides, true);
  return parseConfig({ ...defaults, ...overrides });
}
