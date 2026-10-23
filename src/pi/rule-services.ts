import { mergeConfig } from "../config/schema.ts";
import { settingsFor } from "../config/defaults.ts";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isDeepStrictEqual } from "node:util";
import { counterForModel } from "../window/tokens.ts";
import type { TaskService } from "../task/service.ts";
import { taskContext } from "./task-context.ts";
import type { WindowService } from "./window-service.ts";
import { readConfigInput } from "../config/read.ts";
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
  window?: WindowService;
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
  const frames = new WeakMap<object, Awaited<ReturnType<typeof capture>>>();
  async function capture(ctx: ExtensionContext) {
    if (!ctx.model) throw Error("MODEL_CAPACITY_UNVERIFIED: no selected model");
    const selected = structuredClone(ctx.model);
    const overrides = structuredClone(
      options.readOverrides?.(ctx) ?? options.tasks?.scope(ctx).overrides ?? {},
    );
    const input = await readConfigInput(paths, ctx.signal);
    const settings = settingsFor(input);
    const capacity = await captureModelCapacity(
      ctx,
      selected,
      options.verifyCapacity ?? verifyProviderCapacity,
      settings,
    );
    const config = mergeConfig(input, overrides, capacity.contextLimit);
    const counter = await counterForModel(selected, capacity.modelName);
    const frame = {
      selected,
      overrides,
      capacity,
      config,
      counter,
      limit: capacity.contextLimit,
    };
    frames.set(ctx.sessionManager, frame);
    return frame;
  }
  if (options.tasks)
    options.tasks.resolveBudget = async (ctx) => {
      const old = frames.get(ctx.sessionManager);
      return old &&
        isDeepStrictEqual(old.selected, ctx.model) &&
        isDeepStrictEqual(old.overrides, options.tasks!.scope(ctx).overrides)
        ? old
        : capture(ctx);
    };
  return {
    reset: () => options.window?.resetSources(),
    report: reportRequestError,
    async prepare(messages, ctx) {
      ctx.signal?.throwIfAborted();
      const captured = await capture(ctx);
      const { selected, config, capacity, counter } = captured;
      const output = options.window?.captureOutput(
        selected,
        capacity.contextLimit,
        capacity.maxOutputTokens,
        settingsFor(config),
      );
      const task = options.tasks
        ? await options.tasks.snapshot(ctx, config, captured)
        : undefined;
      const frame: RuleFrame = Object.freeze({ config, capacity, counter });
      const prepared = await prepareRule(messages, frame, paths, ctx.signal);
      const complete =
        task && options.window
          ? {
              ...prepared,
              messages: await options.window.prepare(
                prepared,
                task,
                ctx,
                selected,
                output,
              ),
            }
          : task
            ? { ...prepared, messages: taskContext(prepared.messages, task) }
            : prepared;
      return options.afterRule
        ? options.afterRule(complete, ctx)
        : complete.messages;
    },
  };
}
