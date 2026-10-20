import type {
  ExtensionAPI,
  ExtensionContext,
  SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { Check } from "typebox/value";
import { readConfigSnapshot } from "../config/read.ts";
import {
  SessionMemory,
  scopeOf,
  sourceAssistant,
  workspaceKey,
  SCOPE_TYPE,
} from "../pi/session-memory.ts";
import {
  messageOwners,
  synchronizeReferences,
  type LocatedReference,
} from "../memory/references.ts";
import { StateStore } from "../state/store.ts";
import type { StateItem } from "../state/model.ts";
import { AppendSchema, renderState } from "../state/model.ts";
import { withLock } from "../storage/files.ts";
import { now, stableId } from "../storage/identity.ts";
import type { MemoryPaths } from "../storage/paths.ts";
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

export interface TaskSnapshot {
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
  constructor(paths: MemoryPaths, pi: Pick<ExtensionAPI, "appendEntry">) {
    this.paths = paths;
    this.index = new TaskIndex(paths);
    this.state = new StateStore(paths);
    this.memory = new SessionMemory(pi);
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
    if (
      switches.length > 1 ||
      (switches.length &&
        calls.some((c) =>
          [
            "state_append",
            "update_goal",
            "modify_fact",
            "state_remain",
          ].includes(c.name),
        ))
    )
      throw Error(
        "CONFLICTING_TASK_CALLS: separate Task switching from State writes",
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
    const updated = { ...task, state_version: state.version };
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
    const assistant = sourceAssistant(ctx, callId),
      taskId = `task_${stableId(ctx.sessionManager.getSessionId(), assistant.id, callId).slice(0, 32)}`;
    const location = { task_id: taskId, workspace: workspaceKey(ctx.cwd) };
    return withLock(
      this.paths.taskLock(location),
      async () => {
        const scope = this.scope(ctx),
          config = await readConfigSnapshot(
            this.paths,
            scope.overrides,
            ctx.signal,
          );
        if ([...input.goal].length > config.state_event_max_chars)
          throw Error("STATE_CONTENT_TOO_LONG: initial Goal");
        const state = await this.state.initialize(
          location,
          input.goal,
          this.operation(ctx, callId, taskId),
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
        if (
          task.title !== input.title ||
          state.goal !== input.goal ||
          task.summary !== input.summary ||
          task.project_name !== input.project_name ||
          JSON.stringify(task.keywords) !== JSON.stringify(input.keywords)
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
        const config = await readConfigSnapshot(
          this.paths,
          scope.overrides,
          ctx.signal,
        );
        const state = await this.state.append(
          task,
          items,
          this.operation(ctx, callId, task.task_id),
          config.state_event_max_chars,
          new Set(refs.keys()),
        );
        await this.derivatives({ ...task, updated_at: now() }, state);
        return `State updated: v${state.version}`;
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
  async snapshot(ctx: ExtensionContext): Promise<TaskSnapshot> {
    await this.memory.verify(ctx);
    const scope = this.scope(ctx);
    await this.syncBranch(ctx);
    if (!scope.task_id)
      return { task: null, state: null, references: new Map(), entries: [] };
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
        await this.derivatives(task, state);
        return {
          task: structuredClone(task),
          state: renderState(task.task_id, state),
          references,
          entries: ctx.sessionManager.getBranch(),
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
          await synchronizeReferences(task, ctx, this.memory);
        },
        ctx.signal,
      );
    }
  }
}
