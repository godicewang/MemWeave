import { Type, type Static } from "typebox";
import { budgetPlan } from "../window/policy.ts";
import { Check } from "typebox/value";

const positiveInteger = () =>
  Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER });
export const CONFIG_SCHEMA = Type.Object(
  {
    recent_turns: positiveInteger(),
    evict_turns: positiveInteger(),
    state_max_events: positiveInteger(),
    state_event_max_chars: positiveInteger(),
    state_evict_batch: positiveInteger(),
    state_keep_limit: positiveInteger(),
  },
  { additionalProperties: false },
);
const OVERRIDES_SCHEMA = Type.Partial(CONFIG_SCHEMA);
export type MemoryConfig = Readonly<Static<typeof CONFIG_SCHEMA>>;
export const DEFAULT_CONFIG: MemoryConfig = Object.freeze({
  recent_turns: 200,
  evict_turns: 40,
  state_max_events: 500,
  state_event_max_chars: 100,
  state_evict_batch: 100,
  state_keep_limit: 20,
});
export const CONFIG_KEYS = Object.freeze(
  Object.keys(DEFAULT_CONFIG) as Array<keyof MemoryConfig>,
);

function invalidFields(value: unknown, partial = false): never {
  const object =
    typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const invalid = CONFIG_KEYS.filter(
    (key) =>
      (!partial || Object.hasOwn(object, key)) &&
      (typeof object[key] !== "number" ||
        !Number.isSafeInteger(object[key]) ||
        (object[key] as number) < 1),
  );
  // Never include untrusted keys, values or JSON parser snippets in diagnostics.
  throw new Error(
    `INVALID_CONFIG: ${invalid.length ? `invalid or missing ${invalid.join(", ")}` : "unsupported configuration fields or object"}`,
  );
}

const FILE_SCHEMA = Type.Object(
  {
    ...CONFIG_SCHEMA.properties,
    recent_turns: Type.Optional(positiveInteger()),
    evict_turns: Type.Optional(positiveInteger()),
  },
  { additionalProperties: false },
);
function validateFile(value: unknown) {
  if (!Check(FILE_SCHEMA, value)) invalidFields(value);
  for (const key of CONFIG_KEYS)
    if (Object.hasOwn(value, key) && value[key] === undefined)
      invalidFields(value);
  return value;
}
export function parseConfig(
  value: unknown,
  contextLimit?: number,
): MemoryConfig {
  return mergeConfig(value, {}, contextLimit);
}
export function mergeConfig(
  global: unknown,
  overrides: unknown = {},
  contextLimit?: number,
): MemoryConfig {
  const file = validateFile(global);
  if (!Check(OVERRIDES_SCHEMA, overrides)) invalidFields(overrides, true);
  for (const key of CONFIG_KEYS)
    if (Object.hasOwn(overrides, key) && overrides[key] === undefined)
      invalidFields(overrides, true);
  const values = { ...file, ...overrides };
  let N = values.recent_turns;
  if (N === undefined) {
    if (contextLimit === undefined)
      throw Error(
        "MODEL_CAPACITY_UNVERIFIED: automatic Window requires verified capacity",
      );
    budgetPlan(contextLimit); // Validate the capacity before deriving defaults.
    const baseWindow = Number(BigInt(contextLimit) * 3n / 8n);
    N = Math.max(20, Math.min(200, 10 * Math.floor(baseWindow / 5120)));
  }
  const result = {
    ...values,
    recent_turns: N,
    evict_turns: values.evict_turns ?? Math.max(1, Math.ceil(N / 5)),
  };
  if (!Check(CONFIG_SCHEMA, result)) invalidFields(result);
  if (result.evict_turns > result.recent_turns)
    throw Error("INVALID_CONFIG: evict_turns must not exceed recent_turns");
  return Object.freeze(result);
}
