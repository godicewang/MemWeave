import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { Tokenizer } from "@huggingface/tokenizers";
import type { Api, Model } from "@earendil-works/pi-ai";
export interface TokenCounter {
  readonly estimator: string;
  count(text: string): number;
}
export const conservativeCounter: TokenCounter = Object.freeze({
  estimator: "utf8-bytes-with-protocol-margin",
  count: (text: string) => Buffer.byteLength(text, "utf8"),
});
let official: Promise<TokenCounter> | undefined;
export function deepseekCounter(): Promise<TokenCounter> {
  return (official ??= (async () => {
    const data = await readFile(
      new URL("../../resources/tokenizer/deepseek-v41.json", import.meta.url),
    );
    if (
      createHash("sha256").update(data).digest("hex") !==
      "81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99"
    )
      throw Error("TOKENIZER_RESOURCE_INVALID");
    const json = JSON.parse(data.toString("utf8")) as Record<string, unknown>;
    // User-provided spellings of control tokens are ordinary text, never protocol tokens.
    json.added_tokens = [];
    const tokenizer = new Tokenizer(json, {}); // BPE has bounded upstream LRU (10,000 short pieces).
    return Object.freeze({
      estimator: "deepseek-v41-text-with-protocol-margin",
      count: (text: string) =>
        tokenizer.encode(text, { add_special_tokens: false }).ids.length,
    });
  })());
}
export function counterForModel(
  model: Model<Api>,
  modelName?: string,
): Promise<TokenCounter> {
  const officialEndpoint =
    model.provider === "deepseek" &&
    model.api === "openai-completions" &&
    new URL(model.baseUrl).hostname === "api.deepseek.com";
  // Do not silently assume a future Flash revision still uses this tokenizer.
  return officialEndpoint &&
    model.id === "deepseek-flash" &&
    modelName !== undefined &&
    /(?:^|[- _])V4\.1(?:[- _]|$)/.test(modelName)
    ? deepseekCounter()
    : Promise.resolve(conservativeCounter);
}
