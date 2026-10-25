import { getAgentDir, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { memoryPaths } from "../storage/paths.ts";
import { reportRequestError } from "../pi/request-lifecycle.ts";
import { setGlobalCompaction } from "../pi/setup-settings.ts";
import { registerSetup } from "./setup.ts";
import type { MemweaveOptions, registerMemweaveRuntime } from "./register.ts";

type Mode = "on" | "off";
// Reload retains SessionManager; /new, /resume and /fork replace it. Public shutdown
// events carry the destination file, allowing a one-use handoff to that new instance.
// No ExtensionContext is retained and nothing is written to Session or memory files.
const key = Symbol.for("@godice/memweave/startup-mode/v2");
interface ModeScope { choices: WeakMap<object, Mode>; handoffs: Map<string, Mode> }
const scope = globalThis as typeof globalThis & { [key]?: ModeScope };
const { choices, handoffs } = scope[key] ??= { choices: new WeakMap(), handoffs: new Map() };

export function registerLauncher(pi: ExtensionAPI, options: MemweaveOptions = {}): void {
  const paths = options.paths ?? memoryPaths(), agentDir = options.setupAgentDir ?? getAgentDir();
  const report = options.report ?? reportRequestError;
  const setup = registerSetup(pi, paths, report, agentDir, options.setupPackageVersion, false);
  const destination = (file?: string) => JSON.stringify([agentDir, file ?? null]);
  let ready = false, attempted = false, running = false;
  let runtime: ReturnType<typeof registerMemweaveRuntime> | undefined;
  const unblock = pi.on("context_with_system", (event, ctx) => {
    if (ready) return;
    ctx.abort();
    report(Error("MODE_SELECTION_REQUIRED: finish startup or retry /memweave-setup"), ctx);
    return { messages: event.messages };
  });
  function status(ctx: ExtensionContext, mode: Mode) {
    if (!ctx.hasUI) return;
    ctx.ui.setStatus("memweave", mode === "on" ? "MemWeave 已启用" : "MemWeave 未启用");
  }
  pi.registerCommand("memweave-setup", {
    description: "Choose this Pi instance's startup mode, initialize MemWeave if enabled, and reload native settings",
    async handler(args, ctx) {
      if (running) return;
      running = true;
      ready = false;
      try {
        if (args.trim()) throw Error("SETUP_ARGUMENTS_NOT_SUPPORTED: /memweave-setup takes no arguments");
        if (ctx.mode !== "tui" || !ctx.hasUI) throw Error("SETUP_UI_REQUIRED: start interactive pi to choose startup mode");
        let mode = choices.get(ctx.sessionManager);
        if (!mode) {
          const items = ["启用 MemWeave（全局关闭自动压缩）", "MemWeave 未启用（全局恢复自动压缩）"];
          const selected = await ctx.ui.select("本次 Pi 启动模式（共用原生配置和 Session）", items);
          if (selected === undefined) throw Error("MODE_SELECTION_REQUIRED: selection cancelled; retry /memweave-setup");
          if (!items.includes(selected)) throw Error("MODE_SELECTION_REQUIRED: invalid selection");
          mode = selected === items[0] ? "on" : "off";
        }
        if (mode === "on") await setup.prepareInteractive(ctx);
        await setGlobalCompaction(ctx.cwd, agentDir, mode === "off");
        choices.set(ctx.sessionManager, mode);
        ctx.ui.notify("启动模式已保存到本次实例，正在重新加载 Pi。", "info");
      } catch (error) {
        running = false;
        ctx.abort();
        report(error, ctx);
        return;
      }
      running = false;
      // Terminal operation: reload invalidates this context and all its Pi bindings.
      await ctx.reload();
    },
  });
  pi.on("session_shutdown", (event, ctx) => {
    const mode = choices.get(ctx.sessionManager);
    if (mode && ["new", "resume", "fork"].includes(event.reason))
      handoffs.set(destination(event.targetSessionFile), mode);
    if (event.reason !== "reload") choices.delete(ctx.sessionManager);
  });
  pi.on("session_start", async (event, ctx) => {
    try {
      let mode = choices.get(ctx.sessionManager);
      if (!mode && ["new", "resume", "fork"].includes(event.reason)) {
        const target = destination(ctx.sessionManager.getSessionFile());
        mode = handoffs.get(target);
        handoffs.delete(target);
        if (mode) choices.set(ctx.sessionManager, mode);
      }
      if (!mode && ctx.mode === "tui" && ctx.hasUI) {
        if (!attempted) {
          attempted = true;
          pi.sendUserMessage("/memweave-setup", { expandPromptTemplates: true });
        }
        return;
      }
      // Preserve the existing non-interactive contract; no new global writes.
      mode ??= "on";
      if (mode === "on" && !runtime) {
        const { registerMemweaveRuntime } = await import("./register.ts");
        runtime = registerMemweaveRuntime(pi, options, setup);
        await runtime.startup(ctx);
      }
      ready = true;
      unblock();
      status(ctx, mode);
    } catch (error) {
      ctx.abort();
      report(error, ctx);
    }
  });
}
