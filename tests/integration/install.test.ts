import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { access, cp, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { install, rollback, status, uninstall } from "../../src/install/manager.js";
import { readRelease } from "../../src/install/artifact.js";

const run = promisify(execFile);
let temporary: string;
let artifact: string;
const project = resolve(import.meta.dirname, "../..");

beforeAll(async () => {
  temporary = await mkdtemp(join(tmpdir(), "memweave-install-"));
  const output = join(temporary, "build");
  await run(process.execPath, [join(project, "scripts/release.mjs"), "--out", output], { cwd: project });
  const extracted = join(temporary, "extracted");
  await mkdir(extracted);
  const archive = (await readdir(output)).find((name) => name.endsWith(".tgz"))!;
  await run("tar", ["-xzf", join(output, archive), "-C", extracted]);
  artifact = join(extracted, "package");
}, 60_000);

afterAll(async () => { if (temporary) await rm(temporary, { recursive: true, force: true }); });

describe.sequential("locked application installation", () => {
  it("builds identical archives and includes only runtime files and a complete production lock", async () => {
    const second = join(temporary, "build-again");
    await run(process.execPath, [join(project, "scripts/release.mjs"), "--out", second], { cwd: project });
    const archive = (await readdir(join(temporary, "build"))).find((name) => name.endsWith(".tgz"))!;
    expect(await readFile(join(second, archive))).toEqual(await readFile(join(temporary, "build", archive)));
    const release = await readRelease(artifact);
    expect(Object.keys(release.files).some((name) => /AGENTS|specs|tests|auth|eval/.test(name))).toBe(false);
    const lock = JSON.parse(await readFile(join(artifact, "install-lock.json"), "utf8"));
    expect(Object.values(lock.packages).some((entry: unknown) => (entry as { dev?: boolean }).dev)).toBe(false);
    expect(lock.packages["node_modules/@earendil-works/pi-coding-agent"].version).toBe("1.3.0");
  }, 60_000);

  it("uses real npm ci, switches and rolls back, survives failure, and preserves user data on uninstall", async () => {
    const home = join(temporary, "user's home");
    const options = { root: join(home, ".local/share/memweave"), binDir: join(home, ".local/bin") };
    const data = join(home, ".pi/memory");
    await mkdir(data, { recursive: true });
    const sentinel = join(data, "keep.json");
    await writeFile(sentinel, "user-data");
    const profile = join(home, ".pi/agent");
    await mkdir(profile);
    const preserved = new Map([
      [sentinel, "user-data"],
      [join(profile, "settings.json"), '{"compaction":{"enabled":true}}'],
      [join(profile, "auth.json"), "{}"],
      [join(data, "rule.md"), "user-maintained rule"],
    ]);
    for (const [path, contents] of preserved) await writeFile(path, contents);
    const cleanEnvironment = { ...process.env, HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, PI_CODING_AGENT_DIR: profile };
    await expect(run("/bin/sh", ["-c", "command -v pi"], { env: cleanEnvironment })).rejects.toThrow();
    const initial = await run(process.execPath, [join(artifact, "dist/install/cli.js"), "install", "--root", options.root, "--bin-dir", options.binDir], { cwd: home, env: cleanEnvironment });
    const first = JSON.parse(initial.stdout) as Awaited<ReturnType<typeof status>>;
    const command = join(options.binDir, "memweave");
    expect((await run(command, ["--version"], { cwd: home, env: { ...process.env, HOME: home, PI_CODING_AGENT_DIR: join(home, ".pi/agent") } })).stdout)
      .toContain("MemWeave 0.1.0-dev.0 (Pi SDK 1.3.0)");
    const packageRoot = join(options.root, "releases", first.current!);
    expect(await readFile(join(packageRoot, "package-lock.json"))).toEqual(await readFile(join(artifact, "install-lock.json")));
    const probe = await run(process.execPath, ["--input-type=module", "-e", "import { createMemWeaveHost } from './dist/pi/index.js'; const h = await createMemWeaveHost({cwd:process.cwd()}); await h.dispose(); console.log('HOST_OK');"], {
      cwd: packageRoot, env: { ...process.env, HOME: home, PI_CODING_AGENT_DIR: join(home, ".pi/agent"), PI_OFFLINE: "1", PI_TELEMETRY: "0" },
    });
    expect(probe.stdout).toContain("HOST_OK");
    expect((await run(command, ["manage", "status", "--root", options.root, "--bin-dir", options.binDir])).stdout).toContain(first.current);
    expect((await status(options)).current).toBe(first.current);

    // A second local development artifact exercises activation without changing business formats.
    const next = join(temporary, "next");
    await cp(artifact, next, { recursive: true });
    await writeFile(join(next, "README.md"), "A second local development build.\n");
    const metadata = JSON.parse(await readFile(join(next, "release.json"), "utf8"));
    metadata.files["README.md"] = createHash("sha256").update(await readFile(join(next, "README.md"))).digest("hex");
    await writeFile(join(next, "release.json"), JSON.stringify(metadata, null, 2) + "\n");
    const updated = await install(next, options);
    expect(updated.current).not.toBe(first.current);
    expect(updated.previous).toBe(first.current);
    expect((await rollback(options)).current).toBe(first.current);

    metadata.dataCompatibility = "different-format";
    await writeFile(join(next, "release.json"), JSON.stringify(metadata, null, 2) + "\n");
    await expect(install(next, options)).rejects.toThrow(/compatib/);
    metadata.dataCompatibility = (await readRelease(artifact)).dataCompatibility;
    metadata.environment.npm = "0.0.0";
    await writeFile(join(next, "release.json"), JSON.stringify(metadata, null, 2) + "\n");
    await expect(install(next, options)).rejects.toThrow(/environment/);
    metadata.environment.npm = (await readRelease(artifact)).environment.npm;

    // npm itself fails in a fresh staging directory: an unavailable mandatory tarball, offline.
    const lock = JSON.parse(await readFile(join(next, "install-lock.json"), "utf8"));
    lock.packages["node_modules/@anthropic-ai/sdk"].resolved = "https://registry.npmjs.org/memweave-unavailable-test/-/missing.tgz";
    lock.packages["node_modules/@anthropic-ai/sdk"].integrity = "sha512-" + Buffer.alloc(64).toString("base64");
    await writeFile(join(next, "install-lock.json"), JSON.stringify(lock, null, 2) + "\n");
    metadata.files["install-lock.json"] = createHash("sha256").update(await readFile(join(next, "install-lock.json"))).digest("hex");
    await writeFile(join(next, "release.json"), JSON.stringify(metadata, null, 2) + "\n");
    const previousOffline = process.env.npm_config_offline;
    try {
      process.env.npm_config_offline = "true";
      await expect(install(next, options)).rejects.toThrow();
    } finally {
      if (previousOffline === undefined) delete process.env.npm_config_offline;
      else process.env.npm_config_offline = previousOffline;
    }
    expect((await status(options)).current).toBe(first.current);
    expect((await run(command, ["--version"])).stdout).toContain("Pi SDK 1.3.0");

    // Integrity and environment failures cannot activate a partial new version.
    await writeFile(join(next, "README.md"), "damaged");
    await expect(install(next, options)).rejects.toThrow(/checksum/);
    expect((await status(options)).current).toBe(first.current);
    await mkdir(join(options.root, ".operation-lock"));
    await expect(rollback(options)).rejects.toThrow(/operation/);
    await rm(join(options.root, ".operation-lock"), { recursive: true });
    await uninstall(options);
    await expect(access(command)).rejects.toThrow();
    expect((await status(options)).current).toBeNull();
    for (const [path, contents] of preserved) expect(await readFile(path, "utf8")).toBe(contents);
    expect((await readdir(join(options.root, "releases"))).some((name) => name.startsWith(".staging-"))).toBe(false);
    expect(await readFile(join(artifact, "install-lock.json"))).toEqual(await readFile(join(packageRoot, "package-lock.json")));
    // Reinstall after uninstall and repeated installation are idempotent.
    expect((await install(artifact, options)).current).toBe(first.current);
    expect((await install(artifact, options)).current).toBe(first.current);
    await uninstall(options);
  }, 60_000);

  it("does not replace an unmanaged command", async () => {
    const options = { root: join(temporary, "conflict-root"), binDir: join(temporary, "conflict-bin") };
    await mkdir(options.binDir);
    const command = join(options.binDir, "memweave");
    await writeFile(command, "owned by someone else");
    await expect(install(artifact, options)).rejects.toThrow(/unmanaged/);
    expect(await readFile(command, "utf8")).toBe("owned by someone else");
  });

  it("rejects release symlinks and unexpected development files", async () => {
    const invalid = join(temporary, "invalid");
    await cp(artifact, invalid, { recursive: true });
    await writeFile(join(invalid, "AGENTS.md"), "not a runtime resource");
    await expect(readRelease(invalid)).rejects.toThrow(/file list/);
    await rm(join(invalid, "AGENTS.md"));
    await rm(join(invalid, "README.md"));
    await symlink(join(artifact, "README.md"), join(invalid, "README.md"));
    await expect(readRelease(invalid)).rejects.toThrow(/Symbolic/);
  });
});
