import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerLauncher } from "./launcher.ts";
export default function memweave(pi: ExtensionAPI): void {
  registerLauncher(pi);
}
