import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { discoverAndLoadExtensions } from "@earendil-works/pi-coding-agent";

const run = promisify(execFile);
const root = fileURLToPath(new URL("../../", import.meta.url));

async function assertPackageLoads(packageRoot: string, temporaryRoot: string) {
  const workspace = join(temporaryRoot, "workspace");
  const agentDir = join(temporaryRoot, "agent");
  await mkdir(workspace, { recursive: true });
  await mkdir(agentDir, { recursive: true });

  const result = await discoverAndLoadExtensions([packageRoot], workspace, agentDir);

  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.warnings ?? [], []);
  assert.equal(result.extensions.length, 1);
  const extension = result.extensions[0];
  assert.ok(extension);
  assert.equal(extension.resolvedPath, join(packageRoot, "src/extension/index.ts"));
  assert.equal(extension.tools.size, 0, "阶段 0 不注册生产业务工具");
  assert.deepEqual([...extension.handlers.keys()].sort(), ["context_with_system", "session_before_compact", "session_start"]);
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
  assert.deepEqual(paths, [
    "README.md",
    "package.json",
    "resources/rule.md",
    "src/extension/index.ts",
    "src/pi/context-limit.ts",
    "src/pi/request-lifecycle.ts",
  ]);

  await run("tar", ["-xzf", join(temporaryRoot, archive.filename), "-C", temporaryRoot]);
  const packageRoot = join(temporaryRoot, "package");
  assert.deepEqual(
    await readFile(join(packageRoot, "resources/rule.md")),
    await readFile(join(root, "docs/specs/1.2.rule_v1_3_final_updated.md")),
  );
  await assertPackageLoads(packageRoot, temporaryRoot);
});
