import { conservativeCounter, type TokenCounter } from "./tokens.ts";

/** One prepare call only. Counts are exact; no token IDs or cross-request bodies are retained. */
export function createRequestCounter(
  base: TokenCounter,
  maxEntries = 4096,
  maxBytes = 32 * 1024 * 1024,
) {
  const cache = new Map<string, { count: number; bytes: number }>();
  // UTF-8 byte counting is cheaper than string-cache hashing; preserve its direct path.
  let bytes = 0, active = base.estimator !== conservativeCounter.estimator;
  const counter: TokenCounter = Object.freeze({
    estimator: base.estimator,
    count(text: string) {
      if (!active || !maxEntries || !maxBytes) return base.count(text);
      const previous = cache.get(text);
      if (previous) {
        cache.delete(text);
        cache.set(text, previous);
        return previous.count;
      }
      const count = base.count(text), cost = text.length * 2 + 96;
      if (cost > maxBytes) return count;
      while (cache.size >= maxEntries || bytes + cost > maxBytes) {
        const oldest = cache.keys().next().value;
        if (oldest === undefined) break;
        bytes -= cache.get(oldest)!.bytes;
        cache.delete(oldest);
      }
      cache.set(text, { count, bytes: cost });
      bytes += cost;
      return count;
    },
    ...(base.prefix ? { prefix: (text: string, tokens: number) => base.prefix!(text, tokens) } : {}),
  });
  return {
    counter,
    get size() { return cache.size; },
    get bytes() { return bytes; },
    dispose() {
      active = false;
      cache.clear();
      bytes = 0;
    },
  };
}
