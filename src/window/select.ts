import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import type { RequestMessages } from "../pi/request-lifecycle.ts";
import type { MemoryConfig } from "../config/schema.ts";
import { stableId } from "../storage/identity.ts";
import type { WindowMetadata } from "./model.ts";
export type NativeMessage = Extract<
  RequestMessages[number],
  { role: "user" | "assistant" | "toolResult" }
>;
export interface WindowMessage {
  entryId: string;
  message: NativeMessage;
}
export interface InteractionEvent {
  id: string;
  messages: WindowMessage[];
}
/** Native entry identity, never request labels or serialized provider messages, defines events. */
export function indexEvents(entries: SessionEntry[]): InteractionEvent[] {
  const events: InteractionEvent[] = [];
  let current: InteractionEvent | undefined,
    missing = new Set<string>();
  for (const entry of entries) {
    if (entry.type !== "message" || entry.message.role === "system") continue;
    const message = entry.message;
    if (
      message.role === "assistant" &&
      (message.stopReason === "error" || message.stopReason === "aborted")
    )
      continue;
    if (
      message.role !== "user" &&
      message.role !== "assistant" &&
      message.role !== "toolResult"
    )
      throw Error("UNSUPPORTED_WINDOW_HISTORY: native message representation");
    if (message.role === "toolResult") {
      if (!current || !missing.delete(message.toolCallId))
        throw Error("UNPAIRED_TOOL_RESULT");
      current.messages.push({ entryId: entry.id, message });
    } else {
      if (missing.size) throw Error("INCOMPLETE_TOOL_EVENT");
      current = { id: entry.id, messages: [{ entryId: entry.id, message }] };
      events.push(current);
      missing = new Set(
        message.role === "assistant"
          ? message.content
              .filter((p) => p.type === "toolCall")
              .map((p) => p.id)
          : [],
      );
      if (
        message.role === "assistant" &&
        missing.size !==
          message.content.filter((p) => p.type === "toolCall").length
      )
        throw Error("DUPLICATE_TOOL_CALL_ID");
    }
  }
  if (missing.size) throw Error("INCOMPLETE_TOOL_EVENT");
  return events;
}
export function selectWindow(
  events: InteractionEvent[],
  config: MemoryConfig,
  previous: WindowMetadata | null,
  session: string,
  anchor: string | null,
) {
  let boundary = previous?.boundary_entry_id ?? null,
    reset = false;
  if (
    previous &&
    (previous.recent_turns !== config.recent_turns ||
      previous.evict_turns !== config.evict_turns)
  ) {
    boundary = events.at(-(config.recent_turns + 1))?.id ?? null;
    reset = true;
  }
  const index =
    boundary === null ? -1 : events.findIndex((e) => e.id === boundary);
  if (boundary !== null && index < 0)
    throw Error("WINDOW_BOUNDARY_NOT_ON_BRANCH");
  const visible = events.slice(index + 1);
  const pending = reset ? [] : structuredClone(previous?.pending ?? []);
  let consumed = 0,
    prior = boundary;
  for (const batch of pending) {
    const candidates = visible
      .slice(consumed, consumed + config.evict_turns)
      .map((e) => e.id);
    if (
      batch.candidate_event_ids.length !== config.evict_turns ||
      JSON.stringify(candidates) !== JSON.stringify(batch.candidate_event_ids)
    )
      throw Error("CORRUPT_WINDOW_BATCH");
    consumed += candidates.length;
    prior = candidates.at(-1)!;
  }
  while (visible.length - consumed > config.recent_turns) {
    const candidates = visible
      .slice(consumed, consumed + config.evict_turns)
      .map((e) => e.id);
    pending.push({
      batch_id: stableId(session, prior ?? "", ...candidates),
      candidate_event_ids: candidates,
    });
    consumed += candidates.length;
    prior = candidates.at(-1)!;
  }
  const metadata: WindowMetadata = {
    stage: reset ? "reset" : "prepare",
    recent_turns: config.recent_turns,
    evict_turns: config.evict_turns,
    boundary_entry_id: boundary,
    pending,
    request_anchor_entry_id: anchor,
    completed_by: null,
  };
  return { events: visible, metadata };
}
