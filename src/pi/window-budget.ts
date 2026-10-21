import {
  clampThinkingLevel,
  type Api,
  type Model,
  type ModelThinkingLevel,
} from "@earendil-works/pi-ai";
import { originalImage } from "./original-image.ts";
/** Pi 1.3.0 ordinary main-session output ceiling; reserve overrides conservatively. */
export function outputReserve(
  model: Model<Api>,
  level: ModelThinkingLevel = "off",
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
