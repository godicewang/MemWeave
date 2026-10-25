import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { type TestContext } from "node:test";
import { setTimeout } from "node:timers/promises";
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager,
  type ExtensionUIContext } from "@earendil-works/pi-coding-agent";
import { fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { registerMemweave } from "../../src/extension/register.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { isSetupComplete } from "../../src/storage/setup.ts";

async function fixture(t: TestContext, options: { accept?: boolean; projectEnabled?: boolean; mode?: "tui" | "print";
  confirm?: () => Promise<boolean>; failReload?: boolean; reloadDelayMs?: number } = {}) {
  const root = await mkdtemp(join(tmpdir(), "memweave-native-setup-"));
  const cwd = join(root, "business"), agentDir = join(root, "agent"), paths = memoryPaths(join(root, "memory"));
  await mkdir(cwd); await mkdir(agentDir);
  await writeFile(join(agentDir, "settings.json"), JSON.stringify({ compaction: { enabled: true }, retry: { enabled: false }, cacheWarming: "off" }));
  if (options.projectEnabled) {
    await mkdir(join(cwd, ".pi"));
    await writeFile(join(cwd, ".pi/settings.json"), '{"compaction":{"enabled":true}}');
  }
  const settings = SettingsManager.create(cwd, agentDir, { projectTrusted: true });
  const runtime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null,
    modelsStorePath: join(agentDir, "models.json"), refreshOnCreate: false });
  const faux = fauxProvider({ provider: "setup-fixture", models: [{ id: "test", contextWindow: 1000000, maxTokens: 1024 }], tokensPerSecond: Infinity });
  runtime.registerNativeProvider(faux.provider);
  const diagnostics: string[] = [], errors: string[] = [], prompts: string[] = [];
  let accept = options.accept ?? true, reloads = 0, completedReloads = 0,
    failReload = options.failReload ?? false, packageVersion = "0.1.0";
  const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings,
    noExtensions: true, noSkills: true, noThemes: true, noPromptTemplates: true,
    extensionFactories: [pi => { registerMemweave(pi, { paths, setupAgentDir: agentDir, setupPackageVersion: packageVersion,
      verifyCapacity: async () => 1000000, report: error => diagnostics.push(String(error)) }); }],
  });
  await loader.reload();
  const manager = SessionManager.create(cwd, join(root, "sessions"));
  const { session } = await createAgentSession({ cwd, agentDir, settingsManager: settings,
    modelRuntime: runtime, model: faux.getModel(), sessionManager: manager, resourceLoader: loader, noTools: "builtin", thinkingLevel: "off" });
  t.after(async () => { await session.abort(); session.dispose(); await rm(root, { recursive: true, force: true }); });
  const ui = { confirm: async (_title: string, message: string) => { prompts.push(message); return options.confirm ? options.confirm() : accept; }, notify: () => {}, setFooter: () => {} } as unknown as ExtensionUIContext;
  const bind = () => session.bindExtensions({ mode: options.mode ?? "tui", ...(options.mode === "print" ? {} : { uiContext: ui }),
    onError: error => errors.push(error.error), commandContextActions: {
      waitForIdle: () => session.waitForIdle(), newSession: async () => ({ cancelled: true }),
      fork: async () => ({ cancelled: true }), navigateTree: async () => ({ cancelled: true }), switchSession: async () => ({ cancelled: true }),
      reload: async () => { reloads++; if (failReload) throw Error("fixture reload failure");
        await session.reload({ beforeSessionStart: () => setTimeout(options.reloadDelayMs ?? 0) }); completedReloads++; },
    } });
  return { paths, agentDir, cwd, settings, faux, manager, session, diagnostics, errors, prompts, bind,
    setAccept: (value: boolean) => { accept = value; }, setFailReload: (value: boolean) => { failReload = value; },
    setPackageVersion: (value: string) => { packageVersion = value; }, get reloads() { return reloads; },
    get completedReloads() { return completedReloads; } };
}

async function waitUntil(done: () => boolean) {
  const deadline = Date.now() + 5000;
  while (!done()) { assert.ok(Date.now() < deadline, "setup did not settle"); await setTimeout(10); }
}

test("native first-start command confirms once, replaces Rule, reloads effective settings and never calls a model", async t => {
  const h = await fixture(t);
  await mkdir(h.paths.root); await writeFile(h.paths.rule, "EXISTING CUSTOM RULE");
  await h.bind();
  await waitUntil(() => h.completedReloads === 1 && h.settings.getCompactionEnabled() === false);
  assert.equal(h.prompts.length, 1);
  assert.match(h.prompts[0]!, /替换/); assert.match(h.prompts[0]!, /全局/);
  assert.equal(await isSetupComplete(h.paths, h.agentDir), true);
  assert.match(await readFile(h.paths.rule, "utf8"), /长程任务记忆协议/);
  assert.equal(h.faux.state.callCount, 0);
  assert.equal(h.manager.getBranch().filter(e => e.type === "message").length, 0);
  await writeFile(h.paths.rule, "USER EDIT {{recent_turns}}");
  await h.session.reload();
  await h.session.prompt("/memweave-setup");
  assert.equal(h.prompts.length, 1);
  assert.equal(await readFile(h.paths.rule, "utf8"), "USER EDIT {{recent_turns}}");
  h.faux.setResponses([fauxAssistantMessage("ready")]);
  await h.session.prompt("normal user request");
  assert.equal(h.faux.state.callCount, 1);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
});

test("declining writes nothing and cancels inference; an explicit command can retry and finish", async t => {
  const h = await fixture(t, { accept: false });
  const settingsBefore = await readFile(join(h.agentDir, "settings.json"));
  await h.bind(); await waitUntil(() => h.prompts.length === 1); await setTimeout(20);
  await assert.rejects(readFile(h.paths.rule), { code: "ENOENT" });
  assert.equal(await isSetupComplete(h.paths, h.agentDir), false);
  assert.ok(settingsBefore.equals(await readFile(join(h.agentDir, "settings.json"))));
  await h.session.prompt("cancelled setup must not infer");
  assert.equal(h.faux.state.callCount, 0);
  h.setAccept(true);
  await h.session.prompt("/memweave-setup");
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.equal(h.prompts.length, 2);
  assert.equal(h.reloads, 1);
  assert.deepEqual(h.errors, []);
});

test("global setup preserves project override and blocks inference when effective compaction is still enabled", async t => {
  const h = await fixture(t, { projectEnabled: true });
  await h.bind(); await waitUntil(() => h.completedReloads === 1);
  assert.equal(JSON.parse(await readFile(join(h.agentDir, "settings.json"), "utf8")).compaction.enabled, false);
  assert.equal(h.settings.getCompactionEnabled(), true);
  assert.equal(await readFile(join(h.cwd, ".pi/settings.json"), "utf8"), '{"compaction":{"enabled":true}}');
  await h.session.prompt("project override must be diagnosed");
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(h.diagnostics.some(message => message.includes("COMPACTION_ENABLED")));
  assert.equal(h.prompts.length, 1);
});

test("headless startup never silently initializes or writes user files", async t => {
  const h = await fixture(t, { mode: "print" });
  const before = await readFile(join(h.agentDir, "settings.json"));
  await h.bind();
  await h.session.prompt("no interaction available");
  assert.equal(h.prompts.length, 0); assert.equal(h.reloads, 0);
  assert.equal(h.faux.state.callCount, 0);
  assert.equal(await isSetupComplete(h.paths, h.agentDir), false);
  await assert.rejects(readFile(h.paths.rule), { code: "ENOENT" });
  assert.ok(before.equals(await readFile(join(h.agentDir, "settings.json"))));
});

test("pending confirmation cancels concurrent inference before any initialization is committed", async t => {
  let answer!: (value: boolean) => void;
  const confirmation = new Promise<boolean>(resolve => { answer = resolve; });
  const h = await fixture(t, { confirm: () => confirmation });
  await h.bind(); await waitUntil(() => h.prompts.length === 1);
  await h.session.prompt("do not bypass the pending prompt");
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(h.diagnostics.some(message => message.includes("SETUP_PENDING")));
  assert.equal(await isSetupComplete(h.paths, h.agentDir), false);
  answer(true);
  await waitUntil(() => h.completedReloads === 1 && !h.settings.getCompactionEnabled());
  assert.deepEqual(h.errors, []);
});

test("partial initialization failure blocks inference and can be retried through the native command", async t => {
  const h = await fixture(t);
  await writeFile(join(h.agentDir, "settings.json"), "{");
  await h.bind(); await waitUntil(() => h.diagnostics.some(message => message.includes("SETUP_FAILED")));
  assert.equal(await isSetupComplete(h.paths, h.agentDir), false);
  assert.match(await readFile(h.paths.rule, "utf8"), /长程任务记忆协议/);
  await h.session.prompt("failed setup must not infer");
  assert.equal(h.faux.state.callCount, 0);
  await writeFile(join(h.agentDir, "settings.json"), "{}");
  await h.session.prompt("/memweave-setup");
  assert.equal(h.prompts.length, 2);
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.equal(await isSetupComplete(h.paths, h.agentDir), true);
  assert.deepEqual(h.errors, []);
});

test("failed reload leaves a guard, and retry refreshes settings without replacing Rule again", async t => {
  const h = await fixture(t, { failReload: true });
  await h.bind(); await waitUntil(() => h.errors.some(message => message.includes("fixture reload failure")));
  assert.equal(await isSetupComplete(h.paths, h.agentDir), true);
  await writeFile(h.paths.rule, "KEEP AFTER COMMIT");
  await h.session.prompt("old runtime must not infer");
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(h.diagnostics.some(message => message.includes("SETUP_RELOAD_REQUIRED")));
  h.setFailReload(false);
  await h.session.prompt("/memweave-setup");
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.equal(h.prompts.length, 1);
  assert.equal(await readFile(h.paths.rule, "utf8"), "KEEP AFTER COMMIT");
});

test("native reload after a package version change refreshes Rule without another confirmation or model request", async t => {
  const h = await fixture(t, { reloadDelayMs: 75 });
  await h.bind(); await waitUntil(() => h.completedReloads === 1 && !h.settings.getCompactionEnabled());
  const settingsBefore = await readFile(join(h.agentDir, "settings.json"));
  await writeFile(h.paths.rule, "CUSTOM OLD VERSION");
  h.setPackageVersion("0.2.0");
  await h.session.reload();
  assert.match(await readFile(h.paths.rule, "utf8"), /长程任务记忆协议/);
  assert.deepEqual(JSON.parse(await readFile(h.paths.setup(h.agentDir).marker, "utf8")), { version: 2, package_version: "0.2.0" });
  assert.equal(h.prompts.length, 1); assert.equal(h.faux.state.callCount, 0);
  assert.ok(settingsBefore.equals(await readFile(join(h.agentDir, "settings.json"))));
  await writeFile(h.paths.rule, "SAME VERSION EDIT");
  await h.session.reload();
  assert.equal(await readFile(h.paths.rule, "utf8"), "SAME VERSION EDIT");
  assert.deepEqual(h.errors, []); assert.deepEqual(h.diagnostics, []);
});

test("previously initialized headless startup refreshes a legacy Rule without changing settings", async t => {
  const h = await fixture(t, { mode: "print" });
  await mkdir(join(h.paths.root, "setup"), { recursive: true });
  await writeFile(h.paths.setup(h.agentDir).marker, '{"version":1}');
  await writeFile(h.paths.rule, "LEGACY CUSTOM RULE");
  h.settings.setCompactionEnabled(false); await h.settings.flush();
  const before = await readFile(join(h.agentDir, "settings.json"));
  await h.bind();
  assert.match(await readFile(h.paths.rule, "utf8"), /长程任务记忆协议/);
  assert.deepEqual(JSON.parse(await readFile(h.paths.setup(h.agentDir).marker, "utf8")), { version: 2, package_version: "0.1.0" });
  assert.ok(before.equals(await readFile(join(h.agentDir, "settings.json"))));
  assert.equal(h.prompts.length, 0); assert.equal(h.faux.state.callCount, 0);
  assert.deepEqual(h.errors, []); assert.deepEqual(h.diagnostics, []);
});

test("failed startup upgrade cancels inference until the pending package version is successfully applied", async t => {
  const h = await fixture(t);
  await h.bind(); await waitUntil(() => h.completedReloads === 1 && !h.settings.getCompactionEnabled());
  const markerBefore = await readFile(h.paths.setup(h.agentDir).marker);
  await rm(h.paths.rule); await mkdir(h.paths.rule);
  h.setPackageVersion("0.2.0");
  await h.session.reload();
  await h.session.prompt("failed upgrade must not infer");
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(markerBefore.equals(await readFile(h.paths.setup(h.agentDir).marker)));
  assert.ok(h.diagnostics.some(message => message.includes("SETUP_FAILED")));
  await rm(h.paths.rule, { recursive: true });
  await h.session.reload();
  assert.deepEqual(JSON.parse(await readFile(h.paths.setup(h.agentDir).marker, "utf8")), { version: 2, package_version: "0.2.0" });
  assert.match(await readFile(h.paths.rule, "utf8"), /长程任务记忆协议/);
  assert.equal(h.prompts.length, 1);
  assert.deepEqual(h.errors, []);
});
