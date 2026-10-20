import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerRequestLifecycle } from "../pi/request-lifecycle.ts";
import { createRuleRequestServices } from "../pi/rule-services.ts";

/** Native lifecycle and Rule preparation; Task/State/Window connect at later stages. */
export default function memweave(pi: ExtensionAPI): void {
  registerRequestLifecycle(pi, createRuleRequestServices());
}
