import { readFile } from "node:fs/promises";
import type { MemoryPaths } from "../storage/paths.ts";
import { mergeConfig, type MemoryConfig } from "./schema.ts";

export async function readConfigSnapshot(paths: MemoryPaths, overrides: unknown = {}, signal?: AbortSignal): Promise<MemoryConfig> {
  signal?.throwIfAborted();
  let bytes: Buffer;
  try {
    bytes = await readFile(paths.config, { signal });
  } catch (error) {
    if (signal?.aborted) signal.throwIfAborted();
    throw new Error("CONFIG_READ_FAILED: cannot read config.json");
  }
  let data: unknown;
  try {
    data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new Error("INVALID_CONFIG: config.json must contain valid UTF-8 JSON");
  }
  signal?.throwIfAborted();
  return mergeConfig(data, overrides);
}
