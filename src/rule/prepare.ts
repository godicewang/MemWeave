import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import type { MemoryConfig } from "../config/schema.ts";
import type { RequestMessages } from "../pi/request-lifecycle.ts";
import type { MemoryPaths } from "../storage/paths.ts";
import { applyRule } from "./apply.ts";
import { renderRule } from "./render.ts";

import type { TokenCounter } from "../window/tokens.ts";
export interface RuleFrame {
  readonly counter?: TokenCounter;
  readonly config: MemoryConfig;
  readonly capacity: Readonly<{
    provider: string;
    modelId: string;
    contextWindow: number;
    contextLimit: number;
    modelName?: string;
    maxOutputTokens?: number;
  }>;
}

export async function prepareRule(
  messages: RequestMessages,
  frame: RuleFrame,
  paths: MemoryPaths,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  let bytes: Buffer;
  try {
    bytes = await readFile(paths.rule, { signal });
  } catch {
    if (signal?.aborted) signal.throwIfAborted();
    throw new Error("RULE_READ_FAILED: cannot read rule.md");
  }
  let template: string;
  try {
    template = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true,
    }).decode(bytes);
  } catch {
    throw new Error("INVALID_RULE: rule.md must contain valid UTF-8 text");
  }
  const renderedRule = renderRule(template, frame.config);
  signal?.throwIfAborted();
  return Object.freeze({
    frame,
    template,
    renderedRule,
    templateHash: createHash("sha256").update(bytes).digest("hex"),
    messages: applyRule(messages, renderedRule),
  });
}

export type PreparedRule = Awaited<ReturnType<typeof prepareRule>>;
