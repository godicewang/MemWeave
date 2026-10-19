#!/usr/bin/env node
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { install, rollback, status, uninstall } from "./manager.js";

export async function manage(args: string[]): Promise<void> {
  const { positionals, values } = parseArgs({
    args, allowPositionals: true,
    options: { from: { type: "string" }, root: { type: "string" }, "bin-dir": { type: "string" }, help: { type: "boolean", short: "h" } },
  });
  if (values.help || !positionals.length) {
    console.log("Usage: memweave manage install [--from <extracted-package>] | status | rollback | uninstall\nOptions: --root <application-directory> --bin-dir <command-directory>");
    return;
  }
  if (positionals.length !== 1 || (values.from && positionals[0] !== "install")) throw new Error("Invalid installation command arguments.");
  const options = { ...(values.root ? { root: values.root } : {}), ...(values["bin-dir"] ? { binDir: values["bin-dir"] } : {}) };
  switch (positionals[0]) {
    case "install": console.log(JSON.stringify(await install(values.from ?? fileURLToPath(new URL("../../", import.meta.url)), options), null, 2)); break;
    case "status": console.log(JSON.stringify(await status(options), null, 2)); break;
    case "rollback": console.log(JSON.stringify(await rollback(options), null, 2)); break;
    case "uninstall": await uninstall(options); console.log("MemWeave entry removed. Version files and user data retained."); break;
    default: throw new Error(`Unknown installation command: ${positionals[0]}`);
  }
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await manage(process.argv.slice(2)); }
  catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
}
