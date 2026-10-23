import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { isDeepStrictEqual } from "node:util";
import { alignOutput } from "../pi/window-budget.ts";
import { type TSchema, type Static } from "typebox";
import { Check } from "typebox/value";
import { TaskService } from "../task/service.ts";
import {
  CreateSchema,
  FindSchema,
  StatusSchema,
  ResumeSchema,
} from "../task/model.ts";
import {
  AppendSchema,
  UpdateGoalSchema,
  ModifyFactSchema,
  RemainSchema,
} from "../state/model.ts";
import { memoryPaths, type MemoryPaths } from "../storage/paths.ts";
import {
  registerRequestLifecycle,
  reportRequestError,
  type RequestMessages,
} from "../pi/request-lifecycle.ts";
import { createRuleRequestServices } from "../pi/rule-services.ts";
import type { CapacityVerifier } from "../pi/model-capacity.ts";
import { SCOPE_TYPE } from "../pi/session-memory.ts";
import { MemoryReadSchema } from "../memory/model.ts";
import { SetWindowSchema } from "../window/model.ts";
import { StateReadSchema, historyReadRanges } from "../state/read.ts";
import { WindowService, type WindowOptions } from "../pi/window-service.ts";
export interface MemweaveOptions extends WindowOptions {
  paths?: MemoryPaths;
  verifyCapacity?: CapacityVerifier;
  observe?: (messages: RequestMessages) => void;
  report?: (error: unknown, ctx: ExtensionContext) => void;
}
export function registerMemweave(
  pi: ExtensionAPI,
  options: MemweaveOptions = {},
): TaskService {
  const paths = options.paths ?? memoryPaths(),
    tasks = new TaskService(paths, pi),
    window = new WindowService(tasks, {
      ...options,
      thinkingLevel: () => pi.getThinkingLevel(),
    }),
    report = options.report ?? reportRequestError;
  const services = createRuleRequestServices({
    paths,
    tasks,
    window,
    ...(options.verifyCapacity
      ? { verifyCapacity: options.verifyCapacity }
      : {}),
    afterRule: async (prepared) => {
      options.observe?.(prepared.messages);
      return prepared.messages;
    },
  });
  registerRequestLifecycle(pi, { ...services, report });
  pi.on("before_provider_request", (event, ctx) => {
    try {
      const frame = window.outputFrame;
      if (
        !frame ||
        frame.sessionId !== ctx.sessionManager.getSessionId() ||
        !isDeepStrictEqual(frame.model, ctx.model)
      )
        throw Error("OUTPUT_BUDGET_UNVERIFIED: request snapshot changed");
      return alignOutput(event.payload, frame.model, frame.output);
    } catch (error) {
      ctx.abort();
      report(error, ctx);
      return undefined;
    }
  });
  function tool<S extends TSchema>(
    name: string,
    description: string,
    parameters: S,
    run: (
      params: Static<S>,
      ctx: ExtensionContext,
      id: string,
    ) => Promise<unknown>,
  ) {
    pi.registerTool({
      name,
      label: name,
      description,
      parameters,
      async execute(id, params, signal, _update, ctx) {
        signal?.throwIfAborted();
        if (!Check(parameters, params)) throw Error("INVALID_TOOL_INPUT");
        const value = await run(params, ctx, id);
        return {
          content: [
            {
              type: "text",
              text: typeof value === "string" ? value : JSON.stringify(value),
            },
          ],
          details: {},
        };
      },
    });
  }
  tool(
    "task_create",
    "Create a new Task with title, initial goal, project_name, summary and keywords; bind this Session branch. context is optional.",
    CreateSchema,
    (p, ctx, id) => tasks.create(p, ctx, id),
  );
  tool(
    "recent_window_set",
    "Set the current Session branch Recent Window event capacity turns and optional evict_turns. Positive integers, B <= N; omission preserves B and never silently clamps. Next request reselects originals; does not end the tool loop.",
    SetWindowSchema,
    (p, ctx, id) => window.set(p, ctx, id),
  );
  tool(
    "task_find",
    "Find historical Tasks by query and optional keywords. limit defaults to 5. Discovery only; does not switch Task.",
    FindSchema,
    (p) => tasks.find(p),
  );
  tool(
    "task_resume",
    "Resume an explicit task_id OR mode=latest_paused in the current workspace. Restores cognition and binding, never external actions or cwd.",
    ResumeSchema,
    (p, ctx, id) => tasks.resume(p, ctx, id),
  );
  tool(
    "task_status",
    "Read status and State version for task_id. running refers only to this Pi instance.",
    StatusSchema,
    (p, ctx) => tasks.status(p.task_id, ctx),
  );
  tool(
    "state_append",
    "Append a nonempty batch of facts/decisions. Each item needs content and evidence mapping existing Task-scoped refs to explanations. Never guess IDs from this batch. Returns only State updated: vN.",
    AppendSchema,
    (p, ctx, id) => tasks.append(p.items, ctx, id),
  );
  tool(
    "update_goal",
    "Update the current Goal only when its objective changes. Supply revised summary/keywords and evidence; project_name only when project affiliation changes. Returns State updated: vN.",
    UpdateGoalSchema,
    (p, ctx, id) => tasks.updateGoal(p, ctx, id),
  );
  pi.registerTool({
    name: "state_read",
    label: "state_read",
    description:
      "Read State for task_id without switching Tasks. Omit event_ids for the current State. Supply 1-50 known F/D IDs for active, evicted or archived original entries and evidence; max_total_chars applies only to historical queries, uses the configured default shown in the request snapshot (bundle default 8000), at most 50000, counting body and evidence. Per-item status/truncation is explicit. Does not search or return Session history.",
    parameters: StateReadSchema,
    async execute(_id, input, signal, _update, ctx) {
      signal?.throwIfAborted();
      const value = await tasks.readState(input, ctx);
      return {
        content: [
          {
            type: "text" as const,
            text: typeof value === "string" ? value : JSON.stringify(value),
          },
        ],
        details:
          typeof value === "string"
            ? {}
            : {
                memweave_read: { version: 1, ranges: historyReadRanges(value) },
              },
      };
    },
  });
  tool(
    "modify_fact",
    "Atomically archive existing unarchived F/D IDs and append one corrected Fact with explained evidence. Historical evicted IDs remain valid; already archived IDs cannot be archived again.",
    ModifyFactSchema,
    (p, ctx, id) => tasks.modifyFact(p, ctx, id),
  );
  tool(
    "state_remain",
    "Handle only the State window batch shown in this request. event_ids selects at most the reminder limit from its candidates; [] retains none. No batch ID or Task parameter is needed.",
    RemainSchema,
    (p, ctx, id) => tasks.remain(p.event_ids, ctx, id),
  );
  pi.registerTool({
    name: "memory_read",
    label: "memory_read",
    description:
      "Read known U/A/T/R originals in order, never search or switch Task. items[].task_id reads an explicit other Task U/A/T and returns a reusable current-Task R. offset/limit use Unicode code points. max_total_chars uses the configured default shown in the request snapshot (bundle default 8000), at most 50000. Failures/completeness are per item. Read attachment R explicitly for supported images, never use character ranges on images.",
    parameters: MemoryReadSchema,
    async execute(id, input, signal, _update, ctx) {
      signal?.throwIfAborted();
      const output = await tasks.readMemory(input, ctx, id);
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(output.result) },
          ...output.images,
        ],
        details: {
          memweave_read: {
            version: 1,
            ranges: output.result.items.map((item) => ({
              ref: item.resolved_ref ?? item.ref,
              source_task_id: item.source_task_id,
              offset: item.offset,
              returned_chars: [...item.content].length,
              range_complete: item.range_complete,
              source_complete: item.source_complete,
              status: item.status,
            })),
          },
        },
      };
    },
  });
  // Hook failures must actively stop execution: Pi otherwise catches extension exceptions.
  const guarded =
    (run: (ctx: ExtensionContext) => Promise<void>) =>
    async (_event: unknown, ctx: ExtensionContext) => {
      try {
        if (ctx.signal?.aborted) return;
        await run(ctx);
      } catch (error) {
        ctx.abort();
        report(error, ctx);
      }
    };
  const onTree = guarded(async (ctx) => {
    await tasks.memory.append(ctx, SCOPE_TYPE, tasks.scope(ctx));
  });
  pi.on("session_tree", (event, ctx) => {
    window.resetSources();
    return onTree(event, ctx);
  });
  pi.on("turn_end", async (event, ctx) => {
    try {
      if (ctx.signal?.aborted) return;
      await tasks.syncBranch(ctx);
      await window.complete(event, ctx);
    } catch (error) {
      ctx.abort();
      report(error, ctx);
    }
  });
  pi.on("tool_call", (event, ctx) => {
    if (
      ![
        "task_create",
        "task_resume",
        "state_append",
        "update_goal",
        "modify_fact",
        "state_remain",
        "memory_read",
        "recent_window_set",
      ].includes(event.toolName)
    )
      return;
    try {
      tasks.memory.check();
      tasks.checkCalls(ctx, event.toolCallId);
    } catch (error) {
      return {
        block: true,
        reason:
          error instanceof Error ? error.message : "MEMWEAVE_TOOL_BLOCKED",
      };
    }
  });
  return tasks;
}
