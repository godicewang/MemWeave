import type { ExtensionFactory } from "@earendil-works/pi-coding-agent";
import type { RequestController } from "../pi/requests.js";

/** Registration only: request business logic is supplied by the host's pipeline. */
export function createMemWeaveExtension<Frame>(requests: RequestController<Frame>): ExtensionFactory {
  return (pi) => {
    pi.on("context", (event) => requests.transform(event.messages));
    pi.on("session_before_compact", () => ({ cancel: true }));
    pi.on("session_start", () => { requests.invalidate(); });
    pi.on("session_shutdown", () => { requests.invalidate(); });
    pi.on("agent_end", () => { requests.invalidate(); });
  };
}
