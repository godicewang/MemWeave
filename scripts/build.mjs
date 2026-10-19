import { execFileSync } from "node:child_process";
import { chmod, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
await rm(new URL("dist/", root), { recursive: true, force: true });
execFileSync(process.execPath, [
  fileURLToPath(new URL("node_modules/typescript/bin/tsc", root)),
  "-p", fileURLToPath(new URL("tsconfig.build.json", root)),
], { cwd: fileURLToPath(root), stdio: "inherit" });
await chmod(new URL("dist/cli/index.js", root), 0o755);
