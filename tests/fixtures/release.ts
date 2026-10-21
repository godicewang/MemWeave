import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import type { TestContext } from "node:test";
import { DEFAULT_CONFIG } from "../../src/config/schema.ts";
import { memoryPaths } from "../../src/storage/paths.ts";
export const run = promisify(execFile);
export const repository = fileURLToPath(new URL("../../", import.meta.url));
export interface ReleaseCase {
  root: string;
  artifact: string;
  memory: string;
  cwd: string;
  sessionDir: string;
  action: "create" | "recover" | "concurrent" | "blocked" | "live";
  sessionFile?: string;
  taskId?: string;
  label: string;
  turns?: number;
  authPath?: string;
}
export interface ReleaseResult {
  taskId: string;
  version: number;
  sessionFile: string;
  requests: number;
  toolNames: string[];
  window: boolean;
  settings: number | null;
}
export async function releaseFixture(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), "memweave-release-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(join(root, "memory")),
    cwd = join(root, "business"),
    sessionDir = join(root, "sessions");
  await mkdir(paths.root);
  await mkdir(cwd);
  await mkdir(sessionDir);
  await writeFile(
    paths.config,
    JSON.stringify({ ...DEFAULT_CONFIG, recent_turns: 6, evict_turns: 2 }),
  );
  await writeFile(
    paths.rule,
    await readFile(new URL("../../resources/rule.md", import.meta.url)),
  );
  const base = { root, memory: paths.root, cwd, sessionDir };
  return { root, paths, cwd, sessionDir, base };
}
export async function sourceArtifact(root: string, ref = "HEAD") {
  const path = join(root, `source-${ref.slice(0, 12)}`);
  await mkdir(path);
  const archive = join(root, `source-${ref.slice(0, 12)}.tar`);
  await run("git", ["archive", "--format=tar", `--output=${archive}`, ref], {
    cwd: repository,
  });
  await run("tar", ["-xf", archive, "-C", path]);
  return path;
}
export async function packArtifact(
  root: string,
  source = repository,
  version?: string,
) {
  const npm = process.env.npm_execpath;
  assert.ok(npm, "Run through an npm test script");
  if (version) {
    assert.ok(
      !relative(root, source).startsWith(".."),
      "Version overrides require a temporary source checkout",
    );
    const file = join(source, "package.json"),
      metadata = JSON.parse(await readFile(file, "utf8"));
    await writeFile(file, JSON.stringify({ ...metadata, version }));
  }
  const destination = join(root, `pack-${version ?? "current"}`);
  await mkdir(destination);
  const { stdout } = await run(
    process.execPath,
    [
      npm,
      "--cache",
      join(root, "npm-cache"),
      "pack",
      "--ignore-scripts",
      "--json",
      "--pack-destination",
      destination,
    ],
    { cwd: source },
  );
  const [archive] = JSON.parse(stdout) as { filename: string }[];
  assert.ok(archive);
  return join(destination, archive.filename);
}
export async function unpackArtifact(root: string, archive: string) {
  const destination = join(root, "unpacked");
  await mkdir(destination);
  await run("tar", ["-xzf", archive, "-C", destination]);
  return join(destination, "package");
}
export async function releaseWorker(
  input: ReleaseCase,
): Promise<ReleaseResult> {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    MEMWEAVE_RELEASE_CASE: JSON.stringify(input),
  };
  delete env.NODE_TEST_CONTEXT;
  const { stdout, stderr } = await run(
    process.execPath,
    [
      "--test",
      "--test-reporter=tap",
      fileURLToPath(new URL("./release-worker.ts", import.meta.url)),
    ],
    {
      cwd: input.cwd,
      env,
      timeout: 90_000,
      maxBuffer: 2 * 1024 * 1024,
    },
  );
  const line = stdout
    .split("\n")
    .find((line) => line.startsWith("# MEMWEAVE_RESULT "));
  assert.ok(line, `worker produced no result: ${stderr}`);
  if (input.action === "blocked")
    assert.match(stdout + stderr, /LOCK_OWNER_DEAD/);
  else assert.doesNotMatch(stdout + stderr, /\[MemWeave\]/);
  return JSON.parse(line.slice("# MEMWEAVE_RESULT ".length)) as ReleaseResult;
}
