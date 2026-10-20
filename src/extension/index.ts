import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerMemweave } from "./register.ts";
export default function memweave(pi: ExtensionAPI): void {
  registerMemweave(pi);
}
