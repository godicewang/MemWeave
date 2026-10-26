import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import test, { type TestContext } from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { DefaultPackageManager, DefaultResourceLoader, SettingsManager } from "@earendil-works/pi-coding-agent";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
import { releaseFixture, releaseWorker } from "../fixtures/release.ts";

const run = promisify(execFile);
const repository = fileURLToPath(new URL("../../", import.meta.url));
const hostPeers = ["@earendil-works/pi-ai", "@earendil-works/pi-coding-agent", "typebox"];

async function installation(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), "memweave-distribution-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cwd = join(root, "workspace");
  const agentDir = join(root, "agent");
  const memory = memoryPaths(join(root, "runtime-memory"));
  await mkdir(cwd); await mkdir(agentDir); await mkdir(memory.root);
  const sentinels = new Map([
    [memory.config, JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 240 })],
    [memory.rule, "USER_RULE {{recent_turns}}"],
    [join(memory.root, "task-data-sentinel"), "EXTERNAL_TASK_DATA"],
    [join(agentDir, "auth.json"), JSON.stringify({ example: { type: "api_key", key: "fixture-not-a-secret" } })],
    [join(agentDir, "SYSTEM.md"), "USER_SYSTEM"],
    [join(agentDir, "APPEND_SYSTEM.md"), "USER_APPEND {{untouched}}"],
  ]);
  for (const [path, value] of sentinels) await writeFile(path, value);
  // Persist this test-only command so resource reloads keep cache writes isolated too.
  await writeFile(join(agentDir, "settings.json"), JSON.stringify({
    compaction: { enabled: false },
    npmCommand: ["npm", "--cache", process.env.MEMWEAVE_TEST_NPM_CACHE ?? join(root, "npm-cache"), "--no-audit", "--no-fund"],
  }));
  const settings = SettingsManager.create(cwd, agentDir, { projectTrusted: true });
  const settingsBefore = await readFile(join(agentDir, "settings.json"));
  const manager = new DefaultPackageManager({ cwd, agentDir, settingsManager: settings });
  const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings,
    noSkills: true, noThemes: true, noPromptTemplates: true });
  const assertPreserved = async () => {
    for (const [path, value] of sentinels) assert.equal(await readFile(path, "utf8"), value);
    assert.ok(settingsBefore.equals(await readFile(join(agentDir, "settings.json"))));
    assert.equal(settings.getCompactionEnabled(), false);
  };
  const assertLoaded = async (installed: string, count = 1) => {
    await loader.reload();
    assert.deepEqual(loader.getExtensions().errors, []);
    const extensions = loader.getExtensions().extensions;
    assert.equal(extensions.length, count);
    if (count) {
      assert.equal(extensions[0]?.resolvedPath, join(installed, "src/extension/index.ts"));
      for (const handlers of extensions[0]!.handlers.values()) assert.equal(handlers.length, 1);
    }
    assert.equal(loader.getAgentsFiles().agentsFiles.length, 0, "package development AGENTS must not become user context");
    await assertPreserved();
  };
  const disableAndReload = async (source: string, installed: string) => {
    settings.setProjectPackages([{ source, extensions: [] }]); await settings.flush();
    await assertLoaded(installed, 0);
    await access(installed);
    settings.setProjectPackages([source]); await settings.flush();
    await assertLoaded(installed);
  };
  return { root, cwd, settings, manager, assertPreserved, assertLoaded, disableAndReload };
}

test("远程 Git：固定 commit 安装/更新、禁用/reload、卸载，保留外置用户文件", async t => {
  const h = await installation(t);
  const initialRef = "0fd7bc3395dcdf02f8b2d59231b5f80b2d9118eb";
  const targetRef = process.env.MEMWEAVE_DISTRIBUTION_REF ??
    (await run("git", ["rev-parse", "origin/main^{commit}"], { cwd: repository })).stdout.trim();
  assert.match(targetRef, /^[0-9a-f]{40}$/);
  const transport = process.env.MEMWEAVE_DISTRIBUTION_TRANSPORT ?? "ssh";
  assert.ok(transport === "ssh" || transport === "https");
  const url = transport === "ssh" ? "git@github.com:godicewang/MemWeave.git" : "https://github.com/godicewang/MemWeave.git";
  const source = (ref: string) => `git:${url}@${ref}`;
  await h.manager.installAndPersist(source(initialRef), { local: true }); await h.settings.flush();
  const installed = h.manager.getInstalledPath(source(initialRef), "project"); assert.ok(installed);
  assert.ok(!relative(h.root, installed).startsWith(".."));
  assert.equal((await run("git", ["rev-parse", "HEAD"], { cwd: installed })).stdout.trim(), initialRef);
  await h.assertLoaded(installed);
  // A changed configured ref reconciles the same managed checkout through Pi's public API.
  h.settings.setProjectPackages([source(targetRef)]); await h.settings.flush();
  await h.manager.update(source(targetRef));
  assert.equal(h.manager.getInstalledPath(source(targetRef), "project"), installed);
  assert.equal((await run("git", ["rev-parse", "HEAD"], { cwd: installed })).stdout.trim(), targetRef);
  await h.assertLoaded(installed);
  await h.assertLoaded(installed);
  const business = await releaseFixture(t);
  await writeFile(business.paths.rule, await readFile(join(installed, "resources/rule.md")));
  const created = await releaseWorker({ ...business.base, artifact: installed, action: "create", label: "git-installed" });
  const recovered = await releaseWorker({ ...business.base, artifact: installed, sessionFile: created.sessionFile, taskId: created.taskId, action: "recover", label: "git-recovered" });
  assert.equal(recovered.version, 3);
  assert.equal(recovered.window, true);
  const task = JSON.parse(await readFile(business.paths.index, "utf8"))[0];
  const stateBeforeRemoval = await readFile(business.paths.state(task)), sessionBeforeRemoval = await readFile(created.sessionFile);
  await h.disableAndReload(source(targetRef), installed);
  for (const peer of hostPeers) await assert.rejects(access(join(installed, "node_modules", peer)), { code: "ENOENT" });
  assert.equal(await h.manager.removeAndPersist(source(targetRef), { local: true }), true);
  await h.settings.flush();
  await h.assertLoaded(installed, 0);
  await assert.rejects(access(installed), { code: "ENOENT" });
  assert.ok(stateBeforeRemoval.equals(await readFile(business.paths.state(task))));
  assert.ok(sessionBeforeRemoval.equals(await readFile(created.sessionFile)));
  t.diagnostic(`Remote Git ${transport} install ${initialRef} -> ${targetRef}; installed Runtime recovery in independent Pi processes; 7 local HTTP requests, no real inference`);
});

test("npm 本地归档：经原生 PackageManager 安装/禁用/卸载，不自动安装宿主 peer", async t => {
  const h = await installation(t);
  const npmCli = process.env.npm_execpath; assert.ok(npmCli, "Run through npm run test:distribution");
  const { stdout } = await run(process.execPath, [npmCli, "--cache", process.env.MEMWEAVE_TEST_NPM_CACHE ?? join(h.root, "npm-cache"), "pack", "--json", "--ignore-scripts", "--pack-destination", h.root], { cwd: repository });
  const archive = (JSON.parse(stdout) as Array<{ filename: string }>)[0]; assert.ok(archive);
  const manifest = JSON.parse(await readFile(join(repository, "package.json"), "utf8"));
  const source = `npm:${manifest.name}@file:${join(h.root, archive.filename)}`;
  await h.manager.installAndPersist(source, { local: true }); await h.settings.flush();
  const installed = h.manager.getInstalledPath(source, "project"); assert.ok(installed);
  assert.ok(!relative(h.root, installed).startsWith(".."));
  await h.assertLoaded(installed);
  assert.equal(await readFile(join(installed, "resources/rule.md"), "utf8"), await readFile(new URL("../../resources/rule.md", import.meta.url), "utf8"));
  for (const path of ["AGENTS.md", "docs", "tests", "scripts"]) await assert.rejects(access(join(installed, path)), { code: "ENOENT" });
  for (const peer of hostPeers) {
    await assert.rejects(access(join(installed, "node_modules", peer)), { code: "ENOENT" });
    await assert.rejects(access(join(dirname(installed), peer)), { code: "ENOENT" });
  }
  await h.disableAndReload(source, installed);
  assert.equal(await h.manager.removeAndPersist(source, { local: true }), true);
  await h.settings.flush(); await h.assertLoaded(installed, 0);
  await assert.rejects(access(installed), { code: "ENOENT" });
  t.diagnostic("Installed the local npm archive via a file spec; npm registry publication/installation was not tested");
});
