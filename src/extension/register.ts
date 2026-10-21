import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { type TSchema, type Static } from "typebox";
import { Check } from "typebox/value";
import { TaskService } from "../task/service.ts";
import {
  CreateSchema,
  FindSchema,
  StatusSchema,
  ResumeSchema,
} from "../task/model.ts";
import { AppendSchema,UpdateGoalSchema } from "../state/model.ts";
import { memoryPaths, type MemoryPaths } from "../storage/paths.ts";
import {
  registerRequestLifecycle,
  reportRequestError,
  type RequestMessages,
} from "../pi/request-lifecycle.ts";
import { createRuleRequestServices } from "../pi/rule-services.ts";
import type { CapacityVerifier } from "../pi/model-capacity.ts";
import { SCOPE_TYPE } from "../pi/session-memory.ts";
export interface MemweaveOptions {
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
    report = options.report ?? reportRequestError;
  const services = createRuleRequestServices({
    paths,
    tasks,
    ...(options.verifyCapacity
      ? { verifyCapacity: options.verifyCapacity }
      : {}),
    afterRule: async (prepared) => {
      options.observe?.(prepared.messages);
      return prepared.messages;
    },
  });
  registerRequestLifecycle(pi, { ...services, report });
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
  tool("update_goal","Update the current Goal only when its objective changes. Supply revised summary/keywords and evidence; project_name only when project affiliation changes. Returns State updated: vN.",UpdateGoalSchema,(p,ctx,id)=>tasks.updateGoal(p,ctx,id));
  tool("state_read","Read the current State of an explicit task_id without switching the current Task or returning raw Session history.",StatusSchema,(p,ctx)=>tasks.readState(p.task_id,ctx));
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
  pi.on(
    "session_tree",
    guarded(async (ctx) => {
      await tasks.memory.append(ctx, SCOPE_TYPE, tasks.scope(ctx));
    }),
  );
  pi.on(
    "turn_end",
    guarded((ctx) => tasks.syncBranch(ctx)),
  );
  pi.on("tool_call", (event, ctx) => {
    if (
      !["task_create", "task_resume", "state_append", "update_goal"].includes(event.toolName)
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
