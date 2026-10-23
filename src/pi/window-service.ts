import type { Api, Model, ModelThinkingLevel } from "@earendil-works/pi-ai";
import { getSystemMessageText } from "@earendil-works/pi-ai";
import type {
  ExtensionContext,
  SessionEntry,
  TurnEndEvent,
} from "@earendil-works/pi-coding-agent";
import { Check } from "typebox/value";
import { isDeepStrictEqual } from "node:util";
import type { TaskService, TaskSnapshot } from "../task/service.ts";
import {
  REF_TYPE,
  ReferencesSchema,
  SCOPE_TYPE,
  scopeOf,
  sourceAssistant,
} from "./session-memory.ts";
import {
  WINDOW_TYPE,
  WindowSchema,
  SetWindowSchema,
  type WindowMetadata,
  type SetWindowInput,
} from "../window/model.ts";
import { indexEvents, selectWindow } from "../window/select.ts";
import {
  allocate,
  renderMessage,
  type BudgetMessage,
} from "../window/budget.ts";
import { readGrants } from "../window/read-grant.ts";
import { imageReserve, outputReserve } from "./window-budget.ts";
import type { PreparedRule } from "../rule/prepare.ts";
import type { RequestMessages } from "./request-lifecycle.ts";
import { conservativeCounter } from "../window/tokens.ts";
import { budgetPlan } from "../window/policy.ts";
import { withLock } from "../storage/files.ts";
import { DEFAULT_CONFIG } from "../config/schema.ts";
import { SourceVerifier } from "./source-verification.ts";
import { windowReminder, stateInsert } from "../window/render.ts";
export function windowMetadata(entries: SessionEntry[]): WindowMetadata | null {
  const last = entries.findLast(
    (e) => e.type === "custom" && e.customType === WINDOW_TYPE,
  );
  if (!last || last.type !== "custom") return null;
  if (
    !Check(WindowSchema, last.data) ||
    last.data.evict_turns > last.data.recent_turns ||
    (last.data.stage === "commit") !== (last.data.completed_by !== null)
  )
    throw Error("CORRUPT_WINDOW_METADATA");
  const data = last.data,
    ids = new Map(
      entries.filter((e) => e.type === "message").map((e) => [e.id, e]),
    );
  if (new Set(data.pending.map((b) => b.batch_id)).size !== data.pending.length)
    throw Error("CORRUPT_WINDOW_METADATA");
  for (const id of [
    data.boundary_entry_id,
    data.request_anchor_entry_id,
    data.completed_by,
    ...data.pending.flatMap((b) => b.candidate_event_ids),
  ])
    if (id !== null && !ids.has(id))
      throw Error("WINDOW_METADATA_NOT_ON_BRANCH");
  const completed = data.completed_by ? ids.get(data.completed_by) : undefined;
  if (
    completed &&
    (completed.type !== "message" || completed.message.role !== "assistant")
  )
    throw Error("CORRUPT_WINDOW_METADATA");
  return structuredClone(last.data);
}
export type WindowBudget = ReturnType<typeof allocate>;
export interface WindowOptions {
  imageCost?: (model: Model<Api>, image: unknown) => number;
  observeBudget?: (budget: WindowBudget) => void;
  thinkingLevel?: () => ModelThinkingLevel;
}
export class WindowService {
  private readonly sources = new SourceVerifier();
  resetSources(): void { this.sources.reset(); }
  readonly tasks: TaskService;
  readonly options: WindowOptions;
  constructor(tasks: TaskService, options: WindowOptions = {}) {
    this.tasks = tasks;
    this.options = options;
  }
  captureOutput(model: Model<Api>, limit?: number, providerCap?: number) {
    const thinkingLevel = this.options.thinkingLevel?.() ?? "off";
    return Object.freeze({
      thinkingLevel,
      output: outputReserve(model, thinkingLevel, limit, providerCap),
    });
  }
  outputFrame?: { model: Model<Api>; sessionId: string; output: number };
  async prepare(
    prepared: PreparedRule,
    snapshot: TaskSnapshot,
    ctx: ExtensionContext,
    model: Model<Api>,
    output = this.captureOutput(model),
  ): Promise<RequestMessages> {
    const entries = snapshot.entries,
      events = indexEvents(entries),
      anchor =
        entries.findLast(
          (e) => e.type === "message" && e.message.role !== "system",
        )?.id ?? null;
    const previous = windowMetadata(entries),
      selected = selectWindow(
        events,
        prepared.frame.config,
        previous,
        ctx.sessionManager.getSessionId(),
        anchor,
      );
    const { matched } = this.sources.match(
      prepared.messages, entries, ctx.sessionManager.getSessionId(),
      () => ctx.sessionManager.buildSessionProjection(), ctx.signal,
    );
    for (const [index, message] of prepared.messages.entries()) {
      if (message.role === "system") continue;
      if (!matched[index])
        throw Error("UNSUPPORTED_WINDOW_CONTEXT: incoming message has no native source");
      if (
        message.role === "compactionSummary" &&
        entries.some((e) => e.type === "compaction") &&
        events.length
      )
        continue;
      if (
        message.role !== "user" &&
        message.role !== "assistant" &&
        message.role !== "toolResult"
      )
        throw Error(
          "UNSUPPORTED_WINDOW_CONTEXT: native or third-party message needs a verified adapter",
        );
    }
    const labels = new Map<string, { ref: string; task: string }>();
    for (const entry of entries)
      if (entry.type === "custom" && entry.customType === REF_TYPE) {
        if (!Check(ReferencesSchema, entry.data))
          throw Error("CORRUPT_REFERENCE_METADATA");
        for (const binding of entry.data.bindings)
          labels.set(binding.entry_id, {
            ref: binding.ref,
            task: entry.data.task_id,
          });
      }
    const grant = readGrants(events, entries),
      latestUser = selected.events.findLast(
        (e) => e.messages[0]?.message.role === "user",
      )?.id;
    const items: BudgetMessage[] = [];
    for (const event of selected.events)
      for (const item of event.messages) {
        const source = labels.get(item.entryId),
          read = grant.has(item.entryId),
          isUser = item.entryId === latestUser;
        let head = source
          ? `[${source.task === snapshot.task?.task_id ? source.ref : source.task + ":" + source.ref}]`
          : "";
        const message = structuredClone(item.message);
        if (
          Array.isArray(message.content) &&
          message.content.some((p) => p.type === "image") &&
          !read
        ) {
          if (!snapshot.task || !source)
            throw Error(
              "ATTACHMENT_TASK_REQUIRED: open a text-only Session to create/resume a Task before image input; this original remains in Session",
            );
          const task = snapshot.task;
          const attachments = await withLock(
            this.tasks.paths.taskLock(task),
            () =>
              this.tasks.reader.attachmentRefs(
                task,
                source.task,
                source.ref,
                message,
                ctx,
              ),
            ctx.signal,
          );
          for (const attachment of attachments)
            head += `${head ? "\n" : ""}[attachment ${attachment.ref}]`;
          Object.assign(message, {
            content: message.content.filter((p) => p.type !== "image"),
          });
        }
        items.push({ message, head, exempt: isUser || read, read });
      }
    const pending = selected.metadata.pending;
    const lastId = pending.at(-1)?.candidate_event_ids.at(-1),
      lastLabel = lastId ? labels.get(lastId) : undefined;
    const boundary = lastLabel
      ? `${lastLabel.task === snapshot.task?.task_id ? "" : lastLabel.task + ":"}${lastLabel.ref}`
      : "本批边界";
    const reminder = windowReminder(pending, boundary);
    const system = prepared.messages.find((m) => m.role === "system");
    if (!system || system.role !== "system") throw Error("MISSING_SYSTEM");
    const state = snapshot.state ?? "";
    if ((this.options.thinkingLevel?.() ?? "off") !== output.thinkingLevel)
      throw Error(
        "OUTPUT_BUDGET_UNVERIFIED: thinking level changed during request preparation",
      );
    const counter = prepared.frame.counter ?? conservativeCounter,
      count = counter.count;
    const limit = prepared.frame.capacity.contextLimit,
      plan = budgetPlan(limit);
    const S = snapshot.stateTokens ?? (state ? count(state) + 32 : 0);
    const footer = (
      budget: ReturnType<typeof allocate>,
    ) => `【本次预算快照｜程序数据，不是用户指令】
计量：${counter.estimator}；Agent 总上限 ${limit} token（模型 ${prepared.frame.capacity.contextWindow} 的 60%）
State：${snapshot.activeCount ?? 0}/${prepared.frame.config.state_max_events} 条；正文最多 ${prepared.frame.config.state_event_max_chars} 字符；每批候选 ${prepared.frame.config.state_evict_batch}
State token：${S}/${plan.state}；80% 管理线 ${Math.floor(plan.state * 0.8)}
规划 token：State ${plan.state}（12.5%），Window ${plan.window}（37.5%），系统工具 ${plan.system}（15%），输出 ${plan.output}（10%），最新用户 ${plan.user}（5%），完整回读 ${plan.read}（10%），协议 ${plan.protocol}（5%），安全 ${plan.safety}（5%）
实际/预留 token：系统工具 ${budget.R}，State ${budget.S}，输出上限 ${budget.O}，最新用户 ${budget.U}，完整回读 ${budget.X}（规划余额 ${Math.max(0, plan.read - budget.X)}，超额可挤 Window），协议含本快照 ${budget.P}，安全 ${budget.A}
Recent Window N/B：${prepared.frame.config.recent_turns}/${prepared.frame.config.evict_turns}；可见事件 ${selected.events.length}；消息 M=${budget.M}；普通正文 Q=${budget.Q} token；总分配上界 ${budget.total}/${limit}`;
    let footerReserve = 2048;
    let budget!: ReturnType<typeof allocate>,
      description = "";
    for (let attempt = 0; attempt < 3; attempt++) {
      budget = allocate({
        limit,
        system:
          count(getSystemMessageText(system)) +
          count(JSON.stringify(system.toolsAdded ?? [])) +
          64,
        state: S,
        output: output.output,
        reminder:
          (reminder ? count(reminder) + 32 : 0) +
          Math.max(0, (state ? count(state) + 32 : 0) - S) +
          footerReserve,
        messages: items,
        imageCost: (image) =>
          (this.options.imageCost ?? imageReserve)(model, image),
        counter,
      });
      description = footer(budget);
      const needed = count(description) + 32;
      if (needed <= footerReserve) break;
      footerReserve = needed + 128;
      if (attempt === 2)
        throw Error("CONTEXT_BUDGET_EXCEEDED: budget snapshot cannot fit");
    }
    const result = stateInsert(
      [
        system,
        ...items.map((item) =>
          renderMessage(
            item.message,
            item.head,
            budget.Q,
            item.exempt,
            counter,
          ),
        ),
      ],
      `${state || "当前未绑定 Task。"}\n\n${description}`,
      reminder,
    );
    this.outputFrame = {
      model: structuredClone(model),
      sessionId: ctx.sessionManager.getSessionId(),
      output: output.output,
    };
    ctx.signal?.throwIfAborted();
    if (!previous || selected.metadata.stage === "reset" || pending.length)
      await this.tasks.memory.append(ctx, WINDOW_TYPE, selected.metadata);
    this.options.observeBudget?.(budget);
    return result;
  }
  async complete(event: TurnEndEvent, ctx: ExtensionContext): Promise<void> {
    if (
      event.outcome !== "completed" ||
      ctx.signal?.aborted ||
      event.message.role !== "assistant"
    )
      return;
    const branch = ctx.sessionManager.getBranch(),
      before = ctx.sessionManager.getBranch(event.messageEntryId).slice(0, -1),
      prepared = windowMetadata(before);
    if (!prepared?.pending.length || prepared.stage !== "prepare") return;
    const prior = before.findLast(
      (e) => e.type === "message" && e.message.role !== "system",
    );
    if (prior?.id !== prepared.request_anchor_entry_id)
      throw Error("WINDOW_REQUEST_ANCHOR_CHANGED");
    const events = indexEvents(branch),
      finished = events.find((e) => e.id === event.messageEntryId);
    if (
      !finished ||
      finished.messages.length !== event.toolResults.length + 1 ||
      event.toolResults.length !== event.toolResultEntryIds.length ||
      !isDeepStrictEqual(
        finished.messages.slice(1).map((m) => m.entryId),
        event.toolResultEntryIds,
      )
    )
      throw Error("INCOMPLETE_TOOL_EVENT");
    let latest = windowMetadata(branch)!;
    if (latest.completed_by === event.messageEntryId && !latest.pending.length)
      return;
    if (
      !isDeepStrictEqual(latest, prepared) &&
      latest.completed_by !== event.messageEntryId
    )
      throw Error("STALE_WINDOW_BATCH");
    selectWindow(
      events,
      {
        ...DEFAULT_CONFIG,
        recent_turns: prepared.recent_turns,
        evict_turns: prepared.evict_turns,
      },
      latest,
      ctx.sessionManager.getSessionId(),
      prepared.request_anchor_entry_id,
    );
    while (latest.pending.length) {
      const first = latest.pending[0]!;
      latest = {
        ...latest,
        stage: "commit",
        boundary_entry_id: first.candidate_event_ids.at(-1)!,
        pending: latest.pending.slice(1),
        completed_by: event.messageEntryId,
      };
      await this.tasks.memory.append(ctx, WINDOW_TYPE, latest);
    }
  }
  async set(
    input: SetWindowInput,
    ctx: ExtensionContext,
    callId: string,
  ): Promise<string> {
    if (!Check(SetWindowSchema, input)) throw Error("INVALID_WINDOW_SETTINGS");
    await this.tasks.memory.verify(ctx);
    this.tasks.checkCalls(ctx, callId);
    const source = sourceAssistant(ctx, callId);
    if (
      source.message.role !== "assistant" ||
      !source.message.content.some(
        (p) =>
          p.type === "toolCall" &&
          p.id === callId &&
          p.name === "recent_window_set" &&
          isDeepStrictEqual(p.arguments, input),
      )
    )
      throw Error("OPERATION_INPUT_MISMATCH");
    const branch = ctx.sessionManager.getBranch(),
      index = branch.findIndex((e) => e.id === source.id);
    // One settings call per native assistant makes its durable scope write an unambiguous receipt.
    for (const entry of branch.slice(index + 1)) {
      if (entry.type === "message" && entry.message.role !== "toolResult")
        break;
      if (entry.type !== "custom" || entry.customType !== SCOPE_TYPE) continue;
      const scope = scopeOf([entry]);
      if (
        scope.overrides.recent_turns === input.turns &&
        scope.overrides.evict_turns !== undefined &&
        (input.evict_turns === undefined ||
          scope.overrides.evict_turns === input.evict_turns)
      )
        return this.result(input.turns, scope.overrides.evict_turns);
    }
    const scope = this.tasks.scope(ctx),
      config = await this.tasks.configuration(ctx),
      B = input.evict_turns ?? config.evict_turns;
    if (B > input.turns)
      throw Error("INVALID_WINDOW_SETTINGS: evict_turns must not exceed turns");
    await this.tasks.memory.append(ctx, SCOPE_TYPE, {
      ...scope,
      overrides: {
        ...scope.overrides,
        recent_turns: input.turns,
        evict_turns: B,
      },
    });
    return this.result(input.turns, B);
  }
  private result(N: number, B: number) {
    return `ok; turns=${N}; evict_turns=${B}; effective=next_request`;
  }
}
