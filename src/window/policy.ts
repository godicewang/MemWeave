import { DEFAULT_SETTINGS, percentOf, type PolicySettings } from "../config/defaults.ts";
/** Percentages are planning allocations; only safety/output and State admission are hard reservations. */
export function budgetPlan(limit: number, settings: PolicySettings = DEFAULT_SETTINGS) {
  if (!Number.isSafeInteger(limit) || limit < 1)
    throw Error("MODEL_CAPACITY_UNVERIFIED");
  const part = (key: keyof PolicySettings["context_budget"]["parts_percent"]) => percentOf(limit, settings.context_budget.parts_percent[key]);
  const rest = {
    state: part("state"),
    output: part("output"),
    system: part("system"),
    user: part("user"),
    read: part("read"),
    protocol: part("protocol"),
    safety: part("safety"),
  };
  return Object.freeze({
    ...rest,
    window: limit - Object.values(rest).reduce((a, b) => a + b, 0),
  });
}
