import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
export interface TaskLocation {
  readonly workspace: string;
  readonly task_id: string;
}
export interface MemoryPaths {
  readonly root: string;
  readonly config: string;
  readonly rule: string;
  readonly index: string;
  readonly indexLock: string;
  blob(hash: string): string;
  state(task: TaskLocation): string;
  view(task: TaskLocation): string;
  taskLock(task: TaskLocation): string;
}
function segment(value: string): string {
  if (!/^[^/\\:\x00]+$/.test(value) || value === "." || value === "..")
    throw Error("INVALID_STORAGE_ID");
  return value;
}
export function parentPath(file: string): string {
  return dirname(file);
}
export function temporaryPath(file: string): string {
  return `${file}.${randomUUID()}.tmp`;
}
export function lockOwnerPath(lock: string): string {
  return join(lock, "owner");
}
export function memoryPaths(
  root: string = join(homedir(), ".pi", "memory"),
): MemoryPaths {
  if (typeof root !== "string" || !isAbsolute(root))
    throw Error("INVALID_MEMORY_ROOT: an absolute path is required");
  const normalized = resolve(root);
  const taskFile = (task: TaskLocation, file: string) =>
    join(
      normalized,
      segment(task.workspace),
      "tasks",
      segment(task.task_id),
      file,
    );
  return Object.freeze({
    root: normalized,
    config: join(normalized, "config.json"),
    rule: join(normalized, "rule.md"),
    index: join(normalized, "index.json"),
    indexLock: join(normalized, "index.lock"),
    blob: (hash: string) => {
      if (!/^[a-f0-9]{64}$/.test(hash)) throw Error("INVALID_BLOB_HASH");
      return join(normalized, "blobs", hash);
    },
    state: (task: TaskLocation) => taskFile(task, "state.json"),
    view: (task: TaskLocation) => taskFile(task, "state.md"),
    taskLock: (task: TaskLocation) => taskFile(task, "write.lock"),
  });
}
