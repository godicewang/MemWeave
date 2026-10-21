import { Check } from "typebox/value";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { MemoryReadSchema } from "../memory/model.ts";
import type { InteractionEvent } from "./select.ts";
/** Only the immediately preceding completed native tool turn can grant X; text cannot grant it. */
export function readGrants(
  events: InteractionEvent[],
  entries: SessionEntry[],
): Set<string> {
  const granted = new Set<string>(),
    last = events.at(-1),
    latest = entries.findLast(
      (e) => e.type === "message" && e.message.role !== "system",
    );
  if (!last || last.messages.at(-1)?.entryId !== latest?.id) return granted;
  const assistant = last.messages[0]?.message;
  if (assistant?.role !== "assistant") return granted;
  for (const item of last.messages.slice(1)) {
    const result = item.message;
    if (
      result.role !== "toolResult" ||
      result.toolName !== "memory_read" ||
      result.isError
    )
      continue;
    const call = assistant.content.find(
      (p) => p.type === "toolCall" && p.id === result.toolCallId,
    );
    if (
      call?.type !== "toolCall" ||
      call.name !== "memory_read" ||
      !Check(MemoryReadSchema, call.arguments)
    )
      continue;
    const marker = result.details as
      | { memweave_read?: { version?: unknown; ranges?: unknown } }
      | undefined;
    if (
      marker?.memweave_read?.version !== 1 ||
      !Array.isArray(marker.memweave_read.ranges)
    )
      continue;
    const body = result.content[0];
    if (body?.type !== "text") continue;
    try {
      const payload = JSON.parse(body.text) as { items?: unknown[] };
      if (
        !Array.isArray(payload.items) ||
        payload.items.length !== call.arguments.items.length
      )
        continue;
      const ranges = payload.items.map((value) => {
        const row = value as Record<string, unknown>;
        if (typeof row.content !== "string") throw Error();
        return {
          ref: row.resolved_ref ?? row.ref,
          source_task_id: row.source_task_id,
          offset: row.offset,
          returned_chars: [...row.content].length,
          range_complete: row.range_complete,
          source_complete: row.source_complete,
          status: row.status,
        };
      });
      if (
        JSON.stringify(ranges) !== JSON.stringify(marker.memweave_read.ranges)
      )
        continue;
      if (ranges.some((r) => r.status === "ok" && r.range_complete === true))
        granted.add(item.entryId);
    } catch {
      /* Malformed or untrusted marker never grants an exemption. */
    }
  }
  return granted;
}
