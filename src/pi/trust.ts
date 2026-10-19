import {
  hasTrustRequiringProjectResources,
  ProjectTrustStore,
  type LoadExtensionsResult,
  type ProjectTrustContext,
  type ProjectTrustHandler,
  type SettingsManager,
  type ExtensionError,
} from "@earendil-works/pi-coding-agent";

/** Pi 1.3 does not export its CLI resolver. Adapt the exported trust/extension contracts for a headless host. */
export async function resolveHeadlessProjectTrust(options: {
  cwd: string;
  agentDir: string;
  settings: SettingsManager;
  extensions: LoadExtensionsResult;
  report: (error: ExtensionError) => void;
}): Promise<boolean> {
  if (!hasTrustRequiringProjectResources(options.cwd)) return true;
  const store = new ProjectTrustStore(options.agentDir);
  const context: ProjectTrustContext = {
    cwd: options.cwd, mode: "print", hasUI: false,
    ui: { async select() { return undefined; }, async confirm() { return false; },
      async input() { return undefined; }, notify(message) { console.error(message); } },
  };
  // The ordered handler collections are part of Pi's exported Extension type.
  for (const extension of options.extensions.extensions) {
    for (const handler of extension.handlers.get("project_trust") ?? []) {
      try {
        const result = await (handler as ProjectTrustHandler)({ type: "project_trust", cwd: options.cwd }, context);
        if (result?.trusted === "undecided") continue;
        if (result?.trusted !== "yes" && result?.trusted !== "no") {
          throw new Error("project_trust must return yes, no or undecided");
        }
        const trusted = result.trusted === "yes";
        if (result.remember === true) store.set(options.cwd, trusted);
        return trusted;
      } catch (error) {
        options.report({ extensionPath: extension.path, event: "project_trust",
          error: error instanceof Error ? error.message : String(error) });
      }
    }
  }
  const saved = store.get(options.cwd);
  if (saved !== null) return saved;
  // Pi's headless CLI cannot ask: unknown projects are untrusted unless globally allowed.
  return options.settings.getDefaultProjectTrust() === "always";
}
