import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ModelRuntime, SessionManager } from "@earendil-works/pi-coding-agent";
import { expect, it } from "vitest";
import { createMemWeaveHost } from "../../src/pi/index.js";
import { temporaryWorkspace } from "../fixtures/workspace.js";

// Explicit opt-in; credentials are read in place and never copied into fixtures or output.
const agentDir = process.env.MEMWEAVE_LIVE_AGENT_DIR;
it.skipIf(!agentDir)("runs the native SDK host with the private DeepSeek profile", async () => {
  if (!agentDir) throw new Error("MEMWEAVE_LIVE_AGENT_DIR is required");
  const workspace = await temporaryWorkspace();
  let host: Awaited<ReturnType<typeof createMemWeaveHost>> | undefined;
  try {
    const settingsPath = join(agentDir, "settings.json");
    const before = await readFile(settingsPath, "utf8");
    const modelRuntime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null });
    const model = modelRuntime.getModel("deepseek", "deepseek-flash");
    if (!model) throw new Error("DeepSeek validation model is not available");
    host = await createMemWeaveHost({
      cwd: workspace.cwd, agentDir, modelRuntime, model, thinkingLevel: "off", tools: [],
      sessionManager: SessionManager.create(workspace.cwd, join(workspace.root, "sessions")),
      resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true },
      pipeline: () => ({
        async prepare(request) { return { frame: undefined, messages: request.context.messages }; },
        async transform(messages) { return messages; },
      }),
    });
    await host.session.prompt("Reply with exactly MEMWEAVE_HOST_OK. Do not use tools.");
    expect(host.session.agent.state.errorMessage).toBeUndefined();
    expect(host.session.getLastAssistantText()?.trim()).toBe("MEMWEAVE_HOST_OK");
    expect(host.session.autoCompactionEnabled).toBe(false);
    expect(await readFile(settingsPath, "utf8")).toBe(before);
  } finally {
    try { await host?.dispose(); } finally { await workspace.cleanup(); }
  }
}, 60_000);
