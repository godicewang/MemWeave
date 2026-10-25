import { Check } from "typebox/value";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { MemoryReadSchema } from "../memory/model.ts";
import { StateReadSchema, historyReadRanges } from "../state/read.ts";
import type { InteractionEvent } from "./select.ts";
import { DEFAULT_SETTINGS } from "../config/defaults.ts";
/** Raw branch messages determine age; injected context and retries cannot advance it. */
export function readKinds(
  events: InteractionEvent[],
  entries: SessionEntry[],
  lifetimeMessages = DEFAULT_SETTINGS.read.lifetime_messages,
) {
  const granted = new Set<string>(), active = new Set<string>(), expired = new Set<string>(),
    recent = new Set<string>();
  const accept = (id: string, complete: boolean) => {
    (recent.has(id) ? active : expired).add(id);
    if (complete && recent.has(id)) granted.add(id);
  };
  for (
    let i = entries.length - 1;
    i >= 0 && recent.size < lifetimeMessages;
    i--
  ) {
    const entry = entries[i]!;
    if (
      entry.type === "message" &&
      ["user", "assistant", "toolResult"].includes(entry.message.role)
    )
      recent.add(entry.id);
  }
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i]!;
    const assistant = event.messages[0]?.message;
    if (assistant?.role !== "assistant") continue;
    for (const item of event.messages.slice(1)) {
      const result = item.message;
      if (
        result.role !== "toolResult" ||
        !["memory_read", "state_read"].includes(result.toolName) ||
        result.isError
      )
        continue;
      const call = assistant.content.find(
        (p) => p.type === "toolCall" && p.id === result.toolCallId,
      );
      if (call?.type !== "toolCall" || call.name !== result.toolName) continue;
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
        if (result.toolName === "state_read") {
          if (
            !Check(StateReadSchema, call.arguments) ||
            !("event_ids" in call.arguments)
          )
            continue;
          const payload = JSON.parse(body.text) as {
            task_id?: unknown;
            items?: { id?: unknown }[];
          };
          const ranges = historyReadRanges(payload);
          if (
            payload.task_id !== call.arguments.task_id ||
            JSON.stringify(payload.items?.map((row) => row.id)) !==
              JSON.stringify(call.arguments.event_ids)
          )
            continue;
          if (
            JSON.stringify(ranges) === JSON.stringify(marker.memweave_read.ranges)
          ) accept(item.entryId, ranges.some((r) => r.range_complete));
          continue;
        }
        if (!Check(MemoryReadSchema, call.arguments)) continue;
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
        accept(item.entryId, ranges.some((r) => r.status === "ok" && r.range_complete === true));
      } catch {
        /* Malformed or untrusted marker never grants an exemption. */
      }
    }
  }
  return { active, expired, full: granted };
}

/** Compatibility helper for callers interested in complete, unexpired original ranges. */
export function readGrants(events: InteractionEvent[], entries: SessionEntry[], lifetimeMessages = DEFAULT_SETTINGS.read.lifetime_messages) {
  return readKinds(events, entries, lifetimeMessages).full;
}
