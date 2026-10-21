import { Check } from "typebox/value";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { StateBatchSchema, type StateBatch } from "../state/window.ts";
import { STATE_REQUEST_TYPE, sourceAssistant } from "./session-memory.ts";

/** Only an anchor prepared after the preceding native message belongs to this assistant request. */
export function requestStateBatch(
  ctx: ExtensionContext,
  callId: string,
  taskId: string,
): StateBatch {
  const assistant = sourceAssistant(ctx, callId);
  for (const entry of ctx.sessionManager
    .getBranch(assistant.id)
    .slice(0, -1)
    .reverse()) {
    if (entry.type === "message") break;
    if (entry.type !== "custom" || entry.customType !== STATE_REQUEST_TYPE)
      continue;
    if (!Check(StateBatchSchema, entry.data))
      throw Error("CORRUPT_STATE_BATCH_METADATA");
    if (entry.data.task_id !== taskId) throw Error("STATE_BATCH_TASK_CHANGED");
    return structuredClone(entry.data);
  }
  throw Error("STATE_BATCH_NOT_PREPARED: wait for a State window reminder");
}
