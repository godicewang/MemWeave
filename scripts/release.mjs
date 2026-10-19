import { execFileSync } from "node:child_process";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const root = fileURLToPath(new URL("../", import.meta.url));
const { values } = parseArgs({ options: { out: { type: "string" } } });
if (!values.out) throw new Error("Usage: npm run release:build -- --out <new-directory>");
const output = resolve(values.out);
// Refuse an existing destination; failures only remove the new directory owned by this invocation.
await mkdir(output);
try {
  if (process.platform !== "darwin" || process.arch !== "arm64" || process.versions.node !== "24.22.0") {
    throw new Error("Release toolchain is currently verified only on macOS arm64, Node 24.22.0.");
  }
  execFileSync(process.execPath, [join(root, "scripts/build.mjs")], { cwd: root, stdio: "inherit" });
  const { listFiles, readRelease, sha256 } = await import(new URL("../dist/install/artifact.js", import.meta.url));
  const source = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
  const manifest = Object.fromEntries(["name", "version", "private", "description", "type", "bin", "exports", "engines", "packageManager", "dependencies", "overrides"].map((key) => [key, source[key]]));
  manifest.files = ["dist/", "README.md", "install-lock.json", "release.json"];
  const lock = JSON.parse(await readFile(join(root, "package-lock.json"), "utf8"));
  lock.packages = Object.fromEntries(Object.entries(lock.packages).filter(([, entry]) => !entry.dev));
  delete lock.packages[""].devDependencies;
  const packageRoot = join(output, "package");
  await mkdir(packageRoot);
  await cp(join(root, "dist"), join(packageRoot, "dist"), { recursive: true });
  await cp(join(root, "docs/INSTALL.md"), join(packageRoot, "README.md"));
  await writeFile(join(packageRoot, "package.json"), JSON.stringify(manifest, null, 2) + "\n");
  await writeFile(join(packageRoot, "install-lock.json"), JSON.stringify(lock, null, 2) + "\n");
  const npm = execFileSync("npm", ["--version"], { encoding: "utf8" }).trim();
  if (npm !== "11.19.1") throw new Error("Release toolchain requires npm 11.19.1.");
  const sdk = JSON.parse(execFileSync(process.execPath, [join(root, "dist/pi/installation-probe.js")], {
    cwd: root, env: { ...process.env, PI_OFFLINE: "1", PI_TELEMETRY: "0" }, encoding: "utf8",
  }));
  const files = Object.fromEntries(await Promise.all((await listFiles(packageRoot)).map(async (file) => [file, sha256(await readFile(join(packageRoot, file)))])));
  const release = {
    format: 1, version: source.version, piVersion: sdk.piVersion, sessionVersion: sdk.sessionVersion,
    environment: { node: process.versions.node, npm, platform: process.platform, arch: process.arch },
    dataCompatibility: `pi-session-${sdk.sessionVersion};memory-unimplemented`, files,
  };
  await writeFile(join(packageRoot, "release.json"), JSON.stringify(release, null, 2) + "\n");
  await readRelease(packageRoot);
  const packed = JSON.parse(execFileSync("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", output], { cwd: packageRoot, encoding: "utf8" }));
  const filename = packed[0].filename;
  const digest = sha256(await readFile(join(output, filename)));
  await writeFile(join(output, `${filename}.sha256`), `${digest}  ${filename}\n`);
  console.log(`${filename}\nSHA-256 ${digest}`);
} catch (error) {
  await rm(output, { recursive: true, force: true });
  throw error;
}
