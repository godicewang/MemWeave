import { DEFAULT_SETTINGS, percentOf, type PolicySettings } from "../config/defaults.ts";
/** Input must be the verified capacity of the actual model, never its display label. */
export function deriveContextLimit(verifiedModelCapacity: unknown, settings: PolicySettings = DEFAULT_SETTINGS): number {
  if (
    typeof verifiedModelCapacity !== "number" ||
    !Number.isSafeInteger(verifiedModelCapacity) ||
    verifiedModelCapacity < 2
  ) {
    throw new Error(
      "MODEL_CAPACITY_UNVERIFIED: a verified integer token capacity >= 2 is required",
    );
  }
  const limit = percentOf(verifiedModelCapacity, settings.context_budget.model_percent);
  if (limit < 1) throw Error("MODEL_CAPACITY_UNVERIFIED: configured budget is below one token");
  return limit;
}
