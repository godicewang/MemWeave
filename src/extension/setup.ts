import { getAgentDir, VERSION, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { assertPackageVersion, completeSetup, isSetupComplete } from "../storage/setup.ts";
import type { MemoryPaths } from "../storage/paths.ts";
import { disableGlobalCompaction, loadDefaultRule, loadPackageVersion } from "../pi/setup-settings.ts";
import { assertSupportedHost } from "../pi/request-lifecycle.ts";

/** Initialization is a user command, never an LLM tool or an npm lifecycle script. */
export function registerSetup(
  pi: ExtensionAPI, paths: MemoryPaths,
  report: (error: unknown, ctx: ExtensionContext) => void,
  agentDir = getAgentDir(),
  packageVersion?: string,
  registerCommand = true,
) {
  let attempted = false, pending = false, running = false;
  let failure: unknown;
  let versionPromise: Promise<string> | undefined;
  const version = () => versionPromise ??= (async () => {
    const value = packageVersion ?? await loadPackageVersion();
    assertPackageVersion(value);
    return value;
  })();
  const apply = async (ctx: ExtensionContext) => completeSetup(paths, agentDir, loadDefaultRule,
    () => disableGlobalCompaction(ctx.cwd, agentDir), await version());
  async function prepareInteractive(ctx: ExtensionContext) {
    assertSupportedHost(VERSION);
    if (ctx.mode !== "tui" || !ctx.hasUI)
      throw Error("SETUP_UI_REQUIRED: start interactive pi to confirm initialization");
    if (!await isSetupComplete(paths, agentDir)) {
      const accepted = await ctx.ui.confirm("初始化 MemWeave", [
        `直接创建或替换默认 Rule：${paths.rule}`,
        "以后升级扩展时也会自动更新 Rule，覆盖你的自定义内容。",
        `全局关闭 Pi 自动压缩：${paths.setup(agentDir).settings}`,
        "同一 Pi 配置范围的其他会话读取后也会受影响；卸载后保留。",
        "保留其他设置和记忆；项目显式覆盖仍可能开启压缩。",
        "回车确认后自动重新加载 Pi。",
      ].join("\n"));
      if (!accepted) throw Error("SETUP_CANCELLED: no initialization files written; retry /memweave-setup when ready");
    }
    await apply(ctx);
  }
  if (registerCommand) pi.registerCommand("memweave-setup", {
    description: "Initialize or update the package Rule; confirm first-run global compaction disablement, then reload Pi",
    async handler(args, ctx) {
      if (running) return;
      running = true;
      pending = true;
      failure = undefined;
      try {
        if (args.trim()) throw Error("SETUP_ARGUMENTS_NOT_SUPPORTED: /memweave-setup takes no arguments");
        await prepareInteractive(ctx);
        ctx.ui.notify("MemWeave 初始化已完成，正在重新加载 Pi。", "info");
      } catch (error) {
        failure = error;
        pending = false;
        running = false;
        ctx.abort();
        report(error, ctx);
        return;
      }
      // Reload is terminal: the old context and pi bindings must never be used afterwards.
      pending = false;
      running = false;
      failure = Error("SETUP_RELOAD_REQUIRED: retry /memweave-setup or restart pi to refresh settings");
      await ctx.reload();
    },
  });
  return {
    prepareInteractive,
    async startup(ctx: ExtensionContext): Promise<boolean> {
      try {
        if (await isSetupComplete(paths, agentDir)) {
          await apply(ctx);
          return true;
        }
        if (ctx.mode !== "tui" || !ctx.hasUI) return true;
        if (!attempted) {
          attempted = true;
          pending = true;
          pi.sendUserMessage("/memweave-setup", { expandPromptTemplates: true });
        }
        return false;
      } catch (error) { failure = error; throw error; }
    },
    assertReady() {
      if (failure) throw failure;
      if (pending) throw Error("SETUP_PENDING: finish the initialization confirmation before sending a request");
    },
  };
}
