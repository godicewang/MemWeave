import type { NativeMessage } from "./select.ts";
export const textCost = (text: string) => Buffer.byteLength(text, "utf8");
export const budgetError = () =>
  Error(
    "CONTEXT_BUDGET_EXCEEDED: fixed costs or minimum presentation exceed half context",
  );
const tag = "\n[TRUNCATED]";
function protectedText(p: object) {
  return "textSignature" in p;
}
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
export function allocate(input: {
  limit: number;
  system: number;
  state: number;
  output: number;
  reminder: number;
  messages: BudgetMessage[];
  imageCost: (image: unknown) => number;
}) {
  const M = input.messages.length,
    R = input.system,
    S = input.state,
    O = input.output;
  let H = 4096 + input.reminder,
    U = 0,
    X = 0;
  for (const item of input.messages) {
    const message = item.message;
    const text = textCost(
      (item.head ? item.head + "\n" : "") + ordinaryText(message),
    );
    let images = 0;
    const copy = {
      ...message,
      content:
        typeof message.content === "string"
          ? ""
          : message.content
              .filter((p) => {
                if (p.type === "image") {
                  images += input.imageCost(p);
                  return false;
                }
                return true;
              })
              .map((p) =>
                p.type === "text" && !protectedText(p) ? { ...p, text: "" } : p,
              ),
    };
    const envelope = 64 + textCost(JSON.stringify(copy));
    if (item.read) X += text + images + envelope;
    else if (item.exempt) U += text + images + envelope;
    else {
      H += envelope;
      if (images) throw Error("UNREFERENCED_WINDOW_IMAGE");
    }
  }
  const fixed = R + S + O + H + U + X;
  if (
    !Number.isSafeInteger(fixed) ||
    !Number.isSafeInteger(input.limit) ||
    fixed > input.limit
  )
    throw budgetError();
  const Q = M ? Math.floor((input.limit - fixed) / M) : 0;
  for (const item of input.messages)
    if (!item.exempt) {
      const head = textCost(item.head ? item.head + "\n" : ""),
        body = ordinaryText(item.message);
      if (Q < head + (textCost(body) > Q - head ? textCost(tag) : 0))
        throw budgetError();
    }
  return Object.freeze({
    R,
    S,
    O,
    H,
    U,
    X,
    M,
    Q,
    total: fixed + M * Q,
    limit: input.limit,
    estimator: "utf8-bytes-with-protocol-margin",
  });
}
function prefix(text: string, bytes: number) {
  let result = "";
  for (const point of text) {
    const n = textCost(point);
    if (n > bytes) break;
    result += point;
    bytes -= n;
  }
  return result;
}
export function renderMessage<T extends NativeMessage>(
  message: T,
  head: string,
  Q: number,
  exempt: boolean,
): T {
  const lead = head ? head + "\n" : "",
    body = ordinaryText(message);
  const truncated = !exempt && textCost(lead + body) > Q;
  const available = exempt
    ? Infinity
    : Q - textCost(lead) - (truncated ? textCost(tag) : 0);
  if (available < 0) throw budgetError();
  const copy = structuredClone(message);
  if (typeof copy.content === "string")
    copy.content =
      lead + (exempt ? body : prefix(body, available)) + (truncated ? tag : "");
  else {
    let remaining = available;
    const content = copy.content.map((p) => {
      if (p.type !== "text" || protectedText(p)) return p;
      const text = exempt ? p.text : prefix(p.text, remaining);
      remaining =
        !exempt && text.length < p.text.length ? 0 : remaining - textCost(text);
      return { ...p, text };
    });
    if (lead) content.unshift({ type: "text", text: lead });
    if (truncated) content.push({ type: "text", text: tag });
    Object.assign(copy, { content });
  }
  return copy;
}
