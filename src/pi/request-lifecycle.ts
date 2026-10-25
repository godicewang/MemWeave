import { VERSION, type ContextWithSystemEvent, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";

export type RequestMessages = ContextWithSystemEvent["messages"];

/** Internal seam for the later Rule/Task/Window modules; no persisted frame or new model tool. */
export interface RequestServices {
  /** Clear optional in-memory request helpers on native Session startup/reload/replacement. */
  reset?(): void;
  /** False defers the startup check until a user initialization command reloads Pi. */
  startup?(ctx: ExtensionContext): Promise<boolean>;
  assertReady?(): void;
  prepare(messages: RequestMessages, ctx: ExtensionContext): Promise<RequestMessages>;
  report(error: unknown, ctx: ExtensionContext): void;
}

export function assertSupportedHost(version: string): void {
  if (version !== "1.3.0" && version !== "1.4.0") {
    throw new Error(`UNVERIFIED_PI_VERSION: ${version}; verified targets are 1.3.0 and 1.4.0`);
  }
}

export function reportRequestError(error: unknown, ctx: ExtensionContext): void {
  const message = error instanceof Error ? error.message : "MEMWEAVE_REQUEST_FAILED";
  if (ctx.hasUI) ctx.ui.notify(message, "error");
  else console.error(`[MemWeave] ${message}`);
}

export function registerRequestLifecycle(pi: ExtensionAPI, services?: RequestServices) {
  const report = services?.report ?? reportRequestError;
  const check = () => {
    assertSupportedHost(VERSION);
    services?.assertReady?.();
    if (pi.getSettings().compaction?.enabled !== false) {
      throw new Error("COMPACTION_ENABLED: effective Pi compaction.enabled must be false; a project override can re-enable it; adjust settings and reload");
    }
  };
  const startup = async (ctx: ExtensionContext) => {
    try {
      services?.reset?.();
      assertSupportedHost(VERSION);
      if (services?.startup && !await services.startup(ctx)) return;
      check();
    } catch (error) { report(error, ctx); }
  };
  const subscriptions = [
    pi.on("session_start", (_event, ctx) => startup(ctx)),
    pi.on("session_before_compact", () => ({ cancel: true })),
    pi.on("context_with_system", async (event, ctx) => {
      try {
        check();
        ctx.signal?.throwIfAborted();
        const messages = services ? await services.prepare(event.messages, ctx) : event.messages;
        ctx.signal?.throwIfAborted();
        return { messages };
      } catch (error) {
        ctx.abort(); // Pi catches handler exceptions; cancellation must happen before reporting.
        report(error, ctx);
        return { messages: event.messages };
      }
    }),
  ];
  return { startup, dispose: () => { for (const unsubscribe of subscriptions) unsubscribe(); } };
}
