import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readConfigSnapshot } from "../config/read.ts";
import { prepareRule, type PreparedRule, type RuleFrame } from "../rule/prepare.ts";
import { memoryPaths, type MemoryPaths } from "../storage/paths.ts";
import { captureModelCapacity, verifyProviderCapacity, type CapacityVerifier } from "./model-capacity.ts";
import { reportRequestError, type RequestMessages, type RequestServices } from "./request-lifecycle.ts";

/** Internal module seams; overrides are not persisted until their scope/format is confirmed. */
export interface RuleServiceOptions {
  paths?: MemoryPaths;
  readOverrides?: (ctx: ExtensionContext) => unknown;
  verifyCapacity?: CapacityVerifier;
  afterRule?: (prepared: PreparedRule, ctx: ExtensionContext) => Promise<RequestMessages>;
}

export function createRuleRequestServices(options: RuleServiceOptions = {}): RequestServices {
  const paths = options.paths ?? memoryPaths();
  return {
    report: reportRequestError,
    async prepare(messages, ctx) {
      ctx.signal?.throwIfAborted();
      if (!ctx.model) throw new Error("MODEL_CAPACITY_UNVERIFIED: no selected model");
      const selected = structuredClone(ctx.model);
      const overrides: unknown = structuredClone(options.readOverrides?.(ctx) ?? {});
      const config = await readConfigSnapshot(paths, overrides, ctx.signal);
      const capacity = await captureModelCapacity(ctx, selected, options.verifyCapacity ?? verifyProviderCapacity);
      const frame: RuleFrame = Object.freeze({ config, capacity });
      const prepared = await prepareRule(messages, frame, paths, ctx.signal);
      return options.afterRule ? options.afterRule(prepared, ctx) : prepared.messages;
    },
  };
}
