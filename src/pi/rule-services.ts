import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { TaskService } from "../task/service.ts";
import { taskContext } from "./task-context.ts";
import { readConfigSnapshot } from "../config/read.ts";
import {
  prepareRule,
  type PreparedRule,
  type RuleFrame,
} from "../rule/prepare.ts";
import { memoryPaths, type MemoryPaths } from "../storage/paths.ts";
import {
  captureModelCapacity,
  verifyProviderCapacity,
  type CapacityVerifier,
} from "./model-capacity.ts";
import {
  reportRequestError,
  type RequestMessages,
  type RequestServices,
} from "./request-lifecycle.ts";

/** Internal composition seams; production scope is read from Pi branch metadata. */
export interface RuleServiceOptions {
  paths?: MemoryPaths;
  tasks?: TaskService;
  readOverrides?: (ctx: ExtensionContext) => unknown;
  verifyCapacity?: CapacityVerifier;
  afterRule?: (
    prepared: PreparedRule,
    ctx: ExtensionContext,
  ) => Promise<RequestMessages>;
}

export function createRuleRequestServices(
  options: RuleServiceOptions = {},
): RequestServices {
  const paths = options.paths ?? memoryPaths();
  return {
    report: reportRequestError,
    async prepare(messages, ctx) {
      ctx.signal?.throwIfAborted();
      if (!ctx.model)
        throw new Error("MODEL_CAPACITY_UNVERIFIED: no selected model");
      const selected = structuredClone(ctx.model);
      const overrides: unknown = structuredClone(
        options.readOverrides?.(ctx) ??
          options.tasks?.scope(ctx).overrides ??
          {},
      );
      const config = await readConfigSnapshot(paths, overrides, ctx.signal);
      const task = options.tasks
        ? await options.tasks.snapshot(ctx, config)
        : undefined;
      const capacity = await captureModelCapacity(
        ctx,
        selected,
        options.verifyCapacity ?? verifyProviderCapacity,
      );
      const frame: RuleFrame = Object.freeze({ config, capacity });
      const prepared = await prepareRule(messages, frame, paths, ctx.signal);
      const complete = task
        ? { ...prepared, messages: taskContext(prepared.messages, task) }
        : prepared;
      return options.afterRule
        ? options.afterRule(complete, ctx)
        : complete.messages;
    },
  };
}
