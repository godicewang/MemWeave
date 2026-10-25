import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { isDeepStrictEqual } from "node:util";
import { restartMetadata, type RestartRecord } from "../task/restart-model.ts";
import { indexEvents, type InteractionEvent } from "./select.ts";
import { WINDOW_TYPE, type WindowMetadata } from "./model.ts";
import type { MemoryConfig } from "../config/schema.ts";
import { scopeOf } from "../pi/session-memory.ts";

export function restartSeed(events: InteractionEvent[], N: number): InteractionEvent[] {
  const tail = events.slice(-N);
  if (tail.some((event) => event.messages[0]?.message.role === "user")) return tail;
  const user = events.findLast((event) => event.messages[0]?.message.role === "user");
  return user ? [user, ...(N > 1 ? events.slice(-(N - 1)) : [])] : tail;
}
export function validateRestart(entries: SessionEntry[], receipt: RestartRecord): InteractionEvent[] {
  const before = entries.slice(0, receipt.position);
  const anchor = before.findLast((entry) => entry.type === "message" && entry.message.role !== "system")?.id ?? null;
  const seed = restartSeed(indexEvents(before), receipt.data.recent_turns);
  if (scopeOf(before).task_id !== receipt.data.previous_task_id || anchor !== receipt.data.anchor_entry_id
    || !isDeepStrictEqual(seed.map((event) => event.id), receipt.data.seed_event_ids))
    throw Error("CORRUPT_RESTART_SOURCE: original seed or anchor changed");
  return seed;
}
/** Keep the non-contiguous seed only until ordinary boundaries or an N/B reset supersede it. */
export function restartEvents(
  entries: SessionEntry[],
  previous: WindowMetadata | null,
  config: Pick<MemoryConfig, "recent_turns" | "evict_turns">,
): InteractionEvent[] {
  const all = indexEvents(entries), receipt = restartMetadata(entries);
  if (!receipt) return all;
  const seed = validateRestart(entries, receipt);
  const positions = new Map(entries.map((entry, index) => [entry.id, index]));
  const anchor = receipt.data.anchor_entry_id === null ? -1 : positions.get(receipt.data.anchor_entry_id)!;
  const reset = entries.slice(receipt.position + 1).some((entry) => entry.type === "custom"
    && entry.customType === WINDOW_TYPE && typeof entry.data === "object" && entry.data !== null
    && "stage" in entry.data && entry.data.stage === "reset");
  if (reset || previous && (previous.recent_turns !== config.recent_turns || previous.evict_turns !== config.evict_turns)
    || previous?.boundary_entry_id && positions.get(previous.boundary_entry_id)! >= anchor)
    return all;
  return [...seed, ...all.filter((event) => positions.get(event.id)! > anchor)];
}
