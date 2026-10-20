import { getCurrentSystemMessage } from "@earendil-works/pi-ai";
import type { RequestMessages } from "./request-lifecycle.ts";

/** Pi owns replay and tool projection. The caller only edits a detached request view. */
export function replaySystem(messages: RequestMessages) {
  const system = getCurrentSystemMessage(messages);
  if (!system) throw new Error("MISSING_SYSTEM: effective system message is required");
  return structuredClone(system);
}
