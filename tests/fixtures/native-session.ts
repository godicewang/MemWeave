import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { TestContext } from "node:test";
import {
  createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager,
  type AgentSession, type ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";

export async function nativeSession(t: TestContext, factories: ExtensionFactory[] = [], enabled = false, reserveTokens = 512, additionalExtensionPaths: string[] = []) {
  const root = await mkdtemp(join(tmpdir(), "memweave-stage0-"));
  let activeSession: AgentSession | undefined;
  t.after(async () => {
    await activeSession?.abort();
    activeSession?.dispose();
    await rm(root, { recursive: true, force: true });
  });
  const cwd = join(root, "workspace");
  const agentDir = join(root, "agent");
  await mkdir(cwd); await mkdir(agentDir);
  await writeFile(join(agentDir, "SYSTEM.md"), "NATIVE_SYSTEM");
  await writeFile(join(agentDir, "APPEND_SYSTEM.md"), "NATIVE_APPEND {{untouched}}");
  const settings = SettingsManager.inMemory({
    compaction: { enabled, reserveTokens, keepRecentTokens: 128 },
    retry: { enabled: false }, cacheWarming: "off",
  }, { projectTrusted: true });
  const runtime = await ModelRuntime.create({
    authPath: join(agentDir, "auth.json"), modelsPath: null,
    modelsStorePath: join(agentDir, "models-cache.json"), refreshOnCreate: false,
  });
  const faux = fauxProvider({
    provider: "memweave-test", models: [{ id: "probe", contextWindow: 1_048_576, maxTokens: 1024 }],
    tokensPerSecond: Infinity,
  });
  runtime.registerNativeProvider(faux.provider);
  const loader = new DefaultResourceLoader({
    cwd, agentDir, settingsManager: settings, extensionFactories: factories, additionalExtensionPaths,
    noExtensions: true, noSkills: true, noThemes: true, noPromptTemplates: true,
  });
  await loader.reload();
  const manager = SessionManager.create(cwd, join(root, "sessions"));
  const { session, extensionsResult } = await createAgentSession({
    cwd, agentDir, modelRuntime: runtime, model: faux.getModel(),
    settingsManager: settings, sessionManager: manager, resourceLoader: loader, noTools: "builtin", thinkingLevel: "off",
  });
  activeSession = session;
  assert.deepEqual(extensionsResult.errors, []);
  const errors: string[] = [];
  await session.bindExtensions({ onError: (error) => { errors.push(error.error); } });
  faux.setResponses([fauxAssistantMessage("OK")]);
  return { root, cwd, agentDir, settings, runtime, faux, loader, manager, session, errors };
}
