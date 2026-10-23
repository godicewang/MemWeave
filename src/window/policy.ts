/** Percentages are planning allocations; only safety/output and State admission are hard reservations. */
export function budgetPlan(limit: number) {
  if (!Number.isSafeInteger(limit) || limit < 1)
    throw Error("MODEL_CAPACITY_UNVERIFIED");
  const part = (n: number) => Number((BigInt(limit) * BigInt(n)) / 1000n);
  const rest = {
    state: part(125),
    output: part(100),
    system: part(150),
    user: part(50),
    read: part(100),
    protocol: part(50),
    safety: part(50),
  };
  return Object.freeze({
    ...rest,
    window: limit - Object.values(rest).reduce((a, b) => a + b, 0),
  });
}
