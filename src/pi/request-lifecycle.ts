import { VERSION, type ContextWithSystemEvent, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";

export type RequestMessages = ContextWithSystemEvent["messages"];

/** Internal seam for the later Rule/Task/Window modules; no persisted frame or new model tool. */
export interface RequestServices {
  prepare(messages: RequestMessages, ctx: ExtensionContext): Promise<RequestMessages>;
  report(error: unknown, ctx: ExtensionContext): void;
}

export function assertSupportedHost(version: string): void {
  if (version !== "1.3.0") throw new Error(`UNVERIFIED_PI_VERSION: ${version}; verified target is 1.3.0`);
}

export function registerRequestLifecycle(pi: ExtensionAPI, services?: RequestServices): () => void {
  const report = services?.report ?? ((error: unknown, ctx: ExtensionContext) => {
    const message = error instanceof Error ? error.message : "MEMWEAVE_REQUEST_FAILED";
    if (ctx.hasUI) ctx.ui.notify(message, "error");
    else console.error(`[MemWeave] ${message}`);
  });
  const check = () => {
    assertSupportedHost(VERSION);
    if (pi.getSettings().compaction?.enabled !== false) {
      throw new Error("COMPACTION_ENABLED: explicitly set Pi compaction.enabled=false and reload");
    }
  };
  const subscriptions = [
    pi.on("session_start", (_event, ctx) => {
      try { check(); } catch (error) { report(error, ctx); }
    }),
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
  return () => { for (const unsubscribe of subscriptions) unsubscribe(); };
}
