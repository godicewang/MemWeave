import type { ImageContent } from "@earendil-works/pi-ai";
import type { MemoryReadOutput } from "../memory/service.ts";
import type { HistoricalStateRead } from "../state/read.ts";
import type { TokenCounter } from "./tokens.ts";
import { distribute } from "./budget.ts";

export const READ_TRUNCATION_TAG = "\n[TRUNCATED]";
const chars = (text: string) => [...text].length;
const prefix = (text: string, limit: number) => [...text].slice(0, limit).join("");
const failure = (limit: number) => Error(`READ_BUDGET_EXCEEDED: required result metadata exceeds available ${limit} tokens; request fewer refs/items or a smaller range`);

/** Older results may shrink inside the read pool; native callers provide only verified call keys. */
export function readShares(limit: number, existing: ReadonlyMap<string, number>, calls: string[]) {
  const all = [...new Set([...existing.keys(), ...calls])],
    shares = distribute(limit, all.map(key => existing.get(key) ?? limit)),
    quotas = new Map(calls.map(key => [key, shares[all.indexOf(key)]!]));
  return { quotas, available: [...quotas.values()].reduce((n, value) => n + value, 0) };
}

/** Search character budgets but verify the complete wire body, including JSON and image charges. */
function bounded<T>(full: T, maxChars: number, shrink: (n: number) => T,
  cost: (value: T, tagged: boolean) => number, limit: number) {
  const fullTokens = cost(full, false);
  if (fullTokens <= limit) return { value: full, tokens: fullTokens, truncated: false };
  if (cost(shrink(0), true) > limit) throw failure(limit);
  let low = 0, high = maxChars;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (cost(shrink(mid), true) <= limit) low = mid;
    else high = mid - 1;
  }
  let value = shrink(low), tokens = cost(value, true);
  // JSON escaping and BPE merges do not promise monotone token counts.
  while (tokens > limit && low > 0) { value = shrink(--low); tokens = cost(value, true); }
  if (tokens > limit) throw failure(limit);
  return { value, tokens, truncated: true };
}

export function boundMemoryRead(output: MemoryReadOutput, limit: number, counter: TokenCounter,
  imageCost: (image: ImageContent) => number, overhead = 64) {
  const original = structuredClone(output), keep = original.images.map(() => true);
  const imageItems = original.imageItems ?? original.result.items.flatMap((item, i) =>
    item.ref.startsWith("R") && item.status === "ok" && item.total_chars === 0 && item.range_complete ? [i] : []);
  if (imageItems.length !== original.images.length) throw Error("INVALID_READ_IMAGE_LOCATIONS");
  function shrink(budget: number): MemoryReadOutput {
    const value = structuredClone(original);
    for (const item of value.result.items) {
      const content = prefix(item.content, budget);
      budget -= chars(content);
      if (content !== item.content) {
        item.content = content;
        item.truncated = true;
        item.range_complete = false;
        if (!content && item.status === "ok") item.status = "budget_exhausted";
      }
    }
    value.result.total_chars = value.result.items.reduce((n, item) => n + chars(item.content), 0);
    value.images = value.images.filter((_, i) => keep[i]);
    value.imageItems = imageItems.filter((_, i) => keep[i]);
    imageItems.forEach((itemIndex, i) => {
      if (keep[i]) return;
      Object.assign(value.result.items[itemIndex]!, { truncated: true, range_complete: false, status: "budget_exhausted" });
    });
    return value;
  }
  const cost = (value: MemoryReadOutput, tagged: boolean) => counter.count(JSON.stringify(value.result)) +
    (tagged ? counter.count(READ_TRUNCATION_TAG) : 0) + value.images.reduce((n, image) => n + imageCost(image), 0) + overhead;
  // Keep images whole whenever their cost plus the mandatory response metadata fits.
  for (let i = keep.length - 1; i >= 0 && cost(shrink(0), true) > limit; i--) keep[i] = false;
  const full = shrink(original.result.total_chars), removedImage = keep.some(kept => !kept);
  const result = bounded(full, original.result.total_chars, shrink,
    (value, tagged) => cost(value, tagged || removedImage), limit);
  return { ...result, truncated: result.truncated || removedImage };
}

export function boundStateRead(output: HistoricalStateRead, limit: number, counter: TokenCounter, overhead = 64) {
  function shrink(budget: number): HistoricalStateRead {
    const value = structuredClone(output);
    for (const item of value.items) {
      if (item.status === "not_found") continue;
      const originalChars = item.returned_chars;
      item.content = prefix(item.content, budget);
      budget -= chars(item.content);
      const evidence: Record<string, string> = {};
      for (const [ref, text] of Object.entries(item.evidence)) {
        const key = chars(ref);
        if (budget < key) break;
        budget -= key;
        evidence[ref] = prefix(text, budget);
        budget -= chars(evidence[ref]!);
        if (evidence[ref] !== text) break;
      }
      item.evidence = evidence;
      item.returned_chars = chars(item.content) + Object.entries(evidence).reduce((n, [ref, text]) => n + chars(ref) + chars(text), 0);
      item.truncated = item.total_chars !== item.returned_chars;
      if (originalChars && !item.returned_chars) item.status = "budget_exhausted";
    }
    value.total_chars = value.items.reduce((n, item) => n + item.returned_chars, 0);
    return value;
  }
  return bounded(output, output.total_chars, shrink, (value, tagged) =>
    counter.count(JSON.stringify(value)) + (tagged ? counter.count(READ_TRUNCATION_TAG) : 0) + overhead, limit);
}
