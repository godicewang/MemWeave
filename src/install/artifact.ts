import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

export interface Release {
  format: 1;
  version: string;
  piVersion: string;
  sessionVersion: number;
  environment: { node: string; npm: string; platform: string; arch: string };
  dataCompatibility: string;
  files: Record<string, string>;
}

export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a metadata object.");
  return value as Record<string, unknown>;
}

function version(value: unknown): value is string {
  return typeof value === "string" && /^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$/.test(value) && value.length < 100;
}

export function runtimePath(path: string): boolean {
  if (path.split("/").some((part) => !part || part === "." || part === "..") || path.includes("\\")) return false;
  return ["package.json", "install-lock.json", "README.md"].includes(path)
    || /^dist\/(?:cli|pi|extension|install)\/[a-zA-Z0-9_/-]+\.(?:js|d\.ts)$/.test(path);
}

export function parseRelease(value: unknown): Release {
  const input = object(value);
  if (input.format !== 1 || !version(input.version) || !version(input.piVersion)
    || !Number.isSafeInteger(input.sessionVersion) || Number(input.sessionVersion) < 1
    || typeof input.dataCompatibility !== "string" || !input.dataCompatibility || input.dataCompatibility.length > 200) {
    throw new Error("Invalid MemWeave release metadata or unsupported format.");
  }
  const env = object(input.environment);
  if (!version(env.node) || !version(env.npm) || typeof env.platform !== "string" || !/^[a-z0-9]+$/.test(env.platform)
    || typeof env.arch !== "string" || !/^[a-z0-9]+$/.test(env.arch)) throw new Error("Invalid release environment.");
  const files = object(input.files);
  if (!Object.keys(files).length) throw new Error("Release file list is empty.");
  for (const [path, digest] of Object.entries(files)) {
    if (!runtimePath(path)) throw new Error(`Invalid runtime file path: ${path}`);
    if (typeof digest !== "string" || !/^[a-f0-9]{64}$/.test(digest)) throw new Error(`Invalid checksum: ${path}`);
  }
  return {
    format: 1, version: input.version, piVersion: input.piVersion, sessionVersion: Number(input.sessionVersion),
    environment: { node: env.node, npm: env.npm, platform: env.platform, arch: env.arch },
    dataCompatibility: input.dataCompatibility, files: Object.fromEntries(Object.entries(files).sort()) as Record<string, string>,
  };
}

export function sha256(contents: string | Uint8Array): string {
  return createHash("sha256").update(contents).digest("hex");
}

export function releaseId(release: Release): string {
  return `${release.version}-${sha256(JSON.stringify(release)).slice(0, 16)}`;
}

export function assertCompatible(current: Release, target: Release): void {
  if (current.dataCompatibility !== target.dataCompatibility || current.sessionVersion !== target.sessionVersion) {
    throw new Error("Incompatible data declarations: automatic version switching is refused; no user data was migrated.");
  }
}

export async function listFiles(root: string, installed = false, prefix = ""): Promise<string[]> {
  const result: string[] = [];
  for (const name of (await readdir(join(root, prefix))).sort()) {
    if (!prefix && installed && ["node_modules", "package-lock.json"].includes(name)) continue;
    const path = prefix ? `${prefix}/${name}` : name;
    const info = await lstat(join(root, path));
    if (info.isSymbolicLink()) throw new Error(`Symbolic links are not allowed in release files: ${path}`);
    if (info.isDirectory()) result.push(...await listFiles(root, installed, path));
    else if (info.isFile()) result.push(path);
    else throw new Error(`Unsupported release file: ${path}`);
  }
  return result.sort();
}

export async function readRelease(root: string, installed = false): Promise<Release> {
  if ((await lstat(root)).isSymbolicLink()) throw new Error("Release directory cannot be a symbolic link.");
  const release = parseRelease(JSON.parse(await readFile(join(root, "release.json"), "utf8")) as unknown);
  const actual = await listFiles(root, installed);
  const expected = [...Object.keys(release.files), "release.json"].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("Release file list differs from the manifest.");
  for (const [path, digest] of Object.entries(release.files)) {
    if (sha256(await readFile(join(root, path))) !== digest) throw new Error(`Release checksum mismatch: ${path}`);
  }
  for (const path of ["package.json", "install-lock.json", "README.md", "dist/cli/index.js", "dist/pi/index.js", "dist/install/cli.js", "dist/pi/installation-probe.js"]) {
    if (!release.files[path]) throw new Error(`Missing required runtime file: ${path}`);
  }
  const manifest = object(JSON.parse(await readFile(join(root, "package.json"), "utf8")) as unknown);
  const lock = object(JSON.parse(await readFile(join(root, "install-lock.json"), "utf8")) as unknown);
  const packages = object(lock.packages);
  const lockRoot = object(packages[""]);
  if (manifest.name !== "memweave" || manifest.version !== release.version || lock.name !== manifest.name
    || lock.version !== manifest.version || lockfileInvalid(lock, manifest, lockRoot)) {
    throw new Error("Installation manifest and lock do not match the release.");
  }
  for (const [path, entry] of Object.entries(packages)) {
    const record = object(entry);
    if (record.dev) throw new Error("Installation lock contains development dependencies.");
    if (path && (!path.startsWith("node_modules/") || typeof record.integrity !== "string" || typeof record.resolved !== "string")) {
      throw new Error(`Incomplete installation lock: ${path}`);
    }
    if (path.includes("@earendil-works/pi-")) {
      if (!/^node_modules\/@earendil-works\/pi-[a-z-]+$/.test(path) || record.version !== release.piVersion) {
        throw new Error(`Pi dependency must have a single locked version: ${path}`);
      }
    }
  }
  for (const name of ["pi-coding-agent", "pi-agent-core", "pi-ai", "pi-tui", "pi-mcp", "pi-codemode", "pi-telemetry"]) {
    if (object(packages[`node_modules/@earendil-works/${name}`]).version !== release.piVersion) throw new Error(`Missing locked Pi dependency: ${name}`);
  }
  return release;
}

function lockfileInvalid(lock: Record<string, unknown>, manifest: Record<string, unknown>, root: Record<string, unknown>): boolean {
  return lock.lockfileVersion !== 3 || manifest.devDependencies !== undefined || manifest.scripts !== undefined
    || root.devDependencies !== undefined || JSON.stringify(manifest.dependencies) !== JSON.stringify(root.dependencies);
}
