import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { chmod, copyFile, lstat, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { promisify } from "node:util";
import { assertCompatible, object, readRelease, releaseId, type Release } from "./artifact.js";

const run = promisify(execFile);
export interface InstallOptions { root?: string; binDir?: string }
export interface Activation { format: 1; current: string | null; previous: string | null }
interface Locations { root: string; binDir: string; command: string }
interface Owner { format: 1; binDir: string; node: string }
const empty: Activation = { format: 1, current: null, previous: null };
const identity = /^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?-[a-f0-9]{16}$/;

function locations(options: InstallOptions): Locations {
  const root = resolve(options.root ?? join(homedir(), ".local/share/memweave"));
  const binDir = resolve(options.binDir ?? join(homedir(), ".local/bin"));
  if (root === binDir || root === dirname(root)) throw new Error("Application root must be a separate owned directory.");
  return { root, binDir, command: join(binDir, "memweave") };
}

function absent(error: unknown): boolean { return (error as NodeJS.ErrnoException).code === "ENOENT"; }

async function readOptional(path: string): Promise<string | undefined> {
  try {
    if (!(await lstat(path)).isFile()) throw new Error(`Expected a regular managed file: ${path}`);
    return await readFile(path, "utf8");
  } catch (error) { if (absent(error)) return undefined; throw error; }
}

async function atomicWrite(path: string, contents: string): Promise<void> {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, contents, { flag: "wx", mode: 0o600 });
    await rename(temporary, path);
  } finally { await rm(temporary, { force: true }); }
}

function json(value: unknown): string { return JSON.stringify(value, null, 2) + "\n"; }

async function ownerAt(paths: Locations): Promise<Owner | undefined> {
  try {
    if ((await lstat(paths.root)).isSymbolicLink()) throw new Error("Application root cannot be a symbolic link.");
  } catch (error) { if (absent(error)) return undefined; throw error; }
  const contents = await readOptional(join(paths.root, "installation.json"));
  if (contents === undefined) return undefined;
  const owner = object(JSON.parse(contents) as unknown);
  if (owner.format !== 1 || owner.binDir !== paths.binDir || typeof owner.node !== "string" || !isAbsolute(owner.node)) {
    throw new Error("Invalid installation ownership or mismatched --bin-dir.");
  }
  return { format: 1, binDir: paths.binDir, node: owner.node };
}

export async function status(options: InstallOptions = {}): Promise<Activation> {
  const paths = locations(options);
  const owner = await ownerAt(paths);
  if (!owner) {
    try {
      if ((await readdir(paths.root)).length) throw new Error("Refusing an unmanaged application root.");
    } catch (error) { if (!absent(error)) throw error; }
    return { ...empty };
  }
  const contents = await readOptional(join(paths.root, "active.json"));
  if (contents === undefined) return { ...empty };
  const value = object(JSON.parse(contents) as unknown);
  if (value.format !== 1 || ![value.current, value.previous].every((id) => id === null || (typeof id === "string" && identity.test(id)))) {
    throw new Error("Invalid application activation record.");
  }
  return { format: 1, current: value.current as string | null, previous: value.previous as string | null };
}

async function withLock<T>(paths: Locations, initialize: boolean, action: (owner: Owner) => Promise<T>): Promise<T> {
  let owner = await ownerAt(paths);
  if (!owner && !initialize) throw new Error("MemWeave has no managed installation at this root.");
  if (!owner) {
    await mkdir(paths.root, { recursive: true });
    if ((await readdir(paths.root)).length) throw new Error("Refusing an unmanaged application root.");
  }
  const lock = join(paths.root, ".operation-lock");
  try { await mkdir(lock); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") throw new Error("Another installation operation holds the lock.");
    throw error;
  }
  try {
    // Re-read ownership after taking the lock; another operation may have completed first.
    owner = await ownerAt(paths);
    if (!owner) {
      if ((await readdir(paths.root)).some((name) => name !== ".operation-lock")) throw new Error("Refusing an unmanaged application root.");
      owner = { format: 1, binDir: paths.binDir, node: process.execPath };
      await atomicWrite(join(paths.root, "installation.json"), json(owner));
    }
    return await action(owner);
  } finally { await rm(lock, { recursive: true, force: true }); }
}

function quote(value: string): string { return `'${value.replaceAll("'", "'\\''")}'`; }
function commandContents(paths: Locations, owner: Owner): string {
  return `#!/bin/sh\n# MemWeave managed entry\nexec ${quote(owner.node)} ${quote(join(paths.root, "launcher.mjs"))} "$@"\n`;
}

async function checkCommand(paths: Locations, owner: Owner): Promise<boolean> {
  const contents = await readOptional(paths.command);
  if (contents !== undefined && contents !== commandContents(paths, owner)) throw new Error("Refusing to replace an unmanaged memweave command.");
  return contents !== undefined;
}

const launcher = `import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
try {
  const root = import.meta.dirname;
  const active = JSON.parse(await readFile(join(root, 'active.json'), 'utf8'));
  if (active.format !== 1 || typeof active.current !== 'string' || !/^[0-9][a-zA-Z0-9.-]*-[a-f0-9]{16}$/.test(active.current)) throw new Error('No valid active MemWeave release.');
  const directory = join(root, 'releases', active.current);
  const release = JSON.parse(await readFile(join(directory, 'release.json'), 'utf8'));
  if (release.environment.node !== process.versions.node) throw new Error('MemWeave Node version changed; reinstall with the validated toolchain.');
  const entry = join(directory, 'dist/cli/index.js');
  process.argv[1] = entry;
  await import(pathToFileURL(entry).href);
} catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
`;

const npmEnvironment = () => ({ ...process.env, PATH: `${dirname(process.execPath)}:${process.env.PATH ?? ""}`, PI_OFFLINE: "1", PI_TELEMETRY: "0" });

async function checkEnvironment(release: Release): Promise<void> {
  const actual = { node: process.versions.node, npm: (await run("npm", ["--version"], { env: npmEnvironment() })).stdout.trim(), platform: process.platform, arch: process.arch };
  for (const key of ["node", "npm", "platform", "arch"] as const) {
    if (release.environment[key] !== actual[key]) throw new Error(`Unsupported installation environment: ${key} requires ${release.environment[key]}, found ${actual[key]}.`);
  }
}

async function verifyInstalled(directory: string, release: Release): Promise<void> {
  await readRelease(directory, true);
  if (!(await readFile(join(directory, "package-lock.json"))).equals(await readFile(join(directory, "install-lock.json")))) {
    throw new Error("Installed dependency lock changed.");
  }
  const env = npmEnvironment();
  const probe = object(JSON.parse((await run(process.execPath, [join(directory, "dist/pi/installation-probe.js")], { cwd: directory, env })).stdout) as unknown);
  if (probe.piVersion !== release.piVersion || probe.sessionVersion !== release.sessionVersion) throw new Error("Installed SDK does not match release metadata.");
  const cli = await run(process.execPath, [join(directory, "dist/cli/index.js"), "--version"], { cwd: directory, env });
  if (cli.stdout.trim() !== `MemWeave ${release.version} (Pi SDK ${release.piVersion})`) throw new Error("Installed CLI version does not match release metadata.");
}

export async function install(source: string, options: InstallOptions = {}): Promise<Activation> {
  source = resolve(source);
  const release = await readRelease(source);
  await checkEnvironment(release);
  const paths = locations(options);
  return withLock(paths, true, async (owner) => {
    const prior = await status(options);
    const hasCommand = await checkCommand(paths, owner);
    if (owner.node !== process.execPath) throw new Error("Node location changed; uninstall the managed entry before reinstalling with a new Node location.");
    if (prior.current) assertCompatible(await readRelease(join(paths.root, "releases", prior.current), true), release);
    const id = releaseId(release);
    await mkdir(join(paths.root, "releases"), { recursive: true });
    if ((await lstat(join(paths.root, "releases"))).isSymbolicLink()) throw new Error("Release storage cannot be a symbolic link.");
    const destination = join(paths.root, "releases", id);
    const staging = join(paths.root, "releases", `.staging-${randomUUID()}`);
    try {
      let existing = false;
      try { await lstat(destination); existing = true; } catch (error) { if (!absent(error)) throw error; }
      if (existing) await verifyInstalled(destination, release);
      else {
        await mkdir(staging);
        for (const path of [...Object.keys(release.files), "release.json"]) {
          await mkdir(dirname(join(staging, path)), { recursive: true });
          await copyFile(join(source, path), join(staging, path));
        }
        // Recheck copied bytes, including sources changed while copying.
        if (releaseId(await readRelease(staging)) !== id) throw new Error("Release changed while copying.");
        await copyFile(join(staging, "install-lock.json"), join(staging, "package-lock.json"));
        await run("npm", ["ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"], { cwd: staging, env: npmEnvironment(), timeout: 120_000 });
        await verifyInstalled(staging, release);
        await rename(staging, destination);
      }
      await mkdir(paths.binDir, { recursive: true });
      if ((await lstat(paths.binDir)).isSymbolicLink()) throw new Error("Command directory cannot be a symbolic link.");
      await checkCommand(paths, owner);
      await atomicWrite(join(paths.root, "launcher.mjs"), launcher);
      let createdCommand = false;
      try {
        if (!hasCommand) {
          await writeFile(paths.command, commandContents(paths, owner), { flag: "wx", mode: 0o755 });
          createdCommand = true;
        } else await chmod(paths.command, 0o755);
        const active: Activation = { format: 1, current: id, previous: prior.current === id ? prior.previous : prior.current };
        await atomicWrite(join(paths.root, "active.json"), json(active));
        return active;
      } catch (error) {
        if (createdCommand) await rm(paths.command);
        throw error;
      }
    } finally { await rm(staging, { recursive: true, force: true }); }
  });
}

export async function rollback(options: InstallOptions = {}): Promise<Activation> {
  const paths = locations(options);
  return withLock(paths, false, async (owner) => {
    if (!await checkCommand(paths, owner)) throw new Error("Managed command is missing; reinstall first.");
    const prior = await status(options);
    if (!prior.current || !prior.previous) throw new Error("No previous active release to roll back to.");
    const current = await readRelease(join(paths.root, "releases", prior.current), true);
    const targetDirectory = join(paths.root, "releases", prior.previous);
    const target = await readRelease(targetDirectory, true);
    assertCompatible(current, target);
    await checkEnvironment(target);
    await verifyInstalled(targetDirectory, target);
    const active: Activation = { format: 1, current: prior.previous, previous: prior.current };
    await atomicWrite(join(paths.root, "active.json"), json(active));
    return active;
  });
}

export async function uninstall(options: InstallOptions = {}): Promise<void> {
  const paths = locations(options);
  await withLock(paths, false, async (owner) => {
    if (await checkCommand(paths, owner)) await rm(paths.command);
    await rm(join(paths.root, "active.json"), { force: true });
    // Inactive versions and ownership remain for diagnostics and reinstallation.
    owner.node = process.execPath;
    await atomicWrite(join(paths.root, "installation.json"), json(owner));
  });
}
