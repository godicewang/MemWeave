import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { type TestContext } from "node:test";
import { setTimeout } from "node:timers/promises";
import { AgentSessionRuntime, createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager,
  type AgentSession, type ExtensionUIContext } from "@earendil-works/pi-coding-agent";
import { fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { registerLauncher } from "../../src/extension/launcher.ts";
import { memoryPaths } from "../../src/storage/paths.ts";

async function fixture(t: TestContext, options: { choice?: "on" | "off" | "cancel"; confirm?: boolean;
  headless?: boolean; projectEnabled?: boolean; invalidSettings?: boolean; reloadDelay?: number; reserveTokens?: number } = {}) {
  const root = await mkdtemp(join(tmpdir(), "memweave-mode-"));
  const cwd = join(root, "business"), agentDir = join(root, "agent"), paths = memoryPaths(join(root, "memory"));
  await mkdir(cwd); await mkdir(agentDir);
  await writeFile(join(agentDir, "settings.json"), JSON.stringify({ compaction: { enabled: false, reserveTokens: options.reserveTokens ?? 512, keepRecentTokens: 128 }, retry: { enabled: false }, cacheWarming: "off" }));
  if (options.projectEnabled !== undefined) {
    await mkdir(join(cwd, ".pi"));
    await writeFile(join(cwd, ".pi/settings.json"), JSON.stringify({ compaction: { enabled: options.projectEnabled } }));
  }
  const settings = SettingsManager.create(cwd, agentDir, { projectTrusted: true });
  const runtime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null,
    modelsStorePath: join(agentDir, "models.json"), refreshOnCreate: false });
  const faux = fauxProvider({ provider: "mode-fixture", models: [{ id: "test", contextWindow: 1000000, maxTokens: 1024 }], tokensPerSecond: Infinity });
  runtime.registerNativeProvider(faux.provider);
  const diagnostics: string[] = [], errors: string[] = [], statuses: string[] = [];
  let selections = 0, confirmations = 0, reloads = 0, footers = 0, choice = options.choice ?? "off";
  const makeLoader = () => new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings,
    noExtensions: true, noSkills: true, noThemes: true, noPromptTemplates: true,
    extensionFactories: [pi => registerLauncher(pi, { paths, setupAgentDir: agentDir, setupPackageVersion: "0.1.0",
      verifyCapacity: async () => 1000000, report: error => diagnostics.push(String(error)) })] });
  const loader = makeLoader();
  await loader.reload();
  const manager = SessionManager.create(cwd, join(root, "sessions"));
  const { session } = await createAgentSession({ cwd, agentDir, settingsManager: settings, modelRuntime: runtime,
    model: faux.getModel(), sessionManager: manager, resourceLoader: loader, noTools: "builtin", thinkingLevel: "off" });
  const services = { cwd, agentDir, settingsManager: settings, modelRuntime: runtime, resourceLoader: loader, diagnostics: [] };
  const host = new AgentSessionRuntime(session, services, async input => {
    const nextLoader = makeLoader();
    await nextLoader.reload();
    const next = await createAgentSession({ cwd: input.cwd, agentDir, settingsManager: settings, modelRuntime: runtime,
      model: faux.getModel(), sessionManager: input.sessionManager, resourceLoader: nextLoader, noTools: "builtin", thinkingLevel: "off",
      ...(input.sessionStartEvent ? { sessionStartEvent: input.sessionStartEvent } : {}) });
    return { ...next, services: { ...services, resourceLoader: nextLoader }, diagnostics: [] };
  });
  t.after(async () => { await host.dispose(); await rm(root, { recursive: true, force: true }); });
  const ui = { select: async (_title: string, items: string[]) => { selections++; return choice === "cancel" ? undefined : items[choice === "on" ? 0 : 1]; },
    confirm: async () => { confirmations++; return options.confirm ?? true; },
    setFooter: () => { footers++; },
    setStatus: (_key: string, status: string) => { statuses.push(status); }, notify: () => {} } as unknown as ExtensionUIContext;
  if (options.invalidSettings) await writeFile(join(agentDir, "settings.json"), "{");
  const bind = async (active: AgentSession) => active.bindExtensions({ mode: options.headless ? "print" : "tui", ...(options.headless ? {} : { uiContext: ui }),
    onError: error => errors.push(error.error), commandContextActions: {
      waitForIdle: () => active.waitForIdle(), newSession: options => host.newSession(options),
      fork: async () => ({ cancelled: true }), navigateTree: async () => ({ cancelled: true }), switchSession: async () => ({ cancelled: true }),
      reload: async () => { await active.reload({ beforeSessionStart: () => setTimeout(options.reloadDelay ?? 0) }); reloads++; },
    } });
  host.setRebindSession(bind);
  await bind(session);
  return { paths, agentDir, cwd, settings, faux, diagnostics, errors, statuses,
    get session() { return host.session; }, get manager() { return host.session.sessionManager; },
    get loader() { return host.services.resourceLoader; }, newSession: () => host.newSession(),
    switchSession: (file: string) => host.switchSession(file), fork: (id: string) => host.fork(id, { position: "at" }),
    choose: (next: typeof choice) => { choice = next; }, get selections() { return selections; },
    get confirmations() { return confirmations; }, get reloads() { return reloads; }, get footers() { return footers; } };
}
async function settled(done: () => boolean) {
  const deadline = Date.now() + 5000;
  while (!done()) { assert.ok(Date.now() < deadline, "mode selection did not settle"); await setTimeout(10); }
}

test("plain mode restores compaction, exposes no memory hooks/tools and uses the unchanged native Session", async t => {
  const h = await fixture(t, { reloadDelay: 75 });
  await settled(() => h.reloads === 1);
  assert.equal(h.selections, 1); assert.equal(h.confirmations, 0);
  assert.equal(h.settings.getCompactionEnabled(), true);
  assert.equal(h.statuses.at(-1), "MemWeave 未启用");
  assert.equal(h.footers, 0);
  const extension = h.loader.getExtensions().extensions[0]!;
  assert.deepEqual([...extension.tools.keys()], []);
  assert.deepEqual([...extension.handlers.keys()].sort(), ["session_shutdown", "session_start"]);
  await assert.rejects(readFile(h.paths.rule), { code: "ENOENT" });
  await assert.rejects(readFile(h.paths.setup(h.agentDir).marker), { code: "ENOENT" });
  h.faux.setResponses([fauxAssistantMessage("native answer")]);
  await h.session.prompt("native question");
  assert.equal(h.faux.state.callCount, 1);
  assert.deepEqual(h.manager.getBranch().filter(e => e.type === "message" && e.message.role !== "system")
    .map(e => e.type === "message" && e.message.role), ["user", "assistant"]);
  assert.equal(h.manager.getBranch().filter(e => e.type === "custom").length, 0);
  await h.session.reload();
  assert.equal(h.selections, 1);
  await h.newSession();
  assert.equal(h.selections, 1);
  assert.deepEqual(h.errors, []); assert.deepEqual(h.diagnostics, []);
});

test("plain mode permits actual native compaction and its Session record", async t => {
  const h = await fixture(t);
  await settled(() => h.reloads === 1);
  h.faux.setResponses([fauxAssistantMessage("old answer"), fauxAssistantMessage("recent answer"), fauxAssistantMessage("native summary")]);
  await h.session.prompt("old history ".repeat(2000));
  await h.session.prompt("recent history ".repeat(2000));
  await h.session.compact();
  assert.equal(h.manager.getBranch().filter(e => e.type === "compaction").length, 1);
  assert.equal(h.faux.state.callCount, 3);
  assert.deepEqual(h.errors, []);
});

test("native new/resume/fork replacement keeps the same mode without prompting again", async t => {
  const h = await fixture(t);
  await settled(() => h.reloads === 1);
  h.faux.setResponses([fauxAssistantMessage("original")]);
  await h.session.prompt("original user request");
  const file = h.manager.getSessionFile()!;
  const user = h.manager.getBranch().find(e => e.type === "message" && e.message.role === "user")!;
  await h.newSession();
  await h.switchSession(file);
  await h.fork(user.id);
  assert.equal(h.selections, 1);
  assert.equal(h.loader.getExtensions().extensions[0]!.tools.size, 0);
  assert.match(h.statuses.at(-1)!, /MemWeave 未启用/);
  assert.deepEqual(h.errors, []);
});

test("plain mode also allows Pi's automatic compaction after reaching its native threshold", async t => {
  const h = await fixture(t, { reserveTokens: 999000 });
  await settled(() => h.reloads === 1);
  h.faux.setResponses([fauxAssistantMessage("first"), fauxAssistantMessage("second"), fauxAssistantMessage("automatic summary")]);
  await h.session.prompt("old history ".repeat(2000));
  await h.session.prompt("new history ".repeat(2000));
  assert.ok(h.manager.getBranch().some(e => e.type === "compaction"));
  assert.deepEqual(h.errors, []);
});

test("enabled mode initializes once, registers memory and retains mode across native reload", async t => {
  const h = await fixture(t, { choice: "on" });
  await settled(() => h.reloads === 1);
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.equal(h.selections, 1); assert.equal(h.confirmations, 1);
  assert.equal(h.loader.getExtensions().extensions[0]!.tools.size, 11);
  assert.equal(h.statuses.at(-1), "MemWeave 已启用");
  assert.equal(h.footers, 1);
  await writeFile(h.paths.rule, "USER EDIT {{recent_turns}}");
  await h.session.reload();
  assert.equal(h.selections, 1);
  assert.equal(await readFile(h.paths.rule, "utf8"), "USER EDIT {{recent_turns}}");
  const shared = JSON.parse(await readFile(join(h.agentDir, "settings.json"), "utf8"));
  shared.compaction.enabled = true;
  await writeFile(join(h.agentDir, "settings.json"), JSON.stringify(shared));
  await h.session.prompt("/memweave-setup");
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.equal(await readFile(h.paths.rule, "utf8"), "USER EDIT {{recent_turns}}");
  await h.newSession();
  assert.equal(h.selections, 1);
  assert.equal(h.loader.getExtensions().extensions[0]!.tools.size, 11);
  h.faux.setResponses([fauxAssistantMessage("memory answer")]);
  await h.session.prompt("memory question");
  assert.equal(h.faux.state.callCount, 1);
  assert.deepEqual(h.diagnostics, []); assert.deepEqual(h.errors, []);
});

test("cancelled selection writes nothing, blocks inference and retries the existing command", async t => {
  const h = await fixture(t, { choice: "cancel" });
  await settled(() => h.selections === 1);
  await h.session.prompt("not yet selected");
  assert.equal(h.faux.state.callCount, 0); assert.equal(h.reloads, 0);
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.ok(h.diagnostics.some(e => e.includes("MODE_SELECTION_REQUIRED")));
  h.choose("off");
  await h.session.prompt("/memweave-setup");
  assert.equal(h.settings.getCompactionEnabled(), true);
  assert.equal(h.reloads, 1);
});

test("plain mode preserves explicit project compression settings and displays only its mode", async t => {
  const h = await fixture(t, { projectEnabled: false });
  await settled(() => h.reloads === 1);
  assert.equal(JSON.parse(await readFile(join(h.agentDir, "settings.json"), "utf8")).compaction.enabled, true);
  assert.equal(h.settings.getCompactionEnabled(), false);
  assert.equal(h.statuses.at(-1), "MemWeave 未启用");
  assert.deepEqual(JSON.parse(await readFile(join(h.cwd, ".pi/settings.json"), "utf8")), { compaction: { enabled: false } });
});

test("settings failure aborts requests and never claims mode activation", async t => {
  const h = await fixture(t, { invalidSettings: true });
  await settled(() => h.diagnostics.length > 0);
  await h.session.prompt("must not infer after a failed settings write");
  assert.equal(h.faux.state.callCount, 0); assert.equal(h.reloads, 0);
  assert.ok(h.diagnostics.some(e => e.includes("SETUP_SETTINGS_INVALID")));
  assert.equal(h.statuses.some(s => s.includes("MemWeave 未启用")), false);
});

test("headless mode keeps memory behavior without silently toggling shared settings", async t => {
  const h = await fixture(t, { headless: true });
  assert.equal(h.selections, 0); assert.equal(h.reloads, 0);
  assert.equal(h.loader.getExtensions().extensions[0]!.tools.size, 11);
  assert.equal(h.settings.getCompactionEnabled(), false);
  await assert.rejects(readFile(h.paths.rule), { code: "ENOENT" });
});

test("native instances in one process never inherit another instance's mode", async t => {
  const a = await fixture(t, { choice: "on" });
  await settled(() => a.reloads === 1);
  const b = await fixture(t, { choice: "off" });
  await settled(() => b.reloads === 1);
  assert.equal(a.selections, 1); assert.equal(b.selections, 1);
  assert.equal(a.loader.getExtensions().extensions[0]!.tools.size, 11);
  assert.equal(b.loader.getExtensions().extensions[0]!.tools.size, 0);
});
