import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { TaskIdSchema } from "./model.ts";
import { stableId } from "../storage/identity.ts";
export const RESTART_TYPE = "memweave.restart.v1";
const id = Type.String({ minLength: 1 });
const integer = Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER });
export const RestartSchema = Type.Object({
  restart_id: id,
  previous_task_id: Type.Union([TaskIdSchema, Type.Null()]),
  anchor_entry_id: Type.Union([id, Type.Null()]),
  seed_event_ids: Type.Array(id, { uniqueItems: true }),
  recent_turns: integer,
  evict_turns: integer,
}, { additionalProperties: false });
export type RestartData = Static<typeof RestartSchema>;
export interface RestartRecord { id: string; position: number; data: RestartData }
export function restartMetadata(entries: SessionEntry[]): RestartRecord | null {
  for (let position = entries.length - 1; position >= 0; position--) {
    const entry = entries[position]!;
    if (entry.type !== "custom" || entry.customType !== RESTART_TYPE) continue;
    if (!Check(RestartSchema, entry.data) || entry.data.evict_turns > entry.data.recent_turns
      || entry.data.seed_event_ids.length > entry.data.recent_turns)
      throw Error("CORRUPT_RESTART_METADATA");
    return { id: entry.id, position, data: entry.data };
  }
  return null;
}
export function restartTaskId(session: string, restart: string): string {
  return "task_" + stableId("restart-task", session, restart).slice(0, 32);
}
