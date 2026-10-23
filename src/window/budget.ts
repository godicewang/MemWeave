import type { NativeMessage } from "./select.ts";
import { conservativeCounter, type TokenCounter } from "./tokens.ts";
import { budgetPlan } from "./policy.ts";
export const textCost = conservativeCounter.count;
export const budgetError = () =>
  Error(
    "CONTEXT_BUDGET_EXCEEDED: necessary input/output exceeds 60% context; reduce input/read range or use a larger model to organize State",
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
export function allocate(input: {
  limit: number;
  system: number;
  state: number;
  output: number;
  reminder: number;
  messages: BudgetMessage[];
  imageCost: (image: unknown) => number;
  counter?: TokenCounter;
}) {
  const counter = input.counter ?? conservativeCounter,
    plan = budgetPlan(input.limit);
  const M = input.messages.length,
    R = input.system,
    S = input.state,
    O = input.output,
    A = plan.safety;
  let P = input.reminder,
    U = 0,
    X = 0;
  for (const item of input.messages) {
    const m = item.message,
      text = counter.count(
        (item.head ? item.head + "\n" : "") + ordinaryText(m),
      );
    let images = 0;
    if (Array.isArray(m.content))
      for (const part of m.content)
        if (part.type === "image") images += input.imageCost(part);
    const envelope = protocolCost(m, counter);
    if (item.read) X += text + images + envelope;
    else if (item.exempt) U += text + images + envelope;
    else {
      P += envelope;
      if (images) throw Error("UNREFERENCED_WINDOW_IMAGE");
    }
  }
  const H = P + A,
    fixed = R + S + O + H + U + X;
  if (
    !Number.isSafeInteger(fixed) ||
    fixed > input.limit ||
    [R, S, O, P, A, U, X].some((n) => !Number.isSafeInteger(n) || n < 0)
  )
    throw budgetError();
  const Q = M ? Math.floor((input.limit - fixed) / M) : 0;
  for (const item of input.messages)
    if (!item.exempt) {
      const lead = item.head ? item.head + "\n" : "";
      if (
        counter.count(lead + ordinaryText(item.message)) > Q &&
        counter.count(lead + tag) > Q
      )
        throw budgetError();
    }
  return Object.freeze({
    R,
    S,
    O,
    P,
    A,
    H,
    U,
    X,
    M,
    Q,
    total: fixed + M * Q,
    limit: input.limit,
    plan,
    estimator: counter.estimator,
  });
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
): T {
  const lead = head ? head + "\n" : "",
    body = ordinaryText(message),
    truncated = !exempt && counter.count(lead + body) > Q;
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
