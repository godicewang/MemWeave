import { FooterComponent, type AgentSession, type ContextUsage, type ExtensionAPI,
  type ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AssistantMessage } from "@earendil-works/pi-ai";

/** FooterComponent's read surface, verified against both supported hosts (1.3/1.4).
 * This is a display adapter, never an AgentSession or another agent runtime.
 * Keep the single constructor assertion here: Pi's public component types its
 * argument as the full AgentSession although it only reads the fields below.
 */
function footerView(ctx: ExtensionContext, usage: () => ContextUsage): AgentSession {
  const view = {
    sessionManager: ctx.sessionManager,
    get model() { return ctx.model; },
    get state() { return { model: ctx.model, thinkingLevel: ctx.thinkingLevel }; },
    routedModel: undefined, // Virtual routing is outside MemWeave's supported combinations.
    modelRuntime: {
      isUsingSubscription: (provider: string) => !!ctx.model && ctx.model.provider === provider &&
        ctx.modelRegistry.isUsingOAuth(ctx.model) &&
        ctx.modelRegistry.getProvider(provider)?.auth?.oauth?.isSubscription === true,
    },
    getContextUsage: usage,
  };
  return view as unknown as AgentSession;
}

function modelKey(ctx: ExtensionContext): string {
  return JSON.stringify([ctx.model?.provider, ctx.model?.api, ctx.model?.id]);
}
function actualTokens(message: AssistantMessage): number | undefined {
  if (!["stop", "length", "toolUse"].includes(message.stopReason)) return;
  const parts = [message.usage.input, message.usage.cacheRead, message.usage.cacheWrite, message.usage.output];
  if (!parts.every(n => Number.isSafeInteger(n) && n >= 0)) return;
  const total = parts.reduce((a, b) => a + b, 0);
  // Providers may emit an all-zero placeholder when usage is unavailable.
  if (total > 0 && Number.isSafeInteger(total)) return total;
}

/** Request-local accounting only; the host component owns all rendering/stats. */
export function registerContextFooter(pi: ExtensionAPI) {
  let scope: { manager: object; sessionId: string; model: string } | undefined;
  let pending: { capacity: number; signal: AbortSignal | undefined } | undefined;
  let last: ContextUsage | undefined, capacity = 0;
  let display: { refresh: () => void } | undefined;

  function reset(ctx: ExtensionContext) {
    scope = { manager: ctx.sessionManager, sessionId: ctx.sessionManager.getSessionId(), model: modelKey(ctx) };
    pending = undefined;
    last = undefined;
    capacity = ctx.model?.contextWindow ?? 0;
  }
  function sameScope(ctx: ExtensionContext) {
    return scope?.manager === ctx.sessionManager && scope.sessionId === ctx.sessionManager.getSessionId() &&
      scope.model === modelKey(ctx);
  }
  function usage(): ContextUsage {
    return last ?? { tokens: null, percent: null, contextWindow: capacity };
  }
  function refresh() {
    // setSession invalidates the native component's stats cache by view identity.
    // The old immutable response snapshot remains visible during preparation.
    display?.refresh();
  }
  function startup(ctx: ExtensionContext) {
    if (ctx.mode !== "tui" || !ctx.hasUI) return;
    reset(ctx);
    ctx.ui.setFooter((tui, _theme, data) => {
      const footer = new FooterComponent(footerView(ctx, usage), data);
      footer.setAutoCompactEnabled(false);
      const unsubscribe = data.onBranchChange(() => tui.requestRender());
      const active = { refresh: () => {
        footer.setSession(footerView(ctx, usage));
        tui.requestRender();
      } };
      display = active;
      return {
        render: width => footer.render(width),
        invalidate: () => footer.invalidate(),
        dispose: () => { unsubscribe(); footer.dispose(); if (display === active) display = undefined; },
      };
    });
  }
  pi.on("session_start", (_event, ctx) => startup(ctx));
  const changed = (_event: unknown, ctx: ExtensionContext) => {
    reset(ctx);
    refresh();
  };
  pi.on("session_tree", changed);
  pi.on("model_select", changed);
  pi.on("session_shutdown", () => { pending = undefined; last = undefined; display = undefined; scope = undefined; });
  pi.on("message_end", (event, ctx) => {
    if (event.message.role !== "assistant" || !pending || !sameScope(ctx)) return;
    const frame = pending;
    pending = undefined;
    const message = event.message;
    if (frame.signal?.aborted || message.model !== ctx.model?.id || message.provider !== ctx.model?.provider ||
      message.api !== ctx.model?.api) return;
    const tokens = actualTokens(message);
    if (tokens !== undefined) {
      last = { tokens, contextWindow: frame.capacity, percent: tokens / frame.capacity * 100 };
      refresh();
    }
  });
  return {
    startup,
    prepare(ctx: ExtensionContext, contextWindow: number) {
      if (ctx.mode !== "tui" || !ctx.hasUI) return;
      if (!sameScope(ctx)) reset(ctx);
      capacity = contextWindow;
      pending = { capacity: contextWindow, signal: ctx.signal };
      refresh();
    },
  };
}
