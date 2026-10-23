import { DEFAULT_SETTINGS, type PolicySettings } from "../config/defaults.ts";
import {
  clampThinkingLevel,
  type Api,
  type Model,
  type ModelThinkingLevel,
} from "@earendil-works/pi-ai";
import { budgetPlan } from "../window/policy.ts";
import { originalImage } from "./original-image.ts";
/** Pi 1.3.0 ordinary main-session output ceiling; reserve overrides conservatively. */
export function outputReserve(
  model: Model<Api>,
  level: ModelThinkingLevel = "off",
  contextLimit?: number,
  providerCap?: number,
  settings: PolicySettings = DEFAULT_SETTINGS,
): number {
  let output = model.maxTokens;
  const params = {
    ...model.samplingParams,
    ...model.samplingParamsByThinkingLevel?.[clampThinkingLevel(model, level)],
  };
  const overrides: number[] = [];
  for (const key of [
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
  ]) {
    const value = params?.[key];
    if (value === undefined) continue;
    if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1)
      throw Error("OUTPUT_BUDGET_UNVERIFIED");
    overrides.push(value);
  }
  if (overrides.length) output = Math.max(...overrides);
  if (!Number.isSafeInteger(output) || output < 1)
    throw Error("OUTPUT_BUDGET_UNVERIFIED");
  if (
    providerCap !== undefined &&
    (!Number.isSafeInteger(providerCap) || providerCap < 1)
  )
    throw Error("OUTPUT_BUDGET_UNVERIFIED");
  if (contextLimit !== undefined) {
    if (!overrides.length)
      output = Math.min(
        output,
        providerCap ?? output,
        Math.max(1, budgetPlan(contextLimit, settings).output),
      );
    if (
      (providerCap !== undefined && output > providerCap) ||
      output >= contextLimit
    )
      throw Error("OUTPUT_BUDGET_UNVERIFIED: output exceeds verified budget");
  }
  return output;
}
/** Official Flash vision guide caps each image at 1024 tokens; reserve twice that bound.
 * https://api-docs.deepseek.com/guides/vision/ (verified 2026-10-22).
 * No assumptions for other providers or endpoints, including virtual routing. */
export function imageReserve(model: Model<Api>, image: unknown): number {
  originalImage(image);
  if (
    model.provider === "deepseek" &&
    model.id === "deepseek-flash" &&
    model.api === "openai-completions" &&
    new URL(model.baseUrl).hostname === "api.deepseek.com"
  )
    return 2048;
  throw Error(
    "IMAGE_TOKEN_BUDGET_UNVERIFIED: no verified image budget for this model",
  );
}

/** Only the output limit is changed; payload history and native retry behavior stay with Pi. */
export function alignOutput(
  payload: unknown,
  model: Model<Api>,
  output: number,
): Record<string, unknown> {
  if (
    model.api !== "openai-completions" ||
    typeof payload !== "object" ||
    payload === null ||
    Array.isArray(payload)
  )
    throw Error("OUTPUT_BUDGET_UNVERIFIED: unsupported payload");
  const body = payload as Record<string, unknown>;
  const fields = [
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
  ].filter((k) => Object.hasOwn(body, k));
  if (
    body.model !== model.id ||
    fields.length !== 1 ||
    fields[0] === "max_output_tokens"
  )
    throw Error("OUTPUT_BUDGET_UNVERIFIED: model or output fields changed");
  const key = fields[0]!;
  if (
    typeof body[key] !== "number" ||
    !Number.isSafeInteger(body[key]) ||
    (body[key] as number) < 1
  )
    throw Error("OUTPUT_BUDGET_UNVERIFIED: invalid output field");
  return { ...body, [key]: output };
}
