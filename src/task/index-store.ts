import { isAbsolute } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { Check } from "typebox/value";
import { IndexSchema, type Task } from "./model.ts";
import { atomicWrite, readOptional, withLock } from "../storage/files.ts";
import type { MemoryPaths } from "../storage/paths.ts";
export class TaskIndex {
  readonly paths: MemoryPaths;
  constructor(paths: MemoryPaths) {
    this.paths = paths;
  }
  async read(): Promise<Task[]> {
    const bytes = await readOptional(this.paths.index);
    if (bytes === undefined) return [];
    let value: unknown;
    try {
      value = JSON.parse(bytes);
    } catch {
      throw Error("CORRUPT_TASK_INDEX");
    }
    if (
      !Check(IndexSchema, value) ||
      new Set(value.map((t) => t.task_id)).size !== value.length ||
      value.some(
        (t) =>
          !Number.isFinite(Date.parse(t.updated_at)) ||
          new Set(t.sessions.map((s) => s.session_id)).size !==
            t.sessions.length ||
          t.sessions.some((s) => !isAbsolute(s.file)),
      )
    )
      throw Error("CORRUPT_TASK_INDEX");
    return value;
  }
  async get(id: string): Promise<Task> {
    const task = (await this.read()).find((t) => t.task_id === id);
    if (!task) throw Error(`TASK_NOT_FOUND: ${id}`);
    return task;
  }
  async put(task: Task): Promise<void> {
    if (!Check(IndexSchema, [task])) throw Error("INVALID_TASK_METADATA");
    await withLock(this.paths.indexLock, async () => {
      const tasks = await this.read(),
        i = tasks.findIndex((t) => t.task_id === task.task_id);
      if (i >= 0 && isDeepStrictEqual(tasks[i], task)) return;
      if (i < 0) tasks.push(task);
      else tasks[i] = task;
      await atomicWrite(
        this.paths.index,
        JSON.stringify(tasks, null, 2) + "\n",
      );
    });
  }
}
