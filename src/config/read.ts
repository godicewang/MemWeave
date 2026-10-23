import { readFile } from "node:fs/promises";
import type { MemoryPaths } from "../storage/paths.ts";
import { configInput, mergeConfig } from "./schema.ts";

export async function readConfigInput(paths: MemoryPaths, signal?: AbortSignal) {
  signal?.throwIfAborted();
  let bytes: Buffer;
  try { bytes = await readFile(paths.config, { signal }); }
  catch (error) {
    if (signal?.aborted) signal.throwIfAborted();
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return configInput({});
    throw Error("CONFIG_READ_FAILED: cannot read config.json");
  }
  let data: unknown;
  try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw Error("INVALID_CONFIG: config.json must contain valid UTF-8 JSON"); }
  signal?.throwIfAborted();
  return configInput(data);
}
export async function readConfigSnapshot(paths: MemoryPaths, overrides: unknown = {}, signal?: AbortSignal, contextLimit?: number) {
  return mergeConfig(await readConfigInput(paths, signal), overrides, contextLimit);
}
