import type { Task } from "../task/model.ts";
import { Check } from "typebox/value";
import { SessionMemory, REF_TYPE, ReferencesSchema } from "./session-memory.ts";
import type { LocatedReference } from "../memory/references.ts";
import { isDeepStrictEqual } from "node:util";

/** Read-only lookup tolerates unrelated missing sources, never resets or allocates counters. */
export async function originalSource(
  task: Task,
  ref: string,
  memory: SessionMemory,
) {
  const views = new Map<
    string,
    Awaited<ReturnType<SessionMemory["files"]["readView"]>>
  >();
  let unavailable = false;
  for (const source of task.sessions) {
    try {
      views.set(
        source.session_id,
        await memory.files.readView(source.file, source.session_id),
      );
    } catch {
      unavailable = true;
    }
  }
  let located: LocatedReference | undefined;
  for (const view of views.values())
    for (const entry of view.custom) {
      if (entry.type !== "custom" || entry.customType !== REF_TYPE) continue;
      if (!Check(ReferencesSchema, entry.data))
        throw Error("CORRUPT_REFERENCE_METADATA");
      if (entry.data.task_id !== task.task_id) continue;
      for (const binding of entry.data.bindings) {
        if (binding.ref !== ref) continue;
        const candidate = {
          ...binding,
          source_session_id: entry.data.source_session_id,
        };
        if (located && !isDeepStrictEqual(located, candidate))
          throw Error("REFERENCE_NUMBER_COLLISION");
        located = candidate;
      }
    }
  if (!located)
    throw Error(
      unavailable ? "REFERENCE_SOURCE_MISSING" : "REFERENCE_NOT_FOUND",
    );
  const source = views.get(located.source_session_id);
  if (!source) throw Error("REFERENCE_SOURCE_MISSING");
  const entry = source.byId.get(located.entry_id);
  if (entry?.type !== "message") throw Error("REFERENCE_ENTRY_MISSING");
  const message = entry.message;
  if (
    message.role !== "user" &&
    message.role !== "assistant" &&
    message.role !== "toolResult"
  )
    throw Error("UNSUPPORTED_SOURCE_MESSAGE");
  const role = message.role;
  if (
    (ref[0] === "U" && role !== "user") ||
    (ref[0] === "A" && role !== "assistant") ||
    (ref[0] === "T" &&
      (role !== "toolResult" || message.toolCallId !== located.tool_call_id))
  )
    throw Error("CORRUPT_REFERENCE_KIND");
  if (role === "toolResult") {
    let ancestor = entry.parentId ? source.byId.get(entry.parentId) : undefined;
    while (
      ancestor &&
      !(ancestor.type === "message" && ancestor.message.role === "assistant")
    )
      ancestor = ancestor.parentId
        ? source.byId.get(ancestor.parentId)
        : undefined;
    if (
      !ancestor ||
      ancestor.type !== "message" ||
      ancestor.message.role !== "assistant" ||
      !ancestor.message.content.some(
        (p) => p.type === "toolCall" && p.id === located!.tool_call_id,
      )
    )
      throw Error("UNPAIRED_TOOL_REFERENCE");
  }
  return { location: located, message };
}
