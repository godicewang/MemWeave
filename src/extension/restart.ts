import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WindowService } from "../pi/window-service.ts";

/** Explicit user command; never triggers inference or appends a synthetic user message. */
export function registerRestart(
  pi: ExtensionAPI,
  window: WindowService,
  report: (error: unknown, ctx: ExtensionContext) => void,
): void {
  let running = false;
  pi.registerCommand("memweave-restart", {
    description: "Start a fresh Task from recent events, preserving old memory; then send a new user request",
    async handler(args, ctx) {
      let ownsRun = false;
      try {
        if (args.trim()) throw Error("RESTART_ARGUMENTS_NOT_SUPPORTED: /memweave-restart takes no arguments");
        if (running || !ctx.isIdle() || ctx.hasPendingMessages())
          throw Error("RESTART_BUSY: wait for the current run and queued input to finish");
        running = true;
        ownsRun = true;
        ctx.ui.notify(await window.restart(ctx), "info");
      } catch (error) {
        report(error, ctx);
      } finally { if (ownsRun) running = false; }
    },
  });
}
