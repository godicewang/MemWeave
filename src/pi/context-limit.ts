/** Input must be the verified capacity of the actual model, never its display label. */
export function deriveContextLimit(verifiedModelCapacity: unknown): number {
  if (
    typeof verifiedModelCapacity !== "number" ||
    !Number.isSafeInteger(verifiedModelCapacity) ||
    verifiedModelCapacity < 2
  ) {
    throw new Error(
      "MODEL_CAPACITY_UNVERIFIED: a verified integer token capacity >= 2 is required",
    );
  }
  return Number((BigInt(verifiedModelCapacity) * 3n) / 5n);
}
