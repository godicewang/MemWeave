import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { DefaultPackageManager, DefaultResourceLoader, discoverAndLoadExtensions, SettingsManager } from "@earendil-works/pi-coding-agent";

const run = promisify(execFile);
const root = fileURLToPath(new URL("../../", import.meta.url));

async function assertPackageLoads(packageRoot: string, temporaryRoot: string) {
  const workspace = join(temporaryRoot, "workspace");
  const agentDir = join(temporaryRoot, "agent");
  await mkdir(workspace, { recursive: true });
  await mkdir(agentDir, { recursive: true });

  const manifest = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
  if (manifest.dependencies?.["@huggingface/tokenizers"]) {
    const npm = process.env.npm_execpath!;
    await run(process.execPath, [npm, "install", "--prefix", temporaryRoot, "--cache", join(temporaryRoot, "npm-cache"), "--ignore-scripts", "--no-audit", "--no-fund", "--package-lock=false", `@huggingface/tokenizers@${manifest.dependencies["@huggingface/tokenizers"]}`]);
  }
  const result = await discoverAndLoadExtensions([packageRoot], workspace, agentDir);

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.warnings ?? [], []);
  assert.equal(result.extensions.length, 1);
  const extension = result.extensions[0];
  assert.ok(extension);
  assert.equal(extension.resolvedPath, join(packageRoot, "src/extension/index.ts"));
  const phase2 = (await readFile(join(packageRoot, "src/extension/index.ts"), "utf8")).includes("registerMemweave");
  const expectedTools = phase2 ? ["state_append", "task_create", "task_find", "task_resume", "task_status"] : [];
  const registration = phase2 ? await readFile(join(packageRoot, "src/extension/register.ts"), "utf8") : "";
  if (registration.includes('"update_goal"')) expectedTools.push("update_goal", "state_read");
  if (registration.includes('"state_remain"')) expectedTools.push("modify_fact", "state_remain");
  if (registration.includes('"memory_read"')) expectedTools.push("memory_read");
  if (registration.includes('"recent_window_set"')) expectedTools.push("recent_window_set");
  assert.deepEqual([...extension.tools.keys()].sort(), expectedTools.sort());
  assert.deepEqual([...extension.handlers.keys()].sort(), phase2
    ? [...(registration.includes("alignOutput") ? ["before_provider_request"] : []), "context_with_system", "session_before_compact", "session_start", "session_tree", "tool_call", "turn_end"]
    : ["context_with_system", "session_before_compact", "session_start"]);
  for (const handlers of extension.handlers.values()) assert.equal(handlers.length, 1);
  assert.deepEqual(await readdir(workspace), []);
  assert.deepEqual(await readdir(agentDir), []);
}

test("Pi v1.3.0 通过 manifest 加载本地 TypeScript 入口", async (t) => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "memweave-local-load-"));
  t.after(() => rm(temporaryRoot, { recursive: true, force: true }));

  await assertPackageLoads(root, temporaryRoot);
});

test("npm 归档只含运行资源，解包后由 Pi 加载同一入口", async (t) => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "memweave-package-load-"));
  t.after(() => rm(temporaryRoot, { recursive: true, force: true }));
  const npmCli = process.env.npm_execpath;
  assert.ok(npmCli, "请通过 npm test 或 npm run test:integration 运行集成测试");
  const { stdout } = await run(
    process.execPath,
    [npmCli, "pack", "--json", "--ignore-scripts", "--pack-destination", temporaryRoot],
    { cwd: root },
  );
  const [archive] = JSON.parse(stdout) as Array<{
    filename: string;
    files: Array<{ path: string }>;
  }>;
  assert.ok(archive);
  const paths = archive.files.map((file) => file.path).sort();
  const sources = (await readdir(join(root, "src"), { recursive: true })).filter(path => path.endsWith(".ts")).map(path => `src/${path}`);
  assert.deepEqual(paths, [
    "README.md",
    "USER_GUIDE.md",
    "package.json",
    "src/config/defaults.json",
    "resources/rule.md",
    ...(await readdir(join(root, "resources/tokenizer"))).map(name => `resources/tokenizer/${name}`),
    ...sources,
  ].sort());

  await run("tar", ["-xzf", join(temporaryRoot, archive.filename), "-C", temporaryRoot]);
  const packageRoot = join(temporaryRoot, "package");
  assert.deepEqual(
    await readFile(join(packageRoot, "resources/rule.md")),
    await readFile(join(root, "docs/specs/1.2.rule_v1_3_final_updated.md")),
  );
  await assertPackageLoads(packageRoot, temporaryRoot);
});

test("Git HEAD 的入口和生成资源无需开发构建即可由 Pi 加载", async (t) => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "memweave-git-load-"));
  t.after(() => rm(temporaryRoot, { recursive: true, force: true }));
  const { stdout } = await run("git", ["rev-parse", "--verify", "HEAD^{commit}"], { cwd: root });
  const checkout = join(temporaryRoot, "checkout");
  const archive = join(temporaryRoot, "source.tar");
  await mkdir(checkout);
  await run("git", ["archive", "--format=tar", `--output=${archive}`, stdout.trim()], { cwd: root });
  await run("tar", ["-xf", archive, "-C", checkout]);
  assert.deepEqual(
    await readFile(join(checkout, "resources/rule.md")),
    await readFile(join(checkout, "docs/specs/1.2.rule_v1_3_final_updated.md")),
  );
  await assertPackageLoads(checkout, temporaryRoot);
});

test("原生 PackageManager 项目安装/移除可用，卸载保留用户的压缩设置", async (t) => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "memweave-install-"));
  t.after(() => rm(temporaryRoot, { recursive: true, force: true }));
  const cwd = join(temporaryRoot, "workspace"); const agentDir = join(temporaryRoot, "agent");
  await mkdir(cwd); await mkdir(agentDir);
  const settings = SettingsManager.create(cwd, agentDir, { projectTrusted: true });
  settings.setCompactionEnabled(false); await settings.flush();
  const settingsBefore = await readFile(join(agentDir, "settings.json"));
  const manager = new DefaultPackageManager({ cwd, agentDir, settingsManager: settings });
  await manager.installAndPersist(root, { local: true });
  await settings.flush();
  const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager: settings,
    noSkills: true, noThemes: true, noPromptTemplates: true });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  assert.equal(loader.getExtensions().extensions.filter(extension => extension.resolvedPath === join(root, "src/extension/index.ts")).length, 1);
  assert.equal(loader.getAgentsFiles().agentsFiles.length, 0, "包内 AGENTS 不应作为业务上下文加载");
  assert.equal(await manager.removeAndPersist(root, { local: true }), true);
  await settings.flush();
  await loader.reload();
  assert.equal(loader.getExtensions().extensions.some(extension => extension.resolvedPath === join(root, "src/extension/index.ts")), false);
  assert.equal(settings.getCompactionEnabled(), false);
  assert.deepEqual(await readFile(join(agentDir, "settings.json")), settingsBefore);
});
