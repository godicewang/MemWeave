import { DEFAULT_SETTINGS, type PolicySettings } from "../config/defaults.ts";
import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { deriveContextLimit } from "./context-limit.ts";
import { isDeepStrictEqual } from "node:util";

export type CapacityVerifier = (
  model: Model<Api>,
  ctx: ExtensionContext,
  settings?: PolicySettings,
) => Promise<unknown>;
const unverified = (reason: string) =>
  new Error(`MODEL_CAPACITY_UNVERIFIED: ${reason}`);

export function parseModelCapacity(metadata: unknown, modelId: string): number {
  const data =
    typeof metadata === "object" && metadata !== null && "data" in metadata
      ? metadata.data
      : undefined;
  if (!Array.isArray(data)) throw unverified("model list is missing");
  const matches = data.filter(
    (item: unknown): item is Record<string, unknown> =>
      typeof item === "object" &&
      item !== null &&
      "id" in item &&
      item.id === modelId,
  );
  if (matches.length !== 1)
    throw unverified("expected one exact model in provider metadata");
  const value = matches[0]?.context_window;
  deriveContextLimit(value); // Safe integer, at least two tokens; no display-unit conversion.
  return value as number;
}

/** Metadata lookup only. Pi still owns all inference requests, credentials and retries. */
export const verifyProviderCapacity: CapacityVerifier = async (model, ctx, settings = DEFAULT_SETTINGS) => {
  ctx.signal?.throwIfAborted();
  if (model.api !== "openai-completions")
    throw unverified("no verified capacity adapter for this API");
  try {
    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
    ctx.signal?.throwIfAborted();
    if (!auth.ok)
      throw unverified("provider authentication could not be resolved");
    const base = auth.baseUrl ?? model.baseUrl;
    const url = new URL("models", `${base.replace(/\/+$/, "")}/`);
    if (url.protocol !== "https:" && url.protocol !== "http:")
      throw unverified("unsupported metadata endpoint");
    const headers = new Headers({ accept: "application/json" });
    if (
      auth.apiKey &&
      ctx.modelRegistry.getRegisteredProviderConfig(model.provider)
        ?.authHeader !== false
    ) {
      headers.set("authorization", `Bearer ${auth.apiKey}`);
    }
    for (const source of [model.headers, auth.headers]) {
      for (const [key, value] of Object.entries(source ?? {})) {
        if (value === null) headers.delete(key);
        else if (value !== undefined) headers.set(key, value);
      }
    }
    const timeout = AbortSignal.timeout(settings.model_metadata_timeout_ms);
    const response = await fetch(url, {
      headers,
      redirect: "error",
      signal: ctx.signal ? AbortSignal.any([ctx.signal, timeout]) : timeout,
    });
    if (!response.ok) {
      await response.body?.cancel();
      throw unverified(`provider metadata HTTP ${response.status}`);
    }
    const metadata: unknown = await response.json();
    const contextWindow = parseModelCapacity(metadata, model.id);
    const record = (
      metadata as { data: Array<Record<string, unknown>> }
    ).data.find((item) => item.id === model.id)!;
    const maxOutputTokens = record.max_output_tokens;
    if (
      maxOutputTokens !== undefined &&
      (typeof maxOutputTokens !== "number" ||
        !Number.isSafeInteger(maxOutputTokens) ||
        maxOutputTokens < 1)
    )
      throw unverified("invalid output capacity");
    return {
      contextWindow,
      // Only official metadata authorizes the matching tokenizer, even if auth overrides the selected base URL.
      modelName: url.hostname === "api.deepseek.com" && typeof record.name === "string" ? record.name : undefined,
      maxOutputTokens,
    };
  } catch (error) {
    if (ctx.signal?.aborted) ctx.signal.throwIfAborted();
    // Authentication commands, URLs and provider error bodies may contain credentials.
    if (
      error instanceof Error &&
      error.message.startsWith("MODEL_CAPACITY_UNVERIFIED:")
    )
      throw error;
    throw unverified("provider metadata could not be verified");
  }
};

export async function captureModelCapacity(
  ctx: ExtensionContext,
  selected: Model<Api>,
  verify: CapacityVerifier,
  settings: PolicySettings = DEFAULT_SETTINGS,
) {
  const sameModel = () => isDeepStrictEqual(ctx.model, selected);
  if (!sameModel())
    throw unverified("selected model changed during request preparation");
  const verified = await verify(selected, ctx, settings);
  const metadata =
    typeof verified === "object" && verified !== null
      ? (verified as {
          contextWindow: unknown;
          modelName?: string;
          maxOutputTokens?: number;
        })
      : undefined;
  const contextWindow = metadata ? metadata.contextWindow : verified;
  ctx.signal?.throwIfAborted();
  if (!sameModel())
    throw unverified("selected model changed during request preparation");
  const contextLimit = deriveContextLimit(contextWindow, settings);
  return Object.freeze({
    provider: selected.provider,
    modelId: selected.id,
    contextWindow: contextWindow as number,
    contextLimit,
    ...(metadata?.modelName ? { modelName: metadata.modelName } : {}),
    ...(metadata?.maxOutputTokens
      ? { maxOutputTokens: metadata.maxOutputTokens }
      : {}),
  });
}
