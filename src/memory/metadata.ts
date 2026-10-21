import { Check } from "typebox/value";
import { isDeepStrictEqual } from "node:util";
import type { Task } from "../task/model.ts";
import type { SessionMemory } from "../pi/session-memory.ts";
import {
  ALIAS_TYPE,
  ORIGINAL_TYPE,
  AliasesSchema,
  OriginalsSchema,
  type Alias,
  type Original,
} from "./model.ts";

export function aliasOrigin(alias: Omit<Alias, "ref">): string {
  return JSON.stringify([
    alias.source_task_id,
    alias.source_ref,
    alias.part_index ?? null,
  ]);
}
export async function loadAliases(
  task: Task,
  memory: SessionMemory,
): Promise<Map<string, Alias>> {
  const result = new Map<string, Alias>(),
    origins = new Map<string, string>();
  for (const source of task.sessions) {
    const view = await memory.files.readView(source.file, source.session_id);
    for (const entry of view.custom) {
      if (entry.type !== "custom" || entry.customType !== ALIAS_TYPE) continue;
      if (!Check(AliasesSchema, entry.data))
        throw Error("CORRUPT_ALIAS_METADATA");
      if (entry.data.task_id !== task.task_id) continue;
      for (const binding of entry.data.bindings) {
        if (!Number.isSafeInteger(Number(binding.ref.slice(1))))
          throw Error("CORRUPT_ALIAS_COUNTER");
        const previous = result.get(binding.ref),
          origin = aliasOrigin(binding);
        if (
          (previous && !isDeepStrictEqual(previous, binding)) ||
          (origins.has(origin) && origins.get(origin) !== binding.ref)
        )
          throw Error("ALIAS_COLLISION");
        result.set(binding.ref, binding);
        origins.set(origin, binding.ref);
      }
    }
  }
  return result;
}
export async function loadOriginals(
  task: Task,
  memory: SessionMemory,
): Promise<Map<string, Original>> {
  const result = new Map<string, Original>();
  for (const source of task.sessions) {
    let view;
    try {
      view = await memory.files.readView(source.file, source.session_id);
    } catch {
      continue;
    } // Read-only callers still report missing sources per requested ref.
    for (const entry of view.custom) {
      if (entry.type !== "custom" || entry.customType !== ORIGINAL_TYPE)
        continue;
      if (!Check(OriginalsSchema, entry.data))
        throw Error("CORRUPT_ORIGINAL_METADATA");
      if (entry.data.task_id !== task.task_id) continue;
      for (const binding of entry.data.bindings) {
        const previous = result.get(binding.ref);
        if (previous && !isDeepStrictEqual(previous, binding))
          throw Error("ORIGINAL_COLLISION");
        result.set(binding.ref, binding);
      }
    }
  }
  return result;
}
