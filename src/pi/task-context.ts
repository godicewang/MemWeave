import type { TaskSnapshot } from "../task/service.ts";
import { Check } from "typebox/value";
import { REF_TYPE, ReferencesSchema } from "./session-memory.ts";
import type { RequestMessages } from "./request-lifecycle.ts";

/** Labels live exclusively in this request view; opaque native message fields remain intact. */
export function taskContext(
  messages: RequestMessages,
  snapshot: TaskSnapshot,
): RequestMessages {
  const entries = snapshot.entries;
  const byEntry = new Map<string, string>();
  for (const entry of entries) {
    if (entry.type !== "custom" || entry.customType !== REF_TYPE) continue;
    if (!Check(ReferencesSchema, entry.data))
      throw Error("CORRUPT_REFERENCE_METADATA");
    if (entry.data.task_id !== snapshot.task?.task_id) continue;
    for (const binding of entry.data.bindings) {
      const reference = snapshot.references.get(binding.ref);
      if (
        reference?.source_session_id === entry.data.source_session_id &&
        reference.entry_id === binding.entry_id
      )
        byEntry.set(binding.entry_id, binding.ref);
    }
  }
  const labels = new Map<string, string>();
  for (const entry of entries)
    if (entry.type === "message" && byEntry.has(entry.id))
      labels.set(JSON.stringify(entry.message), byEntry.get(entry.id)!);
  const view = messages.map((message) => {
    const ref = labels.get(JSON.stringify(message));
    if (!ref || message.role === "system") return message;
    const copy = structuredClone(message);
    if (copy.role === "user" && typeof copy.content === "string")
      copy.content = `[${ref}]\n${copy.content}`;
    else if (copy.role === "user" && Array.isArray(copy.content))
      copy.content = [{ type: "text", text: `[${ref}]` }, ...copy.content];
    else if (copy.role === "assistant")
      copy.content = [{ type: "text", text: `[${ref}]` }, ...copy.content];
    else if (copy.role === "toolResult")
      copy.content = [{ type: "text", text: `[${ref}]` }, ...copy.content];
    return copy;
  });
  if (snapshot.state)
    view.push({ role: "user", content: snapshot.state, timestamp: 0 });
  return view;
}
