import { Check } from "typebox/value";
import { Type, type Static } from "typebox";
import { isDeepStrictEqual } from "node:util";
import type {
  ExtensionAPI,
  ExtensionContext,
  SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { scopeOf } from "../pi/session-memory.ts";
import { RESTART_TYPE, RestartSchema } from "./restart-model.ts";
import type { TaskService } from "./service.ts";
import { settingsFor } from "../config/defaults.ts";
import { CLARIFY_TOOL_NAME, ClarifySchema } from "./model.ts";
export const BINDING_TYPE = "memweave.task.binding.v1";
export const BINDING_MESSAGE =
  "回答未通过任务绑定检查（TASK_BINDING_REQUIRED）。请先根据最新真实要求选择 task_create 或 task_resume，成功绑定后再继续原任务。目标不明确时先澄清，不编造占位 Goal，不降低验收要求。本消息是程序失败回执，不是用户、事实或证据。";
const id = Type.String({ minLength: 1 });
export const BindingSchema = Type.Object(
  {
    version: Type.Literal(1),
    trigger_user_entry_id: id,
    rejected_assistant_entry_id: id,
    attempt: Type.Integer({ minimum: 1, maximum: 4 }),
    reason: Type.Literal("TASK_BINDING_REQUIRED"),
  },
  { additionalProperties: false },
);
export function latestUser(entries: SessionEntry[]) {
  return entries.findLast(
    (e) => e.type === "message" && e.message.role === "user",
  );
}
const legacyInitialization = (args: unknown) =>
  typeof args === "object" &&
  args !== null &&
  "initialize" in args &&
  args.initialize === true;
const bindingCall = (name: string) => name === "task_create" || name === "task_resume";
function completedClarification(entries: SessionEntry[], source: SessionEntry | undefined): boolean {
  // Tool-call messages can also carry stopReason="stop"; verify their actual result.
  if (source?.type !== "message" || source.message.role !== "assistant") return false;
  const calls = source.message.content.filter((p) => p.type === "toolCall");
  const call = calls.length === 1 ? calls[0] : undefined;
  if (!call || call.name !== CLARIFY_TOOL_NAME || !Check(ClarifySchema, call.arguments)) return false;
  const result = entries.findLast((entry) => entry.type === "message" &&
    entry.message.role === "toolResult" && entry.message.toolCallId === call.id);
  if (!result || entries.indexOf(result) <= entries.indexOf(source) ||
      result.type !== "message" || result.message.role !== "toolResult" ||
      result.message.toolName !== CLARIFY_TOOL_NAME || result.message.isError) return false;
  const details = result.message.details;
  return typeof details === "object" && details !== null &&
    "question" in details && details.question === call.arguments.question &&
    "status" in details && (details.status === "waiting_for_user" || details.status === "input_queued");
}
export function bindingRequired(entries: SessionEntry[]): boolean {
  if (scopeOf(entries).task_id !== null) return false;
  const user = latestUser(entries);
  if (!user) return false;
  const start = entries.indexOf(user);
  return entries
    .slice(start + 1)
    .some(
      (e) =>
        e.type === "message" &&
        e.message.role === "assistant" &&
        e.message.content.some(
          (p) =>
            p.type === "toolCall" &&
            bindingCall(p.name),
        ),
    );
}
type BindingData = Static<typeof BindingSchema>;
type Receipt = Extract<SessionEntry, { type: "custom_message" }> & {
  details: BindingData;
};
export function bindingReceipts(entries: SessionEntry[]): Receipt[] {
  const result: Receipt[] = [],
    byId = new Map<string, SessionEntry>(),
    attempts = new Map<string, number>();
  let task: string | null = null,
    user: SessionEntry | undefined,
    lastAssistant: SessionEntry | undefined,
    declared = false;
  for (const e of entries) {
    if (e.type === "custom" && e.customType === RESTART_TYPE) {
      if (!Check(RestartSchema, e.data))
        throw Error("CORRUPT_RESTART_METADATA");
      task = null;
    }
    if (e.type === "custom" && e.customType === "memweave.scope.v1")
      task = scopeOf([e]).task_id;
    if (e.type === "message" && e.message.role === "user") {
      user = e;
      declared = false;
      lastAssistant = undefined;
    }
    if (e.type === "message" && e.message.role === "assistant") {
      lastAssistant = e;
      if (
        e.message.content.some(
          (p) =>
            p.type === "toolCall" &&
            (bindingCall(p.name) ||
              // Read-only compatibility for receipts emitted before this parameter was removed.
              (p.name === "task_find" && legacyInitialization(p.arguments))),
        )
      )
        declared = true;
    }
    if (e.type === "custom_message" && e.customType === BINDING_TYPE) {
      if (
        !Check(BindingSchema, e.details) ||
        e.content !== BINDING_MESSAGE ||
        !e.display ||
        !Number.isFinite(Date.parse(e.timestamp))
      )
        throw Error("CORRUPT_TASK_BINDING_RECEIPT");
      const details = e.details,
        rejected = byId.get(details.rejected_assistant_entry_id);
      if (
        user?.id !== details.trigger_user_entry_id ||
        rejected !== lastAssistant ||
        rejected?.type !== "message" ||
        rejected.message.role !== "assistant" ||
        rejected.message.stopReason !== "stop" ||
        task !== null ||
        !declared
      )
        throw Error("TASK_BINDING_RECEIPT_SOURCE_MISMATCH");
      const attempt = (attempts.get(user.id) ?? 0) + 1;
      if (details.attempt !== attempt)
        throw Error("CORRUPT_TASK_BINDING_ATTEMPTS");
      attempts.set(user.id, attempt);
      result.push(e as Receipt);
    }
    byId.set(e.id, e);
  }
  return result;
}
export function withoutBindingMessages<T extends { role: string }>(
  messages: T[],
  entries: SessionEntry[],
): T[] {
  const receipts = bindingReceipts(entries);
  return messages.filter((message) => {
    if (
      message.role !== "custom" ||
      !("customType" in message) ||
      message.customType !== BINDING_TYPE
    )
      return true;
    const m = message as unknown as T & {
      content: unknown;
      details: unknown;
      display: boolean;
      timestamp: number;
    };
    if (
      !receipts.some(
        (r) =>
          isDeepStrictEqual(r.content, m.content) &&
          isDeepStrictEqual(r.details, m.details) &&
          r.display === m.display &&
          Date.parse(r.timestamp) === m.timestamp,
      )
    )
      throw Error("TASK_BINDING_RECEIPT_SOURCE_MISMATCH");
    return false;
  });
}
export function bindingNotice(entries: SessionEntry[]): string {
  const receipts = bindingReceipts(entries);
  if (!bindingRequired(entries)) return "";
  const user = latestUser(entries)!;
  return receipts.some((e) => e.details?.trigger_user_entry_id === user.id)
    ? BINDING_MESSAGE
    : "Task 创建/恢复尚未成功绑定。先修正 task_create/task_resume，或单独调用 task_clarify 请求用户补充。";
}
export function registerTaskBinding(
  pi: ExtensionAPI,
  tasks: TaskService,
  report: (error: unknown, ctx: ExtensionContext) => void,
) {
  const allowed = new Set([
    "task_find",
    "state_read",
    "task_status",
    "task_create",
    "task_resume",
    CLARIFY_TOOL_NAME,
  ]);
  pi.on("tool_call", (event, ctx) => {
    if (event.toolName === CLARIFY_TOOL_NAME && event.parentToolCallId)
      return { block: true, reason: "CLARIFICATION_MUST_BE_TOP_LEVEL: call task_clarify directly and alone" };
    // Inspect just the current assistant batch, without copying the entire history.
    let entry = ctx.sessionManager.getLeafEntry();
    while (entry) {
      if (entry.type === "message" && entry.message.role === "user") break;
      if (entry.type === "message" && entry.message.role === "assistant") {
        const calls = entry.message.content.filter((p) => p.type === "toolCall");
        if (calls.some((p) => p.name === CLARIFY_TOOL_NAME) && calls.length !== 1)
          return { block: true, reason: "CLARIFICATION_MUST_BE_ALONE: call task_clarify by itself before any other tools" };
        break;
      }
      entry = entry.parentId ? ctx.sessionManager.getEntry(entry.parentId) : undefined;
    }
    if (
      !allowed.has(event.toolName) &&
      bindingRequired(ctx.sessionManager.getBranch())
    )
      return {
        block: true,
        reason: "TASK_BINDING_REQUIRED: bind a Task before business tools",
      };
    return undefined;
  });
  pi.on("agent_before_settle", async (event, ctx) => {
    if (event.outcome !== "completed" || ctx.signal?.aborted) return;
    try {
      const entries = ctx.sessionManager.getBranch();
      if (!bindingRequired(entries)) return;
      await tasks.memory.verify(ctx);
      const user = latestUser(entries)!,
        last = entries.findLast(
          (e) => e.type === "message" && e.message.role === "assistant",
        );
      if (completedClarification(entries, last)) return;
      if (
        last?.type !== "message" ||
        last.message.role !== "assistant" ||
        last.message.stopReason !== "stop"
      )
        return;
      const receipts = bindingReceipts(entries);
      if (
        receipts.some((e) => e.details?.rejected_assistant_entry_id === last.id)
      )
        return;
      const attempt =
        receipts.filter((e) => e.details?.trigger_user_entry_id === user.id)
          .length + 1;
      const max = settingsFor(await tasks.configuration(ctx)).task_binding
        .max_corrections;
      if (attempt > max) {
        ctx.abort();
        report(
          Error(
            "TASK_BINDING_REQUIRED: correction limit reached; Task not bound",
          ),
          ctx,
        );
      }
      return {
        entries: [
          {
            type: "custom_message" as const,
            customType: BINDING_TYPE,
            content: BINDING_MESSAGE,
            display: true,
            details: {
              version: 1,
              trigger_user_entry_id: user.id,
              rejected_assistant_entry_id: last.id,
              attempt,
              reason: "TASK_BINDING_REQUIRED",
            },
          },
        ],
        continue: attempt <= max,
      };
    } catch (error) {
      ctx.abort();
      report(error, ctx);
      return undefined;
    }
  });
  pi.on("agent_settled", async (_event, ctx) => {
    try {
      await tasks.memory.verify(ctx);
    } catch (error) {
      ctx.abort();
      report(error, ctx);
    }
  });
}
