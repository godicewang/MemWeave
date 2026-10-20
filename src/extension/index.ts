import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerRequestLifecycle } from "../pi/request-lifecycle.ts";

/** Stage 0: native lifecycle guards; memory business modules are connected in later stages. */
export default function memweave(pi: ExtensionAPI): void {
  registerRequestLifecycle(pi);
}
