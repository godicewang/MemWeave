import { settingsFor, percentOf, percentUnits, type PolicySettings } from "../config/defaults.ts";
import type { NativeMessage } from "./select.ts";
import { conservativeCounter, type TokenCounter } from "./tokens.ts";
import { budgetPlan } from "./policy.ts";
export const textCost = conservativeCounter.count;
export const budgetError = () =>
  Error(
    "CONTEXT_BUDGET_EXCEEDED: necessary input/output exceeds configured context budget; reduce input/read range or use a larger model to organize State",
  );
const tag = "\n[TRUNCATED]";
const protectedText = (p: object) => "textSignature" in p;
export function ordinaryText(message: NativeMessage): string {
  return typeof message.content === "string"
    ? message.content
    : message.content
        .map((p) => (p.type === "text" && !protectedText(p) ? p.text : ""))
        .join("");
}
export interface BudgetMessage {
  message: NativeMessage;
  head: string;
  exempt: boolean;
  read?: boolean;
  group?: "current" | "recent" | "older" | "expired";
  event?: string;
}
/** Counts transmitted structural content, not local Session/usage/timestamp/details metadata. */
export function protocolCost(
  message: NativeMessage,
  counter: TokenCounter,
): number {
  let result = 32 + counter.count(message.role);
  if (message.role === "toolResult")
    result +=
      counter.count(message.toolName) + counter.count(message.toolCallId);
  if (Array.isArray(message.content))
    for (const p of message.content) {
      if (p.type === "toolCall")
        result +=
          16 +
          counter.count(p.name) +
          counter.count(p.id) +
          counter.count(JSON.stringify(p.arguments)) +
          counter.count(p.thoughtSignature ?? "") +
          counter.count(p.namespace ?? "");
      else if (p.type === "thinking")
        result +=
          16 +
          counter.count(p.thinking) +
          counter.count(p.thinkingSignature ?? "");
      else if (p.type === "text" && protectedText(p))
        result +=
          16 + counter.count(p.text) + counter.count(p.textSignature ?? "");
      else result += 8; // Native block boundaries; image cost is charged separately.
    }
  return result;
}
/** Bounded integer water filling; saturated/empty demands return their share to peers. */
export function distribute(capacity: number, demand: number[], weights = demand.map(() => 1)): number[] {
  const result = demand.map(() => 0);
  let remaining = capacity;
  while (remaining > 0) {
    const active = demand.map((n, i) => n > result[i]! && weights[i]! > 0 ? i : -1).filter(i => i >= 0);
    if (!active.length) break;
    const total = active.reduce((n, i) => n + BigInt(weights[i]!), 0n);
    let spent = 0;
    for (const i of active) {
      const share = Number(BigInt(remaining) * BigInt(weights[i]!) / total);
      const add = Math.min(demand[i]! - result[i]!, share);
      result[i]! += add;
      spent += add;
    }
    if (!spent) {
      for (const i of active.slice(0, remaining)) { result[i]!++; spent++; }
    }
    remaining -= spent;
  }
  return result;
}
export interface MessageAllocation {
  tokens: number;
  used: number;
  keepImages: boolean[];
  forceTag: boolean;
  exempt: boolean;
}
export function renderAllocated(item: BudgetMessage, allocation: MessageAllocation, counter: TokenCounter = conservativeCounter): NativeMessage {
  const message = structuredClone(item.message);
  if (Array.isArray(message.content)) {
    let i = 0;
    Object.assign(message, { content: message.content.filter(p => p.type !== "image" || allocation.keepImages[i++]) });
  }
  return renderMessage(message, item.head, allocation.tokens, allocation.exempt, counter, allocation.forceTag);
}
export function allocate(input: {
  limit: number; // Base only: State admission, output, safety and automatic N/B retain this meaning.
  capacity?: number; // Verified model capacity; no reconstruction from a rounded base.
  system: number; state: number; output: number; reminder: number;
  messages: BudgetMessage[]; imageCost: (image: unknown) => number;
  counter?: TokenCounter; settings?: PolicySettings;
}) {
  const counter = input.counter ?? conservativeCounter, settings = settingsFor(input.settings),
    policy = settings.elastic_budget, plan = budgetPlan(input.limit, settings);
  if (input.capacity !== undefined && (!Number.isSafeInteger(input.capacity) || input.capacity < 2 ||
    percentOf(input.capacity, settings.context_budget.model_percent) !== input.limit)) throw budgetError();
  const extra = input.capacity === undefined ? 0 : percentOf(input.capacity, policy.extra_model_percent),
    peak = input.limit + extra, R = input.system, S = input.state, O = input.output, A = plan.safety;
  let P = input.reminder, U = 0;
  const data = input.messages.map(item => {
    const lead = item.head ? item.head + "\n" : "", text = counter.count(lead + ordinaryText(item.message)),
      imageCosts = Array.isArray(item.message.content) ? item.message.content.filter(p => p.type === "image").map(input.imageCost) : [],
      images = imageCosts.reduce((n, v) => n + v, 0), envelope = protocolCost(item.message, counter),
      minimum = Math.min(text, counter.count(lead + tag));
    if (item.exempt && !item.read) U += text + images + envelope;
    else {
      P += envelope;
      if (!item.read && images) throw Error("UNREFERENCED_WINDOW_IMAGE");
    }
    return { text, imageCosts, images, minimum: images ? counter.count(lead + tag) : minimum,
      demand: images ? Math.max(text, counter.count(lead + tag)) + images : text };
  });
  const K = R + S + U + P + O + A;
  if (![input.limit, peak, K, R, S, U, P, O, A, ...data.flatMap(d => [d.text, ...d.imageCosts])]
    .every(n => Number.isSafeInteger(n) && n >= 0) || K > peak) throw budgetError();
  const F = peak - K, readLimit = percentOf(F, policy.pool_percent.read),
    windowLimit = percentOf(F, policy.pool_percent.window), poolSafety = F - readLimit - windowLimit,
    expiredLimit = percentOf(windowLimit, policy.expired_read_percent), quotas = data.map(() => 0);
  const indices = input.messages.map((_, i) => i),
    reads = indices.filter(i => input.messages[i]!.read),
    expired = indices.filter(i => !input.messages[i]!.exempt && !input.messages[i]!.read && input.messages[i]!.group === "expired"),
    ordinary = indices.filter(i => !input.messages[i]!.exempt && !input.messages[i]!.read && input.messages[i]!.group !== "expired");
  const sum = (ids: number[], field: "demand" | "minimum") => ids.reduce((n, i) => n + data[i]![field], 0);
  // First retain each reference/tag, then share within events and messages. No preliminary rendering pass.
  function assign(ids: number[], capacity: number) {
    const minimum = sum(ids, "minimum");
    if (!Number.isSafeInteger(minimum) || minimum > capacity) throw budgetError();
    const events = new Map<string, number[]>();
    for (const i of ids) {
      quotas[i] = data[i]!.minimum;
      const key = input.messages[i]!.event ?? String(i);
      events.set(key, [...(events.get(key) ?? []), i]);
    }
    const groups = [...events.values()], demands = groups.map(group => sum(group, "demand") - sum(group, "minimum"));
    const allocations = distribute(capacity - minimum, demands);
    groups.forEach((group, j) => {
      const perMessage = distribute(allocations[j]!, group.map(i => data[i]!.demand - data[i]!.minimum));
      group.forEach((i, k) => { quotas[i]! += perMessage[k]!; });
    });
  }
  assign(reads, readLimit);
  assign(expired, Math.min(expiredLimit, sum(expired, "demand")));
  const expiredQuota = expired.reduce((n, i) => n + quotas[i]!, 0), available = windowLimit - expiredQuota,
    keys = ["current", "recent", "older"] as const,
    groups = keys.map(key => ordinary.filter(i => (input.messages[i]!.group ?? "older") === key)),
    minima = groups.map(ids => sum(ids, "minimum")), minTotal = minima.reduce((n, v) => n + v, 0);
  if (!Number.isSafeInteger(minTotal) || minTotal > available) throw budgetError();
  const shares = distribute(available - minTotal, groups.map((ids, i) => sum(ids, "demand") - minima[i]!),
    keys.map(key => percentUnits(policy.window_weights[key])));
  groups.forEach((ids, i) => assign(ids, minima[i]! + shares[i]!));
  const allocations: MessageAllocation[] = data.map((d, i) => {
    const item = input.messages[i]!, exempt = item.exempt && !item.read;
    if (exempt) return { tokens: d.text, used: d.text + d.images, keepImages: d.imageCosts.map(() => true), forceTag: false, exempt: true };
    let remaining = quotas[i]!;
    const keepImages = d.imageCosts.map(cost => {
      if (cost > remaining - d.minimum) return false;
      remaining -= cost;
      return true;
    });
    return { tokens: remaining, used: 0, keepImages, forceTag: keepImages.some(keep => !keep), exempt: false };
  });
  let X = 0, windowUsed = 0, expiredUsed = 0;
  input.messages.forEach((item, i) => {
    if (allocations[i]!.exempt) return;
    const shown = renderAllocated(item, allocations[i]!, counter),
      used = counter.count(ordinaryText(shown)) + data[i]!.imageCosts.reduce((n, cost, j) => n + (allocations[i]!.keepImages[j] ? cost : 0), 0);
    allocations[i]!.used = used;
    if (item.read) X += used;
    else { windowUsed += used; if (item.group === "expired") expiredUsed += used; }
  });
  if (X > readLimit || windowUsed > windowLimit || expiredUsed > expiredLimit) throw budgetError();
  allocations.forEach(value => { Object.freeze(value.keepImages); Object.freeze(value); });
  return Object.freeze({ R, S, O, P, A, H: P + A, U, X, M: input.messages.length,
    allocations: Object.freeze(allocations), K, F, extra, peak, readLimit, windowLimit, poolSafety,
    windowUsed, expiredLimit, expiredUsed,
    total: K + X + windowUsed, limit: input.limit, plan, estimator: counter.estimator });
}
/** Search at code-point boundaries and verify the result; BPE prefix counts need not be monotone. */
function fit(
  text: string,
  lead: string,
  tail: string,
  Q: number,
  counter: TokenCounter,
): string {
  if (counter.count(lead + tail) > Q) throw budgetError();
  const points = Array.from(text);
  let low = 0,
    high = points.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (counter.count(lead + points.slice(0, mid).join("") + tail) <= Q)
      low = mid;
    else high = mid - 1;
  }
  let value = points.slice(0, low).join("");
  while (counter.count(lead + value + tail) > Q && low > 0)
    value = points.slice(0, --low).join("");
  if (counter.count(lead + value + tail) > Q) throw budgetError();
  return value;
}
export function renderMessage<T extends NativeMessage>(
  message: T,
  head: string,
  Q: number,
  exempt: boolean,
  counter: TokenCounter = conservativeCounter,
  forceTag = false,
): T {
  const lead = head ? head + "\n" : "",
    body = ordinaryText(message),
    truncated = !exempt && (forceTag || counter.count(lead + body) > Q);
  const shown = truncated ? fit(body, lead, tag, Q, counter) : body;
  const copy = structuredClone(message);
  if (typeof copy.content === "string")
    copy.content = lead + shown + (truncated ? tag : "");
  else {
    let remaining = shown.length;
    const content = copy.content.map((p) => {
      if (p.type !== "text" || protectedText(p)) return p;
      const text = p.text.slice(0, remaining);
      remaining -= text.length;
      return { ...p, text };
    });
    if (lead) content.unshift({ type: "text", text: lead });
    if (truncated) content.push({ type: "text", text: tag });
    Object.assign(copy, { content });
  }
  return copy;
}
