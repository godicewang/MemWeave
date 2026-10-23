import { settingsFor, percentOf } from "../config/defaults.ts";
import type {
  ExtensionAPI,
  ExtensionContext,
  SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { isDeepStrictEqual } from "node:util";
import { Check } from "typebox/value";
import type { MemoryConfig } from "../config/schema.ts";
import { prepareStateBatch, renderStateReminder } from "../state/window.ts";
import { requestStateBatch } from "../pi/state-batch.ts";
import { stateAdmission, stateSize, type StateGuard } from "../state/budget.ts";
import type { TokenCounter } from "../window/tokens.ts";
import { budgetPlan } from "../window/policy.ts";
import {
  SessionMemory,
  scopeOf,
  sourceAssistant,
  workspaceKey,
  SCOPE_TYPE,
  STATE_REQUEST_TYPE,
} from "../pi/session-memory.ts";
import {
  messageOwners,
  synchronizeReferences,
  type LocatedReference,
} from "../memory/references.ts";
import { StateStore } from "../state/store.ts";
import type { StateItem } from "../state/model.ts";
import {
  AppendSchema,
  renderState,
  UpdateGoalSchema,
  type UpdateGoalInput,
  ModifyFactSchema,
  RemainSchema,
  type ModifyFactInput,
} from "../state/model.ts";
import { withLock } from "../storage/files.ts";
import { now, stableId } from "../storage/identity.ts";
import type { MemoryPaths } from "../storage/paths.ts";
import { GoalMetadataResolver } from "./goal-metadata.ts";
import { MemoryService } from "../memory/service.ts";
import { MemoryReadSchema, type MemoryReadInput } from "../memory/model.ts";
import {
  StateReadSchema,
  readHistoricalState,
  type StateReadInput,
} from "../state/read.ts";
import { TaskIndex } from "./index-store.ts";
import {
  CreateSchema,
  FindSchema,
  ResumeSchema,
  StatusSchema,
  type Task,
  type CreateInput,
  type FindInput,
  type ResumeInput,
} from "./model.ts";

export interface TaskBudget {
  readonly config: MemoryConfig;
  readonly counter: TokenCounter;
  readonly limit: number;
}
export interface TaskSnapshot {
  stateTokens?: number;
  activeCount?: number;
  task: Task | null;
  state: string | null;
  references: Map<string, LocatedReference>;
  entries: SessionEntry[];
}
export class TaskService {
  readonly paths: MemoryPaths;
  readonly index: TaskIndex;
  readonly state: StateStore;
  readonly memory: SessionMemory;
  readonly goalMetadata: GoalMetadataResolver;
  readonly reader: MemoryService;
  constructor(paths: MemoryPaths, pi: Pick<ExtensionAPI, "appendEntry">) {
    this.paths = paths;
    this.index = new TaskIndex(paths);
    this.state = new StateStore(paths);
    this.memory = new SessionMemory(pi);
    this.goalMetadata = new GoalMetadataResolver(this.memory);
    this.reader = new MemoryService(paths, this.index, this.memory);
  }
  resolveBudget?: (ctx: ExtensionContext) => Promise<TaskBudget>;
  async configuration(ctx: ExtensionContext) {
    if (!this.resolveBudget) throw Error("STATE_BUDGET_UNVERIFIED");
    return (await this.resolveBudget(ctx)).config;
  }
  private admission(ctx: ExtensionContext): StateGuard {
    return async (task, next, previous) => {
      if (!this.resolveBudget) throw Error("STATE_BUDGET_UNVERIFIED");
      const frame = await this.resolveBudget(ctx);
      ctx.signal?.throwIfAborted();
      stateAdmission(frame.counter, budgetPlan(frame.limit, settingsFor(frame.config)).state)(
        task,
        next,
        previous,
      );
    };
  }
  scope(ctx: ExtensionContext) {
    this.memory.check();
    return scopeOf(ctx.sessionManager.getBranch());
  }
  operation(ctx: ExtensionContext, callId: string, taskId: string): string {
    const source = sourceAssistant(ctx, callId);
    return stableId(
      taskId,
      ctx.sessionManager.getSessionId(),
      source.id,
      callId,
    );
  }
  checkCalls(ctx: ExtensionContext, callId: string): void {
    const source = sourceAssistant(ctx, callId);
    if (source.message.role !== "assistant") throw Error("TOOL_SOURCE_MISSING");
    const calls = source.message.content.filter((p) => p.type === "toolCall");
    const switches = calls.filter(
      (c) => c.name === "task_create" || c.name === "task_resume",
    );
    const windowCalls = calls.filter((c) => c.name === "recent_window_set");
    if (windowCalls.length > 1 || (windowCalls.length && switches.length))
      throw Error(
        "CONFLICTING_WINDOW_CALLS: separate window settings from Task switching and other window settings",
      );
    if (
      switches.length > 1 ||
      (switches.length &&
        calls.some((c) =>
          [
            "state_append",
            "update_goal",
            "modify_fact",
            "state_remain",
            "memory_read",
          ].includes(c.name),
        ))
    )
      throw Error(
        "CONFLICTING_TASK_CALLS: separate Task switching from State writes and original reads",
      );
  }
  async register(task: Task, ctx: ExtensionContext): Promise<Task> {
    const file = ctx.sessionManager.getSessionFile();
    if (!file) throw Error("PERSISTENT_SESSION_REQUIRED");
    const session_id = ctx.sessionManager.getSessionId();
    const previous = task.sessions.find((s) => s.session_id === session_id);
    if (previous && previous.file !== file) throw Error("SESSION_SOURCE_MOVED");
    if (!previous) {
      task = { ...task, sessions: [...task.sessions, { session_id, file }] };
      await this.index.put(task);
    }
    return task;
  }
  async derivatives(
    task: Task,
    state: Awaited<ReturnType<StateStore["read"]>>,
  ): Promise<Task> {
    await this.state.writeView(task, state);
    let metadata;
    try {
      metadata = await this.goalMetadata.current(task, state);
    } catch {
      throw Error(
        `PARTIAL_COMMIT: ${task.task_id} State v${state.version} committed; Goal discovery metadata source failed`,
      );
    }
    const updated = {
      ...task,
      ...(metadata
        ? {
            summary: metadata.summary,
            keywords: metadata.keywords,
            project_name: metadata.project_name,
            updated_at:
              Date.parse(task.updated_at) < Date.parse(metadata.time)
                ? metadata.time
                : task.updated_at,
          }
        : {}),
      state_version: state.version,
    };
    try {
      await this.index.put(updated);
    } catch {
      throw Error(
        `PARTIAL_COMMIT: ${task.task_id} State v${state.version} committed; index.json failed`,
      );
    }
    return updated;
  }
  async create(input: CreateInput, ctx: ExtensionContext, callId: string) {
    if (!Check(CreateSchema, input)) throw Error("INVALID_TASK_CREATE");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const assistant = sourceAssistant(ctx, callId);
    if (
      assistant.message.role !== "assistant" ||
      !assistant.message.content.some(
        (p) =>
          p.type === "toolCall" &&
          p.id === callId &&
          p.name === "task_create" &&
          isDeepStrictEqual(p.arguments, input),
      )
    )
      throw Error("OPERATION_INPUT_MISMATCH");
    const taskId = `task_${stableId(ctx.sessionManager.getSessionId(), assistant.id, callId).slice(0, 32)}`;
    const location = { task_id: taskId, workspace: workspaceKey(ctx.cwd) };
    return withLock(
      this.paths.taskLock(location),
      async () => {
        const scope = this.scope(ctx),
          config = await this.configuration(ctx);
        if ([...input.goal].length > config.state_event_max_chars)
          throw Error("STATE_CONTENT_TOO_LONG: initial Goal");
        const state = await this.state.initialize(
          location,
          input.goal,
          this.operation(ctx, callId, taskId),
          this.admission(ctx),
        );
        let task: Task | undefined;
        try {
          task = (await this.index.read()).find((t) => t.task_id === taskId);
        } catch {
          throw Error(
            `PARTIAL_COMMIT: ${taskId} State v${state.version} committed; index.json read failed`,
          );
        }
        if (!task)
          task = {
            ...location,
            title: input.title,
            project_name: input.project_name,
            summary: input.summary,
            keywords: input.keywords,
            state_version: state.version,
            status: "active",
            updated_at: now(),
            sessions: [],
          };
        const initialGoal = state.events[0];
        if (
          initialGoal?.op !== "update_goal" ||
          initialGoal.goal !== input.goal
        )
          throw Error("OPERATION_INPUT_MISMATCH");
        try {
          task = await this.register(task, ctx);
          task = await this.derivatives(task, state);
          const bootstrap = new Set<string>();
          if (scope.task_id === null) {
            const branch = ctx.sessionManager.getBranch();
            const pos = branch.findIndex((e) => e.id === assistant.id);
            bootstrap.add(assistant.id);
            for (let i = pos - 1; i >= 0; i--) {
              const e = branch[i]!;
              if (e.type === "message" && e.message.role === "user") {
                bootstrap.add(e.id);
                break;
              }
            }
          }
          await synchronizeReferences(task, ctx, this.memory, bootstrap);
          if (scope.task_id !== taskId)
            await this.memory.append(ctx, SCOPE_TYPE, {
              ...scope,
              task_id: taskId,
            });
        } catch (error) {
          throw Error(
            `PARTIAL_COMMIT: ${taskId} State v${state.version} committed; ${error instanceof Error ? error.message : "task metadata or binding failed"}`,
          );
        }
        return {
          task_id: taskId,
          title: task.title,
          summary: task.summary,
          goal: state.goal,
          state_version: state.version,
        };
      },
      ctx.signal,
    );
  }
  async append(items: StateItem[], ctx: ExtensionContext, callId: string) {
    if (!Check(AppendSchema, { items })) throw Error("INVALID_STATE_APPEND");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const scope = this.scope(ctx);
    if (!scope.task_id) throw Error("NO_CURRENT_TASK");
    const initial = await this.index.get(scope.task_id);
    return withLock(
      this.paths.taskLock(initial),
      async () => {
        const task = await this.register(
            await this.index.get(initial.task_id),
            ctx,
          ),
          refs = await synchronizeReferences(task, ctx, this.memory);
        const config = await this.configuration(ctx);
        const state = await this.state.append(
          task,
          items,
          this.operation(ctx, callId, task.task_id),
          config.state_event_max_chars,
          async () =>
            new Set([
              ...refs.keys(),
              ...(await this.reader.evidence(
                task,
                items.flatMap((item) => Object.keys(item.evidence)),
              )),
            ]),
          this.admission(ctx),
        );
        await this.derivatives({ ...task, updated_at: now() }, state);
        return `State updated: v${state.version}`;
      },
      ctx.signal,
    );
  }
  async updateGoal(
    input: UpdateGoalInput,
    ctx: ExtensionContext,
    callId: string,
  ) {
    if (!Check(UpdateGoalSchema, input)) throw Error("INVALID_UPDATE_GOAL");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const scope = this.scope(ctx);
    if (!scope.task_id) throw Error("NO_CURRENT_TASK");
    const initial = await this.index.get(scope.task_id);
    return withLock(
      this.paths.taskLock(initial),
      async () => {
        const task = await this.register(
            await this.index.get(initial.task_id),
            ctx,
          ),
          refs = await synchronizeReferences(task, ctx, this.memory);
        const config = await this.configuration(ctx);
        const state = await this.state.updateGoal(
          task,
          input,
          this.operation(ctx, callId, task.task_id),
          config.state_event_max_chars,
          async () =>
            new Set([
              ...refs.keys(),
              ...(await this.reader.evidence(
                task,
                Object.keys(input.evidence),
              )),
            ]),
          this.admission(ctx),
        );
        await this.derivatives({ ...task, updated_at: now() }, state);
        return `State updated: v${state.version}`;
      },
      ctx.signal,
    );
  }
  async modifyFact(
    input: ModifyFactInput,
    ctx: ExtensionContext,
    callId: string,
  ) {
    if (!Check(ModifyFactSchema, input)) throw Error("INVALID_MODIFY_FACT");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const scope = this.scope(ctx);
    if (!scope.task_id) throw Error("NO_CURRENT_TASK");
    const initial = await this.index.get(scope.task_id);
    return withLock(
      this.paths.taskLock(initial),
      async () => {
        const task = await this.register(
            await this.index.get(initial.task_id),
            ctx,
          ),
          refs = await synchronizeReferences(task, ctx, this.memory),
          config = await this.configuration(ctx);
        const state = await this.state.modifyFact(
          task,
          input,
          this.operation(ctx, callId, task.task_id),
          config.state_event_max_chars,
          async () =>
            new Set([
              ...refs.keys(),
              ...(await this.reader.evidence(
                task,
                Object.keys(input.append_fact.evidence),
              )),
            ]),
          this.admission(ctx),
        );
        await this.derivatives({ ...task, updated_at: now() }, state);
        return `State updated: v${state.version}`;
      },
      ctx.signal,
    );
  }
  async remain(eventIds: string[], ctx: ExtensionContext, callId: string) {
    if (!Check(RemainSchema, { event_ids: eventIds }))
      throw Error("INVALID_STATE_REMAIN");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const scope = this.scope(ctx);
    if (!scope.task_id) throw Error("NO_CURRENT_TASK");
    const initial = await this.index.get(scope.task_id),
      batch = requestStateBatch(ctx, callId, initial.task_id);
    return withLock(
      this.paths.taskLock(initial),
      async () => {
        const task = await this.index.get(initial.task_id),
          state = await this.state.remain(
            task,
            batch,
            eventIds,
            this.operation(ctx, callId, task.task_id),
          );
        await this.derivatives({ ...task, updated_at: now() }, state);
        return `State updated: v${state.version}`;
      },
      ctx.signal,
    );
  }
  async readState(input: StateReadInput | string, ctx: ExtensionContext) {
    const query = typeof input === "string" ? { task_id: input } : input;
    if (!Check(StateReadSchema, query)) throw Error("INVALID_STATE_READ");
    const task = await this.index.get(query.task_id);
    const defaultChars = "event_ids" in query
      ? settingsFor(await this.configuration(ctx)).read.default_total_chars : undefined;
    return withLock(
      this.paths.taskLock(task),
      async () => {
        const state = await this.state.read(task);
        return "event_ids" in query
          ? readHistoricalState(task.task_id, state, query, defaultChars)
          : renderState(task.task_id, state);
      },
      ctx.signal,
    );
  }
  async readMemory(
    input: MemoryReadInput,
    ctx: ExtensionContext,
    callId: string,
  ) {
    if (!Check(MemoryReadSchema, input)) throw Error("INVALID_MEMORY_READ");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const scope = this.scope(ctx);
    if (!scope.task_id) throw Error("NO_CURRENT_TASK");
    const initial = await this.index.get(scope.task_id);
    return withLock(
      this.paths.taskLock(initial),
      async () => {
        const task = await this.register(
          await this.index.get(initial.task_id),
          ctx,
        );
        const refs = await synchronizeReferences(task, ctx, this.memory);
        await this.reader.capture(task, refs, ctx);
        const config = await this.configuration(ctx);
        return this.reader.read(task, input, ctx, settingsFor(config).read.default_total_chars);
      },
      ctx.signal,
    );
  }
  async find(input: FindInput) {
    if (!Check(FindSchema, input)) throw Error("INVALID_TASK_FIND");
    const segmenter = new Intl.Segmenter("zh", { granularity: "word" });
    const words = [
      ...new Set(
        [input.query, ...(input.keywords ?? [])].flatMap((s) =>
          [...segmenter.segment(s.toLocaleLowerCase())]
            .filter((p) => p.isWordLike)
            .map((p) => p.segment),
        ),
      ),
    ];
    return (await this.index.read())
      .map((task) => ({
        task,
        score: words.reduce(
          (score, word) =>
            score +
            ([task.title, task.project_name, task.summary, ...task.keywords]
              .join(" ")
              .toLocaleLowerCase()
              .includes(word)
              ? 1
              : 0),
          0,
        ),
      }))
      .filter((e) => e.score > 0)
      .sort(
        (a, b) =>
          b.score - a.score ||
          Date.parse(b.task.updated_at) - Date.parse(a.task.updated_at),
      )
      .slice(0, input.limit ?? 5)
      .map(({ task }) => ({
        task_id: task.task_id,
        title: task.title,
        summary: task.summary,
        keywords: task.keywords,
      }));
  }
  async status(id: string, ctx: ExtensionContext) {
    if (!Check(StatusSchema, { task_id: id }))
      throw Error("INVALID_TASK_STATUS");
    const task = await this.index.get(id);
    return withLock(
      this.paths.taskLock(task),
      async () => {
        const current = await this.index.get(id),
          state = await this.state.read(current);
        return {
          task_id: id,
          status: current.status,
          state_version: state.version,
          running: this.scope(ctx).task_id === id && !ctx.isIdle(),
        };
      },
      ctx.signal,
    );
  }
  async resume(input: ResumeInput, ctx: ExtensionContext, callId: string) {
    if (!Check(ResumeSchema, input)) throw Error("INVALID_TASK_RESUME");
    await this.memory.verify(ctx);
    this.checkCalls(ctx, callId);
    const target =
      "task_id" in input
        ? await this.index.get(input.task_id)
        : (await this.index.read())
            .filter(
              (t) =>
                t.workspace === workspaceKey(ctx.cwd) && t.status === "paused",
            )
            .sort(
              (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
            )[0];
    if (!target) throw Error("NO_PAUSED_TASK");
    return withLock(
      this.paths.taskLock(target),
      async () => {
        let task = await this.register(
          await this.index.get(target.task_id),
          ctx,
        );
        const state = await this.state.read(task);
        await synchronizeReferences(task, ctx, this.memory);
        task = await this.derivatives(
          { ...task, status: "active", updated_at: now() },
          state,
        );
        const scope = this.scope(ctx);
        if (scope.task_id !== task.task_id) {
          try {
            await this.memory.append(ctx, SCOPE_TYPE, {
              ...scope,
              task_id: task.task_id,
            });
          } catch {
            throw Error(
              `PARTIAL_RESUME: ${task.task_id} State v${state.version} retained, index active; Session binding failed; reopen Session from disk`,
            );
          }
        }
        return {
          task_id: task.task_id,
          title: task.title,
          summary: task.summary,
          goal: state.goal,
          state_version: state.version,
          restored: true,
        };
      },
      ctx.signal,
    );
  }
  async snapshot(
    ctx: ExtensionContext,
    config: MemoryConfig,
    budget?: TaskBudget,
  ): Promise<TaskSnapshot> {
    await this.memory.verify(ctx);
    const scope = this.scope(ctx);
    await this.syncBranch(ctx);
    if (!scope.task_id)
      return {
        task: null,
        state: null,
        references: new Map(),
        entries: structuredClone(ctx.sessionManager.getBranch()),
      };
    const initial = await this.index.get(scope.task_id);
    return withLock(
      this.paths.taskLock(initial),
      async () => {
        const task = await this.register(
            await this.index.get(initial.task_id),
            ctx,
          ),
          references = await synchronizeReferences(task, ctx, this.memory),
          state = await this.state.read(task);
        await this.reader.capture(task, references, ctx);
        const updated = await this.derivatives(task, state);
        const tokens = budget
          ? stateSize(task.task_id, state, budget.counter)
          : undefined;
        const batch = prepareStateBatch(
          task.task_id,
          state,
          config,
          budget !== undefined &&
            tokens! >= percentOf(budgetPlan(budget.limit, settingsFor(config)).state, settingsFor(config).state_policy.token_warning_percent),
        );
        if (batch) await this.memory.append(ctx, STATE_REQUEST_TYPE, batch);
        return {
          task: structuredClone(updated),
          ...(tokens !== undefined ? { stateTokens: tokens } : {}),
          activeCount: state.facts.length + state.decisions.length,
          state:
            renderState(task.task_id, state) +
            (batch ? renderStateReminder(batch, state) : ""),
          references,
          entries: structuredClone(ctx.sessionManager.getBranch()),
        };
      },
      ctx.signal,
    );
  }
  async syncBranch(ctx: ExtensionContext): Promise<void> {
    this.memory.check();
    const ids = new Set(
      [...messageOwners(ctx.sessionManager.getBranch()).values()].filter(
        (id): id is string => id !== null,
      ),
    );
    for (const id of ids) {
      const initial = await this.index.get(id);
      await withLock(
        this.paths.taskLock(initial),
        async () => {
          const task = await this.register(await this.index.get(id), ctx);
          const references = await synchronizeReferences(
            task,
            ctx,
            this.memory,
          );
          await this.reader.capture(task, references, ctx);
        },
        ctx.signal,
      );
    }
  }
}
