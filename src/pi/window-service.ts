import { DEFAULT_SETTINGS, settingsFor, percentOf, type PolicySettings } from "../config/defaults.ts";
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
import { indexEvents, selectWindow, eventGroups } from "../window/select.ts";
import {
  allocate,
  type BudgetMessage,
} from "../window/budget.ts";
import { readKinds } from "../window/read-grant.ts";
import { imageReserve, outputReserve } from "./window-budget.ts";
import type { PreparedRule } from "../rule/prepare.ts";
import type { RequestMessages } from "./request-lifecycle.ts";
import { createRequestCounter } from "../window/request-counter.ts";
import { conservativeCounter } from "../window/tokens.ts";
import { budgetPlan } from "../window/policy.ts";
import { withLock } from "../storage/files.ts";
import { DEFAULT_CONFIG } from "../config/schema.ts";
import { SourceVerifier } from "./source-verification.ts";
import { CURRENT_USER_HEAD, windowReminder, stateInsert } from "../window/render.ts";
import { boundMemoryRead, boundStateRead, readShares } from "../window/read-budget.ts";
import type { MemoryReadOutput } from "../memory/service.ts";
import type { HistoricalStateRead } from "../state/read.ts";
import type { TokenCounter } from "../window/tokens.ts";
import type { MemoryReadInput } from "../memory/model.ts";
import type { StateReadInput } from "../state/read.ts";
import { RESTART_TYPE, restartMetadata } from "../task/restart-model.ts";
import { restartSeed, restartEvents, validateRestart } from "../window/restart.ts";
import { stableId } from "../storage/identity.ts";
export function windowMetadata(entries: SessionEntry[]): WindowMetadata | null {
  const restart = restartMetadata(entries);
  const last = entries.slice(restart ? restart.position + 1 : 0).findLast(
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
export type WindowBudget = Omit<ReturnType<typeof allocate>, "rendered">;
export interface WindowOptions {
  imageCost?: (model: Model<Api>, image: unknown) => number;
  observeBudget?: (budget: WindowBudget) => void;
  thinkingLevel?: () => ModelThinkingLevel;
}
export class WindowService {
  private readonly sources = new SourceVerifier();
  private readFrames = new WeakMap<object, { model: Model<Api>; sessionId: string; limit: number; available: number;
    batchId?: string; released: number; quotas: Map<string, number>;
    counter: TokenCounter; credits: Map<string, number>; returns: Map<string, { kind: string; result: unknown }> }>();
  resetSources(): void { this.sources.reset(); this.readFrames = new WeakMap(); delete this.outputFrame; }
  private boundRead<T extends { tokens: number }>(ctx: ExtensionContext, callId: string, kind: string, input: unknown,
    create: (available: number, counter: TokenCounter) => T): T {
    const frame = this.readFrames.get(ctx.sessionManager);
    if (!frame || frame.sessionId !== ctx.sessionManager.getSessionId() || !isDeepStrictEqual(frame.model, ctx.model))
      throw Error("READ_BUDGET_UNVERIFIED: prepare a request with the current model before reading originals");
    ctx.signal?.throwIfAborted();
    const source = sourceAssistant(ctx, callId), key = `${source.id}:${callId}`, old = frame.returns.get(key);
    if (source.message.role !== "assistant" || !source.message.content.some(p =>
      p.type === "toolCall" && p.id === callId && p.name === kind && isDeepStrictEqual(p.arguments, input)))
      throw Error("OPERATION_INPUT_MISMATCH");
    if (old) {
      if (old.kind !== kind) throw Error("OPERATION_INPUT_MISMATCH");
      return structuredClone(old.result) as T;
    }
    if (frame.batchId === undefined) {
      // Reserve for all native parallel calls before the first completion. Older reads can
      // shrink inside the read pool, so an offset read is not blocked by a full previous result.
      const keys = source.message.content.flatMap(p => p.type === "toolCall" &&
        (p.name === "memory_read" || p.name === "state_read" && typeof p.arguments === "object" && p.arguments !== null && "event_ids" in p.arguments)
          ? [`${source.id}:${p.id}`] : []);
      Object.assign(frame, readShares(frame.limit, frame.credits, keys));
      frame.batchId = source.id;
    }
    const quota = frame.quotas.get(key);
    if (frame.batchId !== source.id || quota === undefined) throw Error("READ_BUDGET_UNVERIFIED: tool call is outside the prepared batch");
    // No await between checking and committing: parallel tool completions share one pool.
    const result = create(Math.min(frame.available, quota + frame.released), frame.counter);
    frame.available -= result.tokens;
    frame.released += quota - result.tokens;
    frame.quotas.delete(key);
    frame.returns.set(key, { kind, result: structuredClone(result) });
    return result;
  }
  boundMemory(output: MemoryReadOutput, ctx: ExtensionContext, callId: string, input: MemoryReadInput) {
    return this.boundRead(ctx, callId, "memory_read", input, (available, counter) => boundMemoryRead(output, available, counter,
      image => (this.options.imageCost ?? imageReserve)(ctx.model!, image), this.readOverhead(ctx, counter, callId, "memory_read", output.images.length)));
  }
  boundHistory(output: HistoricalStateRead, ctx: ExtensionContext, callId: string, input: StateReadInput) {
    return this.boundRead(ctx, callId, "state_read", input, (available, counter) => boundStateRead(output, available, counter,
      this.readOverhead(ctx, counter, callId, "state_read", 0)));
  }
  private readOverhead(ctx: ExtensionContext, counter: TokenCounter, callId: string, name: string, images: number) {
    // Native envelope, tag block and maximum-length Task/ref heads (including image aliases).
    const ref = counter.count(`[${this.tasks.scope(ctx).task_id ?? "unbound"}:T${Number.MAX_SAFE_INTEGER}]\n`);
    return 32 + counter.count("toolResult") + counter.count(callId) + counter.count(name) + 16 + ref + images * (8 + ref);
  }
  readonly tasks: TaskService;
  readonly options: WindowOptions;
  constructor(tasks: TaskService, options: WindowOptions = {}) {
    this.tasks = tasks;
    this.options = options;
  }
  validateRestart(ctx: ExtensionContext): void {
    const entries = ctx.sessionManager.getBranch(), receipt = restartMetadata(entries);
    if (receipt) validateRestart(entries, receipt);
  }
  async restart(ctx: ExtensionContext): Promise<string> {
    await this.tasks.memory.verify(ctx);
    this.validateRestart(ctx);
    if (this.tasks.pendingRestart(ctx)) return "新 Task 初始化已准备，请发送下一条工作要求。旧记忆仍保留。";
    const entries = ctx.sessionManager.getBranch();
    const anchor = entries.findLast((entry) => entry.type === "message" && entry.message.role !== "system")?.id;
    if (!anchor) return "当前 Session 尚无交互。请发送工作要求，无需清空或重建记忆。";
    if (!this.tasks.resolveCommandBudget) throw Error("STATE_BUDGET_UNVERIFIED");
    const { config } = await this.tasks.resolveCommandBudget(ctx);
    ctx.signal?.throwIfAborted();
    if (!ctx.isIdle() || ctx.hasPendingMessages() || ctx.sessionManager.getLeafId() !== entries.at(-1)?.id)
      throw Error("RESTART_CONTEXT_CHANGED: wait for current input to finish and retry");
    const seed = restartSeed(indexEvents(entries), config.recent_turns), scope = this.tasks.scope(ctx);
    await this.tasks.memory.append(ctx, RESTART_TYPE, {
      restart_id: stableId("restart", ctx.sessionManager.getSessionId(), entries.at(-1)?.id ?? ""),
      previous_task_id: scope.task_id, anchor_entry_id: anchor,
      seed_event_ids: seed.map((event) => event.id), recent_turns: config.recent_turns, evict_turns: config.evict_turns,
    });
    await this.tasks.memory.append(ctx, SCOPE_TYPE, { ...scope, task_id: null });
    this.resetSources();
    return `已从近期 ${seed.length} 个完整事件准备新 Task；旧 Task/State 保留。请发送下一条工作要求以生成新 Goal。`;
  }
  captureOutput(model: Model<Api>, limit?: number, providerCap?: number, settings: PolicySettings = DEFAULT_SETTINGS) {
    const thinkingLevel = this.options.thinkingLevel?.() ?? "off";
    return Object.freeze({
      thinkingLevel,
      output: outputReserve(model, thinkingLevel, limit, providerCap, settings),
    });
  }
  outputFrame?: { model: Model<Api>; sessionId: string; output: number; contextWindow: number };
  async prepare(
    prepared: PreparedRule,
    snapshot: TaskSnapshot,
    ctx: ExtensionContext,
    model: Model<Api>,
    output = this.captureOutput(model, prepared.frame.capacity.contextLimit,
      prepared.frame.capacity.maxOutputTokens, settingsFor(prepared.frame.config)),
  ): Promise<RequestMessages> {
    const settings = settingsFor(prepared.frame.config);
    this.sources.configure(settings.source_cache);
    const entries = snapshot.entries,
      persistedPrevious = windowMetadata(entries),
      receipt = restartMetadata(entries),
      previous = persistedPrevious ?? (receipt ? {
        stage: "prepare" as const, recent_turns: receipt.data.recent_turns, evict_turns: receipt.data.evict_turns,
        boundary_entry_id: null, pending: [], request_anchor_entry_id: receipt.data.anchor_entry_id, completed_by: null,
      } : null),
      events = restartEvents(entries, previous, prepared.frame.config),
      anchor =
        entries.findLast(
          (e) => e.type === "message" && e.message.role !== "system",
        )?.id ?? null;
    if (snapshot.restarting && receipt && !entries.slice(receipt.position + 1).some(
      (entry) => entry.type === "message" && entry.message.role === "user",
    )) throw Error("RESTART_INPUT_REQUIRED: send a real user request after /memweave-restart");
    const selected = selectWindow(
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
    const latestRealUser = events.findLast((event) => event.messages[0]?.message.role === "user")?.id;
    const reads = readKinds(selected.events, entries, settings.read.lifetime_messages),
      latestUser = selected.events.findLast(
        (e) => e.messages[0]?.message.role === "user",
      )?.id;
    const groups = eventGroups(selected.events, settings.elastic_budget.recent_events);
    const items: BudgetMessage[] = [];
    for (const event of selected.events)
      for (const item of event.messages) {
        const source = labels.get(item.entryId),
          read = reads.active.has(item.entryId),
          isUser = item.entryId === latestUser;
        let head = source
          ? `[${source.task === snapshot.task?.task_id ? source.ref : source.task + ":" + source.ref}]`
          : "";
        if (item.entryId === latestRealUser)
          head += `${head ? "\n" : ""}${CURRENT_USER_HEAD}`;
        const message = structuredClone(item.message);
        if (
          Array.isArray(message.content) &&
          message.content.some((p) => p.type === "image")
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
          if (!read) Object.assign(message, {
            content: message.content.filter((p) => p.type !== "image"),
          });
        }
        items.push({ message, head, exempt: isUser || read, read, event: event.id,
          group: reads.expired.has(item.entryId) ? "expired" : groups.get(event.id)! });
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
    const runtimeState = state || (snapshot.restarting
      ? "【新 Task 初始化｜程序状态，不是用户目标或证据】\n旧绑定已退出，旧 Task/State 仍保留。本提示不能覆盖最新真实用户要求。先判断用户是否已选定明确目标：目标未定或用户要求先讨论/先问问题时，只澄清，不调用 task_create，不能用“确认目标/等待决定”作占位 Goal。目标明确后才根据近期现场及真实要求调用 task_create，提供新 Goal 和元数据；不要自动恢复旧 State。"
      : "当前未绑定 Task。");
    if ((this.options.thinkingLevel?.() ?? "off") !== output.thinkingLevel)
      throw Error(
        "OUTPUT_BUDGET_UNVERIFIED: thinking level changed during request preparation",
      );
    const baseCounter = prepared.frame.counter ?? conservativeCounter;
    const counting = createRequestCounter(baseCounter);
    try {
      const counter = counting.counter,
        count = counter.count;
      const limit = prepared.frame.capacity.contextLimit,
        plan = budgetPlan(limit, settings);
      const shares = settings.context_budget.parts_percent;
      const S = snapshot.stateTokens ?? (state ? count(state) + 32 : 0);
      const footer = (
        budget: ReturnType<typeof allocate>,
      ) => `【本次预算快照｜程序数据，不是用户指令】
计量：${counter.estimator}；基础 ${limit} token（模型 ${prepared.frame.capacity.contextWindow} 的 ${settings.context_budget.model_percent}%），额外 ${budget.extra}，总上限 ${budget.peak}
State：${snapshot.activeCount ?? 0}/${prepared.frame.config.state_max_events} 条；正文最多 ${prepared.frame.config.state_event_max_chars} 字符；每批候选 ${prepared.frame.config.state_evict_batch}
State token：${S}/${plan.state}；${settings.state_policy.token_warning_percent}% 管理线 ${percentOf(plan.state, settings.state_policy.token_warning_percent)}
基础规划 token：State ${plan.state}（${shares.state}%），Window ${plan.window}（${shares.window}%），系统工具 ${plan.system}（${shares.system}%），输出 ${plan.output}（${shares.output}%），最新用户 ${plan.user}（${shares.user}%），回读 ${plan.read}（${shares.read}%），协议 ${plan.protocol}（${shares.protocol}%），安全 ${plan.safety}（${shares.safety}%）
必需成本 K=${budget.K}：系统工具 ${budget.R}，State ${budget.S}，输出上限 ${budget.O}，最新用户 ${budget.U}，协议含本快照 ${budget.P}，基础安全 ${budget.A}
可分配 F=${budget.F}：回读 ${budget.X}/${budget.readLimit}（${settings.elastic_budget.pool_percent.read}%，闲置不借出），普通 Window ${budget.windowUsed}/${budget.windowLimit}（${settings.elastic_budget.pool_percent.window}%），池内安全 ${budget.poolSafety}；模型外层保留 ${prepared.frame.capacity.contextWindow - budget.peak}
回读期限：${settings.read.lifetime_messages} 条后续真实消息；默认读取 ${settings.read.default_total_chars} 字符；到期回读 ${budget.expiredUsed}/${budget.expiredLimit}（普通池 ${settings.elastic_budget.expired_read_percent}%）
Recent Window N/B：${prepared.frame.config.recent_turns}/${prepared.frame.config.evict_turns}；可见事件 ${selected.events.length}；消息 M=${budget.M}；事件权重 ${settings.elastic_budget.window_weights.current}/${settings.elastic_budget.window_weights.recent}/${settings.elastic_budget.window_weights.older}；总预算上界 ${budget.total}/${budget.peak}`;
      let footerReserve = 2048;
      let budget!: ReturnType<typeof allocate>,
        description = "";
      for (let attempt = 0; attempt < 3; attempt++) {
        budget = allocate({
          limit,
          capacity: prepared.frame.capacity.contextWindow,
          settings,
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
        const needed = Math.max(0, count(`${runtimeState}\n\n${description}`) + 32 - S);
        if (needed <= footerReserve) break;
        footerReserve = needed + 128;
        if (attempt === 2)
          throw Error("CONTEXT_BUDGET_EXCEEDED: budget snapshot cannot fit");
      }
      const result = stateInsert(
        [
          system,
          ...budget.rendered,
        ],
        `${runtimeState}\n\n${description}`,
        reminder,
      );
      const credits = new Map<string, number>();
      items.forEach((item, i) => {
        if (!item.read || item.message.role !== "toolResult") return;
        credits.set(`${item.event}:${item.message.toolCallId}`, budget.allocations[i]!.used);
      });
      this.readFrames.set(ctx.sessionManager, { model: structuredClone(model), sessionId: ctx.sessionManager.getSessionId(),
        limit: budget.readLimit, available: 0, released: 0, quotas: new Map(), counter: baseCounter, credits, returns: new Map() });
      this.outputFrame = {
        model: structuredClone(model),
        sessionId: ctx.sessionManager.getSessionId(),
        output: output.output,
        contextWindow: prepared.frame.capacity.contextWindow,
      };
      ctx.signal?.throwIfAborted();
      if (!persistedPrevious || selected.metadata.stage === "reset" || pending.length)
        await this.tasks.memory.append(ctx, WINDOW_TYPE, selected.metadata);
      const { rendered: _rendered, ...summary } = budget;
      this.options.observeBudget?.(Object.freeze(summary));
      return result;
    } finally {
      counting.dispose();
    }
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
    const events = restartEvents(branch, prepared, { recent_turns: prepared.recent_turns, evict_turns: prepared.evict_turns }),
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
