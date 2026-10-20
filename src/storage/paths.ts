import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

export interface MemoryPaths {
  readonly root: string;
  readonly config: string;
  readonly rule: string;
}

/** The root override is an internal composition/test seam, not a new config field or model tool. */
export function memoryPaths(root: string = join(homedir(), ".pi", "memory")): MemoryPaths {
  if (typeof root !== "string" || !isAbsolute(root)) throw new Error("INVALID_MEMORY_ROOT: an absolute path is required");
  const normalized = resolve(root);
  return Object.freeze({ root: normalized, config: join(normalized, "config.json"), rule: join(normalized, "rule.md") });
}
